"""Ranking helpers for the top NSE movers."""
from __future__ import annotations

import pandas as pd


def rank_movers(returns: pd.DataFrame, limit: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return strictly positive gainers and strictly negative losers, ranked by return."""
    required = {"company", "symbol", "three_day_change_pct"}
    missing = required - set(returns.columns)
    if missing:
        raise ValueError(f"Returns missing required columns: {sorted(missing)}")
    valid = returns.dropna(subset=["three_day_change_pct"]).copy()
    gainers = valid.loc[valid["three_day_change_pct"] > 0].sort_values(
        ["three_day_change_pct", "symbol"], ascending=[False, True]
    ).head(limit).reset_index(drop=True)
    losers = valid.loc[valid["three_day_change_pct"] < 0].sort_values(
        ["three_day_change_pct", "symbol"], ascending=[True, True]
    ).head(limit).reset_index(drop=True)
    gainers.insert(0, "rank", range(1, len(gainers) + 1))
    losers.insert(0, "rank", range(1, len(losers) + 1))
    return gainers, losers

