from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Form, Depends, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, or_
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.db.models import (
    UsuarioAdmin,
    MensagemWhatsapp,
    KitFesta,
    Tenant,
    Conversation,
    Cliente,
    KitFoto,
    RegistroAluguel,
)
from app.admin.auth import verificar_senha, criar_token_sessao, obter_usuario_logado
from app.meta.whatsapp_api import (
    send_text_message,
    upload_media_bytes,
    send_document_message,
    send_image_message,
    send_audio_message,
    send_video_message,
    tipo_conteudo_por_mime,
)
from app.services.mensagens import salvar_mensagem
from app.services.kits import sincronizar_disponibilidade_kit

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def _render(request: Request, template_name: str, context: dict | None = None, status_code: int = 200):
    context = context or {}
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
        status_code=status_code,
    )


def _usuario_atual(request: Request, db: Session):
    sessao = obter_usuario_logado(request)
    if not sessao:
        return None
    return db.query(UsuarioAdmin).filter(UsuarioAdmin.id == sessao["usuario_id"]).first()


def _redirect_login():
    return RedirectResponse(url="/admin/login", status_code=302)


def _somente_digitos(valor: str | None) -> str:
    if not valor:
        return ""
    return "".join(ch for ch in str(valor) if ch.isdigit())


def _normalizar_telefone(telefone: str | None) -> str:
    return _somente_digitos(telefone)


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


def _cliente_esta_bloqueado_por_debito(cliente: Cliente) -> bool:
    saldo = cliente.saldo or Decimal("0.00")
    return saldo < Decimal("0.00")


def _parse_uuid(valor: str | None):
    try:
        return uuid.UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_date(valor: str | None):
    if not valor:
        return None

    valor = valor.strip()
    formatos = [
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(valor, fmt).date()
        except ValueError:
            continue

    return None


def _to_decimal(valor: str | None):
    if valor is None:
        return None

    valor = str(valor).strip()
    if not valor:
        return None

    valor = valor.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return Decimal(valor)
    except (InvalidOperation, ValueError):
        return None


def _buscar_cliente_do_tenant(db: Session, tenant_id, cliente_id: str):
    cliente_uuid = _parse_uuid(cliente_id)
    if not cliente_uuid:
        return None

    return (
        db.query(Cliente)
        .filter(Cliente.id == cliente_uuid, Cliente.tenant_id == tenant_id)
        .first()
    )


def _buscar_kit_do_tenant(db: Session, tenant_id, kit_id: str):
    kit_uuid = _parse_uuid(kit_id)
    if not kit_uuid:
        return None

    return (
        db.query(KitFesta)
        .filter(KitFesta.id == kit_uuid, KitFesta.tenant_id == tenant_id)
        .first()
    )


def _buscar_registro_do_tenant(db: Session, tenant_id, registro_id: str):
    registro_uuid = _parse_uuid(registro_id)
    if not registro_uuid:
        return None

    return (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.id == registro_uuid,
            RegistroAluguel.tenant_id == tenant_id,
        )
        .first()
    )


def _listar_kits_do_tenant(db: Session, tenant_id):
    return (
        db.query(KitFesta)
        .filter(KitFesta.tenant_id == tenant_id, KitFesta.ativo == True)
        .order_by(KitFesta.nome_kit.asc())
        .all()
    )


def _gerar_codigo_kit(db: Session, tenant_id):
    total = db.query(KitFesta).filter(KitFesta.tenant_id == tenant_id).count() + 1
    return f"KIT-{total:04d}"


def existe_conflito_reserva(
    db: Session,
    tenant_id,
    kit_id,
    data_reserva: date,
    data_entrega: date,
    ignorar_registro_id=None,
):
    query = (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.tenant_id == tenant_id,
            RegistroAluguel.kit_id == kit_id,
            RegistroAluguel.status != "cancelado",
            RegistroAluguel.data_reserva <= data_entrega,
            RegistroAluguel.data_entrega >= data_reserva,
        )
    )

    if ignorar_registro_id:
        query = query.filter(RegistroAluguel.id != ignorar_registro_id)

    return query.first() is not None


def _recalcular_cliente(db: Session, cliente_id, tenant_id):
    cliente = (
        db.query(Cliente)
        .filter(
            Cliente.id == cliente_id,
            Cliente.tenant_id == tenant_id,
        )
        .first()
    )
    if not cliente:
        return None

    registros = (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.cliente_id == cliente_id,
            RegistroAluguel.tenant_id == tenant_id,
        )
        .all()
    )

    cliente.quantidade_alugueis = len(registros)
    cliente.aluguel_em_curso = any(
        (registro.status or "") in ["reservado", "entregue", "devolucao_atrasada"]
        for registro in registros
    )

    saldo = Decimal("0.00")
    for registro in registros:
        valor_cobrado = registro.valor_cobrado or Decimal("0.00")
        valor_pago = registro.valor_pago or Decimal("0.00")
        saldo += (valor_cobrado - valor_pago)

    cliente.saldo = saldo
    db.flush()
    return cliente


def _montar_cliente_view(cliente: Cliente):
    kits_nomes = sorted(
        {
            registro.kit.nome_kit
            for registro in cliente.registros_alugueis
            if registro.kit and registro.kit.nome_kit
        }
    )

    return {
        "id": str(cliente.id),
        "nome": cliente.nome,
        "telefone": cliente.telefone,
        "endereco": cliente.endereco,
        "cpf": cliente.cpf,
        "kits_nomes": kits_nomes,
        "saldo": cliente.saldo,
        "quantidade_alugueis": cliente.quantidade_alugueis,
        "aluguel_em_curso": cliente.aluguel_em_curso,
    }


