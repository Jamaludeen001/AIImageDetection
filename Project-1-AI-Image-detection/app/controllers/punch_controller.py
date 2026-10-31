import base64

from app.repositories.image_repository import ImageRepository
from app.schemas.punch_schema import PunchVerifyRequest, PunchVerifyResponse, PunchVerifyUrlRequest
from app.services.punch_service import PunchService


class PunchController:
    def __init__(self):
        self.service = PunchService()

    def verify(self, body: PunchVerifyRequest) -> PunchVerifyResponse:
        images = [
            {"image_base64": item.image_base64, "file_name": item.file_name}
            for item in body.images
        ]
        if not images and body.image_base64:
            images = [{"image_base64": body.image_base64, "file_name": None}]
        result = self.service.verify(
            images,
            adjustment_type=body.adjustment_type,
            attendance_date=body.attendance_date,
            expected_times=body.expected_times,
            office_latitude=body.office_latitude,
            office_longitude=body.office_longitude,
        )
        return PunchVerifyResponse(**result)

    def verify_urls(self, body: PunchVerifyUrlRequest) -> PunchVerifyResponse:
        placeholders = [
            {"image_base64": None, "file_name": item.file_name}
            for item in body.images
        ]
        if self.service._count_error(body.adjustment_type, len(placeholders)):
            result = self.service.verify(
                placeholders,
                adjustment_type=body.adjustment_type,
                attendance_date=body.attendance_date,
                expected_times=body.expected_times,
                office_latitude=body.office_latitude,
                office_longitude=body.office_longitude,
            )
            return PunchVerifyResponse(**result)

        images = []
        downloader = ImageRepository()
        for item in body.images:
            name = item.file_name
            try:
                raw = downloader.fetch_url(item.image_url)
                images.append({
                    "image_base64": base64.b64encode(raw).decode("ascii"),
                    "file_name": name,
                })
            except ValueError as exc:
                images.append({
                    "image_base64": None,
                    "file_name": name or item.image_url,
                    "preload_error": str(exc),
                })
        if not images:
            return PunchVerifyResponse(status="pending", error="No image link was sent.")
        result = self.service.verify(
            images,
            adjustment_type=body.adjustment_type,
            attendance_date=body.attendance_date,
            expected_times=body.expected_times,
            office_latitude=body.office_latitude,
            office_longitude=body.office_longitude,
        )
        return PunchVerifyResponse(**result)

    def health(self) -> dict:
        return self.service.health()
