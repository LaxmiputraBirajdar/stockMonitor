import io
import zipfile
from datetime import datetime

import pandas as pd
import pytest
import requests

from src import prices
from src.data_quality import invalid_close_mask
from src.universe import _normalise_columns


def test_universe_column_normalisation_and_duplicate_detection_contract() -> None:
    frame = pd.DataFrame({"NAME OF COMPANY": ["Alpha"], "SYMBOL": ["abc"], "SERIES": ["EQ"], "ISIN NUMBER": ["INE1"]})
    normalised = _normalise_columns(frame)
    assert set(["COMPANY", "SYMBOL", "SERIES", "ISIN"]).issubset(normalised.columns)
    assert normalised.duplicated("SYMBOL").sum() == 0


def test_invalid_close_validator_handles_missing_zero_and_negative() -> None:
    mask = invalid_close_mask(pd.Series([10, None, 0, -1, "bad"]))
    assert mask.tolist() == [False, True, True, True, True]


def test_latest_eligible_day_excludes_incomplete_session_and_weekend() -> None:
    # Monday before close -> previous calendar day (Sunday), then collector skips it.
    before_close = datetime(2026, 9, 7, 15, 0, tzinfo=prices.IST)
    assert prices.latest_eligible_calendar_day(before_close).isoformat() == "2026-09-06"
    # Saturday after close remains Saturday; the collector deliberately skips weekends.
    saturday = datetime(2026, 9, 5, 18, 0, tzinfo=prices.IST)
    assert prices.latest_eligible_calendar_day(saturday).isoformat() == "2026-09-05"


class _Response:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _HolidayAwareSession:
    headers: dict[str, str] = {}

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.requested: list[str] = []

    def get(self, url: str, timeout: int) -> _Response:
        self.requested.append(url)
        for marker, payload in self.payloads.items():
            if marker in url:
                return _Response(200, payload)
        return _Response(404)


def _bhavcopy_zip(day: str) -> bytes:
    # A normal bhavcopy is much larger than the collector's WAF-response floor.
    csv = f"TckrSymb,SctySrs,TradDt,ClsPric,Filler\nABC,EQ,{day},100,{'x' * 1000}\n".encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bhav.csv", csv)
    return buffer.getvalue()


def test_market_holiday_is_skipped_and_only_valid_embedded_dates_count(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(prices, "RAW_DIR", tmp_path)
    payloads = {
        "20260904": _bhavcopy_zip("2026-09-04"),
        "20260903": _bhavcopy_zip("2026-09-03"),
        "20260902": _bhavcopy_zip("2026-09-02"),
        "20260901": _bhavcopy_zip("2026-09-01"),
        # Sep 7 queried first after close but returns 404: simulated holiday.
    }
    session = _HolidayAwareSession(payloads)
    result = prices.get_completed_sessions(
        now=datetime(2026, 9, 7, 18, 0, tzinfo=prices.IST), refresh=True, session=session
    )
    assert [item.isoformat() for item in result.trading_dates] == ["2026-09-04", "2026-09-03", "2026-09-02", "2026-09-01"]
    assert any("20260907" in url for url in session.requested)
    assert not any("20260905" in url or "20260906" in url for url in session.requested)
