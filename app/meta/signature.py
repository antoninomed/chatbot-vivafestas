import hmac
import hashlib

def verify_meta_signature(app_secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """
    header_value: e.g. "sha256=abc123..."
    """
    if not app_secret:
        # se não configurou o secret, você pode optar por não validar (dev)
        return True

    if not header_value or not header_value.startswith("sha256="):
        return False

    provided = header_value.split("sha256=", 1)[1].strip()
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)