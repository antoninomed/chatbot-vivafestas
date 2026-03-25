import uuid
import mimetypes
from pathlib import Path

import httpx

from app.config import settings


GRAPH_VERSION = getattr(settings, "META_GRAPH_VERSION", "v22.0")
PHONE_NUMBER_ID = settings.META_PHONE_NUMBER_ID
WHATSAPP_TOKEN = settings.META_ACCESS_TOKEN

BASE_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
UPLOAD_DIR = Path("app/static/uploads/whatsapp")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _headers_json():
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def _headers_auth():
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    }


def _guess_extension(filename: str | None, mime_type: str | None) -> str:
    if filename and "." in filename:
        return "." + filename.split(".")[-1].lower()

    ext = mimetypes.guess_extension(mime_type or "")
    return ext or ""


def _local_media_path(filename: str | None, mime_type: str | None) -> tuple[Path, str]:
    ext = _guess_extension(filename, mime_type)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_DIR / safe_name
    public_url = f"/static/uploads/whatsapp/{safe_name}"
    return path, public_url


async def send_text_message(to_phone: str, body: str):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": body},
    }

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()




async def send_location_message(
    to_phone: str,
    latitude: float,
    longitude: float,
    name: str = "",
    address: str = "",
):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "location",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
        },
    }

    if name:
        payload["location"]["name"] = name

    if address:
        payload["location"]["address"] = address

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()



async def send_list_message(to_phone: str, body: str, button_text: str, sections: list):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_text,
                "sections": sections,
            },
        },
    }

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()





async def upload_media_bytes(file_bytes: bytes, filename: str, mime_type: str) -> str:
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/media"

    files = {
        "file": (filename, file_bytes, mime_type),
    }

    data = {
        "messaging_product": "whatsapp",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            data=data,
            files=files,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["id"]


async def send_image_message(to_phone: str, media_id: str, caption: str = ""):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "image",
        "image": {"id": media_id},
    }

    if caption:
        payload["image"]["caption"] = caption

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()


async def send_document_message(to_phone: str, media_id: str, filename: str, caption: str = ""):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
        },
    }

    if caption:
        payload["document"]["caption"] = caption

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()


async def send_audio_message(to_phone: str, media_id: str):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "audio",
        "audio": {"id": media_id},
    }

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()


async def send_video_message(to_phone: str, media_id: str, caption: str = ""):
    url = f"{BASE_GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "video",
        "video": {"id": media_id},
    }

    if caption:
        payload["video"]["caption"] = caption

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(url, headers=_headers_json(), json=payload)
        response.raise_for_status()
        return response.json()


async def obter_url_media_meta(media_id: str) -> dict:
    url = f"{BASE_GRAPH_URL}/{media_id}"

    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.get(url, headers=_headers_auth())
        response.raise_for_status()
        return response.json()


async def baixar_media_meta_para_local(
    media_id: str,
    filename: str | None = None,
    mime_type: str | None = None,
) -> dict:
    media_info = await obter_url_media_meta(media_id)

    media_url = media_info["url"]
    mime_type_final = mime_type or media_info.get("mime_type")
    filename_final = filename or media_info.get("sha256") or f"{media_id}"

    local_path, public_url = _local_media_path(filename_final, mime_type_final)

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(media_url, headers=_headers_auth())
        response.raise_for_status()

        with open(local_path, "wb") as f:
            f.write(response.content)

    return {
        "media_id": media_id,
        "media_url": public_url,
        "media_mime_type": mime_type_final,
        "media_filename": filename_final,
        "media_sha256": media_info.get("sha256"),
    }


def tipo_conteudo_por_mime(mime_type: str | None) -> str:
    if not mime_type:
        return "arquivo"

    if mime_type.startswith("image/"):
        return "imagem"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type == "application/pdf":
        return "pdf"
    return "documento"