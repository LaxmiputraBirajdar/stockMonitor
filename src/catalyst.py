"""Cautious, evidence-linked catalyst classification (not causal claims)."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

NO_CATALYST = "No clear company-specific catalyst found; move may be market/sector/technical driven."

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(result|earnings|profit|loss|revenue|guidance)\b", re.I), "Company-specific"),
    (re.compile(r"\b(order|contract|award|tender|purchase order)\b", re.I), "Company-specific"),
    (re.compile(r"\b(acqui|merger|amalgam|fundrais|preferential|qip|rights issue)\b", re.I), "Company-specific"),
    (re.compile(r"\b(dividend|buyback|bonus|split|record date)\b", re.I), "Company-specific"),
    (re.compile(r"\b(ipo|listing|issue price|allotment)\b", re.I), "Company-specific"),
    (re.compile(r"\b(rating|upgrade|downgrade|promoter|stake sale|pledge)\b", re.I), "Company-specific"),
    (re.compile(r"\b(regulat|penalt|investigat|litigation|resign|appoint)\b", re.I), "Company-specific"),
    (re.compile(r"\b(crude|commodity|interest rate|rupee|inflation|budget|gdp)\b", re.I), "Macro"),
    (re.compile(r"\b(sector|industry|peer|banking|it sector|metal sector)\b", re.I), "Sector-specific"),
]


@dataclass(frozen=True)
class Catalyst:
    primary_reason: str
    reason_type: str
    confidence: str


def _classify(articles: pd.DataFrame) -> Catalyst:
    if articles.empty:
        return Catalyst(NO_CATALYST, "Unclear", "Low")
    ordered = articles.copy()
    ordered["official_priority"] = ordered["source_kind"].eq("official").astype(int)
    ordered = ordered.sort_values(["official_priority", "published_date"], ascending=[False, False], na_position="last")
    for article in ordered.itertuples(index=False):
        title = str(article.title)
        for pattern, reason_type in _RULES:
            if pattern.search(title):
                if article.source_kind == "official":
                    confidence = "High"
                elif article.published_date:
                    confidence = "Medium"
                else:
                    confidence = "Low"
                return Catalyst(
                    "A recent reported development may be relevant: " + title[:350] + ". "
                    "The timing is evidence of association, not proof that it caused the move.",
                    reason_type,
                    confidence,
                )
    return Catalyst(NO_CATALYST, "Unclear", "Low")


def analyze_catalysts(movers: pd.DataFrame, articles: pd.DataFrame) -> pd.DataFrame:
    """Add a calibrated explanation for every mover, always retaining sources."""
    if movers.empty:
        result = movers.copy()
        result["primary_reason"] = pd.Series(dtype="string")
        result["reason_type"] = pd.Series(dtype="string")
        result["confidence"] = pd.Series(dtype="string")
        return result
    records: list[dict[str, object]] = []
    for mover in movers.itertuples(index=False):
        stock_articles = articles.loc[articles["symbol"].eq(mover.symbol)] if not articles.empty else articles
        catalyst = _classify(stock_articles)
        record = mover._asdict()
        record.update(
            primary_reason=catalyst.primary_reason,
            reason_type=catalyst.reason_type,
            confidence=catalyst.confidence,
        )
        records.append(record)
    return pd.DataFrame(records)
