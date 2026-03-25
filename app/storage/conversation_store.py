# app/storage/conversation_store.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Conversation

def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

def get_or_create_conversation(db: Session, tenant_id, user_wa_id: str) -> Conversation:
    tenant_uuid = _as_uuid(tenant_id)

    stmt = select(Conversation).where(
        Conversation.tenant_id == tenant_uuid,
        Conversation.user_wa_id == user_wa_id
    )
    conv = db.execute(stmt).scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        tenant_id=tenant_uuid,
        user_wa_id=user_wa_id,
        state="MENU",
        last_message_at=datetime.utcnow(),
    )

    # Se seu model já tiver data_json, inicializa
    if hasattr(conv, "data_json"):
        conv.data_json = {}

    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv

def save_conversation(db: Session, conv: Conversation) -> None:
    conv.last_message_at = datetime.utcnow()
    db.add(conv)
    db.commit()
    db.refresh(conv)