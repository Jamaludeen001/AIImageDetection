from fastapi import APIRouter

from app.controllers.punch_controller import PunchController
from app.schemas.punch_schema import PunchVerifyRequest, PunchVerifyResponse, PunchVerifyUrlRequest

router = APIRouter()


@router.get("/health")
def health():
    return PunchController().health()


@router.get("/health/live")
def health_live():
    return {"status": "healthy"}


@router.post("/punch-verify", response_model=PunchVerifyResponse)
def punch_verify(body: PunchVerifyRequest):
    return PunchController().verify(body)


@router.post("/punch-verify-urls", response_model=PunchVerifyResponse)
def punch_verify_urls(body: PunchVerifyUrlRequest):
    return PunchController().verify_urls(body)
