"""Synthetic-only bookmaker adapter and explicit optional SQLite archive.

No network client, credentials, scheduler or legacy configuration is imported.
The fixture contract is ours, not a claim of compatibility with a live provider.
"""

from decimal import Decimal, InvalidOperation, localcontext
import gzip
import hashlib
import json
from pathlib import Path
import re

from .identities import team_id
from .planner import Planner, stamp, utc
from .synthetic import (
    Capture, PayloadError, _identifier, _timestamp, _seconds, _no_duplicates, _check_keys,
)

VERSION = "synthetic-bookmaker-v1"


def decode_fixture(body: bytes) -> dict:
    """Strict envelope; malformed/non-synthetic payloads are never archived."""
    if not isinstance(body, bytes) or len(body) > 2_000_000:
        raise PayloadError("invalid_payload_size_or_type")
    try:
        data = json.loads(body, object_pairs_hook=_no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(PayloadError("nonfinite_json")))
        _check_keys(data)
        if not isinstance(data, dict) or data.get("synthetic") is not True or data.get("schema") != VERSION:
            raise PayloadError("synthetic_envelope_required")
        if set(data) - {"schema", "synthetic", "status", "error_code", "events"}:
            raise PayloadError("unknown_envelope_field")
        if data.get("status") not in {"ok", "source_error"}:
            raise PayloadError("invalid_source_status")
        events = data.get("events")
        if not isinstance(events, list):
            raise PayloadError("events_must_be_list")
        if data["status"] == "source_error":
            _identifier(data.get("error_code"))
            if events:
                raise PayloadError("source_error_cannot_have_events")
        elif data.get("error_code") is not None:
            raise PayloadError("unexpected_error_code")
        ids = set()
        for event in events:
            if not isinstance(event, dict):
                raise PayloadError("invalid_event")
            event_id = _identifier(event.get("event_id"))
            if event_id in ids:
                raise PayloadError("duplicate_event_id")
            ids.add(event_id)
            if not isinstance(event.get("bookmakers"), list):
                raise PayloadError("bookmakers_must_be_list")
            book_ids = set()
            for book in event["bookmakers"]:
                if not isinstance(book, dict):
                    raise PayloadError("invalid_bookmaker")
                book_id = _identifier(book.get("book_id"))
                if book_id in book_ids:
                    raise PayloadError("duplicate_book_id")
                book_ids.add(book_id)
                if not isinstance(book.get("markets"), list):
                    raise PayloadError("markets_must_be_list")
                keys = set()
                for market in book["markets"]:
                    if not isinstance(market, dict):
                        raise PayloadError("invalid_market")
                    key = (_identifier(market.get("type")), _identifier(market.get("period")))
                    if key in keys:
                        raise PayloadError("duplicate_market")
                    keys.add(key)
        return data
    except PayloadError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise PayloadError("invalid_json_structure") from None


def normalize_odds(price, odds_format):
    """Return exact-decimal text and implied probability, with fixed precision 28.

    Contract prices are strings; bools/floats/missing/nonfinite values are invalid.
    Source text remains intact in original_price_json and raw evidence.
    """
    if not isinstance(price, str) or len(price) > 64:
        raise ValueError("invalid_price")
    with localcontext() as context:
        context.prec = 28
        try:
            if odds_format == "american" and re.fullmatch(r"[+-]?\d+", price):
                american = Decimal(price)
                if abs(american) < 100:
                    raise ValueError("invalid_price")
                decimal = 1 + (american / 100 if american > 0 else 100 / abs(american))
            elif odds_format == "decimal" and re.fullmatch(r"\d+(?:\.\d+)?", price):
                decimal = Decimal(price)
            else:
                raise ValueError("invalid_price_or_format")
            if not decimal.is_finite() or decimal <= 1:
                raise ValueError("invalid_price")
            return str(decimal), str(1 / decimal)
        except InvalidOperation:
            raise ValueError("invalid_price") from None


