"""Streamlit entry point and reusable daily NSE movers pipeline."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import requests

from src.calculations import calculate_three_session_returns
from src.config import (
    CACHE_DIR,
    DATA_DIR,
    HTTP_TIMEOUT_SECONDS,
    NSE_INDICES_URL,
    ensure_directories,
)
from src.data_quality import exclusions_frame, write_exclusions
from src.news import collect_news_for_movers
from src.catalyst import analyze_catalysts
from src.prices import get_completed_sessions
from src.rankings import rank_movers
from src.universe import download_universe


def _fetch_nifty_50() -> str:
    """Return the latest NSE-reported Nifty 50 level and one-day change if available."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json,*/*",
    }
    try:
        with requests.Session() as session:
            session.headers.update(headers)
            session.get("https://www.nseindia.com", timeout=HTTP_TIMEOUT_SECONDS)
            response = session.get(NSE_INDICES_URL, timeout=HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
            items = response.json().get("data", [])
        index = next(item for item in items if str(item.get("index", "")).upper() == "NIFTY 50")
        last = float(index["last"])
        change = float(index.get("percentChange", 0))
        return f"{last:,.2f} ({change:+.2f}% 1D)"
    except (requests.RequestException, ValueError, KeyError, StopIteration, TypeError):
        return "Unavailable"


def _write_outputs(
    returns: pd.DataFrame,
    gainers: pd.DataFrame,
    losers: pd.DataFrame,
    movers: pd.DataFrame,
    articles: pd.DataFrame,
    metadata: dict[str, Any],
) -> None:
    """Write inspectable, dated pipeline outputs for auditability."""
    returns.to_csv(DATA_DIR / "eligible_returns.csv", index=False)
    gainers.to_csv(DATA_DIR / "top_gainers.csv", index=False)
    losers.to_csv(DATA_DIR / "top_losers.csv", index=False)
    movers.to_csv(DATA_DIR / "movers_with_catalysts.csv", index=False)
    articles.to_csv(DATA_DIR / "news_sources.csv", index=False)
    (DATA_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def run_pipeline(*, refresh: bool = False) -> dict[str, Any]:
    """Run the seven-stage daily pipeline and return dashboard-ready objects."""
    ensure_directories()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    universe_result = download_universe(refresh=refresh)
    price_result = get_completed_sessions(refresh=refresh)
    return_result = calculate_three_session_returns(
        universe_result.securities, price_result.prices, price_result.trading_dates
    )
    gainers, losers = rank_movers(return_result.returns)
    ranked_movers = pd.concat([gainers.assign(direction="Gainer"), losers.assign(direction="Loser")], ignore_index=True)
    latest_date = price_result.trading_dates[0]
    articles = collect_news_for_movers(ranked_movers, as_of=latest_date, refresh=refresh)
    movers = analyze_catalysts(ranked_movers, articles)
    # Put catalyst fields back into the tables used by the dashboard.
    gainers = movers.loc[movers["direction"].eq("Gainer")].sort_values("rank").reset_index(drop=True)
    losers = movers.loc[movers["direction"].eq("Loser")].sort_values("rank").reset_index(drop=True)
    all_exclusions = universe_result.exclusions + return_result.exclusions
    exclusions = exclusions_frame(all_exclusions)
    exclusions_path = write_exclusions(all_exclusions, run_id)
    summary = {
        "latest_trading_date": latest_date.isoformat(),
        "stocks_analyzed": int(len(return_result.returns)),
        "gainer_count": int((return_result.returns["three_day_change_pct"] > 0).sum()),
        "loser_count": int((return_result.returns["three_day_change_pct"] < 0).sum()),
        "nifty_50": _fetch_nifty_50(),
        "sensex": None,  # Only shown when a validated source is configured.
        "exclusions": int(len(exclusions)),
    }
    metadata: dict[str, Any] = {
        "run_id": run_id,
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_trading_date": latest_date.isoformat(),
        "trading_dates_used": [item.isoformat() for item in price_result.trading_dates],
        "universe_source": universe_result.source_url,
        "price_sources": price_result.source_urls,
        "news_source_method": "NSE corporate-announcements API and Google News RSS metadata; sources retained per article",
        "summary": summary,
    }
    _write_outputs(return_result.returns, gainers, losers, movers, articles, metadata)
    return {
        "summary": summary,
        "gainers": gainers,
        "losers": losers,
        "movers": movers,
        "articles": articles,
        "exclusions": exclusions,
        "exclusions_path": str(exclusions_path),
        "metadata": metadata,
    }


def main() -> None:
    """Start the Streamlit dashboard."""
    import streamlit as st
    from src.dashboard import render_dashboard

    with st.sidebar:
        st.header("Controls")
        refresh = st.button("Refresh official NSE data", type="primary")
        st.caption("Cached files are reused by default. A refresh re-downloads official universe, bhavcopies, and news metadata.")
    try:
        with st.spinner("Collecting official NSE data and researching final movers…"):
            result = run_pipeline(refresh=refresh)
        render_dashboard(result)
    except Exception as error:
        st.error("The pipeline could not complete. No estimated data is displayed.")
        st.exception(error)


if __name__ == "__main__":
    main()
