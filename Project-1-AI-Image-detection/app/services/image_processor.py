import os
import asyncio
import tempfile
import base64
import requests
from pathlib import Path
import logging
from PIL import Image

from .forensics_engine import EnterpriseImageForensicsEngine
from .ai_detector import AIImageDetector
from .ocr_detector import AttendanceOCR
from ..schemas.image import ImageResponse, ForensicsReport, AIDetectionReport, OCRReport

logger = logging.getLogger(__name__)

forensics_engine = EnterpriseImageForensicsEngine()
ai_detector = AIImageDetector()
attendance_ocr = AttendanceOCR()

api_queue = asyncio.Semaphore(1)
BASE_DIR = Path.cwd()
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

def is_safe_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(BASE_DIR.resolve())
        return True
    except ValueError:
        return False

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
    
    # --- 1. Input Routing ---
    if input_str.startswith("data:image") or (len(input_str) > 200 and "base64" in input_str[:30]):
        loop = asyncio.get_running_loop()
        temp_path = await loop.run_in_executor(None, decode_base64_to_temp, input_str)
        if not temp_path:
            return ImageResponse(success=False, imgpath="[Base64 String]", error="Invalid Base64 image data")
        img_path = Path(temp_path)

    elif input_str.startswith("http://") or input_str.startswith("https://"):
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

    # --- 2. Image Validation ---
    try:
        with Image.open(img_path) as im:
            width, height = im.size
            img_format = im.format
    except Exception as e:
        if temp_path: os.remove(temp_path)
        return ImageResponse(success=False, imgpath=input_str, error=f"Not a valid image: {e}")

    loop = asyncio.get_running_loop()
    
    # --- 3. LAYER 1: OCR EXTRACTION (GATEKEEPER) ---
    ocr_raw = await loop.run_in_executor(None, attendance_ocr.extract_attendance_data, str(img_path))
    if "error" in ocr_raw:
        if temp_path: os.remove(temp_path)
        return ImageResponse(success=False, imgpath=input_str, error=f"OCR error: {ocr_raw['error']}")
        
    ocr_report = OCRReport(**ocr_raw)
    
    # 🛑 GATEKEEPER LOGIC: Reject only if timestamp is invalid OR if watermark exists but is invalid.
    # If the watermark is completely missing (null), we pass it to the next layers.
    is_invalid_time = ocr_report.is_valid_timestamp is False
    is_invalid_mark = (ocr_report.watermark is not None) and (ocr_report.is_valid_watermark is False)

    if is_invalid_time or is_invalid_mark:
        logger.warning(f"Image rejected by OCR Gatekeeper: Invalid Time={is_invalid_time}, Invalid Mark={is_invalid_mark}")
        if temp_path: os.remove(temp_path)
        
        display_path = input_str if not input_str.startswith("data:image") else "[Base64 String]"
        
        return ImageResponse(
            success=True, 
            imgpath=display_path,
            dimensions=f"{width}x{height}",
            format=img_format,
            is_edited=None, 
            is_ai_generated=None,
            ai_detection=None,
            forensics=None,
            ocr_data=ocr_report
        )

    # --- 4. LAYER 2: FORENSICS (Only runs if OCR passes) ---
    forensics_raw = await loop.run_in_executor(None, forensics_engine.analyze_image, str(img_path))
    if "error" in forensics_raw:
        if temp_path: os.remove(temp_path)
        return ImageResponse(success=False, imgpath=input_str, error=f"Forensics error: {forensics_raw['error']}")
    forensics_report = ForensicsReport(**forensics_raw)

    # --- 5. LAYER 3: AI DETECTION (Only runs if Forensics passes) ---
    ai_report = None
    
    # 🛑 Check if the image was edited based on forensics
    if forensics_raw["is_edited"]:
        logger.info("Image flagged as EDITED by forensics. Skipping AI detection to save costs.")
    else:
        ai_raw = await trigger_ai_detector_production(str(img_path))
        if "error" in ai_raw:
            ai_report = AIDetectionReport(success=False, error=ai_raw["error"])
        else:
            ai_report = AIDetectionReport(**ai_raw)

    # --- 6. Cleanup ---
    if temp_path:
        try: os.remove(temp_path)
        except: pass

    display_path = input_str if not input_str.startswith("data:image") else "[Base64 String]"
    ai_status = ai_report.is_ai_generated if (ai_report and ai_report.success) else False

    return ImageResponse(
        success=True,
        imgpath=display_path,
        dimensions=f"{width}x{height}",
        format=img_format,
        is_edited=forensics_raw["is_edited"],
        is_ai_generated=ai_status,
        ai_detection=ai_report,
        forensics=forensics_report,
        ocr_data=ocr_report
    )
