from sqlalchemy.orm import Session

from app.services.consulta_kits import responder_consulta_kit


def gerar_resposta_inteligente(
    db: Session,
    tenant_id: str,
    mensagem_cliente: str,
) -> str | None:
    mensagem_cliente = (mensagem_cliente or "").strip()

    if not mensagem_cliente:
        return None

    resposta_kit = responder_consulta_kit(db, tenant_id, mensagem_cliente)
    if resposta_kit:
        return resposta_kit

    return None