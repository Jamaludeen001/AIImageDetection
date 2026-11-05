from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["approved", "rejected"]


class PunchImageInput(BaseModel):
    image_base64: str = Field(..., description="JPG or PNG bytes, raw base64 or a data URL")
    file_name: Optional[str] = None


class PunchPdfInput(BaseModel):
    pdf_base64: str = Field(..., description="PDF bytes, raw base64")
    file_name: Optional[str] = None


class PunchImageLink(BaseModel):
    image_url: str = Field(..., description="Full http or https URL of a JPG or PNG")
    file_name: Optional[str] = None


class PunchVerifyRequest(BaseModel):
    image_base64: Optional[str] = Field(None, description="One image, used when images is empty")
    images: List[PunchImageInput] = Field(default_factory=list)
    pdfs: List[PunchPdfInput] = Field(default_factory=list)
    adjustment_type: int = Field(..., description="0 regular, 1 static, 2 semi punch, 3 check-in correction")
    attendance_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    expected_times: List[str] = Field(default_factory=list, description="HH:MM or HH:MM:SS")
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None


class PunchVerifyUrlRequest(BaseModel):
    images: List[PunchImageLink]
    adjustment_type: int = Field(..., description="0 regular, 1 static, 2 semi punch, 3 check-in correction")
    attendance_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    expected_times: List[str] = Field(default_factory=list, description="HH:MM or HH:MM:SS")
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None


class PunchImageResult(BaseModel):
    file_name: Optional[str] = None
    status: Status
    reason: Optional[str] = Field(
        None, 
        description="A concise summary of why the photo was rejected (e.g. 'Marked as AI generated, Date mismatch')"
    ) # <--- NEW FIELD ADDED HERE
    metadata_edited: bool = False
    metadata_flags: List[str] = Field(default_factory=list)
    c2pa_present: Optional[bool] = None
    c2pa_state: Optional[str] = None
    c2pa_issuer: Optional[str] = None
    sightengine_score: Optional[float] = None
    sightengine_is_ai: Optional[bool] = None
    is_ai_generated: Optional[bool] = None
    is_edited: Optional[bool] = None
    edit_confidence: Optional[float] = Field(None, ge=0, le=1)
    missing_confidence: Optional[float] = Field(None, ge=0, le=1)
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    timestamp: Optional[str] = None
    location: Optional[str] = None
    accuracy: Optional[str] = None
    distance_metres: Optional[float] = None
    time_match: Optional[bool] = None
    matched_minute: Optional[str] = None
    service_error: bool = Field(
        False,
        description="True when this photo was rejected because a verification service failed, not because of the photo",
    )
    service_name: Optional[str] = Field(None, description="Which part failed: gemini, sightengine or internal")
    service_error_detail: Optional[str] = Field(None, description="Actual cause of the service failure, secrets removed")
    error: Optional[str] = None


class PunchServiceErrorDetail(BaseModel):
    file_name: Optional[str] = None
    service: Optional[str] = Field(None, description="gemini, sightengine or internal")
    error: Optional[str] = Field(None, description="Generic message shown to users")
    detail: Optional[str] = Field(None, description="Actual cause of the failure, secrets removed, max 300 chars")


class PunchVerifyResponse(BaseModel):
    status: Status
    error: Optional[str] = None
    service_error: bool = Field(
        False,
        description="True only when every rejection was a service failure. "
        "False if any photo was rejected for a real reason.",
    )
    service_errors: List[PunchServiceErrorDetail] = Field(
        default_factory=list,
        description="Photos that failed because of a service problem, always listed here",
    )
    results: List[PunchImageResult] = Field(default_factory=list)
