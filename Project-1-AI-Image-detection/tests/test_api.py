import logging

import pytest
from fastapi.testclient import TestClient

import app.controllers.punch_controller as controller_module
from app.logging_config import RequestIdFilter
from app.main import app
from tests.helpers import FakeGemini, FakeSightengine, jpeg_b64, make_service, stamp


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
        self.addFilter(RequestIdFilter())

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(controller_module, "PunchService",
                        lambda: make_service(FakeGemini(stamp()), FakeSightengine(0.01)))
    return TestClient(app)


BODY = {
    "adjustment_type": 0,
    "attendance_date": "2026-10-28",
    "expected_times": [],
    "office_latitude": 13.007155,
    "office_longitude": 80.206531,
}


def test_live(client):
    assert client.get("/health/live").json() == {"status": "healthy"}


def test_punch_verify_real(client):
    body = {**BODY, "images": [{"image_base64": jpeg_b64(), "file_name": "a.jpg"}]}
    response = client.post("/punch-verify", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "real"
    assert response.json()["results"][0]["file_name"] == "a.jpg"


def test_data_url_and_single_image_field(client):
    body = {**BODY, "image_base64": "data:image/jpeg;base64," + jpeg_b64()}
    assert client.post("/punch-verify", json=body).json()["status"] == "real"


def test_missing_adjustment_type_is_422(client):
    assert client.post("/punch-verify", json={"images": []}).status_code == 422


def test_request_id_is_returned_and_logged(client):
    handler = ListHandler()
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        body = {**BODY, "images": [{"image_base64": jpeg_b64()}]}
        response = client.post("/punch-verify", json=body, headers={"X-Request-ID": "abc123"})
    finally:
        logger.removeHandler(handler)
    assert response.headers["X-Request-ID"] == "abc123"
    ids = {r.request_id for r in handler.records if "result=" in r.getMessage() or "photo 1" in r.getMessage()}
    assert ids == {"abc123"}


def test_request_id_is_generated_when_missing(client):
    assert len(client.get("/health/live").headers["X-Request-ID"]) == 12