def _mapa_clientes_por_telefone(db: Session, tenant_id):
    clientes = db.query(Cliente).filter(Cliente.tenant_id == tenant_id).all()
    mapa = {}

    for cliente in clientes:
        nome_real = (cliente.nome or "").strip()

        kits_nomes = sorted(
            {
                registro.kit.nome_kit
                for registro in cliente.registros_alugueis
                if registro.kit and registro.kit.nome_kit
            }
        )

        info = {
            "nome_cliente": nome_real if nome_real else None,
            "nome_exibicao": nome_real if nome_real else (cliente.telefone or ""),
            "telefone": cliente.telefone,
            "kits_nomes": kits_nomes,
            "cliente_existe": True,
        }

        for variante in _variantes_telefone_br(cliente.telefone):
            mapa[variante] = info

    return mapa


def _buscar_nome_cliente_por_telefone(db: Session, tenant_id, telefone: str):
    variantes_recebidas = _variantes_telefone_br(telefone)
    if not variantes_recebidas:
        return None

    clientes = (
        db.query(Cliente)
        .filter(Cliente.tenant_id == tenant_id)
        .all()
    )

    for cliente in clientes:
        variantes_cliente = _variantes_telefone_br(cliente.telefone)
        if variantes_recebidas & variantes_cliente:
            nome = (cliente.nome or "").strip()
            return nome if nome else None

    return None


def _query_conversas(usuario, db: Session):
    prioridade_status = case(
        (
            and_(
                Conversation.atendimento_humano == True,
                Conversation.status_atendimento == "aguardando",
            ),
            0,
        ),
        (
            and_(
                Conversation.atendimento_humano == True,
                Conversation.status_atendimento == "em_atendimento",
            ),
            1,
        ),
        (Conversation.status_atendimento == "finalizado", 2),
        else_=3,
    )

    return (
        db.query(
            MensagemWhatsapp.telefone_usuario.label("telefone_usuario"),
            func.max(MensagemWhatsapp.criada_em).label("ultima_data"),
            Conversation.status_atendimento.label("status_atendimento"),
            Conversation.atendimento_humano.label("atendimento_humano"),
            prioridade_status.label("prioridade"),
        )
        .outerjoin(
            Conversation,
            and_(
                Conversation.tenant_id == usuario.tenant_id,
                Conversation.user_wa_id == MensagemWhatsapp.telefone_usuario,
            ),
        )
        .filter(MensagemWhatsapp.tenant_id == usuario.tenant_id)
        .group_by(
            MensagemWhatsapp.telefone_usuario,
            Conversation.status_atendimento,
            Conversation.atendimento_humano,
        )
        .order_by(
            prioridade_status.asc(),
            func.max(MensagemWhatsapp.criada_em).desc(),
        )
        .all()
    )


def _enriquecer_conversas(db: Session, tenant_id, conversas, busca: str = ""):
    clientes_map = _mapa_clientes_por_telefone(db, tenant_id)
    busca_normalizada = (busca or "").strip().lower()
    resultado = []

    for conversa in conversas:
        telefone = conversa.telefone_usuario
        cliente_info = None

        for variante in _variantes_telefone_br(telefone):
            cliente_info = clientes_map.get(variante)
            if cliente_info:
                break

        nome_cliente = cliente_info["nome_cliente"] if cliente_info else None
        nome_exibicao = cliente_info["nome_exibicao"] if cliente_info else telefone
        kits_nomes = cliente_info["kits_nomes"] if cliente_info else []
        cliente_existe = bool(cliente_info)

        item = {
            "telefone_usuario": telefone,
            "ultima_data": conversa.ultima_data,
            "status_atendimento": conversa.status_atendimento,
            "atendimento_humano": conversa.atendimento_humano,
            "prioridade": conversa.prioridade,
            "nome_cliente": nome_cliente,
            "nome_exibicao": nome_exibicao,
            "kits_nomes": kits_nomes,
            "cliente_existe": cliente_existe,
        }

        if busca_normalizada:
            if not (
                busca_normalizada in (telefone or "").lower()
                or busca_normalizada in (nome_exibicao or "").lower()
                or any(busca_normalizada in (nome_kit or "").lower() for nome_kit in kits_nomes)
            ):
                continue

        resultado.append(item)

    return resultado


@router.get("/login")
def login_page(request: Request):
    return _render(
        request,
        "login.html",
        {"erro": None},
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_db),
):
    usuario = db.query(UsuarioAdmin).filter(UsuarioAdmin.email == email).first()
    if not usuario or not verificar_senha(senha, usuario.senha_hash):
        return _render(
            request,
            "login.html",
            {"erro": "Credenciais inválidas."},
            status_code=400,
        )

    response = RedirectResponse(url="/admin/conversas", status_code=302)
    response.set_cookie("admin_session", criar_token_sessao(usuario.id), httponly=True)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    return response


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    return RedirectResponse(url="/admin/conversas", status_code=302)