class BookmakerArchive:
    """Attach to P01 after an explicit install; opening never migrates the database."""

    @staticmethod
    def install(planner: Planner):
        """Explicit additive extension. Existing P01 rows/schema version are retained."""
        exists = planner.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bookmaker_component'"
        ).fetchone()
        if exists:
            BookmakerArchive(planner)
            return
        try:
            planner.db.executescript(Path(__file__).with_name("bookmaker_schema.sql").read_text())
        except Exception:
            if planner.db.in_transaction:
                planner.db.execute("ROLLBACK")
            raise

    def __init__(self, planner: Planner):
        self.planner = planner
        self.db = planner.db
        exists = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bookmaker_component'"
        ).fetchone()
        if not exists:
            raise ValueError("Call BookmakerArchive.install explicitly first")
        if [row[0] for row in self.db.execute("SELECT version FROM bookmaker_component")] != [1]:
            raise ValueError("Unsupported bookmaker component version")

    def ingest(self, body: bytes, *, capture: Capture, slots: dict[str, int],
               expected_books: tuple[str, ...], max_quote_age_seconds: int | None = None):
        """Archive one synthetic response against explicitly selected slots atomically.

        Idempotency is capture_id + complete input metadata. Identical bodies on a new
        capture remain distinct observations. No slot state is completed or advanced.
        """
        data = decode_fixture(body)
        times = capture.times()
        if not slots or any(type(v) is not int for v in slots.values()):
            raise ValueError("Explicit event-to-slot bindings required")
        for event_id in slots:
            _identifier(event_id)
        if len(set(slots.values())) != len(slots):
            raise ValueError("Multiple source events cannot bind one slot")
        if not expected_books or len(set(expected_books)) != len(expected_books):
            raise ValueError("Require unique expected bookmaker IDs")
        for book in expected_books:
            _identifier(book)
        if max_quote_age_seconds is not None and (
            type(max_quote_age_seconds) is not int or max_quote_age_seconds < 0
        ):
            raise ValueError("Quote age policy must be nonnegative integer seconds")
        digest = hashlib.sha256(body).hexdigest()
        bindings_json = json.dumps(slots, sort_keys=True)
        books_json = json.dumps(sorted(expected_books))
        metadata = (capture.capture_id, digest, VERSION, *times, bindings_json,
                    books_json, max_quote_age_seconds, data["status"], data.get("error_code"))
        events = {e["event_id"]: e for e in data["events"]}
        with self.planner._transaction():
            existing = self.db.execute("SELECT * FROM bookmaker_captures WHERE capture_id=?",
                                       (capture.capture_id,)).fetchone()
            if existing:
                if tuple(existing) != metadata:
                    raise ValueError("Capture ID conflicts with prior evidence")
                self.raw_response(digest)  # Verify stored bytes before accepting replay.
                return self.markets(capture.capture_id)
            bindings = {event_id: self._slot(slot_id, times[2]) for event_id, slot_id in slots.items()}
            self.db.execute("INSERT OR IGNORE INTO bookmaker_raw_responses VALUES(?,?)",
                            (digest, gzip.compress(body, mtime=0)))
            self.raw_response(digest)
            self.db.execute("INSERT INTO bookmaker_captures VALUES(?,?,?,?,?,?,?,?,?,?,?)", metadata)
            for event_id, slot in bindings.items():
                event = events.get(event_id)
                identity_ok = self._identity_matches(event, slot)
                books = {b["book_id"]: b for b in event["bookmakers"]} if event else {}
                for book_id in sorted(set(expected_books) | set(books)):
                    self._market(capture, data, event_id, event, slot, identity_ok,
                                 book_id, books.get(book_id), max_quote_age_seconds)
            return self.markets(capture.capture_id)

    def _slot(self, slot_id, received_at):
        row = self.db.execute("""
            SELECT s.*,r.game_id,r.scheduled_start_utc,g.away_team_id,g.home_team_id,
                   g.status AS game_status,
                   (SELECT MAX(revision_number) FROM schedule_revisions WHERE game_id=r.game_id) AS latest,
                   r.revision_number
            FROM snapshot_slots s JOIN schedule_revisions r USING(revision_id)
            JOIN games g USING(game_id) WHERE slot_id=?""", (slot_id,)).fetchone()
        if row is None or row["state"] != "planned" or row["revision_number"] != row["latest"]:
            raise ValueError("Slot is absent, terminal or superseded")
        if received_at < row["planned_at"]:
            raise ValueError("Cannot attach a future observation slot")
        return row

    def _identity_matches(self, event, slot):
        if event is None:
            return False
        try:
            teams = {team_id(event["away"]), team_id(event["home"])}
            if teams != {slot["away_team_id"], slot["home_team_id"]}:
                return False
            if stamp(_timestamp(event["starts_at"])) != slot["scheduled_start_utc"]:
                return False
            mapping = self.db.execute(
                "SELECT game_id FROM source_event_mappings WHERE source=? AND source_event_id=?",
                (VERSION, event["event_id"])).fetchone()
            return mapping is None or mapping[0] == slot["game_id"]
        except (KeyError, ValueError):
            return False

    def _market(self, capture, data, event_id, event, slot, identity_ok,
                book_id, book, age_policy):
        flags = []
        rules_ref = updated = age = None
        market = None
        availability = "available"
        if data["status"] == "source_error":
            availability = "source_error"
        elif event is None:
            availability = "event_missing"
        elif not identity_ok:
            availability = "identity_mismatch"
        elif book is None:
            availability = "book_missing"
        else:
            market = next((m for m in book["markets"] if
                           m["type"] == "moneyline" and m["period"] == "full_game"), None)
            if book.get("status") == "suspended":
                availability = "suspended"
            elif market is None:
                availability = "market_missing"
            elif market.get("status") == "suspended":
                availability = "suspended"
            elif book.get("status") != "open" or market.get("status") != "open":
                availability = "unknown_status"
        if market is not None:
            rules_ref = market.get("rules_ref")
            if rules_ref is not None:
                _identifier(rules_ref)
            try:
                updated_dt = _timestamp(market.get("updated_at"))
                updated = stamp(updated_dt)
                age = str(_seconds(utc(capture.received_at) - updated_dt))
                if Decimal(age) < 0:
                    flags.append("unexpected_future_timestamp")
                elif age_policy is None:
                    flags.append("freshness_unassessed")
                elif Decimal(age) > age_policy:
                    flags.append("stale")
            except ValueError:
                flags.append("source_timestamp_missing_or_invalid")
        if availability != "available":
            flags.append(availability)
        if event and event.get("status") not in {"scheduled", "delayed"}:
            flags.append("source_game_not_confirmed_pregame")
        if slot["game_status"] not in {"scheduled", "delayed"}:
            flags.append("planner_game_not_pregame")
        received = stamp(capture.received_at)
        if received >= slot["scheduled_start_utc"]:
            flags.append("boundary_or_after_start")
        if rules_ref is None:
            flags.append("rules_unknown")
        outcomes = {}
        if market is not None:
            items = market.get("outcomes")
            if not isinstance(items, list):
                flags.append("invalid_outcomes")
            else:
                for item in items:
                    try:
                        if not isinstance(item, dict):
                            raise ValueError
                        outcome_id = team_id(item.get("team"))
                        if outcome_id not in {slot["away_team_id"], slot["home_team_id"]} or outcome_id in outcomes:
                            raise ValueError
                        outcomes[outcome_id] = item
                    except ValueError:
                        flags.append("ambiguous_or_unknown_outcome")
        rows = []
        for outcome_id in (slot["away_team_id"], slot["home_team_id"]):
            item = outcomes.get(outcome_id)
            price = item.get("price") if item else None
            odds_format = market.get("odds_format") if market else None
            decimal = implied = None
            state = availability
            if market is not None:
                if item is None:
                    state = "outcome_missing"
                else:
                    try:
                        decimal, implied = normalize_odds(price, odds_format)
                    except ValueError:
                        state = "invalid_price"
            if state != "available":
                flags.append(state)
            rows.append((capture.capture_id, slot["slot_id"], book_id, outcome_id,
                         json.dumps(price), odds_format if isinstance(odds_format, str) else None,
                         decimal, implied, state))
        if market is not None and any(row[-1] in {"outcome_missing", "invalid_price"} for row in rows):
            if availability == "available":
                availability = "partial"
            flags.append("incomplete_two_sided_book")
        if all(row[7] is not None for row in rows):
            if sum(Decimal(row[7]) for row in rows) < 1:
                flags.append("overround_below_one")
        lateness = str(_seconds(utc(capture.received_at) - _timestamp(slot["planned_at"])))
        if Decimal(lateness) > 0:
            flags.append("lateness_unassessed")
        flags = sorted(set(flags))
        unassessed = {"freshness_unassessed", "lateness_unassessed"}
        blocking = set(flags) - unassessed - {"rules_unknown"}
        eligible = 0 if blocking else (None if unassessed.intersection(flags) else 1)
        self.db.execute("INSERT INTO bookmaker_markets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (capture.capture_id, slot["slot_id"], book_id, event_id, "moneyline", "full_game",
                         rules_ref, availability, updated, age, lateness, json.dumps(flags), eligible))
        self.db.executemany("INSERT INTO bookmaker_quotes VALUES(?,?,?,?,?,?,?,?,?)", rows)

    def markets(self, capture_id):
        return self.db.execute(
            "SELECT * FROM bookmaker_markets WHERE capture_id=? ORDER BY slot_id,book_id",
            (capture_id,)).fetchall()

    def quotes(self, capture_id):
        return self.db.execute(
            "SELECT * FROM bookmaker_quotes WHERE capture_id=? ORDER BY slot_id,book_id,team_id",
            (capture_id,)).fetchall()

    def raw_response(self, sha256):
        row = self.db.execute("SELECT body_gzip FROM bookmaker_raw_responses WHERE sha256=?",
                              (sha256,)).fetchone()
        if row is None:
            raise ValueError("Unknown response hash")
        body = gzip.decompress(row[0])
        if hashlib.sha256(body).hexdigest() != sha256:
            raise ValueError("Raw evidence hash mismatch")
        return body
