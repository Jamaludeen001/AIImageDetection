from typing import Optional

from pydantic import BaseModel, Field


class PunchImageInput(BaseModel):
    image_base64: str = Field(..., description="JPG or PNG bytes, raw base64 or a data URL")
    file_name: Optional[str] = None


class PunchImageLink(BaseModel):
    image_url: str = Field(..., description="Full http or https URL of a JPG or PNG")
    file_name: Optional[str] = None


class PunchVerifyRequest(BaseModel):
    image_base64: Optional[str] = Field(None, description="One image, used when images is empty")
    images: list[PunchImageInput] = []
    adjustment_type: int = Field(..., description="0 regular, 1 static, 2 semi punch, 3 check-in correction")
    attendance_date: Optional[str] = None
    expected_times: list[str] = []
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None


class PunchVerifyUrlRequest(BaseModel):
    images: list[PunchImageLink]
    adjustment_type: int = Field(..., description="0 regular, 1 static, 2 semi punch, 3 check-in correction")
    attendance_date: Optional[str] = None
    expected_times: list[str] = []
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None


class PunchImageResult(BaseModel):
    file_name: Optional[str] = None
    status: str
    metadata_edited: bool = False
    metadata_flags: list[str] = []
    c2pa_present: Optional[bool] = None
    c2pa_state: Optional[str] = None
    c2pa_issuer: Optional[str] = None
    sightengine_score: Optional[float] = None
    sightengine_is_ai: Optional[bool] = None
    is_ai_generated: Optional[bool] = None
    is_edited: Optional[bool] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    timestamp: Optional[str] = None
    location: Optional[str] = None
    accuracy: Optional[str] = None
    distance_metres: Optional[float] = None
    time_match: Optional[bool] = None
    matched_minute: Optional[str] = None
    error: Optional[str] = None


class PunchVerifyResponse(BaseModel):
    status: str
    error: Optional[str] = None
    results: list[PunchImageResult] = []