@router.get("/conversas", response_class=HTMLResponse)
def listar_conversas(request: Request, busca: str = "", db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    conversas = _enriquecer_conversas(db, usuario.tenant_id, _query_conversas(usuario, db), busca)
    return _render(
        request,
        "conversas.html",
        {"usuario": usuario, "conversas": conversas, "busca": busca},
    )


@router.get("/conversas/parcial", response_class=HTMLResponse)
def listar_conversas_parcial(request: Request, busca: str = "", db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return HTMLResponse("Não autorizado", status_code=401)

    conversas = _enriquecer_conversas(db, usuario.tenant_id, _query_conversas(usuario, db), busca)

    return _render(
        request,
        "partials/conversas_lista.html",
        {
            "usuario": usuario,
            "conversas": conversas,
            "busca": busca,
        },
    )


@router.get("/conversas/{telefone}", response_class=HTMLResponse)
def detalhe_conversa(telefone: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    mensagens = (
        db.query(MensagemWhatsapp)
        .filter(
            MensagemWhatsapp.tenant_id == usuario.tenant_id,
            MensagemWhatsapp.telefone_usuario == telefone,
        )
        .order_by(MensagemWhatsapp.criada_em.asc())
        .all()
    )

    conversa = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == usuario.tenant_id,
            Conversation.user_wa_id == telefone,
        )
        .first()
    )

    nome_cliente = _buscar_nome_cliente_por_telefone(db, usuario.tenant_id, telefone)
    nome_exibicao = nome_cliente or telefone
    cliente_existe = bool(nome_cliente)

    return _render(
        request,
        "conversa_detalhe.html",
        {
            "usuario": usuario,
            "telefone": telefone,
            "mensagens": mensagens,
            "conversa": conversa,
            "nome_cliente": nome_cliente,
            "nome_exibicao": nome_exibicao,
            "contato_existe": cliente_existe,
            "cliente_existe": cliente_existe,
        },
    )


@router.get("/conversas/{telefone}/mensagens", response_class=HTMLResponse)
def carregar_mensagens_conversa(telefone: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return HTMLResponse("Não autorizado", status_code=401)

    mensagens = (
        db.query(MensagemWhatsapp)
        .filter(
            MensagemWhatsapp.tenant_id == usuario.tenant_id,
            MensagemWhatsapp.telefone_usuario == telefone,
        )
        .order_by(MensagemWhatsapp.criada_em.asc())
        .all()
    )

    conversa = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == usuario.tenant_id,
            Conversation.user_wa_id == telefone,
        )
        .first()
    )

    nome_cliente = _buscar_nome_cliente_por_telefone(db, usuario.tenant_id, telefone)
    nome_exibicao = nome_cliente or telefone
    cliente_existe = bool(nome_cliente)

    return _render(
        request,
        "partials/conversa_mensagens.html",
        {
            "usuario": usuario,
            "telefone": telefone,
            "mensagens": mensagens,
            "conversa": conversa,
            "nome_cliente": nome_cliente,
            "nome_exibicao": nome_exibicao,
            "contato_existe": cliente_existe,
            "cliente_existe": cliente_existe,
        },
    )


@router.post("/conversas/{telefone}/encerrar")
def encerrar_conversa(telefone: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    conversa = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == usuario.tenant_id,
            Conversation.user_wa_id == telefone,
        )
        .first()
    )

    if conversa:
        conversa.status_atendimento = "finalizado"
        conversa.atendimento_humano = False
        conversa.last_message_at = datetime.now(timezone.utc)
        db.commit()

    return RedirectResponse(url="/admin/conversas", status_code=303)


@router.post("/webhook")
async def webhook(request: Request):
    print("\n[WEBHOOK] POST recebido")
    print("[WEBHOOK] headers:", dict(request.headers))

    raw_body = await request.body()
    print("[WEBHOOK] raw body:", raw_body.decode("utf-8", errors="ignore"))

    return Response(status_code=200)


@router.post("/conversas/{telefone}/responder")
async def responder_conversa(
    telefone: str,
    request: Request,
    mensagem: str = Form(""),
    arquivos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    mensagem = (mensagem or "").strip()
    arquivos = [a for a in arquivos if getattr(a, "filename", None)]

    if not mensagem and not arquivos:
        return RedirectResponse(url=f"/admin/conversas/{telefone}", status_code=302)

    try:
        if mensagem:
            await send_text_message(telefone, mensagem)
            salvar_mensagem(
                db=db,
                tenant_id=usuario.tenant_id,
                telefone_usuario=telefone,
                tipo_mensagem="enviada",
                conteudo=mensagem,
            )

        for arquivo in arquivos:
            conteudo = await arquivo.read()
            mime_type = (
                arquivo.content_type
                or mimetypes.guess_type(arquivo.filename)[0]
                or "application/octet-stream"
            )
            upload = await upload_media_bytes(conteudo, mime_type, arquivo.filename)
            media_id = upload.get("id")
            tipo = tipo_conteudo_por_mime(mime_type)

            if tipo == "imagem":
                await send_image_message(telefone, media_id, filename=arquivo.filename)
            elif tipo == "audio":
                await send_audio_message(telefone, media_id)
            elif tipo == "video":
                await send_video_message(telefone, media_id, filename=arquivo.filename)
            else:
                await send_document_message(telefone, media_id, filename=arquivo.filename)

            salvar_mensagem(
                db=db,
                tenant_id=usuario.tenant_id,
                telefone_usuario=telefone,
                tipo_mensagem="enviada",
                conteudo=f"[arquivo] {arquivo.filename}",
                tipo_conteudo=tipo,
                media_filename=arquivo.filename,
                media_mime_type=mime_type,
                media_id=media_id,
            )

        conversa = (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == usuario.tenant_id,
                Conversation.user_wa_id == telefone,
            )
            .first()
        )
        if conversa:
            conversa.atendimento_humano = True
            conversa.status_atendimento = "em_atendimento"
            conversa.last_message_at = datetime.now(timezone.utc)
            db.commit()

        return RedirectResponse(url=f"/admin/conversas/{telefone}", status_code=302)
    except Exception as e:
        db.rollback()
        return JSONResponse(
            {"ok": False, "error": f"Erro ao enviar mensagem: {str(e)}"},
            status_code=500,
        )


