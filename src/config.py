"""Application constants and filesystem paths."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / "cache"
RAW_DIR = CACHE_DIR / "raw"
LOG_DIR = DATA_DIR / "logs"

NSE_SECURITIES_PAGE = "https://www.nseindia.com/static/market-data/securities-available-for-trading"
# This is the direct download currently linked by NSE's securities page.  The
# page itself is still fetched first; the direct URL is a resilience fallback.
NSE_EQUITY_CSV_FALLBACK = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{date:%Y%m%d}_F_0000.csv.zip"
)
NSE_CORPORATE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_INDICES_URL = "https://www.nseindia.com/api/allIndices"

# EQ is the normal equity-share series; BE and BZ are also equity shares in
# trade-to-trade / surveillance series. NSE's equity source currently uses
# these three series, while ETFs, funds, debt, units, preference shares, etc.
# use other series or their own source files.
ELIGIBLE_SERIES = {"EQ", "BE", "BZ"}
MINIMUM_BHAVCOPY_BYTES = 500
MAX_LOOKBACK_CALENDAR_DAYS = 35
SESSIONS_REQUIRED = 4  # latest close plus the close three completed sessions earlier
MARKET_CLOSE_HOUR_IST = 15
MARKET_CLOSE_MINUTE_IST = 45
NEWS_LOOKBACK_DAYS = 7
HTTP_TIMEOUT_SECONDS = 30
# Bhavcopy closes are unadjusted. A very large raw three-session discontinuity
# is surfaced for review rather than quietly presented as an ordinary move.
CORPORATE_ACTION_REVIEW_THRESHOLD_PCT = 50.0


def ensure_directories() -> None:
    """Create runtime directories only when the pipeline is used."""
    for directory in (DATA_DIR, CACHE_DIR, RAW_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
