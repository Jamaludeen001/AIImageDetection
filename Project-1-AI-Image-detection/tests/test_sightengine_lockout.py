import pytest

from app.repositories.sightengine_repository import SightengineRepository


@pytest.fixture
def repo():
    return SightengineRepository()


def test_rate_limit_waits_grow_and_are_capped(repo):
    waits = [repo._lockout_seconds(n, 429) for n in range(1, 9)]
    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600]
    assert waits == sorted(waits)  # later failures never wait less


def test_bad_key_waits_a_day_every_time(repo):
    assert {repo._lockout_seconds(n, 401) for n in range(1, 5)} == {86400}


def test_first_rate_limit_is_short(repo):
    assert repo._lockout_seconds(1) == 60
