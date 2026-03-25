from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Conversation


def _agora_utc():
    return datetime.now(timezone.utc)


def obter_ou_criar_conversa(db: Session, tenant_id, user_wa_id: str) -> Conversation:
    conversa = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.user_wa_id == user_wa_id
        )
        .first()
    )

    if conversa:
        return conversa

    conversa = Conversation(
        tenant_id=tenant_id,
        user_wa_id=user_wa_id,
        state="inicio",
        contexto_json={},
        atendimento_humano=False,
        status_atendimento="bot",
        last_message_at=_agora_utc(),
    )

    db.add(conversa)
    db.commit()
    db.refresh(conversa)
    return conversa


def atualizar_estado_conversa(
    db: Session,
    conversa: Conversation,
    novo_estado: str,
    contexto: dict | None = None
):
    conversa.state = novo_estado

    if contexto is not None:
        conversa.contexto_json = contexto

    conversa.last_message_at = _agora_utc()

    db.add(conversa)
    db.commit()
    db.refresh(conversa)


def resetar_conversa(db: Session, conversa: Conversation):
    conversa.state = "inicio"
    conversa.contexto_json = {}
    conversa.atendimento_humano = False
    conversa.status_atendimento = "bot"
    conversa.last_message_at = _agora_utc()

    db.add(conversa)
    db.commit()
    db.refresh(conversa)


def tratar_estado_ao_receber_mensagem(db: Session, conversa: Conversation) -> Conversation:
    """
    Sempre que o usuário mandar mensagem, garantimos que a conversa
    esteja em um estado válido.

    Se a conversa estava finalizada, ela volta automaticamente
    para o fluxo do bot.
    """

    if conversa.status_atendimento == "finalizado":
        conversa.status_atendimento = "bot"
        conversa.atendimento_humano = False
        conversa.state = "inicio"
        conversa.contexto_json = {}

    conversa.last_message_at = _agora_utc()

    db.add(conversa)
    db.commit()
    db.refresh(conversa)

    return conversa