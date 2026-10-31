import pytest

from app.settings import settings
from tests.helpers import FakeGemini, FakeSightengine, jpeg_b64, make_service, stamp, verify_one


def run(gemini_answer, sight=None, **kwargs):
    gemini = FakeGemini(gemini_answer)
    sight = sight or FakeSightengine(0.01)
    service = make_service(gemini, sight)
    return verify_one(service, **kwargs), gemini, sight


def test_clean_photo_is_real():
    out, _, sight = run(stamp())
    assert out["status"] == "real"
    assert out["results"][0]["sightengine_score"] == 0.01
    assert out["results"][0]["distance_metres"] < 10
    assert sight.calls == 1


def test_timestamp_without_seconds_is_accepted():
    out, _, _ = run(stamp(timestamp="28/10/2026 09:30 AM"))
    assert out["status"] == "real"


# ---- item 12: Gemini flags go to Sightengine, which finalizes ----

def test_gemini_ai_and_sightengine_high_is_rejected():
    out, _, sight = run(stamp(is_ai_generated=True), FakeSightengine(0.92))
    assert out["status"] == "rejected"
    assert out["results"][0]["sightengine_is_ai"] is True
    assert sight.calls == 1


def test_gemini_ai_and_sightengine_low_goes_to_manual_review():
    out, _, _ = run(stamp(is_ai_generated=True), FakeSightengine(0.05))
    r = out["results"][0]
    assert out["status"] == "pending"
    assert r["sightengine_is_ai"] is False
    assert "Manual review" in r["error"] and "Gemini marked the photo as AI-generated" in r["error"]


def test_gemini_ai_and_sightengine_down_is_pending():
    out, _, _ = run(stamp(is_ai_generated=True), FakeSightengine(ok=False, error="Sightengine credentials missing."))
    assert out["status"] == "pending"
    assert "credentials missing" in out["error"]


def test_gemini_edited_only_is_pending_without_calling_sightengine():
    out, _, sight = run(stamp(is_edited=True))
    assert out["status"] == "pending"
    assert sight.calls == 0
    assert "Manual review" in out["error"]


def test_gemini_flag_with_wrong_date_is_still_rejected_without_sightengine():
    out, _, sight = run(stamp(is_ai_generated=True), attendance_date="2026-10-29")
    assert out["status"] == "rejected"
    assert sight.calls == 0
    assert "does not match the attendance date" in out["error"]


def test_gemini_flag_with_unreadable_gps_is_pending_without_sightengine():
    out, _, sight = run(stamp(is_ai_generated=True, latitude=None))
    assert out["status"] == "pending"
    assert sight.calls == 0


def test_sightengine_threshold_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "SIGHTENGINE_AI_THRESHOLD", 0.8)
    assert run(stamp(), FakeSightengine(0.5))[0]["status"] == "real"
    assert run(stamp(), FakeSightengine(0.8))[0]["status"] == "rejected"


# ---- date, time, distance rules ----

def test_far_from_office_is_rejected_without_sightengine():
    out, _, sight = run(stamp(latitude="13.0100"))
    assert out["status"] == "rejected" and sight.calls == 0
    assert "allowed distance is 100 metres" in out["error"]


def test_radius_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "OFFICE_RADIUS_METRES", 500)
    assert run(stamp(latitude="13.0100"))[0]["status"] == "real"


def test_south_west_coordinates_keep_their_sign():
    # A photo at 33.8688 S must be measured against an office at -33.8688, not +33.8688.
    service = make_service(FakeGemini(stamp(latitude="33.8688 S", longitude="151.2093 E")), FakeSightengine())
    out = verify_one(service, office_latitude=-33.8688, office_longitude=151.2093)
    assert out["status"] == "real"
    assert out["results"][0]["distance_metres"] < 1


def test_wrong_time_for_static_request_is_rejected():
    out, _, _ = run(stamp(timestamp="28/10/2026 10:45:00 AM"), adjustment_type=3)
    assert out["status"] == "rejected" and "does not match 09:30" in out["error"]


def test_regular_adjustment_ignores_the_minute():
    out, _, _ = run(stamp(timestamp="28/10/2026 04:11:00 PM"), adjustment_type=0)
    assert out["status"] == "real"


def test_unreadable_clock_is_pending():
    out, _, _ = run(stamp(timestamp="sometime"))
    assert out["status"] == "pending"


def test_missing_office_coordinates_is_pending():
    service = make_service(FakeGemini(stamp()), FakeSightengine())
    out = service.verify([{"image_base64": jpeg_b64(), "file_name": "a"}], adjustment_type=0,
                         attendance_date="2026-10-28", expected_times=[])
    assert out["status"] == "pending"


def test_gemini_without_verdict_is_pending():
    out, _, _ = run({"latitude": "13.0", "longitude": "80.2", "timestamp": "28/10/2026 09:30 AM"})
    assert out["status"] == "pending"


def test_gemini_failure_is_pending():
    out, _, sight = run({"error": "Gemini could not read this image."})
    assert out["status"] == "pending" and sight.calls == 0


# ---- photo count and the static two-photo rule ----

def test_wrong_count_is_rejected_before_any_call():
    gemini, sight = FakeGemini(stamp()), FakeSightengine()
    out = make_service(gemini, sight).verify([{"image_base64": jpeg_b64()}] * 3, adjustment_type=1)
    assert out["status"] == "rejected"
    assert gemini.calls == 0 and sight.calls == 0


def test_unknown_adjustment_type():
    out = make_service(FakeGemini(stamp()), FakeSightengine()).verify([{"image_base64": jpeg_b64()}], adjustment_type=9)
    assert out["status"] == "rejected" and "not recognized" in out["error"]


def two_photo_request(first, second):
    service = make_service(FakeGemini(first, second), FakeSightengine())
    return service.verify(
        [{"image_base64": jpeg_b64(), "file_name": "in"}, {"image_base64": jpeg_b64(), "file_name": "out"}],
        adjustment_type=1, attendance_date="2026-10-28", expected_times=["09:30", "18:30"],
        office_latitude=13.007155, office_longitude=80.206531,
    )


def test_static_with_check_in_and_check_out_is_real():
    out = two_photo_request(stamp(), stamp(timestamp="28/10/2026 06:30:00 PM"))
    assert out["status"] == "real"


def test_static_with_two_check_in_photos_is_rejected():
    out = two_photo_request(stamp(), stamp())
    assert out["status"] == "rejected" and "Missing 18:30" in out["error"]
