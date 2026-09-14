from src.news import _is_relevant
from src.catalyst import analyze_catalysts
import pandas as pd


def test_generic_technical_headline_cannot_become_a_catalyst() -> None:
    article = {
        "source_kind": "news",
        "publisher": "Economic Times",
        "title": "Alpha (ALPHA.NS) edges higher; key support and resistance in focus",
    }
    assert not _is_relevant(article, "Alpha Industries Limited", "ALPHA")


def test_unvetted_price_site_cannot_become_a_catalyst() -> None:
    article = {
        "source_kind": "news",
        "publisher": "Unknown price blog",
        "title": "Alpha wins a major order worth Rs 100 crore",
    }
    assert not _is_relevant(article, "Alpha Industries Limited", "ALPHA")


def test_relevant_reputable_news_is_retained_for_cautious_analysis() -> None:
    article = {
        "source_kind": "news",
        "publisher": "Reuters",
        "title": "Alpha Industries reports quarterly profit growth after new order",
    }
    assert _is_relevant(article, "Alpha Industries Limited", "ALPHA")


def test_reputable_ipo_headline_is_relevant() -> None:
    article = {
        "source_kind": "news",
        "publisher": "NDTV Profit",
        "title": "Alpha Industries IPO allotment details announced",
    }
    assert _is_relevant(article, "Alpha Industries Limited", "ALPHA")


def test_publisher_name_is_not_classified_as_company_profit() -> None:
    movers = pd.DataFrame({"company": ["Alpha Limited"], "symbol": ["ALPHA"]})
    articles = pd.DataFrame(
        {
            "symbol": ["ALPHA"],
            "title": ["Alpha shares list at Rs 72 on NSE"],
            "publisher": ["NDTV Profit"],
            "published_date": ["2026-09-01"],
            "url": ["https://example.test/article"],
            "source_kind": ["news"],
        }
    )
    result = analyze_catalysts(movers, articles)
    assert result.iloc[0].reason_type == "Unclear"


def test_empty_mover_set_preserves_dashboard_fields() -> None:
    movers = pd.DataFrame(columns=["company", "symbol"])
    result = analyze_catalysts(movers, pd.DataFrame())
    assert {"primary_reason", "reason_type", "confidence"}.issubset(result.columns)
