"""Replay the known synthetic Polymarket fixture against an explicitly pinned mapping."""

import argparse
from datetime import timedelta
import json
from pathlib import Path
import tempfile

from .planner import Planner
from .polymarket import PolymarketArchive
from .synthetic import Capture, _timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--received-at", required=True)
    parser.add_argument("--max-quote-age-seconds", type=int, default=None)
    parser.add_argument("--max-levels", type=int, default=10)
    args = parser.parse_args()
    received = _timestamp(args.received_at)
    with tempfile.TemporaryDirectory(prefix="nba-p03-demo-") as directory:
        with Planner(Path(directory)/"synthetic.sqlite") as planner:
            # Explicit fictional reference fixture; never infer a mapping from source order.
            planner.reconcile(game_id="fictional-lal-bos", season="synthetic-season",
                              away="LAL", home="BOS", start=_timestamp("2026-10-29T00:00:00Z"),
                              observed_at=received-timedelta(hours=1))
            PolymarketArchive.install(planner)
            archive = PolymarketArchive(planner)
            archive.bind_market(binding_id="synthetic-binding", game_id="fictional-lal-bos",
                                event_id="fictional-lal-bos", market_id="synthetic-moneyline-1",
                                condition_id="synthetic-condition-1",
                                assets_by_team={"LAL":"synthetic-asset-lal", "BOS":"synthetic-asset-bos"},
                                rules_ref="synthetic-including-overtime-v1",
                                observed_at=received-timedelta(hours=1), evidence="explicit synthetic demo mapping")
            quotes = archive.ingest(args.fixture.read_bytes(),
                capture=Capture("synthetic-demo", received-timedelta(seconds=2),
                                received-timedelta(seconds=1), received),
                slots={"synthetic-binding":planner.slots("fictional-lal-bos")[0]["slot_id"]},
                max_quote_age_seconds=args.max_quote_age_seconds, max_levels=args.max_levels)
            result = {"synthetic":True, "live_collection":"disabled; no transport implemented",
                      "database":"temporary; removed on exit", "quote_count":len(quotes),
                      "level_count":len(archive.levels("synthetic-demo")),
                      "quotes":[dict(q) for q in quotes]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
