from fastapi import FastAPI, Request

from app.logging_config import new_request_id, request_id_var, setup_logging
from app.routers.punch_router import router as punch_router
from fastapi.middleware.cors import CORSMiddleware

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


app.include_router(punch_router)
