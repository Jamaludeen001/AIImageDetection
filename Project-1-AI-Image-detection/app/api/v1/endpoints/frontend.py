from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "templates"

@router.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(TEMPLATES_DIR / "index.html")