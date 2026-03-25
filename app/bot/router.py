from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from uuid import UUID
from pathlib import Path
from decimal import Decimal
import mimetypes

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Cliente, KitFesta, RegistroAluguel, KitFoto, Tenant
from app.meta.whatsapp_api import (
    baixar_media_meta_para_local,
    send_list_message,
    send_text_message,
    send_image_message,
    send_location_message,
    upload_media_bytes,
    tipo_conteudo_por_mime,
)
from app.bot.menus import main_menu_list
from app.services.mensagens import salvar_mensagem
from app.services.conversas import (
    obter_ou_criar_conversa,
    atualizar_estado_conversa,
    resetar_conversa,
    tratar_estado_ao_receber_mensagem,
)

ATENDIMENTO_HUMANO_TIMEOUT_HORAS = 12
TZ = ZoneInfo("America/Sao_Paulo")


def _agora_utc():
    return datetime.now(timezone.utc)


def _somente_digitos(valor: str | None) -> str:
    if not valor:
        return ""
    return "".join(ch for ch in str(valor) if ch.isdigit())


def _canonizar_telefone_br(telefone: str | None) -> str:
    digits = _somente_digitos(telefone)

    if len(digits) == 12 and digits.startswith("55"):
        ddd = digits[2:4]
        numero = digits[4:]
        if len(numero) == 8:
            return f"55{ddd}9{numero}"

    return digits


def _variantes_telefone_br(telefone: str | None) -> set[str]:
    digits = _somente_digitos(telefone)
    variantes = set()

    if not digits:
        return variantes

    variantes.add(digits)

    if len(digits) == 13 and digits.startswith("55"):
        ddd = digits[2:4]
        numero = digits[4:]
        if len(numero) == 9 and numero.startswith("9"):
            variantes.add(f"55{ddd}{numero[1:]}")

    if len(digits) == 12 and digits.startswith("55"):
        ddd = digits[2:4]
        numero = digits[4:]
        if len(numero) == 8:
            variantes.add(f"55{ddd}9{numero}")

    return variantes


def _telefone_brasileiro_valido_flexivel(telefone: str | None) -> bool:
    telefone = _somente_digitos(telefone)

    if not telefone.startswith("55"):
        return False

    if len(telefone) == 13:
        ddd = telefone[2:4]
        numero = telefone[4:]
        return (
            len(ddd) == 2
            and ddd.isdigit()
            and len(numero) == 9
            and numero.isdigit()
            and numero.startswith("9")
        )

    if len(telefone) == 12:
        ddd = telefone[2:4]
        numero = telefone[4:]
        return (
            len(ddd) == 2
            and ddd.isdigit()
            and len(numero) == 8
            and numero.isdigit()
        )

    return False


def _cpf_valido(cpf: str | None) -> bool:
    cpf = _somente_digitos(cpf)

    if len(cpf) != 11:
        return False

    if cpf == cpf[0] * 11:
        return False

    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    dig1 = 11 - (soma % 11)
    if dig1 >= 10:
        dig1 = 0

    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    dig2 = 11 - (soma % 11)
    if dig2 >= 10:
        dig2 = 0

    return cpf[9] == str(dig1) and cpf[10] == str(dig2)


def _nome_completo_valido(nome: str | None) -> bool:
    nome = (nome or "").strip()
    partes = [p for p in nome.split() if p.strip()]
    return len(partes) >= 2 and len(nome) >= 6


def _endereco_valido(endereco: str | None) -> bool:
    endereco = (endereco or "").strip()
    return len(endereco) >= 8


def _buscar_cliente_por_telefone(db: Session, tenant_id, telefone: str):
    variantes_recebidas = _variantes_telefone_br(telefone)
    if not variantes_recebidas:
        return None

    clientes = (
        db.query(Cliente)
        .filter(Cliente.tenant_id == tenant_id)
        .all()
    )

    for cliente in clientes:
        if variantes_recebidas & _variantes_telefone_br(cliente.telefone):
            return cliente

    return None


def _cliente_esta_bloqueado_por_debito(cliente: Cliente) -> bool:
    saldo = cliente.saldo or Decimal("0.00")
    return saldo < Decimal("0.00")


def _formatar_valor_brl(valor):
    if valor is None or valor == "":
        return None
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)


def _nome_kit(kit):
    return (
        getattr(kit, "nome_kit", None)
        or getattr(kit, "tema", None)
        or getattr(kit, "categoria", None)
        or "kit"
    )


def _buscar_kit_por_id(db: Session, tenant_id, kit_id: str):
    try:
        kit_uuid = UUID(str(kit_id))
    except Exception:
        return None

    return (
        db.query(KitFesta)
        .filter(
            KitFesta.id == kit_uuid,
            KitFesta.tenant_id == tenant_id,
        )
        .first()
    )


