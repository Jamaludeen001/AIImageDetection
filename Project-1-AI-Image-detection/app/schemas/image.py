from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class BulkImageRequest(BaseModel):
    imgpaths: List[str] = Field(
        ..., 
        description="List of local paths, HTTP URLs, or Base64 encoded strings"
    )

class ForensicsReport(BaseModel):
    is_suspicious: bool
    risk_score: float
    flags: List[str]
    metrics: Dict[str, Any]

class AIDetectionReport(BaseModel):
    success: bool
    is_ai_generated: Optional[bool] = None
    ai_score: Optional[float] = None
    operations_used: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    error: Optional[str] = None

class OCRReport(BaseModel):
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    timestamp: Optional[str] = None
    location: Optional[str] = None
    accuracy: Optional[str] = None
    error: Optional[str] = None

class ImageResponse(BaseModel):
    success: bool
    imgpath: str
    dimensions: Optional[str] = None
    format: Optional[str] = None
    is_edited: Optional[bool] = None
    is_ai_generated: Optional[bool] = None
    ai_detection: Optional[AIDetectionReport] = None 
    forensics: Optional[ForensicsReport] = None
    ocr_data: Optional[OCRReport] = None
    error: Optional[str] = None

class BulkImageResponse(BaseModel):
    total_images: int
    processed: int
    results: List[ImageResponse]