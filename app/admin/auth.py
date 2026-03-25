from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer, BadSignature, BadData
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
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


def obter_usuario_logado_api(request: Request):
    token = request.cookies.get("admin_session")
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")

    try:
        dados = ler_token_sessao(token)
        if not dados or "usuario_id" not in dados:
            raise HTTPException(status_code=401, detail="Sessão inválida")
        return dados
    except (BadSignature, BadData):
        raise HTTPException(status_code=401, detail="Sessão inválida")


def obter_usuario_logado(request: Request):
    token = request.cookies.get("admin_session")

    if not token:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        dados = ler_token_sessao(token)

        if not dados or "usuario_id" not in dados:
            response = RedirectResponse(url="/admin/login", status_code=303)
            response.delete_cookie("admin_session")
            return response

        return dados

    except (BadSignature, BadData):
        response = RedirectResponse(url="/admin/login", status_code=303)
        response.delete_cookie("admin_session")
        return response
