import csv
import os
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from app.schemas.punch_schema import PunchVerifyRequest, PunchVerifyResponse, PunchVerifyUrlRequest
from app.controllers.punch_controller import PunchController

import hashlib
import hmac
import json
import logging
import os

from fastapi import BackgroundTasks, Query
from fastapi.responses import PlainTextResponse

router = APIRouter()

# Dependency Injection: Create a controller instance using the singleton service
def get_punch_controller(request: Request) -> PunchController:
    return PunchController(service=request.app.state.punch_service)

@router.get("/health")
def health(controller: PunchController = Depends(get_punch_controller)):
    return controller.health()

@router.get("/health/live")
def health_live():
    return {"status": "healthy"}

@router.post("/punch-verify", response_model=PunchVerifyResponse)
def punch_verify(
    body: PunchVerifyRequest, 
    controller: PunchController = Depends(get_punch_controller)
):
    return controller.verify(body)

@router.post("/punch-verify-urls", response_model=PunchVerifyResponse)
def punch_verify_urls(
    body: PunchVerifyUrlRequest,
    controller: PunchController = Depends(get_punch_controller)
):
    return controller.verify_urls(body)

@router.get("/api/offices")
def get_offices():
    offices = []
    # Adjust path if your uvicorn is run from a different root
    csv_path = os.path.join("data", "offices.csv") 
    
    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                offices.append({
                    "name": row.get("Office Name", "").strip(),
                    "lat": row.get("Latitude", "").strip(),
                    "lng": row.get("Longitude", "").strip()
                })
        return JSONResponse(content=offices)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="offices.csv not found in data folder")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp")
logger.setLevel(logging.INFO)

GRAPH = "https://graph.facebook.com/v21.0"

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# In-memory stores. Fine for one instance; use Redis/DB if you scale out or restart often.
_seen_ids: set[str] = set()           # dedupe, since Meta retries
_last_location: dict[str, dict] = {}  # sender -> {"lat": ..., "lng": ...}


def _valid_signature(raw_body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def _auth() -> dict:
    return {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}


def send_text(to: str, body: str) -> None:
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set; cannot reply")
        return
    try:
        r = httpx.post(
            f"{GRAPH}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers=_auth(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
            timeout=20,
        )
        if r.status_code >= 400:
            logger.error("Send failed %s: %s", r.status_code, r.text)
        else:
            logger.info("Reply sent to %s", to)
    except Exception:
        logger.exception("Send request crashed")


def download_media(media_id: str) -> tuple[bytes, str]:
    """Two steps: get the temporary URL, then download the file with the same token."""
    meta = httpx.get(f"{GRAPH}/{media_id}", headers=_auth(), timeout=20)
    meta.raise_for_status()
    info = meta.json()
    file = httpx.get(info["url"], headers=_auth(), timeout=60)
    file.raise_for_status()
    return file.content, info.get("mime_type", "image/jpeg")


def run_punch_verification(image_bytes: bytes, mime: str, location: dict | None) -> str:
    """
    TODO: connect this to your existing verification.
    Paste punch_schema.py and PunchController.verify and I'll wire it exactly.
    Must return the text to send back to the user.
    """
    loc = f" at ({location['lat']}, {location['lng']})" if location else ""
    return f"Image received ({len(image_bytes)} bytes, {mime}){loc}. Verification not connected yet."


def handle_message(msg: dict) -> None:
    msg_id = msg.get("id")
    if msg_id in _seen_ids:
        logger.info("Duplicate %s skipped", msg_id)
        return
    _seen_ids.add(msg_id)

    sender = msg.get("from")
    msg_type = msg.get("type")

    if msg_type == "text":
        logger.info("Text %s from %s: %s", msg_id, sender, msg["text"]["body"])
        send_text(sender, "Please send a location and then a photo for punch verification.")

    elif msg_type == "location":
        loc = msg["location"]
        _last_location[sender] = {"lat": loc["latitude"], "lng": loc["longitude"]}
        logger.info("Location from %s: %s", sender, _last_location[sender])
        send_text(sender, "Location saved. Now send your punch photo.")

    elif msg_type == "image":
        media_id = msg["image"]["id"]
        logger.info("Image %s from %s (media_id=%s)", msg_id, sender, media_id)
        try:
            image_bytes, mime = download_media(media_id)
            result = run_punch_verification(image_bytes, mime, _last_location.get(sender))
            send_text(sender, result)
        except Exception:
            logger.exception("Failed processing image")
            send_text(sender, "Sorry, I couldn't process that image. Please try again.")

    else:
        logger.info("Unhandled type %s from %s", msg_type, sender)


def process_whatsapp_payload(payload: dict) -> None:
    """Runs after we've already returned 200 to Meta."""
    logger.info("WHATSAPP PAYLOAD: %s", json.dumps(payload))

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            for msg in value.get("messages", []):
                try:
                    handle_message(msg)
                except Exception:
                    logger.exception("Error handling message")

            for status in value.get("statuses", []):
                logger.info(
                    "Status %s for %s: %s",
                    status.get("status"),
                    status.get("recipient_id"),
                    status.get("errors"),
                )


@router.get("/whatsapp/webhook")
def whatsapp_verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    if mode == "subscribe" and WHATSAPP_VERIFY_TOKEN and token == WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()

    if WHATSAPP_APP_SECRET:
        if not _valid_signature(raw_body, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    background_tasks.add_task(process_whatsapp_payload, payload)
    return {"status": "received"}
