from fastapi import Request
from sqlalchemy.orm import Session

from app.tenants.resolver import resolve_tenant_by_phone_number_id
from app.db.models import ProcessedMessage
from app.bot.router import handle_incoming
from app.services.mensagens import salvar_mensagem
from app.meta.whatsapp_api import (
    baixar_media_meta_para_local,
    tipo_conteudo_por_mime,
)


def _extract_text(msg: dict) -> str:
    if msg.get("type") == "text":
        return ((msg.get("text") or {}).get("body") or "").strip()
    return ""


def _extract_interactive_id(msg: dict) -> str | None:
    """
    Para cliques em botões/listas:
    - interactive.button_reply.id
    - interactive.list_reply.id
    """
    if msg.get("type") != "interactive":
        return None

    inter = msg.get("interactive") or {}
    if "button_reply" in inter:
        return (inter["button_reply"] or {}).get("id")
    if "list_reply" in inter:
        return (inter["list_reply"] or {}).get("id")
    return None


async def handle_messages(request: Request, db: Session) -> None:
    body = await request.json()

    entry = (body.get("entry") or [{}])[0]
    changes = (entry.get("changes") or [{}])[0]
    value = changes.get("value") or {}

    # Status events (delivered/failed/read)
    statuses = value.get("statuses") or []
    if statuses:
        print("[STATUSES]", statuses)
        return

    # Mensagens recebidas
    messages = value.get("messages") or []
    metadata = value.get("metadata") or {}
    phone_number_id = metadata.get("phone_number_id")

    if not phone_number_id:
        print("[WEBHOOK] missing metadata.phone_number_id")
        return

    tenant = resolve_tenant_by_phone_number_id(db, str(phone_number_id))
    if not tenant:
        print("[WEBHOOK] tenant not found for phone_number_id:", phone_number_id)
        return

    if not messages:
        return

    msg = messages[0]
    msg_id = msg.get("id")
    from_phone = msg.get("from")
    msg_type = msg.get("type")

    text = _extract_text(msg)
    button_id = _extract_interactive_id(msg)

    # Idempotência
    if msg_id:
        exists = db.query(ProcessedMessage).filter(
            ProcessedMessage.tenant_id == tenant.id,
            ProcessedMessage.message_id == msg_id
        ).first()
        if exists:
            print("[IDEMPOTENCY] already processed:", msg_id)
            return

        db.add(ProcessedMessage(tenant_id=tenant.id, message_id=msg_id))
        db.commit()

    print("[INBOUND]", {
        "tenant": tenant.name,
        "from": from_phone,
        "type": msg_type,
        "text": text,
        "button_id": button_id
    })

    if not from_phone:
        return

    # =========================
    # SALVAR MENSAGEM RECEBIDA
    # =========================

    # TEXTO
    if msg_type == "text":
        salvar_mensagem(
            db=db,
            tenant_id=tenant.id,
            telefone_usuario=from_phone,
            tipo_mensagem="recebida",
            conteudo=text,
            tipo_conteudo="texto",
            mensagem_id_whatsapp=msg_id,
        )

        await handle_incoming(
            db=db,
            tenant_id=tenant.id,
            from_phone=from_phone,
            text=text,
            button_id=None,
        )
        return

    # INTERACTIVE (botão/lista)
    if msg_type == "interactive":
        conteudo_salvo = f"[interactive:{button_id}]" if button_id else "[interactive]"

        salvar_mensagem(
            db=db,
            tenant_id=tenant.id,
            telefone_usuario=from_phone,
            tipo_mensagem="recebida",
            conteudo=conteudo_salvo,
            tipo_conteudo="texto",
            mensagem_id_whatsapp=msg_id,
        )

        await handle_incoming(
            db=db,
            tenant_id=tenant.id,
            from_phone=from_phone,
            text="",
            button_id=button_id,
        )
        return

    # MÍDIA
    if msg_type in ["image", "document", "audio", "video"]:
        bloco = msg.get(msg_type) or {}
        media_id = bloco.get("id")
        mime_type = bloco.get("mime_type")
        filename = bloco.get("filename")
        caption = bloco.get("caption", "")

        if not media_id:
            print("[WEBHOOK] mídia recebida sem media_id")
            return

        try:
            media_info = await baixar_media_meta_para_local(
                media_id=media_id,
                filename=filename,
                mime_type=mime_type,
            )

            salvar_mensagem(
                db=db,
                tenant_id=tenant.id,
                telefone_usuario=from_phone,
                tipo_mensagem="recebida",
                conteudo=caption,
                tipo_conteudo=tipo_conteudo_por_mime(media_info.get("media_mime_type")),
                media_url=media_info.get("media_url"),
                media_mime_type=media_info.get("media_mime_type"),
                media_filename=media_info.get("media_filename"),
                media_id=media_info.get("media_id"),
                mensagem_id_whatsapp=msg_id,
            )

            print("[WEBHOOK] mídia salva com sucesso:", media_info)

            # Se a mídia vier com legenda, você pode passar essa legenda ao bot.
            await handle_incoming(
                db=db,
                tenant_id=tenant.id,
                from_phone=from_phone,
                text=caption or "",
                button_id=None,
            )
            return

        except Exception as e:
            print("[WEBHOOK] erro ao baixar/salvar mídia:", repr(e))
            return

    # Fallback para outros tipos não tratados
    print("[WEBHOOK] tipo não tratado:", msg_type)