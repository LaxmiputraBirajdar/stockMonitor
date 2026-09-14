"""Acquire all-security NSE daily OHLC data from official bhavcopies."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .config import (
    HTTP_TIMEOUT_SECONDS,
    MARKET_CLOSE_HOUR_IST,
    MARKET_CLOSE_MINUTE_IST,
    MAX_LOOKBACK_CALENDAR_DAYS,
    NSE_BHAVCOPY_URL,
    RAW_DIR,
    SESSIONS_REQUIRED,
    ensure_directories,
)

IST = ZoneInfo("Asia/Kolkata")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/zip,application/octet-stream,*/*",
}


@dataclass
class PriceResult:
    prices: pd.DataFrame
    trading_dates: list[date]
    source_urls: list[str]


def latest_eligible_calendar_day(now: datetime | None = None) -> date:
    """Exclude today until 15:45 IST, when its close should be finalized."""
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    candidate = now_ist.date()
    if (now_ist.hour, now_ist.minute) < (MARKET_CLOSE_HOUR_IST, MARKET_CLOSE_MINUTE_IST):
        candidate -= timedelta(days=1)
    return candidate


def _normalise_bhavcopy(frame: pd.DataFrame, expected_date: date) -> pd.DataFrame:
    """Map current UDiFF bhavcopy fields to a stable price schema."""
    frame = frame.copy()
    frame.columns = [str(c).strip() for c in frame.columns]
    aliases = {
        "TckrSymb": "symbol",
        "SctySrs": "series",
        "FinInstrmNm": "security_name",
        "ISIN": "isin",
        "TradDt": "trade_date",
        "OpnPric": "open",
        "HghPric": "high",
        "LwPric": "low",
        "ClsPric": "close",
        "TtlTradgVol": "volume",
        # Legacy fallback fields, should NSE switch historical format.
        "SYMBOL": "symbol",
        "SERIES": "series",
        "TIMESTAMP": "trade_date",
        "OPEN": "open",
        "HIGH": "high",
        "LOW": "low",
        "CLOSE": "close",
        "TOTTRDQTY": "volume",
    }
    frame = frame.rename(columns={source: target for source, target in aliases.items() if source in frame.columns})
    required = {"symbol", "series", "trade_date", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Unexpected bhavcopy layout; missing {sorted(missing)}")
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["series"] = frame["series"].astype(str).str.strip().str.upper()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce", dayfirst=False).dt.date
    actual_dates = frame["trade_date"].dropna().unique()
    if len(actual_dates) != 1 or actual_dates[0] != expected_date:
        raise ValueError(f"Bhavcopy date mismatch: expected {expected_date}, found {list(actual_dates)}")
    return frame[["symbol", "series", "trade_date", "open", "high", "low", "close", "volume"]]


def _read_bhavcopy(content: bytes, expected_date: date) -> pd.DataFrame:
    if len(content) < 500 or content.lstrip().startswith(b"<"):
        raise ValueError("NSE returned a non-bhavcopy response")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not members:
                raise ValueError("Bhavcopy ZIP contains no CSV")
            with archive.open(members[0]) as csv_file:
                raw = pd.read_csv(csv_file, low_memory=False)
    except zipfile.BadZipFile as error:
        raise ValueError("Bhavcopy download is not a valid ZIP") from error
    return _normalise_bhavcopy(raw, expected_date)


def _cache_path(day: date) -> Path:
    return RAW_DIR / f"nse_bhavcopy_{day:%Y%m%d}.csv"


def get_completed_sessions(
    *,
    required_sessions: int = SESSIONS_REQUIRED,
    now: datetime | None = None,
    refresh: bool = False,
    session: requests.Session | None = None,
) -> PriceResult:
    """Find the most recent completed NSE sessions, skipping weekends/holidays.

    A session only counts after the file parses and its embedded trade date
    matches the requested date. This protects against holiday redirect/stale-file
    anomalies observed on some archive endpoints.
    """
    ensure_directories()
    own_session = session is None
    session = session or requests.Session()
    session.headers.update(_HEADERS)
    frames: list[pd.DataFrame] = []
    dates: list[date] = []
    urls: list[str] = []
    candidate = latest_eligible_calendar_day(now)
    try:
        for _ in range(MAX_LOOKBACK_CALENDAR_DAYS):
            if candidate.weekday() < 5:
                cache_path = _cache_path(candidate)
                try:
                    if cache_path.exists() and not refresh:
                        frame = _normalise_bhavcopy(pd.read_csv(cache_path), candidate)
                    else:
                        url = NSE_BHAVCOPY_URL.format(date=candidate)
                        response = session.get(url, timeout=HTTP_TIMEOUT_SECONDS)
                        if response.status_code == 404:
                            candidate -= timedelta(days=1)
                            continue
                        response.raise_for_status()
                        frame = _read_bhavcopy(response.content, candidate)
                        frame.to_csv(cache_path, index=False)
                    frames.append(frame)
                    dates.append(candidate)
                    urls.append(NSE_BHAVCOPY_URL.format(date=candidate))
                    if len(frames) >= required_sessions:
                        break
                except (requests.RequestException, ValueError, pd.errors.ParserError):
                    # A holiday, unavailable file, or WAF response is not a
                    # trading session. It is represented in run metadata.
                    pass
            candidate -= timedelta(days=1)
    finally:
        if own_session:
            session.close()
    if len(frames) < required_sessions:
        raise RuntimeError(
            f"Only found {len(frames)} completed NSE sessions in {MAX_LOOKBACK_CALENDAR_DAYS} calendar days"
        )
    prices = pd.concat(frames, ignore_index=True)
    return PriceResult(prices=prices, trading_dates=dates, source_urls=urls)

