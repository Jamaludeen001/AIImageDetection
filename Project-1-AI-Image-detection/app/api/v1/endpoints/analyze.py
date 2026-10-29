from fastapi import APIRouter
from ....schemas.image import BulkImageRequest, BulkImageResponse
from ....services.image_processor import process_single_image

router = APIRouter()

@router.post("/validate-images", response_model=BulkImageResponse)
async def validate_images(payload: BulkImageRequest):
    results = []
    for path in payload.imgpaths:
        res = await process_single_image(path)
        results.append(res)
        
    return BulkImageResponse(
        total_images=len(payload.imgpaths),
        processed=len([r for r in results if r.success]),
        results=results
    )