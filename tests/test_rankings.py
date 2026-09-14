import pandas as pd

from src.rankings import rank_movers


def test_ranking_separates_positive_and_negative_returns() -> None:
    returns = pd.DataFrame(
        {
            "company": ["A", "B", "C", "D", "E"],
            "symbol": ["A", "B", "C", "D", "E"],
            "three_day_change_pct": [5.0, -3.0, 9.0, -10.0, 0.0],
        }
    )
    gainers, losers = rank_movers(returns)
    assert gainers.symbol.tolist() == ["C", "A"]
    assert losers.symbol.tolist() == ["D", "B"]
    assert gainers["rank"].tolist() == [1, 2]
    assert losers["rank"].tolist() == [1, 2]


def test_ranking_limits_to_five() -> None:
    returns = pd.DataFrame(
        {
            "company": [str(number) for number in range(8)],
            "symbol": [f"S{number}" for number in range(8)],
            "three_day_change_pct": list(range(1, 9)),
        }
    )
    gainers, losers = rank_movers(returns)
    assert len(gainers) == 5
    assert losers.empty

