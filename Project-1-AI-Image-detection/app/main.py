from fastapi import FastAPI
import logging
from .api.v1.router import api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Production Image Forensics API",
    version="10.0.0 (Clean Architecture)",
    description="Submit local paths, HTTP URLs, or Base64 strings.",
)

app.include_router(api_router)