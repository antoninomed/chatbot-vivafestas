import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db.models import Tenant

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def main():
    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter(
            Tenant.whatsapp_phone_number_id == settings.META_PHONE_NUMBER_ID
        ).first()
        if existing:
            print("Tenant já existe:", existing.id)
            return

        t = Tenant(
            id=uuid.uuid4(),
            name="Kit Festa Piloto",
            whatsapp_phone_number_id=settings.META_PHONE_NUMBER_ID,
            timezone="America/Fortaleza",
            config_json={"welcome": "Bem-vindo!"},
            is_active=True,
        )
        db.add(t)
        db.commit()
        print("Tenant criado:", t.id)
    finally:
        db.close()

if __name__ == "__main__":
    main()