from fastapi import APIRouter
from .endpoints import analyze, health, frontend

api_router = APIRouter()

api_router.include_router(frontend.router, tags=["Frontend"])
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(analyze.router, tags=["Analysis"])