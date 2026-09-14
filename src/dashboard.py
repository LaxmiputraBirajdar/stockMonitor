"""Streamlit rendering, kept separate from acquisition and calculations."""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st


def _format_mover_table(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["rank", "company", "symbol", "three_day_change_pct", "latest_price", "primary_reason", "confidence"]
    result = frame.reindex(columns=columns).copy()
    result.columns = ["Rank", "Company", "Symbol", "3-Day %", "Latest Price", "Reason", "Confidence"]
    return result


def _mover_chart(frame: pd.DataFrame, title: str, color: str) -> None:
    if frame.empty:
        st.info("No qualifying securities in this group.")
        return
    ordered = frame.sort_values("three_day_change_pct")
    chart = px.bar(
        ordered,
        x="three_day_change_pct",
        y="symbol",
        orientation="h",
        color_discrete_sequence=[color],
        hover_data={"company": True, "latest_price": ":.2f", "three_day_change_pct": ":.2f"},
        labels={"three_day_change_pct": "3-session return (%)", "symbol": "NSE symbol"},
        title=title,
    )
    chart.update_layout(height=300, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(chart, use_container_width=True)


def render_dashboard(result: dict[str, Any]) -> None:
    """Render a complete run result supplied by app.py."""
    st.set_page_config(page_title="NSE Daily Movers", page_icon="📈", layout="wide")
    st.title("NSE Indian Equity Movers")
    st.caption("Three completed-session close-to-close returns. Explanations are evidence-linked and do not assert causality.")

    summary = result["summary"]
    st.subheader("Market summary")
    metric_columns = st.columns(5)
    metric_columns[0].metric("Latest trading date", summary["latest_trading_date"])
    metric_columns[1].metric("Stocks analyzed", summary["stocks_analyzed"])
    metric_columns[2].metric("Gainers", summary["gainer_count"])
    metric_columns[3].metric("Losers", summary["loser_count"])
    metric_columns[4].metric("Nifty 50", summary.get("nifty_50", "Unavailable"))
    if summary.get("sensex"):
        st.caption(f"Sensex: {summary['sensex']}")

    gainers, losers = result["gainers"], result["losers"]
    left, right = st.columns(2)
    with left:
        st.subheader("Top 5 gainers")
        _mover_chart(gainers, "Top positive three-session returns", "#16a34a")
        st.dataframe(_format_mover_table(gainers), hide_index=True, use_container_width=True)
    with right:
        st.subheader("Top 5 losers")
        _mover_chart(losers, "Top negative three-session returns", "#dc2626")
        st.dataframe(_format_mover_table(losers), hide_index=True, use_container_width=True)

    st.subheader("News / catalyst detail")
    detail = result["movers"]
    articles = result["articles"]
    for mover in detail.itertuples(index=False):
        with st.expander(f"{mover.company} ({mover.symbol}) — {mover.three_day_change_pct:+.2f}%", expanded=False):
            st.write(mover.primary_reason)
            st.caption(f"Type: {mover.reason_type} · Confidence: {mover.confidence}")
            if mover.corporate_action_review:
                st.warning(
                    "Large raw price discontinuity: check the linked official disclosures for a split, bonus, rights issue, "
                    "or other corporate action before interpreting this as a normal three-session move."
                )
            stock_articles = articles.loc[articles["symbol"].eq(mover.symbol)] if not articles.empty else articles
            if stock_articles.empty:
                st.caption("No relevant attributable article or official announcement was found in the search window.")
            else:
                for article in stock_articles.itertuples(index=False):
                    date_label = article.published_date or "Publication date unavailable"
                    link = article.url or ""
                    if link:
                        st.markdown(f"- [{article.title}]({link}) — {article.publisher}, {date_label}")
                    else:
                        st.markdown(f"- {article.title} — {article.publisher}, {date_label}")

    st.subheader("Data quality")
    st.caption(f"Excluded stocks are logged to `{result['exclusions_path']}`. {summary['exclusions']} exclusion(s) recorded this run.")
    if result["exclusions"].empty:
        st.success("No exclusions were recorded.")
    else:
        st.dataframe(result["exclusions"], hide_index=True, use_container_width=True)
