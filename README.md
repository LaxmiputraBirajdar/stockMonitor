# NSE Indian Stock Movers

A Streamlit dashboard that identifies the top five rising and falling **actively listed NSE equity shares** by close-to-close performance over three completed trading sessions. It acquires one official NSE bhavcopy per session for the entire market, then researches only the ten final movers.

It is deliberately evidence-first: the app never invents a catalyst, keeps every article URL and publication date it receives, and uses the mandated fallback when no reliable company-specific explanation is found.

## What it calculates

For each security with valid closes on the latest completed NSE session and the session exactly three completed sessions before it:

```
3-session percentage change = ((latest close / close 3 completed sessions earlier) - 1) × 100
```

This requires four market-wide completed sessions. It is not the exchange's one-day percentage-change field.

The collector determines the latest session by checking daily official files backwards. It ignores the current day before 15:45 IST, weekends, holidays, unavailable files, and files whose embedded trade date does not match the requested session.

## Sources used

| Purpose | Source | How it is used |
| --- | --- | --- |
| Equity universe | [NSE Securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading) | The page is fetched first and its Equity CSV link is discovered. An official NSE archive `EQUITY_L.csv` URL is only a fallback if page discovery cannot find it. Active equity-share series `EQ`, `BE`, and `BZ` are admitted. |
| Daily OHLC | [NSE CM UDiFF Bhavcopy](https://www.nseindia.com/all-reports/) | One final CM bhavcopy ZIP per completed date. It contains all symbols, ISINs, series, OHLC, and volume. |
| Official disclosures | [NSE Corporate announcements](https://www.nseindia.com/corporates/corporateHome.html) | Recent symbol-specific announcements are collected through NSE's public endpoint, with attachment URLs retained where supplied. |
| News discovery | [Google News RSS](https://news.google.com/) | Recent matching story metadata is gathered for the final ten names only; the actual publisher and link are preserved in the dashboard. |
| Nifty 50 (optional) | [NSE indices](https://www.nseindia.com/market-data/live-equity-market) | Latest reported level and one-day percentage change, when NSE makes it available. |

The exact URLs used on a run are recorded in `data/run_metadata.json` and the headline-level source information is exported to `data/news_sources.csv`.

## Catalyst policy

1. Official NSE announcements have priority over news articles.
2. A headline is retained only if it is recent, identifiable, and relevant to the company/symbol; duplicate/syndicated entries are removed.
3. A rule-based classifier labels possible results, orders, corporate actions, ratings, regulatory events, sector items, or macro items. It says an event **may be relevant** and explicitly does not prove causality.
4. An official, relevant disclosure gets **High** confidence; dated secondary reporting gets **Medium**; otherwise the result is **Low**.
5. With no reliable evidence, it displays: `No clear company-specific catalyst found; move may be market/sector/technical driven.`

## Installation and use

Requires Python 3.11+.

```powershell
cd indian_stock_movers
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
streamlit run app.py
```

Use **Refresh official NSE data** in the sidebar for a fresh run. Otherwise the current cached universe, bhavcopies, and final-mover news metadata are reused to minimize requests.

To run the pipeline without opening the dashboard:

```powershell
python -c "from app import run_pipeline; result = run_pipeline(refresh=True); print(result['gainers'][['rank','company','symbol','three_day_change_pct']].to_string(index=False)); print(result['losers'][['rank','company','symbol','three_day_change_pct']].to_string(index=False))"
```

## Project layout

```
indian_stock_movers/
├── app.py                    # pipeline coordinator and Streamlit entry point
├── src/
│   ├── universe.py            # official NSE universe discovery + EQ filter
│   ├── prices.py              # all-market bhavcopy collection/session discovery
│   ├── calculations.py        # three-session return and anomaly flag
│   ├── rankings.py            # top-five selection
│   ├── news.py                # NSE disclosures + news metadata collection
│   ├── catalyst.py            # cautious evidence classification
│   ├── data_quality.py        # exclusion log and validation helpers
│   └── dashboard.py           # Streamlit presentation only
├── data/                      # auditable run outputs (created at runtime)
├── cache/                     # reusable raw files and news metadata (created at runtime)
└── tests/                     # calculation, ranking, calendar, and validation tests
```

## Data-quality safeguards

- Duplicate official-universe symbols are removed and logged.
- Non-equity series are excluded; the application admits the official equity-share series `EQ`, `BE`, and `BZ`, while screening out ETFs, mutual funds, debt, warrants, REITs/InvITs, preference shares, indexes, and SME/non-equity series.
- A symbol is excluded with a recorded reason if it is absent from either required endpoint date, has duplicate date records, or has a missing/zero/negative close. This covers many suspended and newly listed cases without assuming their status.
- Invalid arithmetic is rejected rather than ranked.
- Every exclusion is written to `data/excluded_stocks.csv`.
- Raw unadjusted moves of 50% or more are flagged as `corporate_action_review` rather than silently treated as ordinary performance. Such moves may be a split/bonus/other corporate-action discontinuity or a genuine move and should be checked against the linked official disclosures.
- Duplicate news is removed by URL/title keys; only relevance-filtered articles are displayed.

## Limitations and operational notes

- The NSE universe/download formats and anti-bot behavior can change. The application validates responses and fails visibly rather than showing guessed data. Run it from a network that can access NSE.
- NSE bhavcopy closing prices are raw exchange closes, not a total-return/fully adjusted price history. The built-in large-move flag requires human review around splits, bonuses, and rights issues.
- “Active” is operationally defined as the current official NSE equity-share universe (`EQ`/`BE`/`BZ`) and trading in the required sessions. A status-specific suspension feed is not inferred when price data is absent.
- News RSS is a discovery layer, not proof of price causality. Some publishers block, delay, syndicate, or omit dates. A missing reliable source intentionally produces the fallback explanation.
- The dashboard shows Nifty 50 only when NSE returns validated data. Sensex is left unavailable rather than mixing an unvalidated secondary source.
- Be considerate of NSE and publisher rate limits. The app downloads four all-market files rather than thousands of per-symbol calls; its disk cache avoids repeat downloads. Do not schedule aggressive refreshes.
