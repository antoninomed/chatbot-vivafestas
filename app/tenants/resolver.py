from sqlalchemy.orm import Session
from app.db.models import Tenant

def resolve_tenant_by_phone_number_id(db: Session, phone_number_id: str) -> Tenant | None:
    return db.query(Tenant).filter(
        Tenant.whatsapp_phone_number_id == phone_number_id,
        Tenant.is_active == True
    ).first()