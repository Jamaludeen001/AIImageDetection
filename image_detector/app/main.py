import os
import shutil
import logging
import uuid
import time
from typing import List

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import UPLOAD_DIR, OUTPUT_DIR, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
from app.pipeline import ImageAnalysisPipeline
from app.ocr import extract_text as ocr_extract_text, _get_engine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ForgeryAPI")

app = FastAPI(title="Image Forgery Detection API", version="1.4")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/artifacts", StaticFiles(directory=OUTPUT_DIR), name="artifacts")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

pipeline = ImageAnalysisPipeline()


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


def _validate_and_save(upload: UploadFile) -> str:
    if not upload.content_type or not upload.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Not an image.")
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported extension.")

    unique_name = f"{uuid.uuid4().hex}_{os.path.basename(upload.filename)}"
    dest = os.path.join(UPLOAD_DIR, unique_name)

    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large.")

    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


@app.post("/detect")
async def detect_forgery(images: List[UploadFile] = File(...)):
    if len(images) != 2:
        raise HTTPException(status_code=400, detail="Exactly two images are required.")

    saved_paths: List[str] = []
    try:
        for upload in images:
            saved_paths.append(_validate_and_save(upload))

        metrics = pipeline.execute_pipeline(saved_paths[0], saved_paths[1])

        response = {"status": "success", "results": {}}
        for file_path, data in metrics.items():
            ela_name = os.path.basename(data.get("ela_map_path", "")) if data.get("ela_map_path") else ""
            edge_name = os.path.basename(data.get("edge_map_path", "")) if data.get("edge_map_path") else ""

            response["results"][os.path.basename(file_path)] = {
                "verdict": data["verdict"],
                "cloud_confidence": data["cloud_confidence"],
                "metadata_forgery_detected": data["metadata_forgery_detected"],
                "ela_map_url": f"/artifacts/{ela_name}" if ela_name else None,
                "edge_map_url": f"/artifacts/{edge_name}" if edge_name else None,
            }
        return JSONResponse(content=response)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Detection pipeline failed")
        raise HTTPException(status_code=500, detail=f"Detection failed: {str(e)}")
    finally:
        for upload in images:
            await upload.close()


@app.post("/extract-text")
async def extract_text_endpoint(image: UploadFile = File(...), side: str = Form("left")):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file is not an image.")
    
    unique_name = f"{uuid.uuid4().hex}_{os.path.basename(image.filename)}"
    dest = os.path.join(UPLOAD_DIR, unique_name)

    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(image.file, f)
            
        t0 = time.time()
        text = ocr_extract_text(dest) or ""
        elapsed = round(time.time() - t0, 2)
        
        # Extract Lat/Long
        engine = _get_engine()
        coords = engine.extract_location_and_time(text)
        
        logger.info(f"OCR on {side} finished in {elapsed}s")
        
        return JSONResponse(content={
            "status": "success",
            "side": side,
            "filename": os.path.basename(dest),
            "text": text,
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
            "elapsed_seconds": elapsed,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("OCR endpoint failed")
        raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")
    finally:
        await image.close()