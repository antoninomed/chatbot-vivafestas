from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer
from fastapi import Request, HTTPException
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeSerializer(settings.WEBHOOK_VERIFY_TOKEN, salt="admin-session")


def gerar_hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return pwd_context.verify(senha, senha_hash)


def criar_token_sessao(usuario_id: str) -> str:
    return serializer.dumps({"usuario_id": str(usuario_id)})


def ler_token_sessao(token: str):
    return serializer.loads(token)


def obter_usuario_logado(request: Request):
    token = request.cookies.get("admin_session")
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return ler_token_sessao(token)