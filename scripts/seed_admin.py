import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Tenant, UsuarioAdmin
from app.admin.auth import gerar_hash_senha

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def run():
    db = SessionLocal()

    tenant = db.query(Tenant).filter(
        Tenant.whatsapp_phone_number_id == settings.META_PHONE_NUMBER_ID
    ).first()

    if not tenant:
        print("Tenant não encontrado.")
        return

    usuario = db.query(UsuarioAdmin).filter(UsuarioAdmin.email == "admin@escola.com").first()
    if usuario:
        print("Usuário admin já existe.")
        return

    admin = UsuarioAdmin(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        nome="Administrador",
        email="admin@escola.com",
        senha_hash=gerar_hash_senha("123456"),
        ativo=True,
    )

    db.add(admin)
    db.commit()
    print("Admin criado com sucesso.")
    print("Email: admin@escola.com")
    print("Senha: 123456")


if __name__ == "__main__":
    run()