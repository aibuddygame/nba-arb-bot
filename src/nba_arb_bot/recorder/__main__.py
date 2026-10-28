"""Explicit synthetic demonstration; no live data, config, email or durable database."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

from .planner import Planner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True,
                        help="plan one fictional fixture in a temporary database")
    parser.parse_args()
    start = datetime(2026, 10, 29, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix="nba-p01-demo-") as directory:
        with Planner(Path(directory) / "synthetic.sqlite") as planner:
            planner.reconcile(game_id="synthetic-LAL-BOS", season="2026-27",
                              away="LAL", home="BOS", start=start,
                              observed_at=start - timedelta(hours=13))
            slots = [dict(row) for row in planner.slots("synthetic-LAL-BOS")]
    print(json.dumps({"synthetic": True, "database": "temporary; removed on exit",
                      "slot_count": len(slots), "slots": slots}, indent=2))


if __name__ == "__main__":
    main()
