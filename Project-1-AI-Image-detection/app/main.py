import os
import asyncio
import tempfile
import base64
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from PIL import Image
import logging

from .modules.forensics_engine import EnterpriseImageForensicsEngine
from .modules.ai_detector import AIImageDetector

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Production Image Forensics API",
    version="8.1.0 (Health Check Added)",
    description="Submit local paths, HTTP URLs, or Base64 strings. Returns is_edited and is_ai_generated.",
)

forensics_engine = EnterpriseImageForensicsEngine()
ai_detector = AIImageDetector()

api_queue = asyncio.Semaphore(1)

# ---------- Pydantic Models ----------
class BulkImageRequest(BaseModel):
    imgpaths: List[str] = Field(
        ..., 
        description="List of local paths, HTTP URLs, or Base64 encoded strings",
        examples=[["https://example.com/img.jpg", "data:image/jpeg;base64,/9j/4AAQSkZJRg..."]]
    )

class ForensicsReport(BaseModel):
    is_suspicious: bool
    risk_score: float
    flags: List[str]
    metrics: Dict[str, Any]

class AIDetectionReport(BaseModel):
    success: bool
    is_ai_generated: Optional[bool] = None
    ai_score: Optional[float] = None
    operations_used: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    error: Optional[str] = None

class ImageResponse(BaseModel):
    success: bool
    imgpath: str
    dimensions: Optional[str] = None
    format: Optional[str] = None
    is_edited: Optional[bool] = None
    is_ai_generated: Optional[bool] = None
    ai_detection: Optional[AIDetectionReport] = None 
    forensics: Optional[ForensicsReport] = None
    error: Optional[str] = None

class BulkImageResponse(BaseModel):
    total_images: int
    processed: int
    results: List[ImageResponse]

# ---------- Config ----------
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}
BASE_DIR = Path.cwd()

def is_safe_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(BASE_DIR.resolve())
        return True
    except ValueError:
        return False


# ==========================================
# ROOT & HEALTH ROUTES
# ==========================================
@app.get("/")
def root():
    return {"status": "ok", "message": "Production Image Forensics API is running"}

@app.get("/health")
def health():
    # You can add database checks or queue checks here in the future
    return {
        "status": "healthy", 
        "api_keys_loaded": len(ai_detector.keys) > 0
    }


# 🛡️ SAFE QUEUE TRIGGER
async def trigger_ai_detector_production(img_path: str):
    try:
        await asyncio.wait_for(api_queue.acquire(), timeout=15.0)
    except asyncio.TimeoutError:
        return {"error": "Server busy. Try again shortly."}

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, ai_detector.detect, img_path)
        await asyncio.sleep(1.0) 
        return result
    finally:
        api_queue.release()


def download_image(url: str) -> str:
    try:
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None


def decode_base64_to_temp(base64_str: str) -> str:
    try:
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        image_bytes = base64.b64decode(base64_str)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        temp_file.write(image_bytes)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        logger.error(f"Failed to decode Base64 string: {e}")
        return None


async def process_single_image(input_str: str) -> ImageResponse:
    temp_path = None
    
    # 1. Determine input type (Base64, URL, or Local Path)
    if input_str.startswith("data:image") or (len(input_str) > 200 and "base64" in input_str[:30]):
        logger.info("Received Base64 string. Decoding...")
        loop = asyncio.get_running_loop()
        temp_path = await loop.run_in_executor(None, decode_base64_to_temp, input_str)
        if not temp_path:
            return ImageResponse(success=False, imgpath="[Base64 String]", error="Invalid Base64 image data")
        img_path = Path(temp_path)

    elif input_str.startswith("http://") or input_str.startswith("https://"):
        logger.info(f"Downloading image from URL: {input_str}")
        loop = asyncio.get_running_loop()
        temp_path = await loop.run_in_executor(None, download_image, input_str)
        if not temp_path:
            return ImageResponse(success=False, imgpath=input_str, error="Failed to download image from URL")
        img_path = Path(temp_path)

    else:
        img_path = Path(input_str)
        if not is_safe_path(img_path):
            return ImageResponse(success=False, imgpath=input_str, error="Path outside allowed directory")
        if not img_path.exists() or not img_path.is_file():
            return ImageResponse(success=False, imgpath=input_str, error="File not found")
        if img_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            return ImageResponse(success=False, imgpath=input_str, error="Unsupported extension")

    # 2. Validate it's a real image
    try:
        with Image.open(img_path) as im:
            width, height = im.size
            img_format = im.format
    except Exception as e:
        if temp_path: os.remove(temp_path)
        return ImageResponse(success=False, imgpath=input_str, error=f"Not a valid image: {e}")

    # LAYER 1: Forensics
    loop = asyncio.get_running_loop()
    forensics_raw = await loop.run_in_executor(None, forensics_engine.analyze_image, str(img_path))
    
    if "error" in forensics_raw:
        if temp_path: os.remove(temp_path)
        return ImageResponse(success=False, imgpath=input_str, error=f"Forensics error: {forensics_raw['error']}")

    forensics_report = ForensicsReport(
        is_suspicious=forensics_raw["is_suspicious"],
        risk_score=forensics_raw["risk_score"],
        flags=forensics_raw["flags"],
        metrics=forensics_raw["metrics"],
    )

    # LAYER 2: AI Detection (Queued)
    ai_report = None
    if not forensics_raw["is_edited"]:
        ai_raw = await trigger_ai_detector_production(str(img_path))
        if "error" in ai_raw:
            ai_report = AIDetectionReport(success=False, error=ai_raw["error"])
        else:
            ai_report = AIDetectionReport(**ai_raw)

    # 🧹 CLEANUP
    if temp_path:
        try:
            os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp file {temp_path}: {e}")

    display_path = input_str if not input_str.startswith("data:image") else "[Base64 String]"
    
    # Safely extract the AI status for the top-level response
    ai_status = False
    if ai_report and ai_report.success:
        ai_status = ai_report.is_ai_generated

    return ImageResponse(
        success=True,
        imgpath=display_path,
        dimensions=f"{width}x{height}",
        format=img_format,
        is_edited=forensics_raw["is_edited"],
        is_ai_generated=ai_status,
        ai_detection=ai_report,
        forensics=forensics_report
    )

# ---------- Unified Route ----------
@app.post("/validate-images", response_model=BulkImageResponse)
async def validate_images(payload: BulkImageRequest):
    results = []
    for path in payload.imgpaths:
        res = await process_single_image(path)
        results.append(res)
        
    return BulkImageResponse(
        total_images=len(payload.imgpaths),
        processed=len([r for r in results if r.success]),
        results=results
    )