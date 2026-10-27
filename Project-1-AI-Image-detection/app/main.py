import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from PIL import Image

from AIimagedetector import image_detector

app = FastAPI(
    title="Image Path Validator API",
    description="Accepts a JSON payload with an image path and validates it.",
    version="1.0.0",
)

# ---------- Pydantic Models ----------
class ImageRequest(BaseModel):
    imgpath: str = Field(..., description="Path to the image file", examples=["images/sample.jpg"])


class ImageResponse(BaseModel):
    success: bool
    message: str
    imgpath: str
    exists: bool
    size_bytes: Optional[int] = None
    dimensions: Optional[str] = None
    format: Optional[str] = None


# ---------- Config ----------
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

# Optional: restrict reads to a base directory for security
BASE_DIR = Path.cwd()


def is_safe_path(path: Path) -> bool:
    """Prevent path traversal outside BASE_DIR."""
    try:
        path.resolve().relative_to(BASE_DIR.resolve())
        return True
    except ValueError:
        return False


# ---------- Routes ----------
@app.get("/")
def root():
    return {"status": "ok", "message": "Image Path Validator API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/validate-image", response_model=ImageResponse)
def validate_image(payload: ImageRequest):
    img_path = Path(payload.imgpath)

    # 1. Safety check
    if not is_safe_path(img_path):
        raise HTTPException(status_code=400, detail="Path outside allowed directory")

    # 2. Existence check
    if not img_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {payload.imgpath}")

    if not img_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    # 3. Extension check
    if img_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported extension '{img_path.suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # 4. Try to open as image
    try:
        with Image.open(img_path) as im:
            width, height = im.size
            img_format = im.format
        size_bytes = img_path.stat().st_size
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {e}")

    
    return ImageResponse(
        success=True,
        message="Image path is valid",
        imgpath=str(img_path),
        exists=True,
        size_bytes=size_bytes,
        dimensions=f"{width}x{height}",
        format=img_format,
    )