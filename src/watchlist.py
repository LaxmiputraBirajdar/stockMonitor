"""Rules-based next-session momentum watchlist; deliberately not a price forecast."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_next_session_watchlist(returns: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    """Rank liquid recent momentum without predicting a future return.

    Candidates must have a complete four-session history, positive three-session
    and latest-session momentum, above-baseline latest volume, and no large raw
    discontinuity flagged for corporate-action review. The score is solely a
    transparent ordering mechanism for a high-risk watchlist.
    """
    columns = [
        "rank",
        "company",
        "symbol",
        "latest_price",
        "three_day_change_pct",
        "latest_daily_change_pct",
        "latest_volume_ratio",
        "positive_close_days",
        "latest_trading_date",
        "momentum_score",
        "watchlist_note",
    ]
    required = {
        "company",
        "symbol",
        "latest_price",
        "three_day_change_pct",
        "latest_daily_change_pct",
        "latest_volume_ratio",
        "positive_close_days",
        "history_complete",
        "corporate_action_review",
        "latest_trading_date",
    }
    if returns.empty:
        return pd.DataFrame(columns=columns)
    missing = required - set(returns.columns)
    if missing:
        raise ValueError(f"Returns missing watchlist fields: {sorted(missing)}")

    candidates = returns.loc[
        returns["history_complete"]
        & ~returns["corporate_action_review"]
        & (returns["three_day_change_pct"] > 0)
        & (returns["latest_daily_change_pct"] > 0)
        & (returns["latest_volume_ratio"] >= 1.0)
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=columns)
    # Cap volume contribution so one anomalous print cannot dominate the score.
    candidates["momentum_score"] = (
        candidates["three_day_change_pct"]
        + (candidates["latest_daily_change_pct"] * 1.5)
        + (candidates["positive_close_days"] * 2)
        + (candidates["latest_volume_ratio"].clip(upper=5) * 2)
    ).round(4)
    candidates["watchlist_note"] = candidates.apply(
        lambda row: (
            f"Momentum screen: {int(row['positive_close_days'])}/3 positive closes; "
            f"latest close {row['latest_daily_change_pct']:+.2f}%; "
            f"volume {row['latest_volume_ratio']:.2f}× its prior-three-session average. "
            "Watch only — this is not a predicted gain."
        ),
        axis=1,
    )
    candidates = candidates.sort_values(
        ["momentum_score", "three_day_change_pct", "symbol"], ascending=[False, False, True]
    ).head(limit).reset_index(drop=True)
    candidates.insert(0, "rank", range(1, len(candidates) + 1))
    return candidates.reindex(columns=columns)
