from datetime import date

import pandas as pd
import pytest

from src.calculations import calculate_three_session_returns, potential_corporate_action_anomaly


DATES = [date(2026, 9, 4), date(2026, 9, 3), date(2026, 9, 2), date(2026, 9, 1)]


def _universe(*symbols: str) -> pd.DataFrame:
    return pd.DataFrame({"COMPANY": [f"{s} Ltd" for s in symbols], "SYMBOL": symbols, "ISIN": ["INE000" for _ in symbols]})


def _prices(symbol: str, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [symbol] * 4,
            "series": ["EQ"] * 4,
            "trade_date": DATES,
            "close": closes,
            "open": closes,
            "high": closes,
            "low": closes,
            "volume": [100] * 4,
        }
    )


def test_three_session_return_uses_close_three_completed_sessions_earlier() -> None:
    # Rows are newest first: 130 / 100 is a +30% three-session return.
    result = calculate_three_session_returns(_universe("ABC"), _prices("ABC", [130, 120, 110, 100]), DATES)
    assert result.returns.iloc[0].three_day_change_pct == pytest.approx(30.0)
    assert result.returns.iloc[0].price_3_sessions_ago == 100
    assert result.returns.iloc[0].latest_price == 130


def test_missing_or_insufficient_history_is_logged_not_silently_dropped() -> None:
    prices = _prices("ABC", [130, 120, 110, 100]).query("trade_date != @DATES[3]")
    result = calculate_three_session_returns(_universe("ABC"), prices, DATES)
    assert result.returns.empty
    assert result.exclusions[0].reason == "insufficient history across required completed sessions"


def test_zero_close_is_rejected() -> None:
    result = calculate_three_session_returns(_universe("ABC"), _prices("ABC", [130, 120, 110, 0]), DATES)
    assert result.returns.empty
    assert "zero" in result.exclusions[0].reason


def test_large_raw_move_is_flagged_for_corporate_action_review() -> None:
    result = calculate_three_session_returns(_universe("ABC"), _prices("ABC", [200, 100, 100, 100]), DATES)
    assert result.returns.iloc[0].corporate_action_review
    assert potential_corporate_action_anomaly(-51)
    assert not potential_corporate_action_anomaly(49.9)


def test_active_be_equity_series_is_included() -> None:
    prices = _prices("ABC", [110, 105, 102, 100])
    prices["series"] = "BE"
    result = calculate_three_session_returns(_universe("ABC"), prices, DATES)
    assert len(result.returns) == 1
    assert result.returns.iloc[0].three_day_change_pct == pytest.approx(10.0)


def test_no_eligible_prices_preserves_return_schema() -> None:
    result = calculate_three_session_returns(_universe("ABSENT"), _prices("OTHER", [1, 1, 1, 1]), DATES)
    assert result.returns.empty
    assert {"symbol", "three_day_change_pct", "corporate_action_review"}.issubset(result.returns.columns)
