"""Collect attributable, recent company news and NSE announcements."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import feedparser
import pandas as pd
import requests

from .config import (
    CACHE_DIR,
    HTTP_TIMEOUT_SECONDS,
    NEWS_LOOKBACK_DAYS,
    NSE_CORPORATE_ANNOUNCEMENTS_URL,
)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json,text/html,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}
_RELEVANT_TERMS = re.compile(
    r"\b(results?|earnings?|profit|loss|revenue|order|contract|acqui[rs]|merger|"
    r"fundrais|dividend|buyback|rating|upgrade|downgrade|stake|promoter|"
    r"regulat|resign|appoint|investigat|penalt|litigation|approval|launch|"
    r"guidance|capacity|board meeting|ipo|listing|allotment|issue price)\b",
    flags=re.IGNORECASE,
)
_GENERIC_MARKET_TITLE = re.compile(
    r"\b(key support|resistance|technical analysis|share price today|stock price today|"
    r"edges higher|edges lower|stock rises|stock falls|upper circuit|lower circuit|"
    r"dividend growth stocks)\b",
    flags=re.IGNORECASE,
)
# The RSS feed is only a discovery mechanism.  Restrict secondary articles to
# established financial/business publishers rather than allowing arbitrary
# scraped price pages to become a stated reason for a stock move.
_REPUTABLE_PUBLISHERS = (
    "reuters",
    "economic times",
    "et markets",
    "moneycontrol",
    "business standard",
    "financial express",
    "cnbc-tv18",
    "cnbctv18",
    "livemint",
    "mint",
    "businessline",
    "the hindu",
    "bloomberg",
    "ndtv profit",
    "zeebiz",
    "press trust of india",
    "pti",
)


def _parse_date(value: object) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    for parser in (
        lambda: parsedate_to_datetime(text),
        lambda: datetime.fromisoformat(text.replace("Z", "+00:00")),
        lambda: pd.to_datetime(text, dayfirst=True, errors="raise").to_pydatetime(),
    ):
        try:
            return parser().date().isoformat()
        except (ValueError, TypeError, IndexError, OverflowError):
            continue
    return None


def _within_window(date_value: str | None, cutoff: date) -> bool:
    if date_value is None:
        return True  # retain undated official evidence, visibly labelled as such
    return date.fromisoformat(date_value) >= cutoff


def _attachment_url(item: dict) -> str | None:
    for field in ("attchmntFile", "attachment", "attachmentFile", "filePath"):
        raw = item.get(field)
        if not raw or str(raw).strip() in {"-", "--", "N.A.", "NA"}:
            continue
        raw = str(raw)
        if raw.startswith("http"):
            return raw
        return requests.compat.urljoin("https://nsearchives.nseindia.com/", raw.lstrip("/"))
    return None


def _title_from_announcement(item: dict) -> str:
    fields = ("desc", "subject", "sm_name", "an_desc", "headline", "bm_desc")
    parts = [str(item[field]).strip() for field in fields if item.get(field)]
    return " — ".join(dict.fromkeys(parts))[:700] or "NSE corporate announcement"


def fetch_nse_announcements(
    symbol: str,
    *,
    as_of: date,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
    session: requests.Session | None = None,
) -> list[dict[str, str | None]]:
    """Get recent official NSE corporate announcements for one security.

    An API failure yields no official articles rather than a fabricated fallback;
    the dashboard will then label the catalyst as unclear.
    """
    own_session = session is None
    session = session or requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    cutoff = as_of - timedelta(days=lookback_days)
    try:
        # Visiting the homepage establishes the cookies normally required by NSE.
        session.get("https://www.nseindia.com", timeout=HTTP_TIMEOUT_SECONDS)
        params = {
            "index": "equities",
            "symbol": symbol,
            "from_date": cutoff.strftime("%d-%m-%Y"),
            "to_date": as_of.strftime("%d-%m-%Y"),
        }
        response = session.get(NSE_CORPORATE_ANNOUNCEMENTS_URL, params=params, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return []
    finally:
        if own_session:
            session.close()
    raw_items = payload if isinstance(payload, list) else payload.get("data", [])
    articles: list[dict[str, str | None]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        published = _parse_date(item.get("an_dt") or item.get("sort_date") or item.get("date"))
        if not _within_window(published, cutoff):
            continue
        articles.append(
            {
                "symbol": symbol,
                "title": _title_from_announcement(item),
                "publisher": "NSE corporate announcement",
                "published_date": published,
                "url": _attachment_url(item) or NSE_CORPORATE_ANNOUNCEMENTS_URL,
                "source_kind": "official",
            }
        )
    return articles


def _google_news_rss_url(company: str, symbol: str) -> str:
    # An exact company/symbol query cuts down on same-name false positives.
    query = f'"{company}" OR "{symbol}" stock India'
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"


def fetch_news_rss(
    company: str,
    symbol: str,
    *,
    as_of: date,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
    session: requests.Session | None = None,
) -> list[dict[str, str | None]]:
    """Read recent article metadata from Google News RSS; no article text is invented."""
    cutoff = as_of - timedelta(days=lookback_days)
    own_session = session is None
    session = session or requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    try:
        response = session.get(_google_news_rss_url(company, symbol), timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except requests.RequestException:
        return []
    finally:
        if own_session:
            session.close()
    articles: list[dict[str, str | None]] = []
    company_tokens = {token.lower() for token in re.findall(r"[A-Za-z]{4,}", company)}
    for entry in feed.entries:
        raw_title = str(entry.get("title", "")).strip()
        published = _parse_date(entry.get("published") or entry.get("updated"))
        # Unlike official exchange items, undated RSS entries cannot be proved
        # to belong to the requested seven-day search window.
        if not raw_title or published is None or not _within_window(published, cutoff):
            continue
        # RSS titles include the publisher after " - "; preserve its title as
        # supplied through the publisher field but remove it from the headline
        # so, for example, “NDTV Profit” is not mistaken for company profit.
        source = entry.get("source", {})
        publisher = source.get("title") if hasattr(source, "get") else None
        publisher = str(publisher or urlparse(str(entry.get("link", ""))).netloc or "News source")
        suffix = " - " + publisher
        title = raw_title[: -len(suffix)].strip() if raw_title.lower().endswith(suffix.lower()) else raw_title
        lowered = title.lower()
        relevant_to_company = symbol.lower() in lowered or bool(company_tokens & set(re.findall(r"[a-z]{4,}", lowered)))
        if not relevant_to_company:
            continue
        articles.append(
            {
                "symbol": symbol,
                "title": title,
                "publisher": publisher,
                "published_date": published,
                "url": str(entry.get("link", "")) or None,
                "source_kind": "news",
            }
        )
    return articles


def _is_relevant(article: dict[str, str | None], company: str, symbol: str) -> bool:
    title = article.get("title") or ""
    if article.get("source_kind") == "official":
        return True
    lowered = title.lower()
    publisher = (article.get("publisher") or "").lower()
    if _GENERIC_MARKET_TITLE.search(title):
        return False
    if not any(reputable in publisher for reputable in _REPUTABLE_PUBLISHERS):
        return False
    company_words = [word.lower() for word in re.findall(r"[A-Za-z]{4,}", company)]
    mentions_company = symbol.lower() in lowered or any(word in lowered for word in company_words)
    return mentions_company and bool(_RELEVANT_TERMS.search(title))


def deduplicate_articles(articles: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """De-duplicate syndications using URL and normalised title/publisher keys."""
    kept: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for article in articles:
        url = (article.get("url") or "").strip().lower()
        title = re.sub(r"\W+", " ", article.get("title") or "").strip().lower()
        key = (url, title) if url else (title, (article.get("publisher") or "").lower())
        if not title or key in seen:
            continue
        seen.add(key)
        kept.append(article)
    return kept


def collect_news_for_movers(movers: pd.DataFrame, *, as_of: date, refresh: bool = False) -> pd.DataFrame:
    """Collect only the final movers' news and cache the attributable metadata."""
    cache_path = CACHE_DIR / f"news_{as_of.isoformat()}.json"
    symbols = sorted(movers["symbol"].astype(str).unique())
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if sorted(cached.get("symbols", [])) == symbols:
            return pd.DataFrame(cached.get("articles", []))

    articles: list[dict[str, str | None]] = []
    with requests.Session() as session:
        for mover in movers.drop_duplicates("symbol").itertuples(index=False):
            official = fetch_nse_announcements(mover.symbol, as_of=as_of, session=session)
            rss = fetch_news_rss(mover.company, mover.symbol, as_of=as_of, session=session)
            combined = [article for article in official + rss if _is_relevant(article, mover.company, mover.symbol)]
            articles.extend(deduplicate_articles(combined))
    articles = deduplicate_articles(articles)
    cache_path.write_text(json.dumps({"symbols": symbols, "articles": articles}, indent=2), encoding="utf-8")
    return pd.DataFrame(articles, columns=["symbol", "title", "publisher", "published_date", "url", "source_kind"])
