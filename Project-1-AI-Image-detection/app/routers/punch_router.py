import csv
import os
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from app.schemas.punch_schema import PunchVerifyRequest, PunchVerifyResponse, PunchVerifyUrlRequest
from app.controllers.punch_controller import PunchController

router = APIRouter()

# Dependency Injection: Create a controller instance using the singleton service
def get_punch_controller(request: Request) -> PunchController:
    return PunchController(service=request.app.state.punch_service)

@router.get("/health")
def health(controller: PunchController = Depends(get_punch_controller)):
    return controller.health()

@router.get("/health/live")
def health_live():
    return {"status": "healthy"}

@router.post("/punch-verify", response_model=PunchVerifyResponse)
def punch_verify(
    body: PunchVerifyRequest, 
    controller: PunchController = Depends(get_punch_controller)
):
    return controller.verify(body)

@router.post("/punch-verify-urls", response_model=PunchVerifyResponse)
def punch_verify_urls(
    body: PunchVerifyUrlRequest,
    controller: PunchController = Depends(get_punch_controller)
):
    return controller.verify_urls(body)

@router.get("/api/offices")
def get_offices():
    offices = []
    # Adjust path if your uvicorn is run from a different root
    csv_path = os.path.join("data", "offices.csv") 
    
    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                offices.append({
                    "name": row.get("Office Name", "").strip(),
                    "lat": row.get("Latitude", "").strip(),
                    "lng": row.get("Longitude", "").strip()
                })
        return JSONResponse(content=offices)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="offices.csv not found in data folder")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
