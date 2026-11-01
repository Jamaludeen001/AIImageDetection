import csv
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.controllers.punch_controller import PunchController
from app.schemas.punch_schema import PunchVerifyRequest, PunchVerifyResponse, PunchVerifyUrlRequest

router = APIRouter()


@router.get("/health")
def health():
    return PunchController().health()


@router.get("/health/live")
def health_live():
    return {"status": "healthy"}


@router.post("/punch-verify", response_model=PunchVerifyResponse)
def punch_verify(body: PunchVerifyRequest):
    return PunchController().verify(body)


@router.post("/punch-verify-urls", response_model=PunchVerifyResponse)
def punch_verify_urls(body: PunchVerifyUrlRequest):
    return PunchController().verify_urls(body)


# --- NEW ROUTE: Serve Offices CSV ---
@router.get("/api/offices")
def get_offices():
    offices = []
    # Path relative to where the app is run (assuming uvicorn is run from root)
    # Adjust the path if your working directory is different.
    csv_path = os.path.join("data", "offices.csv") 
    
    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Ensure your CSV headers match exactly: "Office Name", "Latitude", "Longitude"
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
# ------------------------------------
