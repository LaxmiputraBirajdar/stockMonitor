"""Price-return calculations with explicit rejection reasons."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .config import CORPORATE_ACTION_REVIEW_THRESHOLD_PCT, ELIGIBLE_SERIES
from .data_quality import Exclusion, invalid_close_mask


@dataclass
class ReturnResult:
    returns: pd.DataFrame
    exclusions: list[Exclusion]


def potential_corporate_action_anomaly(change_pct: float) -> bool:
    """Flag, but do not automatically discard, unusually large raw close gaps.

    NSE bhavcopy closes are not an adjusted total-return series. A large move can
    be genuine, so it remains eligible and is clearly marked for review.
    """
    return bool(abs(change_pct) >= CORPORATE_ACTION_REVIEW_THRESHOLD_PCT)


def calculate_three_session_returns(
    universe: pd.DataFrame,
    prices: pd.DataFrame,
    trading_dates: list[date],
) -> ReturnResult:
    """Calculate (latest / close three sessions earlier - 1) * 100.

    Four completed sessions are needed: date[0] is the latest and date[3] is
    exactly three completed sessions earlier.  The function does not substitute
    an older individual-symbol price, because that would change the definition.
    """
    if len(trading_dates) < 4:
        raise ValueError("Four completed trading sessions are required")
    latest_date, base_date = trading_dates[0], trading_dates[3]
    universe = universe.copy()
    universe["SYMBOL"] = universe["SYMBOL"].astype(str).str.upper().str.strip()
    equity_prices = prices.loc[prices["series"].isin(ELIGIBLE_SERIES)].copy()
    equity_prices["symbol"] = equity_prices["symbol"].astype(str).str.upper().str.strip()
    exclusions: list[Exclusion] = []
    records: list[dict[str, object]] = []

    duplicate_keys = equity_prices.duplicated(["symbol", "trade_date"], keep=False)
    duplicate_symbols = set(equity_prices.loc[duplicate_keys, "symbol"])

    by_symbol = {symbol: group.set_index("trade_date") for symbol, group in equity_prices.groupby("symbol")}
    for security in universe.itertuples(index=False):
        symbol = security.SYMBOL
        company = security.COMPANY
        if symbol in duplicate_symbols:
            exclusions.append(Exclusion(symbol, company, "prices", "duplicate symbol/date records in bhavcopy"))
            continue
        history = by_symbol.get(symbol)
        if history is None:
            exclusions.append(Exclusion(symbol, company, "prices", "not traded in required completed sessions (suspended/new/missing)"))
            continue
        if latest_date not in history.index or base_date not in history.index:
            exclusions.append(Exclusion(symbol, company, "prices", "insufficient history across required completed sessions"))
            continue
        selected = history.loc[[latest_date, base_date]]
        if invalid_close_mask(selected["close"]).any():
            exclusions.append(Exclusion(symbol, company, "prices", "missing, zero, or negative closing price"))
            continue
        base_close = float(selected.loc[base_date, "close"])
        latest_close = float(selected.loc[latest_date, "close"])
        change = ((latest_close / base_close) - 1) * 100
        if not np.isfinite(change):
            exclusions.append(Exclusion(symbol, company, "calculation", "invalid percentage calculation"))
            continue
        recent_history = history.reindex(trading_dates[:4])
        recent_closes = pd.to_numeric(recent_history["close"], errors="coerce")
        complete_history = not invalid_close_mask(recent_closes).any()
        latest_daily_change: float | None = None
        volume_ratio: float | None = None
        positive_close_days = 0
        if complete_history:
            daily_changes = recent_closes.pct_change(periods=-1).iloc[:3] * 100
            latest_daily_change = float(daily_changes.iloc[0])
            positive_close_days = int((daily_changes > 0).sum())
            recent_volumes = pd.to_numeric(recent_history["volume"], errors="coerce")
            previous_average_volume = recent_volumes.iloc[1:].mean(skipna=True)
            if pd.notna(recent_volumes.iloc[0]) and pd.notna(previous_average_volume) and previous_average_volume > 0:
                volume_ratio = float(recent_volumes.iloc[0] / previous_average_volume)
        records.append(
            {
                "company": company,
                "symbol": symbol,
                "isin": getattr(security, "ISIN", pd.NA),
                "price_3_sessions_ago": base_close,
                "latest_price": latest_close,
                "three_day_change_pct": change,
                "latest_trading_date": latest_date.isoformat(),
                "corporate_action_review": potential_corporate_action_anomaly(change),
                "history_complete": complete_history,
                "latest_daily_change_pct": latest_daily_change,
                "positive_close_days": positive_close_days,
                "latest_volume_ratio": volume_ratio,
            }
        )
    result = pd.DataFrame(
        records,
        columns=[
            "company",
            "symbol",
            "isin",
            "price_3_sessions_ago",
            "latest_price",
            "three_day_change_pct",
            "latest_trading_date",
            "corporate_action_review",
            "history_complete",
            "latest_daily_change_pct",
            "positive_close_days",
            "latest_volume_ratio",
        ],
    )
    if not result.empty:
        result["three_day_change_pct"] = result["three_day_change_pct"].round(4)
    return ReturnResult(result, exclusions)