def _listar_kits(db: Session, tenant_id):
    return (
        db.query(KitFesta)
        .filter(
            KitFesta.tenant_id == tenant_id,
            KitFesta.ativo == True,
        )
        .order_by(KitFesta.nome_kit.asc(), KitFesta.tema.asc(), KitFesta.categoria.asc())
        .all()
    )


def _listar_fotos(db: Session, kit_id):
    return (
        db.query(KitFoto)
        .filter(KitFoto.kit_id == kit_id)
        .order_by(KitFoto.ordem.asc(), KitFoto.id.asc())
        .all()
    )


def _expirou_atendimento_humano(conversa) -> bool:
    if not getattr(conversa, "atendimento_humano", False):
        return False

    last_message_at = getattr(conversa, "last_message_at", None)
    if not last_message_at:
        return False

    if last_message_at.tzinfo is None:
        last_message_at = last_message_at.replace(tzinfo=timezone.utc)

    return last_message_at < (_agora_utc() - timedelta(hours=ATENDIMENTO_HUMANO_TIMEOUT_HORAS))


def _parse_data(texto: str) -> date | None:
    texto = (texto or "").strip()

    formatos = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue

    return None


def existe_conflito(db: Session, tenant_id, kit_id, data: date):
    return (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.tenant_id == tenant_id,
            RegistroAluguel.kit_id == kit_id,
            RegistroAluguel.status != "cancelado",
            RegistroAluguel.data_reserva <= data,
            RegistroAluguel.data_entrega >= data,
        )
        .first()
    )


def _foto_url_para_caminho_local(foto_url: str | None) -> Path | None:
    if not foto_url:
        return None

    foto_url = str(foto_url).strip()
    if not foto_url:
        return None

    if foto_url.startswith("/static/"):
        caminho_relativo = foto_url[len("/static/"):]
        return Path("app/static") / caminho_relativo

    if foto_url.startswith("static/"):
        caminho_relativo = foto_url[len("static/"):]
        return Path("app/static") / caminho_relativo

    return Path(foto_url)


def _buscar_tenant(db: Session, tenant_id):
    return db.query(Tenant).filter(Tenant.id == tenant_id).first()


def _nome_empresa(db: Session, tenant_id) -> str:
    tenant = _buscar_tenant(db, tenant_id)
    if tenant and getattr(tenant, "name", None):
        return tenant.name
    return getattr(settings, "SCHOOL_NAME", "Viva Festas")



async def _enviar_localizacao_loja(db: Session, tenant_id, telefone: str):
    endereco = (
        "Rua 16, Quadra 10, Número 54- Cohatrac II \n"
        "São Luís - MA"
    )

    nome_loja = _nome_empresa(db, tenant_id)

    latitude = -2.5377014
    longitude = -44.1979748

    await _enviar_texto(
        db,
        tenant_id,
        telefone,
        f"📍 *Nosso endereço:*\n\n{endereco}"
    )

    await send_location_message(
        telefone,
        latitude=latitude,
        longitude=longitude,
        name=nome_loja,
        address="Rua 16, Quadra 10, Número 54 - Cohatrac II, São Luís - MA",
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[localizacao_loja] {nome_loja}",
        tipo_conteudo="localizacao",
    )


async def _notificar_venda_pendente():
    numero_alerta = getattr(settings, "WHATSAPP_ALERT_PHONE", None)
    numero_alerta = _canonizar_telefone_br(numero_alerta)

    if not numero_alerta:
        print("[ALERTA] WHATSAPP_ALERT_PHONE não configurado.")
        return

    mensagem = (
        "🔔 Tem uma venda aguardando finalização no painel.\n\n"
        "Acesse o sistema para concluir o atendimento."
    )

    try:
        await send_text_message(numero_alerta, mensagem)
        print(f"[ALERTA] Notificação de venda pendente enviada para {numero_alerta}")
    except Exception as e:
        print(f"[ERRO ALERTA FINALIZACAO] {repr(e)}")


async def _notificar_atendimento_humano():
    numero_alerta = getattr(settings, "WHATSAPP_ALERT_PHONE", None)
    numero_alerta = _canonizar_telefone_br(numero_alerta)

    if not numero_alerta:
        print("[ALERTA] WHATSAPP_ALERT_PHONE não configurado.")
        return

    mensagem = (
        "🔔 Um cliente solicitou atendimento humano.\n\n"
        "Acesse o painel para responder."
    )

    try:
        await send_text_message(numero_alerta, mensagem)
        print(f"[ALERTA] Notificação de atendimento humano enviada para {numero_alerta}")
    except Exception as e:
        print(f"[ERRO ALERTA ATENDIMENTO] {repr(e)}")


