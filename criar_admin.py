from passlib.hash import bcrypt
from app.db.session import SessionLocal
from app.db.models import UsuarioAdmin, Tenant
import uuid

db = SessionLocal()

tenant = db.query(Tenant).first()

admin = UsuarioAdmin(
    id=uuid.uuid4(),
    nome="Administrador",
    email="admin@vivafestas.com",
    senha_hash=bcrypt.hash("viva123"),
    tenant_id=tenant.id
)

db.add(admin)
db.commit()

print("Admin criado com sucesso")
