from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.logging_config import new_request_id, request_id_var, setup_logging
from app.routers.punch_router import router as punch_router
from fastapi.middleware.cors import CORSMiddleware
import os

setup_logging()

app = FastAPI(title="Punch verification API")

# --- ADD THIS BLOCK ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with your frontend's actual URL
    allow_credentials=True,
    allow_methods=["*"], # This allows the OPTIONS preflight request to succeed
    allow_headers=["*"],
)
# ----------------------

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response

# --- Templates setup ---
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="sample.html",
        context={},  # add template variables here if needed
    )
# -----------------------
app.include_router(punch_router)
