from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path
from ....services.image_processor import ai_detector, attendance_ocr

router = APIRouter()

@router.get("/health")
def health():
    return {
        "status": "healthy", 
        "sightengine_keys_loaded": len(ai_detector.keys) > 0,
        "gemini_api_loaded": attendance_ocr.client is not None
    }