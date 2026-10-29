import re
from datetime import datetime, timedelta, timezone

import pytest

from api.core import utc_time
from api.core.utc_time import (
    utc_now,
    utc_now_iso,
    utc_now_iso_seconds,
    utc_now_naive,
    utc_now_naive_iso,
    utc_now_naive_iso_z,
)

TOLERANCE = timedelta(seconds=5)


def _reference_utc() -> datetime:
    return datetime.now(timezone.utc)


def test_utc_now_is_aware_utc_and_current():
    value = utc_now()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
    assert abs(value - _reference_utc()) < TOLERANCE


def test_utc_now_naive_is_naive_and_current():
    value = utc_now_naive()
    assert value.tzinfo is None
    assert abs(value - _reference_utc().replace(tzinfo=None)) < TOLERANCE


def test_utc_now_naive_matches_the_deprecated_utcnow_it_replaces():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = datetime.utcnow()
    assert abs(utc_now_naive() - legacy) < TOLERANCE


def test_utc_now_iso_is_aware_with_offset():
    value = utc_now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00", value)
    assert abs(datetime.fromisoformat(value) - _reference_utc()) < TOLERANCE


def test_utc_now_iso_seconds_has_no_fraction():
    value = utc_now_iso_seconds()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", value)
    assert abs(datetime.fromisoformat(value) - _reference_utc()) < TOLERANCE


def test_utc_now_naive_iso_has_no_offset():
    value = utc_now_naive_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?", value)
    assert datetime.fromisoformat(value).tzinfo is None
    assert abs(datetime.fromisoformat(value) - _reference_utc().replace(tzinfo=None)) < TOLERANCE


def test_utc_now_naive_iso_z_ends_with_z_and_otherwise_matches_naive_iso():
    value = utc_now_naive_iso_z()
    assert value.endswith("Z")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z", value)
    assert abs(datetime.fromisoformat(value[:-1]) - _reference_utc().replace(tzinfo=None)) < TOLERANCE


def test_stored_formats_stay_distinct_so_existing_rows_keep_sorting():
    """Naive and aware strings sort differently as text; the helpers must not collapse into one."""
    naive = utc_now_naive_iso()
    aware = utc_now_iso()
    assert "+" not in naive
    assert aware.endswith("+00:00")


def test_module_exposes_exactly_the_documented_helpers():
    public = sorted(name for name in dir(utc_time) if name.startswith("utc_now"))
    assert public == [
        "utc_now",
        "utc_now_iso",
        "utc_now_iso_seconds",
        "utc_now_naive",
        "utc_now_naive_iso",
        "utc_now_naive_iso_z",
    ]


@pytest.mark.parametrize("name", ["utc_now_naive_iso", "utc_now_naive_iso_z", "utc_now_iso", "utc_now_iso_seconds"])
def test_string_helpers_return_str(name):
    assert isinstance(getattr(utc_time, name)(), str)
