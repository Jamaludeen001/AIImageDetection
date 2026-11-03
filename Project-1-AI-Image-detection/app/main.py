from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import os

from app.logging_config import new_request_id, request_id_var, setup_logging
from app.routers.punch_router import router as punch_router
from app.services.punch_service import PunchService

setup_logging()

# 1. Lifespan: Initialize heavy services ONCE on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.punch_service = PunchService()
    yield
    # Cleanup resources on shutdown
    if hasattr(app.state.punch_service, "gemini") and app.state.punch_service.gemini:
        app.state.punch_service.gemini.close()

app = FastAPI(title="Punch verification API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="sample.html",
        context={}, 
    )

app.include_router(punch_router)
