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

logger = logging.getLogger("whatsapp")

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")


def _valid_signature(raw_body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def process_whatsapp_payload(payload: dict) -> None:
    """Runs after we've already returned 200 to Meta."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Incoming user messages
            for msg in value.get("messages", []):
                sender = msg.get("from")
                msg_type = msg.get("type")
                msg_id = msg.get("id")

                if msg_type == "text":
                    text = msg["text"]["body"]
                    logger.info("Message %s from %s: %s", msg_id, sender, text)
                elif msg_type == "image":
                    media_id = msg["image"]["id"]
                    logger.info("Image %s from %s (media_id=%s)", msg_id, sender, media_id)
                    # TODO: download media, then pass to controller.verify(...)
                elif msg_type == "interactive":
                    logger.info("Interactive reply from %s: %s", sender, msg["interactive"])
                else:
                    logger.info("Unhandled type %s from %s", msg_type, sender)

            # Delivery statuses (sent / delivered / read / failed)
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
