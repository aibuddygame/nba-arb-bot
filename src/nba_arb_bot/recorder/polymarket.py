"""Synthetic Polymarket full-snapshot adapter. No REST, WebSocket or trade transport."""

from decimal import Decimal, localcontext
import gzip
import hashlib
import json
from pathlib import Path
import re

from .identities import team_id
from .planner import Planner, stamp, utc
from .synthetic import (
    Capture, PayloadError, _check_keys, _identifier, _no_duplicates, _seconds, _timestamp,
)

VERSION = "synthetic-polymarket-v1"


def decode_fixture(body: bytes):
    if not isinstance(body, bytes) or len(body) > 2_000_000:
        raise PayloadError("invalid_payload_size_or_type")
    try:
        data = json.loads(body, object_pairs_hook=_no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(PayloadError("nonfinite_json")))
        _check_keys(data)
        if (not isinstance(data, dict) or data.get("synthetic") is not True
                or data.get("schema") != VERSION or data.get("kind") != "full_snapshot"):
            raise PayloadError("synthetic_full_snapshot_required")
        if set(data) - {"schema", "synthetic", "kind", "status", "error_code", "events"}:
            raise PayloadError("unknown_envelope_field")
        if data.get("status") not in {"ok", "source_error"} or not isinstance(data.get("events"), list):
            raise PayloadError("invalid_source_status_or_events")
        if data["status"] == "source_error":
            _identifier(data.get("error_code"))
            if data["events"]:
                raise PayloadError("source_error_cannot_have_events")
        elif data.get("error_code") is not None:
            raise PayloadError("unexpected_error_code")
        event_ids, market_ids, condition_ids, asset_ids = set(), set(), set(), set()
        for event in data["events"]:
            if not isinstance(event, dict):
                raise PayloadError("invalid_event")
            _unique(event.get("event_id"), event_ids)
            if not isinstance(event.get("markets"), list):
                raise PayloadError("invalid_markets")
            for market in event["markets"]:
                if not isinstance(market, dict):
                    raise PayloadError("invalid_market")
                _unique(market.get("market_id"), market_ids)
                _unique(market.get("condition_id"), condition_ids)
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    raise PayloadError("invalid_outcomes")
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        raise PayloadError("invalid_outcome")
                    _unique(outcome.get("asset_id"), asset_ids)
        return data
    except PayloadError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise PayloadError("invalid_json_structure") from None


def _unique(value, seen):
    value = _identifier(value)
    if value in seen:
        raise PayloadError("duplicate_source_identity")
    seen.add(value)


def _decimal(value, *, price=False):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("invalid_decimal_text")
    number = Decimal(value)
    if number <= 0 or (price and number >= 1):
        raise ValueError("invalid_price_or_size")
    return number


def _side(levels, *, reverse, limit):
    """Validate the entire side before sorting/truncating; never infer missing levels."""
    if not isinstance(levels, list):
        raise ValueError("missing_book_side")
    values, seen = [], set()
    for level in levels:
        if not isinstance(level, dict):
            raise ValueError("invalid_level")
        p, size = _decimal(level.get("price"), price=True), _decimal(level.get("size"))
        if p in seen:
            raise ValueError("duplicate_book_price")
        seen.add(p)
        values.append((p, size))
    values.sort(key=lambda value: value[0], reverse=reverse)
    return values[:limit], len(values) > limit


def _fee_known(fees, received):
    """Synthetic metadata validation only; no claim about live Polymarket fee rules."""
    try:
        if not isinstance(fees, dict) or set(fees) != {"model", "rate", "currency", "updated_at"}:
            return False
        if fees["model"] != "synthetic-parabolic-v1" or fees["currency"] != "synthetic-usdc":
            return False
        # A zero rate is explicitly known, not missing.
        rate = fees["rate"]
        if not isinstance(rate, str) or not re.fullmatch(r"\d+(?:\.\d+)?", rate) or len(rate) > 64:
            return False
        return 0 <= Decimal(rate) <= 1 and stamp(_timestamp(fees["updated_at"])) <= received
    except (ValueError, KeyError):
        return False