async def _enviar_texto(db: Session, tenant_id, telefone: str, msg: str):
    await send_text_message(telefone, msg)
    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=msg,
        tipo_conteudo="texto",
    )


async def _enviar_menu(db: Session, tenant_id, telefone: str, company: str):
    body, btn, sections = main_menu_list(company)
    await send_list_message(telefone, body, btn, sections)
    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[menu_lista] {body}",
        tipo_conteudo="texto",
    )


async def _enviar_lista_kits(db: Session, tenant_id, telefone: str, acao: str, titulo: str, msg: str):
    kits = _listar_kits(db, tenant_id)

    if not kits:
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "No momento não encontrei kits cadastrados para exibir. Digite *MENU* para voltar ou fale com nosso atendimento."
        )
        return

    rows = []
    for k in kits[:10]:
        rows.append(
            {
                "id": f"{acao}::{k.id}",
                "title": _nome_kit(k)[:24],
                "description": _formatar_valor_brl(k.valor_locacao) or "Ver detalhes",
            }
        )

    await send_list_message(
        telefone,
        msg,
        "Ver kits",
        [
            {
                "title": titulo,
                "rows": rows,
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[lista_kits::{acao}] {msg}",
        tipo_conteudo="texto",
    )


async def _enviar_opcoes_pos_kit(db: Session, tenant_id, telefone: str, kit):
    await send_list_message(
        telefone,
        f"O que deseja fazer com *{_nome_kit(kit)}*?",
        "Escolher",
        [
            {
                "title": "Opções",
                "rows": [
                    {
                        "id": "POST_KIT_OTHER",
                        "title": "Ver outro kit",
                        "description": "Voltar ao catálogo",
                    },
                    {
                        "id": f"POST_KIT_AVAIL::{kit.id}",
                        "title": "Ver disponibilidade",
                        "description": "Consultar data",
                    },
                ],
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[opcoes_pos_kit] {_nome_kit(kit)}",
        tipo_conteudo="texto",
    )


async def _enviar_opcoes_disponivel(db: Session, tenant_id, telefone: str, kit, data_evento: date):
    await send_list_message(
        telefone,
        (
            f"✅ *{_nome_kit(kit)}* disponível em "
            f"{data_evento.strftime('%d/%m/%Y')}.\n"
            "O que deseja fazer?"
        ),
        "Escolher",
        [
            {
                "title": "Reserva",
                "rows": [
                    {
                        "id": "PAYMENT_START",
                        "title": "Ir para pagamento",
                        "description": "Continuar reserva",
                    },
                    {
                        "id": f"RETRY_DATE::{kit.id}",
                        "title": "Escolher outra data",
                        "description": "Tentar nova data",
                    },
                    {
                        "id": "POST_KIT_OTHER",
                        "title": "Ver outro kit",
                        "description": "Voltar ao catálogo",
                    },
                ],
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[opcoes_disponivel] {_nome_kit(kit)} {data_evento.isoformat()}",
        tipo_conteudo="texto",
    )


async def _enviar_opcoes_indisponivel(db: Session, tenant_id, telefone: str, kit, data_evento: date):
    await send_list_message(
        telefone,
        (
            f"❌ *{_nome_kit(kit)}* indisponível em "
            f"{data_evento.strftime('%d/%m/%Y')}.\n"
            "Escolha uma opção:"
        ),
        "Escolher",
        [
            {
                "title": "Alternativas",
                "rows": [
                    {
                        "id": f"RETRY_DATE::{kit.id}",
                        "title": "Escolher outra data",
                        "description": "Tentar nova data",
                    },
                    {
                        "id": "POST_KIT_OTHER",
                        "title": "Ver outros kits",
                        "description": "Voltar ao catálogo",
                    },
                    {
                        "id": "END_SERVICE",
                        "title": "Finalizar",
                        "description": "Encerrar atendimento",
                    },
                ],
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[opcoes_indisponivel] {_nome_kit(kit)} {data_evento.isoformat()}",
        tipo_conteudo="texto",
    )


async def _enviar_opcoes_tipo_pagamento(db: Session, tenant_id, telefone: str):
    await send_list_message(
        telefone,
        "Escolha o tipo de pagamento:",
        "Escolher",
        [
            {
                "title": "Pagamento",
                "rows": [
                    {
                        "id": "PAY_TYPE::COMPLETO",
                        "title": "Pagamento completo",
                        "description": "Valor total",
                    },
                    {
                        "id": "PAY_TYPE::PARCIAL",
                        "title": "Pagamento parcial",
                        "description": "Pagamento inicial",
                    },
                ],
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo="[tipo_pagamento]",
        tipo_conteudo="texto",
    )


async def _enviar_opcoes_forma_pagamento(
    db: Session,
    tenant_id,
    telefone: str,
    tipo_pagamento: str,
):
    await send_list_message(
        telefone,
        "Escolha a forma de pagamento:",
        "Escolher",
        [
            {
                "title": "Forma",
                "rows": [
                    {
                        "id": f"PAY_METHOD::PIX::{tipo_pagamento}",
                        "title": "Pix",
                        "description": "Transferência Pix",
                    },
                    {
                        "id": f"PAY_METHOD::CARTAO_CREDITO::{tipo_pagamento}",
                        "title": "Cartão crédito",
                        "description": "Pagamento no crédito",
                    },
                    {
                        "id": f"PAY_METHOD::CARTAO_DEBITO::{tipo_pagamento}",
                        "title": "Cartão débito",
                        "description": "Pagamento no débito",
                    },
                    {
                        "id": f"PAY_METHOD::DINHEIRO::{tipo_pagamento}",
                        "title": "Dinheiro",
                        "description": "Pagamento em espécie",
                    },
                ],
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo=f"[forma_pagamento] {tipo_pagamento}",
        tipo_conteudo="texto",
    )


async def _encaminhar_para_humano_pagamento(
    db: Session,
    tenant_id,
    telefone: str,
    conversa,
    kit,
    data_evento: date,
    tipo_pagamento: str,
    forma_pagamento: str,
):
    conversa.atendimento_humano = True
    conversa.status_atendimento = "aguardando"
    atualizar_estado_conversa(db, conversa, "aguardando_atendimento")
    conversa.last_message_at = _agora_utc()

    contexto = conversa.contexto_json or {}

    forma_legivel = (
        forma_pagamento.replace("_", " ")
        .replace("CARTAO", "Cartão")
        .replace("PIX", "Pix")
        .title()
    )

    tipo_legivel = tipo_pagamento.title()

    msg = (
        "👩‍💼 Perfeito! Vou encaminhar você para o *atendimento humano* para finalizar a reserva.\n\n"
        f"📦 Kit: *{_nome_kit(kit)}*\n"
        f"📅 Data: *{data_evento.strftime('%d/%m/%Y')}*\n"
        f"💳 Tipo de pagamento: *{tipo_legivel}*\n"
        f"💰 Forma de pagamento: *{forma_legivel}*\n\n"
        "Nossa equipe seguirá com o seu atendimento."
    )

    await _enviar_texto(db, tenant_id, telefone, msg)

    if not contexto.get("alerta_finalizacao_enviado"):
        await _notificar_venda_pendente()
        contexto["alerta_finalizacao_enviado"] = True
        conversa.contexto_json = contexto

    db.commit()


async def _encaminhar_para_humano_por_debito(
    db: Session,
    tenant_id,
    telefone: str,
    conversa,
):
    conversa.atendimento_humano = True
    conversa.status_atendimento = "aguardando"
    atualizar_estado_conversa(db, conversa, "aguardando_atendimento")
    conversa.last_message_at = _agora_utc()

    contexto = conversa.contexto_json or {}

    await _enviar_texto(
        db,
        tenant_id,
        telefone,
        "Notamos um débito em seu cadastro. Clique abaixo para falar com nossa equipe e regularizar sua situação de forma rápida."
    )

    await send_list_message(
        telefone,
        "Selecione uma opção para continuar:",
        "Escolher",
        [
            {
                "title": "Atendimento",
                "rows": [
                    {
                        "id": "ATTENDANT",
                        "title": "Falar com a equipe",
                        "description": "Regularizar cadastro e débitos",
                    }
                ],
            }
        ],
    )

    salvar_mensagem(
        db=db,
        tenant_id=tenant_id,
        telefone_usuario=telefone,
        tipo_mensagem="enviada",
        conteudo="[debito_pendente]",
        tipo_conteudo="texto",
    )

    if not contexto.get("alerta_atendimento_humano_enviado"):
        await _notificar_atendimento_humano()
        contexto["alerta_atendimento_humano_enviado"] = True
        conversa.contexto_json = contexto

    db.commit()


async def _enviar_fotos_kit(db: Session, tenant_id, from_phone: str, kit):
    fotos = _listar_fotos(db, kit.id)

    print(f"[DEBUG] kit.id={kit.id} | fotos_encontradas={len(fotos)}")

    if not fotos:
        await _enviar_texto(
            db,
            tenant_id,
            from_phone,
            "📸 Este kit ainda não possui fotos cadastradas."
        )
        return

    enviou_alguma = False

    for idx, foto in enumerate(fotos):
        foto_url_original = getattr(foto, "foto_url", None)
        caminho_local = _foto_url_para_caminho_local(foto_url_original)

        print(f"[DEBUG] foto original={foto_url_original}")
        print(f"[DEBUG] caminho_local={caminho_local}")

        if not caminho_local or not caminho_local.exists() or not caminho_local.is_file():
            print(f"[ERRO FOTO] arquivo não encontrado: {caminho_local}")
            continue

        try:
            conteudo = caminho_local.read_bytes()
            mime_type = mimetypes.guess_type(str(caminho_local))[0] or "image/jpeg"

            media_id = await upload_media_bytes(
                conteudo,
                caminho_local.name,
                mime_type,
            )

            print(f"[DEBUG] media_id={media_id}")

            legenda = f"📸 Fotos do kit *{_nome_kit(kit)}*" if idx == 0 else ""

            await send_image_message(
                from_phone,
                media_id,
                caption=legenda,
            )

            salvar_mensagem(
                db=db,
                tenant_id=tenant_id,
                telefone_usuario=from_phone,
                tipo_mensagem="enviada",
                conteudo=legenda or f"[foto_kit] {_nome_kit(kit)}",
                tipo_conteudo="imagem",
                media_url=foto_url_original,
                media_filename=caminho_local.name,
                media_mime_type=mime_type,
                media_id=media_id,
            )
            enviou_alguma = True

        except Exception as e:
            import traceback
            print(f"[ERRO AO ENVIAR FOTO] {repr(e)}")
            traceback.print_exc()

    if not enviou_alguma:
        await _enviar_texto(
            db,
            tenant_id,
            from_phone,
            "📸 Encontrei fotos cadastradas para este kit, mas não consegui enviá-las."
        )


async def _enviar_detalhes_kit(db: Session, tenant_id, telefone: str, kit):
    if not kit:
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "Não consegui localizar esse kit. Digite *MENU* para voltar."
        )
        return

    msg = (
        f"🎉 *{_nome_kit(kit)}*\n\n"
        f"📦 Categoria: {kit.categoria or '-'}\n"
        f"💰 Valor: {_formatar_valor_brl(kit.valor_locacao) or 'sob consulta'}\n"
    )

    await _enviar_texto(db, tenant_id, telefone, msg)
    await _enviar_fotos_kit(db, tenant_id, telefone, kit)
    await _enviar_opcoes_pos_kit(db, tenant_id, telefone, kit)


async def processar_mensagem_recebida(payload_mensagem, db: Session, tenant_id):
    telefone = payload_mensagem["from"]
    tipo = payload_mensagem.get("type")

    if tipo == "text":
        texto = payload_mensagem["text"]["body"]
        salvar_mensagem(
            db=db,
            tenant_id=tenant_id,
            telefone_usuario=telefone,
            tipo_mensagem="recebida",
            conteudo=texto,
            tipo_conteudo="texto",
        )
        return

    if tipo in ["image", "document", "audio", "video"]:
        bloco = payload_mensagem.get(tipo, {})
        media_info = await baixar_media_meta_para_local(
            media_id=bloco.get("id"),
            filename=bloco.get("filename"),
            mime_type=bloco.get("mime_type"),
        )
        salvar_mensagem(
            db=db,
            tenant_id=tenant_id,
            telefone_usuario=telefone,
            tipo_mensagem="recebida",
            conteudo=bloco.get("caption", ""),
            tipo_conteudo=tipo_conteudo_por_mime(media_info.get("media_mime_type")),
            media_url=media_info.get("media_url"),
            media_mime_type=media_info.get("media_mime_type"),
            media_filename=media_info.get("media_filename"),
            media_id=media_info.get("media_id"),
        )


async def handle_incoming(
    db: Session,
    tenant_id,
    from_phone: str,
    text: str,
    button_id: str | None = None,
):
    company = _nome_empresa(db, tenant_id)
    telefone = from_phone
    texto = (text or "").strip()

    numero_alerta = _canonizar_telefone_br(getattr(settings, "WHATSAPP_ALERT_PHONE", None))
    telefone_origem = _canonizar_telefone_br(from_phone)

    if numero_alerta and telefone_origem == numero_alerta:
        print(f"[ALERTA] Mensagem ignorada do número interno: {telefone_origem}")
        return

    conversa = obter_ou_criar_conversa(db, tenant_id, telefone)
    conversa = tratar_estado_ao_receber_mensagem(db, conversa)

    if _expirou_atendimento_humano(conversa):
        conversa.atendimento_humano = False
        conversa.status_atendimento = "expirado"
        resetar_conversa(db, conversa)
        conversa.last_message_at = _agora_utc()
        db.commit()

    if texto.lower() in ["menu", "inicio", "início", "voltar"]:
        resetar_conversa(db, conversa)
        conversa.last_message_at = _agora_utc()
        db.commit()
        await _enviar_menu(db, tenant_id, telefone, company)
        return

    conversa.last_message_at = _agora_utc()
    db.commit()

    if button_id == "CATALOG":
        resetar_conversa(db, conversa)
        await _enviar_lista_kits(
            db,
            tenant_id,
            telefone,
            "KIT_INFO",
            "Catálogo",
            "🎉 Escolha um kit para ver os detalhes e as fotos:",
        )
        return

    if button_id and button_id.startswith("KIT_INFO::"):
        kit_id = button_id.split("::", 1)[1]
        kit = _buscar_kit_por_id(db, tenant_id, kit_id)
        resetar_conversa(db, conversa)
        await _enviar_detalhes_kit(db, tenant_id, telefone, kit)
        return

    if button_id == "LOCATION":
        resetar_conversa(db, conversa)
        await _enviar_localizacao_loja(db, tenant_id, telefone)
        return

    if button_id == "POST_KIT_OTHER":
        resetar_conversa(db, conversa)
        await _enviar_lista_kits(
            db,
            tenant_id,
            telefone,
            "KIT_INFO",
            "Catálogo",
            "🎉 Escolha outro kit para ver os detalhes e as fotos:",
        )
        return

    if button_id and button_id.startswith("POST_KIT_AVAIL::"):
        kit_id = button_id.split("::", 1)[1]
        kit = _buscar_kit_por_id(db, tenant_id, kit_id)

        if not kit:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui localizar esse kit. Digite *MENU* para voltar."
            )
            return

        atualizar_estado_conversa(db, conversa, f"aguardando_data::{kit.id}")
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            f"📅 Informe a data desejada para o kit *{_nome_kit(kit)}* no formato *DD/MM/AAAA*."
        )
        return

    if button_id and button_id.startswith("RETRY_DATE::"):
        kit_id = button_id.split("::", 1)[1]
        kit = _buscar_kit_por_id(db, tenant_id, kit_id)

        if not kit:
            resetar_conversa(db, conversa)
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui localizar esse kit. Digite *MENU* para começar novamente."
            )
            return

        atualizar_estado_conversa(db, conversa, f"aguardando_data::{kit.id}")
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            f"📅 Informe a nova data desejada para o kit *{_nome_kit(kit)}* no formato *DD/MM/AAAA*."
        )
        return

    if conversa.state and conversa.state.startswith("aguardando_data::"):
        kit_id = conversa.state.split("::", 1)[1]
        kit = _buscar_kit_por_id(db, tenant_id, kit_id)

        if not kit:
            resetar_conversa(db, conversa)
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui localizar esse kit. Digite *MENU* para começar novamente."
            )
            return

        data = _parse_data(texto)
        if not data:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Data inválida. Envie no formato *DD/MM/AAAA*. Exemplo: *25/03/2026*."
            )
            return

        valor = _formatar_valor_brl(kit.valor_locacao)
        conflito = existe_conflito(db, tenant_id, kit.id, data)

        if conflito:
            atualizar_estado_conversa(db, conversa, f"data_consulta::{kit.id}::{data.isoformat()}")

            msg = (
                f"❌ O kit *{_nome_kit(kit)}* não está disponível na data *{data.strftime('%d/%m/%Y')}*."
            )
            if valor:
                msg += f"\n💰 Valor da locação: *{valor}*"

            await _enviar_texto(db, tenant_id, telefone, msg)
            await _enviar_opcoes_indisponivel(db, tenant_id, telefone, kit, data)
            return

        atualizar_estado_conversa(db, conversa, f"kit_confirmado::{kit.id}::{data.isoformat()}")

        msg = (
            f"✅ O kit *{_nome_kit(kit)}* está disponível na data *{data.strftime('%d/%m/%Y')}*."
        )
        if valor:
            msg += f"\n💰 Valor da locação: *{valor}*"

        await _enviar_texto(db, tenant_id, telefone, msg)
        await _enviar_opcoes_disponivel(db, tenant_id, telefone, kit, data)
        return

    if button_id == "PAYMENT_START":
        if not conversa.state or not conversa.state.startswith("kit_confirmado::"):
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não encontrei a reserva em andamento. Digite *MENU* e escolha o kit novamente."
            )
            return

        try:
            _, kit_id, data_iso = conversa.state.split("::", 2)
        except Exception:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui continuar com o pagamento. Digite *MENU* para recomeçar."
            )
            return

        kit = _buscar_kit_por_id(db, tenant_id, kit_id)
        if not kit:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui localizar esse kit. Digite *MENU* para voltar."
            )
            return

        cliente = _buscar_cliente_por_telefone(db, tenant_id, telefone)

        if cliente and _cliente_esta_bloqueado_por_debito(cliente):
            await _encaminhar_para_humano_por_debito(db, tenant_id, telefone, conversa)
            return

        if not cliente:
            atualizar_estado_conversa(db, conversa, f"cadastro_nome::{kit.id}::{data_iso}")
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Antes de continuar com a reserva, preciso fazer seu cadastro.\n\n"
                "Por favor, envie seu *nome completo*."
            )
            return

        atualizar_estado_conversa(db, conversa, f"pagamento_tipo::{kit.id}::{data_iso}")
        await _enviar_opcoes_tipo_pagamento(db, tenant_id, telefone)
        return

    if conversa.state and conversa.state.startswith("cadastro_nome::"):
        try:
            _, kit_id, data_iso = conversa.state.split("::", 2)
        except Exception:
            resetar_conversa(db, conversa)
            await _enviar_texto(db, tenant_id, telefone, "Não consegui continuar seu cadastro. Digite *MENU* para recomeçar.")
            return

        if not _nome_completo_valido(texto):
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Por favor, informe seu *nome completo* com nome e sobrenome."
            )
            return

        nome = " ".join((texto or "").strip().split())
        atualizar_estado_conversa(db, conversa, f"cadastro_cpf::{kit_id}::{data_iso}::{nome}")
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "Perfeito. Agora envie seu *CPF*."
        )
        return

    if conversa.state and conversa.state.startswith("cadastro_cpf::"):
        partes = conversa.state.split("::", 3)
        if len(partes) != 4:
            resetar_conversa(db, conversa)
            await _enviar_texto(db, tenant_id, telefone, "Não consegui continuar seu cadastro. Digite *MENU* para recomeçar.")
            return

        _, kit_id, data_iso, nome = partes
        cpf = _somente_digitos(texto)

        if not _cpf_valido(cpf):
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "CPF inválido. Por favor, envie um *CPF válido*."
            )
            return

        atualizar_estado_conversa(db, conversa, f"cadastro_endereco::{kit_id}::{data_iso}::{nome}::{cpf}")
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "Ótimo. Agora envie seu *endereço completo*."
        )
        return

    if conversa.state and conversa.state.startswith("cadastro_endereco::"):
        partes = conversa.state.split("::", 4)
        if len(partes) != 5:
            resetar_conversa(db, conversa)
            await _enviar_texto(db, tenant_id, telefone, "Não consegui concluir seu cadastro. Digite *MENU* para recomeçar.")
            return

        _, kit_id, data_iso, nome, cpf = partes
        endereco = " ".join((texto or "").strip().split())

        if not _endereco_valido(endereco):
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Endereço inválido. Por favor, envie um *endereço mais completo*."
            )
            return

        telefone_canonico = _canonizar_telefone_br(telefone)
        if not _telefone_brasileiro_valido_flexivel(telefone_canonico):
            conversa.atendimento_humano = True
            conversa.status_atendimento = "aguardando"
            atualizar_estado_conversa(db, conversa, "aguardando_atendimento")
            conversa.last_message_at = _agora_utc()

            contexto = conversa.contexto_json or {}
            if not contexto.get("alerta_atendimento_humano_enviado"):
                await _notificar_atendimento_humano()
                contexto["alerta_atendimento_humano_enviado"] = True
                conversa.contexto_json = contexto

            db.commit()

            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui validar automaticamente seu telefone para cadastro. Vou encaminhar você para nossa equipe."
            )
            return

        cliente_existente = _buscar_cliente_por_telefone(db, tenant_id, telefone_canonico)
        if not cliente_existente:
            cliente = Cliente(
                tenant_id=tenant_id,
                nome=nome,
                telefone=telefone_canonico,
                cpf=cpf,
                endereco=endereco,
            )
            db.add(cliente)
            db.commit()
        else:
            if not cliente_existente.nome:
                cliente_existente.nome = nome
            if not cliente_existente.cpf:
                cliente_existente.cpf = cpf
            if not cliente_existente.endereco:
                cliente_existente.endereco = endereco
            if not cliente_existente.telefone:
                cliente_existente.telefone = telefone_canonico
            db.commit()

        atualizar_estado_conversa(db, conversa, f"pagamento_tipo::{kit_id}::{data_iso}")
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "✅ Cadastro realizado com sucesso. Vamos continuar sua reserva."
        )
        await _enviar_opcoes_tipo_pagamento(db, tenant_id, telefone)
        return

    if button_id and button_id.startswith("PAY_TYPE::"):
        partes = button_id.split("::")
        if len(partes) != 2:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui identificar o tipo de pagamento. Digite *MENU* para recomeçar."
            )
            return

        _, tipo_pagamento = partes

        if not conversa.state or not conversa.state.startswith("pagamento_tipo::"):
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não encontrei a etapa do pagamento. Digite *MENU* para começar novamente."
            )
            return

        try:
            _, kit_id, data_iso = conversa.state.split("::", 2)
        except Exception:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui continuar o pagamento. Digite *MENU* para recomeçar."
            )
            return

        kit = _buscar_kit_por_id(db, tenant_id, kit_id)
        if not kit:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui localizar esse kit. Digite *MENU* para voltar."
            )
            return

        cliente = _buscar_cliente_por_telefone(db, tenant_id, telefone)
        if cliente and _cliente_esta_bloqueado_por_debito(cliente):
            await _encaminhar_para_humano_por_debito(db, tenant_id, telefone, conversa)
            return

        atualizar_estado_conversa(
            db,
            conversa,
            f"pagamento_forma::{tipo_pagamento}::{kit.id}::{data_iso}",
        )
        await _enviar_opcoes_forma_pagamento(
            db,
            tenant_id,
            telefone,
            tipo_pagamento,
        )
        return

    if button_id and button_id.startswith("PAY_METHOD::"):
        partes = button_id.split("::")
        if len(partes) != 3:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui identificar a forma de pagamento. Digite *MENU* para recomeçar."
            )
            return

        _, forma_pagamento, tipo_pagamento = partes

        if not conversa.state or not conversa.state.startswith("pagamento_forma::"):
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não encontrei a etapa final do pagamento. Digite *MENU* para começar novamente."
            )
            return

        try:
            _, _, kit_id, data_iso = conversa.state.split("::", 3)
        except Exception:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui finalizar essa etapa. Digite *MENU* para recomeçar."
            )
            return

        kit = _buscar_kit_por_id(db, tenant_id, kit_id)
        if not kit:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui localizar esse kit. Digite *MENU* para voltar."
            )
            return

        try:
            data_evento = datetime.strptime(data_iso, "%Y-%m-%d").date()
        except Exception:
            await _enviar_texto(
                db,
                tenant_id,
                telefone,
                "Não consegui recuperar a data da reserva. Digite *MENU* para começar novamente."
            )
            return

        cliente = _buscar_cliente_por_telefone(db, tenant_id, telefone)
        if cliente and _cliente_esta_bloqueado_por_debito(cliente):
            await _encaminhar_para_humano_por_debito(db, tenant_id, telefone, conversa)
            return

        await _encaminhar_para_humano_pagamento(
            db,
            tenant_id,
            telefone,
            conversa,
            kit,
            data_evento,
            tipo_pagamento,
            forma_pagamento,
        )
        return

    if button_id == "END_SERVICE":
        resetar_conversa(db, conversa)
        conversa.atendimento_humano = False
        conversa.status_atendimento = "finalizado"
        conversa.last_message_at = _agora_utc()
        db.commit()

        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "✅ Atendimento finalizado.\n\nQuando quiser, envie *MENU* para iniciar novamente."
        )
        return

    if button_id == "PAYMENT":
        resetar_conversa(db, conversa)
        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "💳 *Pagamento para reserva*\n\n"
            "Para reservar um Kit Festa, é necessário realizar a sinalização de pagamento de *metade do valor* "
            "ou o *pagamento total* do kit na data do agendamento.\n\n"
            "Digite *MENU* para voltar ao início ou escolha outra opção."
        )
        return

    if button_id == "ATTENDANT":
        conversa.atendimento_humano = True
        conversa.status_atendimento = "aguardando"
        atualizar_estado_conversa(db, conversa, "aguardando_atendimento")
        conversa.last_message_at = _agora_utc()
        db.commit()

        await _enviar_texto(
            db,
            tenant_id,
            telefone,
            "👩‍💼 Você foi encaminhado para o *atendimento humano*.\n\n"
            "Nossa equipe continuará o seu atendimento."
        )

        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        numero_interno = None

        if tenant and tenant.config_json:
            numero_interno = (
                tenant.config_json.get("numero_interno")
                or tenant.config_json.get("telefone_interno")
                or tenant.config_json.get("atendimento_numero")
            )

        numero_interno = _canonizar_telefone_br(numero_interno)

        if numero_interno and numero_interno != telefone:
            try:
                nome_cliente = None
                if conversa.contexto_json:
                    nome_cliente = (
                        conversa.contexto_json.get("nome")
                        or conversa.contexto_json.get("nome_cliente")
                        or conversa.contexto_json.get("responsavel")
                    )

                if not nome_cliente:
                    cliente = _buscar_cliente_por_telefone(db, tenant_id, telefone)
                    if cliente and cliente.nome:
                        nome_cliente = cliente.nome

                texto_interno = (
                    "🔔 *Novo atendimento humano solicitado*\n\n"
                    f"*Cliente:* {nome_cliente or 'Não informado'}\n"
                    f"*Telefone:* {telefone}\n"
                    "Abra o painel para continuar o atendimento."
                )

                await send_text_message(numero_interno, texto_interno)
            except Exception as e:
                print(f"[ATENDIMENTO HUMANO] erro ao avisar número interno: {e}")

        return

    await _enviar_menu(db, tenant_id, telefone, company)
