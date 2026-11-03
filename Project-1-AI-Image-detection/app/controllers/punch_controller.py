from app.schemas.punch_schema import PunchVerifyRequest, PunchVerifyUrlRequest
from app.services.punch_service import PunchService

class PunchController:
    def __init__(self, service: PunchService):
        self.service = service

    def health(self):
        return self.service.health()

    def verify(self, body: PunchVerifyRequest):
        return self.service.verify(
            images=body.images,
            pdfs=body.pdfs,
            adjustment_type=body.adjustment_type,
            attendance_date=body.attendance_date,
            expected_times=body.expected_times,
            office_latitude=body.office_latitude,
            office_longitude=body.office_longitude,
        )

    def verify_urls(self, body: PunchVerifyUrlRequest):
        return self.service.verify(
            images=body.images,
            pdfs=[],
            adjustment_type=body.adjustment_type,
            attendance_date=body.attendance_date,
            expected_times=body.expected_times,
            office_latitude=body.office_latitude,
            office_longitude=body.office_longitude,
        )
