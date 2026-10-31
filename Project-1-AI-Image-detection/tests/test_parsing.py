import pytest

from app.services import punch_service as ps


@pytest.mark.parametrize("text,expected", [
    ("28/10/2026 09:23:43 AM", (2026, 10, 28, 9, 23, 43)),
    ("28/10/2026 09:23 AM", (2026, 10, 28, 9, 23, 0)),
    ("28/10/2026 21:05:10", (2026, 10, 28, 21, 5, 10)),
    ("28/10/2026 21:05", (2026, 10, 28, 21, 5, 0)),
    ("28/10/2026 09:23:43 PM", (2026, 10, 28, 21, 23, 43)),
    ("28 Oct 2026 09:23:43 AM", (2026, 10, 28, 9, 23, 43)),
    ("  28/10/2026   09:23:43  AM ", (2026, 10, 28, 9, 23, 43)),
])
def test_photo_time_formats(text, expected):
    parsed = ps._parse_photo_time(text)
    assert (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute, parsed.second) == expected


@pytest.mark.parametrize("text", ["", "yesterday", "2026-10-28 09:23", "32/10/2026 09:23 AM"])
def test_photo_time_rejects_garbage(text):
    assert ps._parse_photo_time(text) is None


@pytest.mark.parametrize("text,limit,expected", [
    ("13.007155", 90, 13.007155),
    ("-33.8688", 90, -33.8688),
    ("33.8688 S", 90, -33.8688),
    ("33.8688 N", 90, 33.8688),
    ("80.2 W", 180, -80.2),
    ("80.2065 E", 180, 80.2065),
    ("13.0071°N", 90, 13.0071),
    ("13 0 25.8 N", 90, 13 + 25.8 / 3600),
    ("-33.8688 S", 90, -33.8688),
])
def test_coordinate_reads_direction(text, limit, expected):
    assert ps._coordinate(text, limit) == pytest.approx(expected)


@pytest.mark.parametrize("text,limit", [
    (None, 90), ("", 90), ("abc", 90), ("95.0", 90), ("-91", 90), ("181", 180), ("1 2 3 4", 90),
])
def test_coordinate_rejects_bad_values(text, limit):
    assert ps._coordinate(text, limit) is None


def test_minute_ignores_seconds():
    assert ps._minute("09:30") == "09:30"
    assert ps._minute("09:30:59") == "09:30"
    assert ps._minute("nine") is None


def test_haversine():
    assert ps._haversine_metres(13.0, 80.0, 13.0, 80.0) == pytest.approx(0)
    # about 111.2 km per degree of latitude
    assert ps._haversine_metres(13.0, 80.0, 14.0, 80.0) == pytest.approx(111195, rel=0.01)
    assert ps._haversine_metres(13.007155, 80.206531, 13.0072, 80.2073) == pytest.approx(83.5, abs=1)
