"""Regenerate the example table of the README from synthetic data (never real data).

Usage: createdb lifter_example && uv run python scripts/readme_example.py postgresql:///lifter_example
then: DATABASE_URL=postgresql:///lifter_example uv run lifter metrics --days 14
"""

import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from lifter.db import connect, migrate  # noqa: E402
from synthetic import load_days  # noqa: E402

FIRST_DAY = date(2026, 8, 3)
DAYS = 56


def synthetic_days(seed: int = 7) -> list[dict]:
    """56 days with two rest days a week, then a hard last week with falling HRV."""
    rng = random.Random(seed)
    days = []
    for i in range(DAYS):
        weekday = i % 7
        rest = weekday in (0, 4)
        load = 0 if rest else rng.choice([45, 60, 75, 90, 120])
        if i >= 49:
            load = 0 if weekday == 0 else rng.choice([110, 130, 150])
        days.append(
            {
                "load": load or None,
                "hrv": round(rng.gauss(62, 3), 1) - (6 if i >= 52 else 0),
                "rhr": round(rng.gauss(51, 1)) + (3 if i >= 53 else 0),
                "sleep_hours": round(rng.uniform(6.2, 8.1), 2),
            }
        )
    return days


def main(url: str) -> None:
    with connect(url) as conn:
        migrate(conn)
        load_days(conn, FIRST_DAY, synthetic_days())


if __name__ == "__main__":
    main(sys.argv[1])