@router.get("/kits", response_class=HTMLResponse)
def listar_kits(request: Request, busca: str = "", db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    query = db.query(KitFesta).filter(
        KitFesta.tenant_id == usuario.tenant_id,
        KitFesta.ativo == True,
    )

    if busca:
        termo = f"%{busca}%"
        query = query.filter(
            or_(
                KitFesta.nome_kit.ilike(termo),
                KitFesta.categoria.ilike(termo),
                KitFesta.tema.ilike(termo),
                KitFesta.codigo_kit.ilike(termo),
            )
        )

    kits = query.order_by(KitFesta.nome_kit.asc()).all()

    return _render(
        request,
        "kits.html",
        {"usuario": usuario, "kits": kits, "busca": busca},
    )


@router.get("/kits/novo", response_class=HTMLResponse)
def kit_novo(request: Request, db: Session = Depends(get_db)):
    if not _usuario_atual(request, db):
        return _redirect_login()
    return _render(
        request,
        "kit_novo.html",
        {"kit": None, "erro": None},
    )


@router.post("/kits/novo")
async def criar_kit(
    request: Request,
    nome_kit: str = Form(...),
    categoria: str = Form(""),
    tema: str = Form(""),
    valor_locacao: str = Form(""),
    status_disponibilidade: str = Form("Disponível"),
    quantidade_itens: str = Form(""),
    descricao: str = Form(""),
    observacoes: str = Form(""),
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    codigo_kit = _gerar_codigo_kit(db, usuario.tenant_id)

    kit = KitFesta(
        tenant_id=usuario.tenant_id,
        nome_kit=(nome_kit or "").strip(),
        categoria=(categoria or "").strip() or None,
        tema=(tema or "").strip() or None,
        codigo_kit=codigo_kit,
        valor_locacao=(valor_locacao or "").strip() or None,
        status_disponibilidade=(status_disponibilidade or "").strip() or "Disponível",
        quantidade_itens=(quantidade_itens or "").strip() or None,
        descricao=(descricao or "").strip() or None,
        observacoes=(observacoes or "").strip() or None,
    )

    db.add(kit)
    db.flush()

    pasta_upload = Path("app/static/uploads/kits")
    pasta_upload.mkdir(parents=True, exist_ok=True)

    ordem = 0
    for foto in fotos:
        if not foto or not foto.filename:
            continue

        extensao = Path(foto.filename).suffix.lower() or ".jpg"
        nome_arquivo = f"{uuid.uuid4()}{extensao}"
        caminho_arquivo = pasta_upload / nome_arquivo

        conteudo = await foto.read()
        with open(caminho_arquivo, "wb") as f:
            f.write(conteudo)

        foto_url = f"/static/uploads/kits/{nome_arquivo}"

        db.add(
            KitFoto(
                kit_id=kit.id,
                foto_url=foto_url,
                ordem=ordem,
            )
        )
        ordem += 1

    db.commit()
    return RedirectResponse(url="/admin/kits", status_code=303)


@router.get("/kits/{kit_id}/editar", response_class=HTMLResponse)
def editar_kit_page(kit_id: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    kit = _buscar_kit_do_tenant(db, usuario.tenant_id, kit_id)

    if not kit:
        return RedirectResponse(url="/admin/kits", status_code=302)

    return _render(
        request,
        "kit_editar.html",
        {
            "usuario": usuario,
            "kit": kit,
        },
    )


@router.post("/kits/{kit_id}/editar")
async def editar_kit_submit(
    kit_id: str,
    request: Request,
    categoria: str = Form(""),
    tema: str = Form(""),
    valor_locacao: str = Form(""),
    status_disponibilidade: str = Form("Disponível"),
    quantidade_itens: str = Form(""),
    descricao: str = Form(""),
    observacoes: str = Form(""),
    fotos_excluir: list[str] = Form(default=[]),
    fotos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    kit = _buscar_kit_do_tenant(db, usuario.tenant_id, kit_id)

    if not kit:
        return RedirectResponse(url="/admin/kits", status_code=302)

    kit.categoria = (categoria or "").strip() or None
    kit.tema = (tema or "").strip() or None
    kit.valor_locacao = (valor_locacao or "").strip() or None
    kit.status_disponibilidade = (status_disponibilidade or "").strip() or "Disponível"
    kit.quantidade_itens = (quantidade_itens or "").strip() or None
    kit.descricao = (descricao or "").strip() or None
    kit.observacoes = (observacoes or "").strip() or None

    fotos_excluir_ids = [_parse_uuid(fid) for fid in fotos_excluir]
    fotos_excluir_ids = [fid for fid in fotos_excluir_ids if fid]

    if fotos_excluir_ids:
        fotos_para_apagar = (
            db.query(KitFoto)
            .filter(KitFoto.id.in_(fotos_excluir_ids), KitFoto.kit_id == kit.id)
            .all()
        )

        for foto in fotos_para_apagar:
            db.delete(foto)

    upload_dir = Path("app/static/uploads/kits")
    upload_dir.mkdir(parents=True, exist_ok=True)

    for foto in fotos:
        if foto and foto.filename:
            extensao = Path(foto.filename).suffix.lower() or ".jpg"
            nome_arquivo = f"{uuid.uuid4()}{extensao}"
            caminho_arquivo = upload_dir / nome_arquivo

            conteudo = await foto.read()
            with open(caminho_arquivo, "wb") as f:
                f.write(conteudo)

            db.add(
                KitFoto(
                    kit_id=kit.id,
                    foto_url=f"/static/uploads/kits/{nome_arquivo}",
                )
            )

    db.commit()
    return RedirectResponse(url=f"/admin/kits/{kit.id}/editar", status_code=302)


@router.post("/kits/{kit_id}/excluir")
def excluir_kit_submit(kit_id: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    kit = _buscar_kit_do_tenant(db, usuario.tenant_id, kit_id)

    if not kit:
        return RedirectResponse("/admin/kits", status_code=302)

    kit.ativo = False
    db.delete(kit)

    db.commit()
    return RedirectResponse("/admin/kits", status_code=302)


@router.get("/clientes", response_class=HTMLResponse)
def listar_clientes(request: Request, busca: str = "", db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    query = db.query(Cliente).filter(Cliente.tenant_id == usuario.tenant_id)

    if busca:
        termo = f"%{busca.strip()}%"
        query = query.filter(
            or_(
                Cliente.nome.ilike(termo),
                Cliente.telefone.ilike(termo),
                Cliente.endereco.ilike(termo),
                Cliente.cpf.ilike(termo),
                Cliente.registros_alugueis.any(
                    RegistroAluguel.kit.has(KitFesta.nome_kit.ilike(termo))
                ),
            )
        )

    clientes_db = query.order_by(Cliente.nome.asc()).all()
    clientes = [_montar_cliente_view(cliente) for cliente in clientes_db]

    return _render(
        request,
        "clientes.html",
        {
            "usuario": usuario,
            "clientes": clientes,
            "busca": busca,
        },
    )


@router.get("/clientes/novo", response_class=HTMLResponse)
def novo_cliente_form(request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    return _render(
        request,
        "cliente_novo.html",
        {
            "usuario": usuario,
            "erro": None,
        },
    )


@router.post("/clientes/novo", response_class=HTMLResponse)
def novo_cliente_submit(
    request: Request,
    nome: str = Form(...),
    telefone: str = Form(...),
    endereco: str = Form(""),
    cpf: str = Form(""),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    nome = (nome or "").strip()
    telefone_digitado = telefone
    telefone = _canonizar_telefone_br(telefone)
    endereco = (endereco or "").strip() or None
    cpf = _somente_digitos(cpf) if cpf else None

    if not nome or not telefone:
        return _render(
            request,
            "cliente_novo.html",
            {
                "usuario": usuario,
                "erro": "Nome e telefone são obrigatórios.",
            },
            status_code=400,
        )

    if not _telefone_brasileiro_valido_flexivel(telefone_digitado):
        return _render(
            request,
            "cliente_novo.html",
            {
                "usuario": usuario,
                "erro": "Informe um telefone válido no formato brasileiro com +55 e DDD.",
            },
            status_code=400,
        )

    if cpf and not _cpf_valido(cpf):
        return _render(
            request,
            "cliente_novo.html",
            {
                "usuario": usuario,
                "erro": "Informe um CPF válido.",
            },
            status_code=400,
        )

    cliente_existente = (
        db.query(Cliente)
        .filter(
            Cliente.tenant_id == usuario.tenant_id,
            Cliente.telefone == telefone,
        )
        .first()
    )
    if cliente_existente:
        return _render(
            request,
            "cliente_novo.html",
            {
                "usuario": usuario,
                "erro": "Já existe um cliente com esse telefone para esta empresa.",
            },
            status_code=400,
        )

    try:
        cliente = Cliente(
            tenant_id=usuario.tenant_id,
            nome=nome,
            telefone=telefone,
            endereco=endereco,
            cpf=cpf,
        )
        db.add(cliente)
        db.commit()
        return RedirectResponse("/admin/clientes", status_code=302)
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            "cliente_novo.html",
            {
                "usuario": usuario,
                "erro": "Não foi possível cadastrar o cliente.",
            },
            status_code=400,
        )


@router.get("/clientes/{cliente_id}/editar", response_class=HTMLResponse)
def editar_cliente_form(cliente_id: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    cliente = _buscar_cliente_do_tenant(db, usuario.tenant_id, cliente_id)
    if not cliente:
        return RedirectResponse("/admin/clientes", status_code=302)

    return _render(
        request,
        "cliente_editar.html",
        {
            "usuario": usuario,
            "cliente": cliente,
            "erro": None,
        },
    )


@router.post("/clientes/{cliente_id}/editar", response_class=HTMLResponse)
def editar_cliente_submit(
    cliente_id: str,
    request: Request,
    nome: str = Form(...),
    telefone: str = Form(...),
    endereco: str = Form(""),
    saldo: str = Form("0"),
    cpf: str = Form(""),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    cliente = _buscar_cliente_do_tenant(db, usuario.tenant_id, cliente_id)
    if not cliente:
        return RedirectResponse("/admin/clientes", status_code=302)

    nome = (nome or "").strip()
    telefone_digitado = telefone
    telefone = _canonizar_telefone_br(telefone)
    endereco = (endereco or "").strip() or None
    cpf = _somente_digitos(cpf) if cpf else None

    saldo_str = (saldo or "0").strip()
    saldo_str = saldo_str.replace("R$", "").replace(" ", "")

    if "," in saldo_str:
        saldo_str = saldo_str.replace(".", "").replace(",", ".")
    else:
        saldo_str = saldo_str.replace(",", ".")

    if not nome or not telefone:
        return _render(
            request,
            "cliente_editar.html",
            {
                "usuario": usuario,
                "cliente": cliente,
                "erro": "Nome e telefone são obrigatórios.",
            },
            status_code=400,
        )

    if not _telefone_brasileiro_valido_flexivel(telefone_digitado):
        return _render(
            request,
            "cliente_editar.html",
            {
                "usuario": usuario,
                "cliente": cliente,
                "erro": "Informe um telefone válido no formato brasileiro com +55 e DDD.",
            },
            status_code=400,
        )

    if cpf and not _cpf_valido(cpf):
        return _render(
            request,
            "cliente_editar.html",
            {
                "usuario": usuario,
                "cliente": cliente,
                "erro": "Informe um CPF válido.",
            },
            status_code=400,
        )

    try:
        saldo_decimal = Decimal(saldo_str or "0").quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return _render(
            request,
            "cliente_editar.html",
            {
                "usuario": usuario,
                "cliente": cliente,
                "erro": "Informe um saldo válido.",
            },
            status_code=400,
        )

    cliente_existente = (
        db.query(Cliente)
        .filter(
            Cliente.tenant_id == usuario.tenant_id,
            Cliente.telefone == telefone,
            Cliente.id != cliente.id,
        )
        .first()
    )
    if cliente_existente:
        return _render(
            request,
            "cliente_editar.html",
            {
                "usuario": usuario,
                "cliente": cliente,
                "erro": "Já existe outro cliente com esse telefone para esta empresa.",
            },
            status_code=400,
        )

    try:
        cliente.nome = nome
        cliente.telefone = telefone
        cliente.endereco = endereco
        cliente.cpf = cpf
        cliente.saldo = saldo_decimal

        db.commit()
        return RedirectResponse("/admin/clientes", status_code=302)

    except IntegrityError:
        db.rollback()
        return _render(
            request,
            "cliente_editar.html",
            {
                "usuario": usuario,
                "cliente": cliente,
                "erro": "Não foi possível atualizar o cliente.",
            },
            status_code=400,
        )


@router.post("/clientes/{cliente_id}/excluir")
def excluir_cliente_submit(cliente_id: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    cliente = _buscar_cliente_do_tenant(db, usuario.tenant_id, cliente_id)
    if not cliente:
        return RedirectResponse("/admin/clientes", status_code=302)

    db.delete(cliente)
    db.commit()
    return RedirectResponse("/admin/clientes", status_code=302)


@router.get("/configuracoes", response_class=HTMLResponse)
def configuracoes_page(request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    empresa = db.query(Tenant).filter(Tenant.id == usuario.tenant_id).first()

    return _render(
        request,
        "configuracoes.html",
        {
            "usuario": usuario,
            "escola": empresa,
            "empresa": empresa,
        },
    )


@router.get("/registros-alugueis", response_class=HTMLResponse)
def listar_registros_alugueis(
    request: Request,
    busca: str = "",
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    query = db.query(RegistroAluguel).filter(RegistroAluguel.tenant_id == usuario.tenant_id)

    if busca:
        termo = f"%{busca.strip()}%"
        query = query.filter(
            or_(
                RegistroAluguel.status.ilike(termo),
                RegistroAluguel.pagamento_status.ilike(termo),
                RegistroAluguel.pagamento_metodo.ilike(termo),
                RegistroAluguel.cliente.has(Cliente.nome.ilike(termo)),
                RegistroAluguel.kit.has(KitFesta.nome_kit.ilike(termo)),
            )
        )

    registros = query.order_by(RegistroAluguel.created_at.desc()).all()

    return _render(
        request,
        "registros-alugueis.html",
        {
            "usuario": usuario,
            "registros": registros,
            "busca": busca,
        },
    )


@router.get("/registros-alugueis/novo", response_class=HTMLResponse)
def novo_registro_aluguel_form(request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    clientes = (
        db.query(Cliente)
        .filter(Cliente.tenant_id == usuario.tenant_id)
        .order_by(Cliente.nome.asc())
        .all()
    )
    kits = (
        db.query(KitFesta)
        .filter(KitFesta.tenant_id == usuario.tenant_id, KitFesta.ativo == True)
        .order_by(KitFesta.nome_kit.asc())
        .all()
    )

    return _render(
        request,
        "registro_aluguel_novo.html",
        {
            "usuario": usuario,
            "clientes": clientes,
            "kits": kits,
            "registro": None,
            "erro": None,
            "data_reserva_valor": "",
            "data_entrega_valor": "",
        },
    )


@router.post("/registros-alugueis/novo", response_class=HTMLResponse)
def novo_registro_aluguel_submit(
    request: Request,
    cliente_id: str = Form(...),
    kit_id: str = Form(...),
    data_reserva: str = Form(""),
    data_entrega: str = Form(""),
    valor_cobrado: str = Form(""),
    valor_pago: str = Form(""),
    pagamento_status: str = Form(""),
    pagamento_metodo: str = Form(""),
    status: str = Form("reservado"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    clientes = (
        db.query(Cliente)
        .filter(Cliente.tenant_id == usuario.tenant_id)
        .order_by(Cliente.nome.asc())
        .all()
    )
    kits = (
        db.query(KitFesta)
        .filter(KitFesta.tenant_id == usuario.tenant_id, KitFesta.ativo == True)
        .order_by(KitFesta.nome_kit.asc())
        .all()
    )

    cliente_uuid = _parse_uuid(cliente_id)
    kit_uuid = _parse_uuid(kit_id)

    if not cliente_uuid or not kit_uuid:
        return _render(
            request,
            "registro_aluguel_novo.html",
            {
                "usuario": usuario,
                "clientes": clientes,
                "kits": kits,
                "registro": None,
                "erro": "Cliente ou kit inválido.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    cliente = (
        db.query(Cliente)
        .filter(Cliente.id == cliente_uuid, Cliente.tenant_id == usuario.tenant_id)
        .first()
    )
    kit = (
        db.query(KitFesta)
        .filter(KitFesta.id == kit_uuid, KitFesta.tenant_id == usuario.tenant_id)
        .first()
    )

    if not cliente or not kit:
        return _render(
            request,
            "registro_aluguel_novo.html",
            {
                "usuario": usuario,
                "clientes": clientes,
                "kits": kits,
                "registro": None,
                "erro": "Cliente ou kit não encontrado.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    if _cliente_esta_bloqueado_por_debito(cliente):
        return _render(
            request,
            "registro_aluguel_novo.html",
            {
                "usuario": usuario,
                "clientes": clientes,
                "kits": kits,
                "registro": None,
                "erro": "Este cliente possui débito em aberto e não pode realizar novo aluguel até regularizar a situação.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    data_reserva_dt = _parse_date(data_reserva)
    data_entrega_dt = _parse_date(data_entrega)

    if not data_reserva_dt or not data_entrega_dt:
        return _render(
            request,
            "registro_aluguel_novo.html",
            {
                "usuario": usuario,
                "clientes": clientes,
                "kits": kits,
                "registro": None,
                "erro": "Informe datas válidas para reserva e entrega.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    if data_entrega_dt < data_reserva_dt:
        return _render(
            request,
            "registro_aluguel_novo.html",
            {
                "usuario": usuario,
                "clientes": clientes,
                "kits": kits,
                "registro": None,
                "erro": "A data de entrega não pode ser menor que a data de reserva.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    if existe_conflito_reserva(db, usuario.tenant_id, kit.id, data_reserva_dt, data_entrega_dt):
        return _render(
            request,
            "registro_aluguel_novo.html",
            {
                "usuario": usuario,
                "clientes": clientes,
                "kits": kits,
                "registro": None,
                "erro": "Este kit já está reservado nesse período.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    registro = RegistroAluguel(
        tenant_id=usuario.tenant_id,
        cliente_id=cliente.id,
        kit_id=kit.id,
        data_reserva=data_reserva_dt,
        data_entrega=data_entrega_dt,
        valor_cobrado=_to_decimal(valor_cobrado),
        valor_pago=_to_decimal(valor_pago),
        pagamento_status=(pagamento_status or "").strip() or None,
        pagamento_metodo=(pagamento_metodo or "").strip() or None,
        status=(status or "").strip() or "reservado",
        observacoes=(observacoes or "").strip() or None,
    )

    db.add(registro)
    db.flush()

    _recalcular_cliente(db, cliente.id, usuario.tenant_id)
    db.commit()

    sincronizar_disponibilidade_kit(db, kit.id, usuario.tenant_id)

    return RedirectResponse("/admin/registros-alugueis", status_code=302)


@router.get("/registros-alugueis/{registro_id}/editar", response_class=HTMLResponse)
def editar_registro_aluguel_form(
    registro_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    registro = _buscar_registro_do_tenant(db, usuario.tenant_id, registro_id)
    if not registro:
        return RedirectResponse("/admin/registros-alugueis", status_code=302)

    clientes = (
        db.query(Cliente)
        .filter(Cliente.tenant_id == usuario.tenant_id)
        .order_by(Cliente.nome.asc())
        .all()
    )
    kits = (
        db.query(KitFesta)
        .filter(KitFesta.tenant_id == usuario.tenant_id, KitFesta.ativo == True)
        .order_by(KitFesta.nome_kit.asc())
        .all()
    )

    data_reserva_valor = registro.data_reserva.strftime("%Y-%m-%d") if registro.data_reserva else ""
    data_entrega_valor = registro.data_entrega.strftime("%Y-%m-%d") if registro.data_entrega else ""

    return _render(
        request,
        "editar_registro.html",
        {
            "usuario": usuario,
            "registro": registro,
            "clientes": clientes,
            "kits": kits,
            "erro": None,
            "data_reserva_valor": data_reserva_valor,
            "data_entrega_valor": data_entrega_valor,
        },
    )


@router.post("/registros-alugueis/{registro_id}/editar", response_class=HTMLResponse)
def editar_registro_aluguel_submit(
    registro_id: str,
    request: Request,
    cliente_id: str = Form(...),
    kit_id: str = Form(...),
    data_reserva: str = Form(""),
    data_entrega: str = Form(""),
    valor_cobrado: str = Form(""),
    valor_pago: str = Form(""),
    pagamento_status: str = Form(""),
    pagamento_metodo: str = Form(""),
    status: str = Form("reservado"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    registro = _buscar_registro_do_tenant(db, usuario.tenant_id, registro_id)
    if not registro:
        return RedirectResponse("/admin/registros-alugueis", status_code=302)

    clientes = (
        db.query(Cliente)
        .filter(Cliente.tenant_id == usuario.tenant_id)
        .order_by(Cliente.nome.asc())
        .all()
    )
    kits = (
        db.query(KitFesta)
        .filter(KitFesta.tenant_id == usuario.tenant_id, KitFesta.ativo == True)
        .order_by(KitFesta.nome_kit.asc())
        .all()
    )

    cliente_uuid = _parse_uuid(cliente_id)
    kit_uuid = _parse_uuid(kit_id)

    if not cliente_uuid or not kit_uuid:
        return _render(
            request,
            "editar_registro.html",
            {
                "usuario": usuario,
                "registro": registro,
                "clientes": clientes,
                "kits": kits,
                "erro": "Cliente ou kit inválido.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    cliente = (
        db.query(Cliente)
        .filter(Cliente.id == cliente_uuid, Cliente.tenant_id == usuario.tenant_id)
        .first()
    )
    kit = (
        db.query(KitFesta)
        .filter(KitFesta.id == kit_uuid, KitFesta.tenant_id == usuario.tenant_id)
        .first()
    )

    if not cliente or not kit:
        return _render(
            request,
            "editar_registro.html",
            {
                "usuario": usuario,
                "registro": registro,
                "clientes": clientes,
                "kits": kits,
                "erro": "Cliente ou kit não encontrado.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    if _cliente_esta_bloqueado_por_debito(cliente) and str(registro.cliente_id) != str(cliente.id):
        return _render(
            request,
            "editar_registro.html",
            {
                "usuario": usuario,
                "registro": registro,
                "clientes": clientes,
                "kits": kits,
                "erro": "Este cliente possui débito em aberto e não pode ser vinculado a um novo aluguel até regularizar a situação.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    data_reserva_dt = _parse_date(data_reserva)
    data_entrega_dt = _parse_date(data_entrega)

    if not data_reserva_dt or not data_entrega_dt:
        return _render(
            request,
            "editar_registro.html",
            {
                "usuario": usuario,
                "registro": registro,
                "clientes": clientes,
                "kits": kits,
                "erro": "Informe datas válidas para reserva e entrega.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    if data_entrega_dt < data_reserva_dt:
        return _render(
            request,
            "editar_registro.html",
            {
                "usuario": usuario,
                "registro": registro,
                "clientes": clientes,
                "kits": kits,
                "erro": "A data de entrega não pode ser menor que a data de reserva.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    if existe_conflito_reserva(
        db,
        usuario.tenant_id,
        kit.id,
        data_reserva_dt,
        data_entrega_dt,
        ignorar_registro_id=registro.id,
    ):
        return _render(
            request,
            "editar_registro.html",
            {
                "usuario": usuario,
                "registro": registro,
                "clientes": clientes,
                "kits": kits,
                "erro": "Este kit já está reservado nesse período.",
                "data_reserva_valor": data_reserva,
                "data_entrega_valor": data_entrega,
            },
            status_code=400,
        )

    cliente_id_antigo = registro.cliente_id
    kit_id_antigo = registro.kit_id

    registro.cliente_id = cliente.id
    registro.kit_id = kit.id
    registro.data_reserva = data_reserva_dt
    registro.data_entrega = data_entrega_dt
    registro.valor_cobrado = _to_decimal(valor_cobrado)
    registro.valor_pago = _to_decimal(valor_pago)
    registro.pagamento_status = (pagamento_status or "").strip() or None
    registro.pagamento_metodo = (pagamento_metodo or "").strip() or None
    registro.status = (status or "").strip() or "reservado"
    registro.observacoes = (observacoes or "").strip() or None

    db.flush()

    _recalcular_cliente(db, cliente.id, usuario.tenant_id)
    if str(cliente_id_antigo) != str(cliente.id):
        _recalcular_cliente(db, cliente_id_antigo, usuario.tenant_id)

    db.commit()

    sincronizar_disponibilidade_kit(db, registro.kit_id, usuario.tenant_id)
    if str(kit_id_antigo) != str(registro.kit_id):
        sincronizar_disponibilidade_kit(db, kit_id_antigo, usuario.tenant_id)

    return RedirectResponse("/admin/registros-alugueis", status_code=302)


@router.post("/registros-alugueis/{registro_id}/entregar")
def marcar_entrega_registro(
    registro_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    registro = _buscar_registro_do_tenant(db, usuario.tenant_id, registro_id)
    if not registro:
        return RedirectResponse("/admin/registros-alugueis", status_code=302)

    registro.status = "entregue"

    db.flush()
    _recalcular_cliente(db, registro.cliente_id, usuario.tenant_id)
    db.commit()

    sincronizar_disponibilidade_kit(db, registro.kit_id, usuario.tenant_id)

    return RedirectResponse("/admin/registros-alugueis", status_code=302)


@router.post("/registros-alugueis/{registro_id}/devolver")
def marcar_devolucao_registro(
    registro_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    registro = _buscar_registro_do_tenant(db, usuario.tenant_id, registro_id)
    if not registro:
        return RedirectResponse("/admin/registros-alugueis", status_code=302)

    registro.status = "finalizado"

    db.flush()
    _recalcular_cliente(db, registro.cliente_id, usuario.tenant_id)
    db.commit()

    sincronizar_disponibilidade_kit(db, registro.kit_id, usuario.tenant_id)

    return RedirectResponse("/admin/registros-alugueis", status_code=302)


@router.post("/registros-alugueis/{registro_id}/cancelar")
def cancelar_registro_aluguel(
    registro_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    registro = _buscar_registro_do_tenant(db, usuario.tenant_id, registro_id)
    if not registro:
        return RedirectResponse("/admin/registros-alugueis", status_code=302)

    registro.status = "cancelado"

    db.flush()
    _recalcular_cliente(db, registro.cliente_id, usuario.tenant_id)
    db.commit()

    sincronizar_disponibilidade_kit(db, registro.kit_id, usuario.tenant_id)

    return RedirectResponse("/admin/registros-alugueis", status_code=302)


@router.post("/conversas/{telefone}/apagar")
def apagar_conversa(telefone: str, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    conversa = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == usuario.tenant_id,
            Conversation.user_wa_id == telefone,
        )
        .first()
    )

    mensagens = (
        db.query(MensagemWhatsapp)
        .filter(
            MensagemWhatsapp.tenant_id == usuario.tenant_id,
            MensagemWhatsapp.telefone_usuario == telefone,
        )
        .all()
    )

    for mensagem in mensagens:
        db.delete(mensagem)

    if conversa:
        db.delete(conversa)

    db.commit()
    return RedirectResponse(url="/admin/conversas", status_code=303)


@router.post("/registros-alugueis/{registro_id}/excluir")
def excluir_registro_aluguel(
    registro_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    usuario = _usuario_atual(request, db)
    if not usuario:
        return _redirect_login()

    registro = _buscar_registro_do_tenant(db, usuario.tenant_id, registro_id)
    if not registro:
        return RedirectResponse("/admin/registros-alugueis", status_code=302)

    cliente_id = registro.cliente_id
    kit_id = registro.kit_id

    db.delete(registro)
    db.flush()

    _recalcular_cliente(db, cliente_id, usuario.tenant_id)
    db.commit()

    sincronizar_disponibilidade_kit(db, kit_id, usuario.tenant_id)

    return RedirectResponse("/admin/registros-alugueis", status_code=302)