class PolymarketArchive:
    @staticmethod
    def install(planner: Planner):
        if planner.db.execute("SELECT name FROM sqlite_master WHERE name='polymarket_component'").fetchone():
            PolymarketArchive(planner)
            return
        try:
            planner.db.executescript(Path(__file__).with_name("polymarket_schema.sql").read_text())
        except Exception:
            if planner.db.in_transaction:
                planner.db.execute("ROLLBACK")
            raise

    def __init__(self, planner: Planner):
        self.planner, self.db = planner, planner.db
        if not self.db.execute("SELECT name FROM sqlite_master WHERE name='polymarket_component'").fetchone():
            raise ValueError("Call PolymarketArchive.install explicitly first")
        if [r[0] for r in self.db.execute("SELECT version FROM polymarket_component")] != [1]:
            raise ValueError("Unsupported Polymarket component version")

    def bind_market(self, *, binding_id, game_id, event_id, market_id, condition_id,
                    assets_by_team, rules_ref, observed_at, evidence):
        """Pin a reviewed game/market/condition/outcome identity; no fuzzy auto-binding."""
        for value in (binding_id, game_id, event_id, market_id, condition_id):
            _identifier(value)
        if rules_ref is not None:
            _identifier(rules_ref)
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Binding requires evidence")
        at = stamp(observed_at)
        assets = {team_id(team): _identifier(asset) for team, asset in assets_by_team.items()}
        if len(assets) != 2 or len(set(assets.values())) != 2 or len(assets_by_team) != 2:
            raise ValueError("Require distinct explicit assets for exactly two teams")
        metadata = (binding_id, game_id, event_id, market_id, condition_id, rules_ref, at, evidence)
        with self.planner._transaction():
            game = self.db.execute("SELECT * FROM games WHERE game_id=?", (game_id,)).fetchone()
            if game is None or set(assets) != {game["away_team_id"], game["home_team_id"]}:
                raise ValueError("Binding teams do not match game")
            existing = self.db.execute("SELECT * FROM polymarket_bindings WHERE binding_id=?", (binding_id,)).fetchone()
            if existing:
                saved = dict(self.db.execute("SELECT team_id,asset_id FROM polymarket_bound_outcomes WHERE binding_id=?", (binding_id,)))
                if tuple(existing) != metadata or saved != assets:
                    raise ValueError("Binding conflicts with pinned identity")
                return
            mapping = self.db.execute("SELECT game_id FROM source_event_mappings WHERE source=? AND source_event_id=?",
                                      (VERSION, event_id)).fetchone()
            if mapping and mapping[0] != game_id:
                raise ValueError("Event already bound to another game")
            if mapping is None:
                self.db.execute("INSERT INTO source_event_mappings VALUES(?,?,?,?,?)", (VERSION, event_id, game_id, at, evidence))
            self.db.execute("INSERT INTO polymarket_bindings VALUES(?,?,?,?,?,?,?,?)", metadata)
            self.db.executemany("INSERT INTO polymarket_bound_outcomes VALUES(?,?,?)",
                                [(binding_id, team, asset) for team, asset in assets.items()])

    def _slot(self, binding_id, slot_id, received):
        row = self.db.execute("""SELECT s.*,r.game_id,r.scheduled_start_utc,g.status AS game_status,
            g.away_team_id,g.home_team_id,r.revision_number,
            (SELECT MAX(revision_number) FROM schedule_revisions WHERE game_id=r.game_id) AS latest
            FROM snapshot_slots s JOIN schedule_revisions r USING(revision_id)
            JOIN games g USING(game_id) WHERE slot_id=?""", (slot_id,)).fetchone()
        binding = self.db.execute("SELECT * FROM polymarket_bindings WHERE binding_id=?", (binding_id,)).fetchone()
        if (row is None or binding is None or row["game_id"] != binding["game_id"]
                or row["state"] != "planned" or row["revision_number"] != row["latest"]):
            raise ValueError("Unknown, mismatched or terminal slot/binding")
        if received < row["planned_at"] or received < binding["observed_at"]:
            raise ValueError("Slot or binding is in the future")
        return row, binding

    def ingest(self, body, *, capture: Capture, slots: dict[str, int],
               max_quote_age_seconds=None, max_levels=10):
        data, times = decode_fixture(body), capture.times()
        if (not slots or any(type(v) is not int for v in slots.values())
                or len(set(slots.values())) != len(slots)):
            raise ValueError("Require explicit unique binding-to-slot IDs")
        for binding in slots:
            _identifier(binding)
        if type(max_levels) is not int or not 1 <= max_levels <= 100:
            raise ValueError("Depth limit must be an integer from 1 to 100")
        if max_quote_age_seconds is not None and (type(max_quote_age_seconds) is not int or max_quote_age_seconds < 0):
            raise ValueError("Quote age policy must be nonnegative integer seconds")
        digest = hashlib.sha256(body).hexdigest()
        metadata = (capture.capture_id, digest, VERSION, *times, json.dumps(slots, sort_keys=True),
                    max_quote_age_seconds, max_levels, data["status"], data.get("error_code"))
        with self.planner._transaction():
            old = self.db.execute("SELECT * FROM polymarket_captures WHERE capture_id=?", (capture.capture_id,)).fetchone()
            if old:
                if tuple(old) != metadata:
                    raise ValueError("Capture ID conflicts with prior evidence")
                self.raw_response(digest)
                return self.quotes(capture.capture_id)
            selected = [self._slot(binding, slot, times[2]) for binding, slot in slots.items()]
            self.db.execute("INSERT OR IGNORE INTO polymarket_raw_responses VALUES(?,?)", (digest, gzip.compress(body, mtime=0)))
            self.raw_response(digest)
            self.db.execute("INSERT INTO polymarket_captures VALUES(?,?,?,?,?,?,?,?,?,?,?)", metadata)
            events = {e["event_id"]: e for e in data["events"]}
            for slot, binding in selected:
                self._market(data, events.get(binding["event_id"]), slot, binding,
                             capture, max_quote_age_seconds, max_levels)
            return self.quotes(capture.capture_id)

    def _market(self, data, event, slot, binding, capture, age_policy, limit):
        state, flags, market = "available", [], None
        if data["status"] == "source_error":
            state = "source_error"
        elif event is None:
            state = "event_missing"
        else:
            try:
                teams = {team_id(event["away"]), team_id(event["home"])}
                if teams != {slot["away_team_id"], slot["home_team_id"]} or stamp(_timestamp(event["starts_at"])) != slot["scheduled_start_utc"]:
                    raise ValueError
                market = next((m for m in event["markets"] if m["market_id"] == binding["market_id"]), None)
                if market is None:
                    state = "market_missing"
                elif market["condition_id"] != binding["condition_id"]:
                    state, market = "identity_mismatch", None
                elif market.get("type") != "moneyline" or market.get("period") != "full_game":
                    state, market = "unsupported_market", None
            except (KeyError, ValueError):
                state, market = "identity_mismatch", None
        if market is not None and market.get("status") != "open":
            state = market["status"] if market.get("status") in ("suspended", "closed", "resolved") else "unknown_status"
        if state != "available":
            flags.append(state)
        if event and event.get("status") not in ("scheduled", "delayed"):
            flags.append("source_game_not_confirmed_pregame")
        if slot["game_status"] not in ("scheduled", "delayed"):
            flags.append("planner_game_not_pregame")
        at = stamp(capture.received_at)
        if at >= slot["scheduled_start_utc"]:
            flags.append("boundary_or_after_start")
        rules = market.get("rules_ref") if market else None
        if rules is not None:
            _identifier(rules)
        if rules is None or binding["rules_ref"] is None:
            flags.append("rules_unknown")
        elif rules != binding["rules_ref"]:
            flags.append("rules_mismatch")
        fees = market.get("fees") if market else None
        fee_known = _fee_known(fees, at)
        if not fee_known:
            flags.append("fees_unknown_or_invalid")
        assets = dict(self.db.execute("SELECT team_id,asset_id FROM polymarket_bound_outcomes WHERE binding_id=?", (binding["binding_id"],)))
        outcomes = {}
        if market:
            for item in market["outcomes"]:
                try:
                    team = team_id(item.get("team"))
                    if team in outcomes or assets.get(team) != item["asset_id"]:
                        raise ValueError
                    outcomes[team] = item
                except ValueError:
                    flags.append("outcome_mapping_mismatch")
            if len(outcomes) != 2:
                flags.append("incomplete_outcomes")
        self.db.execute("INSERT INTO polymarket_markets VALUES(?,?,?,?,?,?,?)",
                        (capture.capture_id, binding["binding_id"], slot["slot_id"], state,
                         rules, json.dumps(fees, sort_keys=True), json.dumps(sorted(set(flags)))))
        for team, asset in assets.items():
            self._quote(outcomes.get(team), slot, binding, capture, team, asset, state,
                        flags, fee_known, age_policy, limit)

    def _quote(self, item, slot, binding, capture, team, asset, market_state, base_flags,
               fee_known, age_policy, limit):
        flags, levels = list(base_flags), []
        state = market_state if market_state != "available" else ("available" if item else "outcome_missing")
        bid = ask = midpoint = last_price = last_at = updated = age = None
        bid_size = ask_size = depth = None
        if item is not None:
            for side, reverse in (("bid", True), ("ask", False)):
                try:
                    values, truncated = _side(item.get(side + "s"), reverse=reverse, limit=limit)
                    if truncated:
                        flags.append("depth_truncated")
                    for rank, (price, size) in enumerate(values):
                        levels.append((capture.capture_id, binding["binding_id"], team, side, rank, str(price), str(size)))
                    if values:
                        if side == "bid":
                            bid, bid_size = map(str, values[0])
                        else:
                            ask, ask_size = map(str, values[0])
                except ValueError:
                    flags.append("invalid_" + side + "_levels")
            if bid is None or ask is None:
                flags.append("one_sided_or_empty_book")
                if state == "available":
                    state = "partial" if bid or ask else "empty"
            elif Decimal(bid) >= Decimal(ask):
                flags.append("crossed_or_locked_book")
            else:
                with localcontext() as context:
                    context.prec = 28
                    midpoint = str((Decimal(bid) + Decimal(ask)) / 2)
            supplied_depth = item.get("depth_complete")
            if type(supplied_depth) is bool:
                depth = int(supplied_depth and "depth_truncated" not in flags)
                if not supplied_depth:
                    flags.append("partial_depth")
            else:
                flags.append("depth_unknown")
            try:
                updated_dt = _timestamp(item.get("updated_at"))
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
            if item.get("last_trade") is not None:
                try:
                    last = item["last_trade"]
                    last_price = str(_decimal(last["price"], price=True))
                    last_at = stamp(_timestamp(last["at"]))
                    if last_at > stamp(capture.received_at):
                        flags.append("future_last_trade")
                except (ValueError, KeyError, TypeError):
                    last_price = last_at = None
                    flags.append("invalid_last_trade")
        if state != "available":
            flags.append(state)
        late = str(_seconds(utc(capture.received_at) - _timestamp(slot["planned_at"])))
        if Decimal(late) > 0:
            flags.append("lateness_unassessed")
        informational = {"fees_unknown_or_invalid", "partial_depth", "depth_unknown", "depth_truncated",
                         "invalid_last_trade", "future_last_trade"}
        unassessed = {"freshness_unassessed", "lateness_unassessed", "rules_unknown"}
        blocking = set(flags) - informational - unassessed
        eligible = 0 if blocking else (None if unassessed.intersection(flags) else 1)
        cost_complete = int(eligible == 1 and fee_known and depth == 1
                            and "rules_unknown" not in flags and not informational.intersection(flags))
        self.db.execute("INSERT INTO polymarket_quotes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (capture.capture_id, binding["binding_id"], team, asset, state,
                         bid, bid_size, ask, ask_size, midpoint, last_price, last_at, updated,
                         age, late, depth, json.dumps(sorted(set(flags))), eligible, cost_complete))
        self.db.executemany("INSERT INTO polymarket_levels VALUES(?,?,?,?,?,?,?)", levels)

    def quotes(self, capture_id):
        return self.db.execute("SELECT * FROM polymarket_quotes WHERE capture_id=? ORDER BY binding_id,team_id", (capture_id,)).fetchall()

    def levels(self, capture_id):
        return self.db.execute("SELECT * FROM polymarket_levels WHERE capture_id=? ORDER BY binding_id,team_id,side,rank", (capture_id,)).fetchall()

    def raw_response(self, digest):
        row = self.db.execute("SELECT body_gzip FROM polymarket_raw_responses WHERE sha256=?", (digest,)).fetchone()
        if row is None:
            raise ValueError("Unknown response hash")
        body = gzip.decompress(row[0])
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Raw evidence hash mismatch")
        return body
