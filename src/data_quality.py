"""Explicit data-quality logging and small reusable validators."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import DATA_DIR, ensure_directories


@dataclass(frozen=True)
class Exclusion:
    symbol: str
    company: str
    stage: str
    reason: str


def exclusions_frame(exclusions: Iterable[Exclusion]) -> pd.DataFrame:
    """Return exclusions in a stable, exportable layout."""
    rows = [asdict(item) for item in exclusions]
    return pd.DataFrame(rows, columns=["symbol", "company", "stage", "reason"])


def write_exclusions(exclusions: Iterable[Exclusion], run_id: str) -> Path:
    """Persist every known exclusion instead of silently dropping it."""
    ensure_directories()
    frame = exclusions_frame(exclusions)
    frame.insert(0, "run_id", run_id)
    frame.insert(1, "logged_at_utc", datetime.now(timezone.utc).isoformat())
    output = DATA_DIR / "excluded_stocks.csv"
    frame.to_csv(output, index=False)
    return output


def invalid_close_mask(series: pd.Series) -> pd.Series:
    """True for missing, non-numeric, zero, or negative close values."""
    values = pd.to_numeric(series, errors="coerce")
    return values.isna() | (values <= 0)

