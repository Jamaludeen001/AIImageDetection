import base64
import io

from PIL import Image

from app.repositories.image_repository import ImageRepository
from app.services.punch_service import PunchService

OFFICE = {"office_latitude": 13.007155, "office_longitude": 80.206531}


def jpeg_bytes(size=(64, 48), exif=None):
    buffer = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, (120, 130, 140)).save(buffer, format="JPEG", **kwargs)
    return buffer.getvalue()


def jpeg_b64(**kwargs):
    return base64.b64encode(jpeg_bytes(**kwargs)).decode("ascii")


def stamp(**overrides):
    data = {
        "is_ai_generated": False,
        "is_edited": False,
        "latitude": "13.007155",
        "longitude": "80.206531",
        "timestamp": "28/10/2026 09:30:00 AM",
        "location": "Guindy, Chennai",
        "accuracy": "5 m",
    }
    data.update(overrides)
    return data


class FakeC2pa:
    available = True

    def inspect(self, path):
        return {"present": False, "state": None, "issuer": None,
                "ai_generated": False, "edited": False, "flags": [], "error": None}


class FakeGemini:
    client = object()

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def extract(self, path):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


class FakeSightengine:
    keys = [("u", "s")]

    def __init__(self, score=0.01, ok=True, error="Sightengine request failed."):
        self.score = score
        self.ok = ok
        self.error = error
        self.calls = 0

    def detect(self, path):
        self.calls += 1
        if not self.ok:
            return {"ok": False, "error": self.error}
        return {"ok": True, "ai_score": self.score}


def make_service(gemini, sightengine):
    service = PunchService.__new__(PunchService)
    service.images = ImageRepository()
    service.c2pa = FakeC2pa()
    service.gemini = gemini
    service.sightengine = sightengine
    return service


def verify_one(service, adjustment_type=0, attendance_date="2026-10-28", expected=("09:30",), **extra):
    args = {**OFFICE, **extra}
    return service.verify(
        [{"image_base64": jpeg_b64(), "file_name": "a.jpg"}],
        adjustment_type=adjustment_type,
        attendance_date=attendance_date,
        expected_times=list(expected),
        **args,
    )
