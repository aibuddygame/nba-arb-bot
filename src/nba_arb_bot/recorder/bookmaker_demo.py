"""Replay an explicit synthetic fixture in a temporary database; live IO is absent."""

import argparse
from datetime import timedelta
import json
from pathlib import Path
import tempfile

from .bookmaker import BookmakerArchive, Capture, _timestamp, decode_fixture
from .planner import Planner, stamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--received-at", required=True)
    parser.add_argument("--expected-books", nargs="+", required=True)
    parser.add_argument("--max-quote-age-seconds", type=int, default=None)
    args = parser.parse_args()
    body = args.fixture.read_bytes()
    data = decode_fixture(body)
    received = _timestamp(args.received_at)
    with tempfile.TemporaryDirectory(prefix="nba-p02-demo-") as directory:
        with Planner(Path(directory)/"synthetic.sqlite") as planner:
            bindings = {}
            for event in data["events"]:
                game_id = "synthetic-" + event["event_id"]
                planner.reconcile(game_id=game_id, season="synthetic-season",
                                  away=event["away"], home=event["home"],
                                  start=_timestamp(event["starts_at"]), observed_at=received)
                matches = [s for s in planner.slots(game_id) if s["planned_at"] == stamp(received)]
                if len(matches) != 1:
                    raise ValueError("Demo receipt must coincide with a planned slot")
                bindings[event["event_id"]] = matches[0]["slot_id"]
            BookmakerArchive.install(planner)
            archive = BookmakerArchive(planner)
            markets = archive.ingest(
                body, capture=Capture("synthetic-demo", received-timedelta(seconds=2),
                                      received-timedelta(seconds=1), received),
                slots=bindings, expected_books=tuple(args.expected_books),
                max_quote_age_seconds=args.max_quote_age_seconds)
            result = {"synthetic": True, "live_collection": "disabled; no transport implemented",
                      "database": "temporary; removed on exit", "market_count": len(markets),
                      "quote_count": len(archive.quotes("synthetic-demo")),
                      "markets": [dict(row) for row in markets]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
