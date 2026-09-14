"""Download and validate the NSE equity securities universe."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from .config import (
    CACHE_DIR,
    ELIGIBLE_SERIES,
    HTTP_TIMEOUT_SECONDS,
    NSE_EQUITY_CSV_FALLBACK,
    NSE_SECURITIES_PAGE,
    ensure_directories,
)
from .data_quality import Exclusion

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


@dataclass
class UniverseResult:
    securities: pd.DataFrame
    exclusions: list[Exclusion]
    source_url: str
    cache_path: Path


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(col).strip().upper().replace("_", " ") for col in frame.columns]
    aliases = {
        "NAME OF COMPANY": "COMPANY",
        "COMPANY NAME": "COMPANY",
        "SECURITY NAME": "COMPANY",
        "ISIN NUMBER": "ISIN",
        "ISIN": "ISIN",
        "SYMBOL": "SYMBOL",
        "SERIES": "SERIES",
    }
    return frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})


def _find_equity_csv_url(page_html: str) -> str | None:
    """Extract NSE's currently advertised equity CSV link from its source page."""
    links = re.findall(r'''href=["']([^"']+\.csv(?:\?[^"']*)?)["']''', page_html, flags=re.I)
    for link in links:
        lowered = link.lower()
        if "equity" in lowered and "etf" not in lowered and "sme" not in lowered:
            return requests.compat.urljoin(NSE_SECURITIES_PAGE, link)
    return None


def _download_csv(session: requests.Session, url: str) -> pd.DataFrame:
    response = session.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    # NSE can return a WAF HTML response with HTTP 200; do not cache it as CSV.
    if response.content.lstrip().startswith(b"<"):
        raise ValueError(f"NSE returned HTML instead of CSV from {url}")
    return pd.read_csv(io.BytesIO(response.content), dtype=str, encoding_errors="replace")


def download_universe(*, refresh: bool = False, session: requests.Session | None = None) -> UniverseResult:
    """Fetch active NSE equity shares, retaining NSE's equity-share series.

    The official page is used as the primary discovery source. A known direct
    official archive link is tried only when page discovery cannot find a CSV.
    """
    ensure_directories()
    cache_path = CACHE_DIR / "nse_equity_universe.csv"
    source_path = CACHE_DIR / "nse_equity_universe_source.txt"
    if cache_path.exists() and not refresh:
        cached = pd.read_csv(cache_path, dtype=str)
        return UniverseResult(cached, [], source_path.read_text() if source_path.exists() else "cache", cache_path)

    own_session = session is None
    session = session or requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    try:
        try:
            page = session.get(NSE_SECURITIES_PAGE, timeout=HTTP_TIMEOUT_SECONDS)
            page.raise_for_status()
            discovered_url = _find_equity_csv_url(page.text)
        except requests.RequestException:
            discovered_url = None

        candidate_urls = [url for url in (discovered_url, NSE_EQUITY_CSV_FALLBACK) if url]
        last_error: Exception | None = None
        raw: pd.DataFrame | None = None
        source_url = ""
        for url in candidate_urls:
            try:
                raw = _download_csv(session, url)
                source_url = url
                break
            except (requests.RequestException, ValueError, pd.errors.ParserError) as error:
                last_error = error
        if raw is None:
            raise RuntimeError("Could not download the official NSE equity universe") from last_error
    finally:
        if own_session:
            session.close()

    raw = _normalise_columns(raw)
    required = {"SYMBOL", "COMPANY", "SERIES"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Unexpected NSE universe layout; missing columns: {sorted(missing)}")
    if "ISIN" not in raw.columns:
        raw["ISIN"] = pd.NA

    raw["SYMBOL"] = raw["SYMBOL"].astype(str).str.strip().str.upper()
    raw["COMPANY"] = raw["COMPANY"].astype(str).str.strip()
    raw["SERIES"] = raw["SERIES"].astype(str).str.strip().str.upper()
    exclusions: list[Exclusion] = []
    for row in raw.loc[~raw["SERIES"].isin(ELIGIBLE_SERIES), ["SYMBOL", "COMPANY"]].itertuples(index=False):
        exclusions.append(Exclusion(row.SYMBOL, row.COMPANY, "universe", "non-EQ or non-equity series"))

    equity = raw.loc[raw["SERIES"].isin(ELIGIBLE_SERIES), ["COMPANY", "SYMBOL", "ISIN", "SERIES"]].copy()
    duplicates = equity.duplicated("SYMBOL", keep="first")
    for row in equity.loc[duplicates, ["SYMBOL", "COMPANY"]].itertuples(index=False):
        exclusions.append(Exclusion(row.SYMBOL, row.COMPANY, "universe", "duplicate symbol in official universe"))
    equity = equity.loc[~duplicates].sort_values("SYMBOL").reset_index(drop=True)
    if equity.empty:
        raise ValueError("Official NSE universe returned no eligible EQ securities")

    equity.to_csv(cache_path, index=False)
    source_path.write_text(source_url, encoding="utf-8")
    return UniverseResult(equity, exclusions, source_url, cache_path)
