from sqlalchemy.orm import Session
from app.db.models import MensagemWhatsapp


def salvar_mensagem(
    db: Session,
    tenant_id,
    telefone_usuario: str,
    tipo_mensagem: str,
    conteudo: str = "",
    tipo_conteudo: str = "texto",
    media_url: str | None = None,
    media_mime_type: str | None = None,
    media_filename: str | None = None,
    media_id: str | None = None,
    mensagem_id_whatsapp: str | None = None,
):
    msg = MensagemWhatsapp(
        tenant_id=tenant_id,
        telefone_usuario=telefone_usuario,
        tipo_mensagem=tipo_mensagem,
        conteudo=conteudo or "",
        tipo_conteudo=tipo_conteudo,
        media_url=media_url,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
        media_id=media_id,
        mensagem_id_whatsapp=mensagem_id_whatsapp,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg