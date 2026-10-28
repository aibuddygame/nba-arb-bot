"""Offline, persistent game-relative slot planning. No network or notifications."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import sqlite3

from .identities import TEAMS, team_id

UTC = timezone.utc
STATUSES = {"scheduled", "delayed", "postponed", "live", "final", "cancelled"}


def utc(value: datetime) -> datetime:
    """Reject naive/nonexistent local times; callers must supply an explicit instant."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    result = value.astimezone(UTC)
    if result.astimezone(value.tzinfo).replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ValueError("Nonexistent local time; supply a valid UTC instant")
    return result


def stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds")


def planned_times(start: datetime) -> tuple[datetime, ...]:
    """25 UTC instants, including scheduled tip-off; elapsed-time arithmetic across DST."""
    first = utc(start) - timedelta(hours=12)
    return tuple(first + timedelta(minutes=30 * i) for i in range(25))


class Planner:
    """Explicit-path SQLite planner. Open/close it with a context manager.

    Past unobserved slots are missed (no collection/backfill). P04 must define a
    collection lateness policy and implement attempts/leases before live use.
    """

    def __init__(self, database: str | Path):
        self.db = sqlite3.connect(str(database), isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone():
                    raise ValueError("Refusing to initialize an unrelated nonempty database")
                self.db.executescript(Path(__file__).with_name("schema.sql").read_text())
            elif version != 1:
                raise ValueError(f"Unsupported planner schema version: {version}")
            if self.db.execute("PRAGMA application_id").fetchone()[0] != 1312964944:
                raise ValueError("Not a planner database")
            with self._transaction():
                self.db.executemany("INSERT OR IGNORE INTO teams VALUES (?, ?)",
                                    [(t.team_id, t.name) for t in TEAMS])
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self):
        # Adapter writes may participate in a fenced collector transaction.
        nested = self.db.in_transaction
        savepoint = "nested_" + uuid4().hex
        self.db.execute("SAVEPOINT " + savepoint if nested else "BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("RELEASE " + savepoint if nested else "COMMIT")
        except Exception:
            if nested:
                self.db.execute("ROLLBACK TO " + savepoint)
                self.db.execute("RELEASE " + savepoint)
            else:
                self.db.execute("ROLLBACK")
            raise

    def _transition(self, slot, state: str, at: str, reason: str):
        if slot["state"] == state:
            return
        self.db.execute("UPDATE snapshot_slots SET state=? WHERE slot_id=?",
                        (state, slot["slot_id"]))
        self.db.execute(
            "INSERT INTO slot_events(slot_id,from_state,to_state,observed_at,reason) VALUES(?,?,?,?,?)",
            (slot["slot_id"], slot["state"], state, at, reason))

    def reconcile(self, *, game_id: str, season: str, away: str, home: str,
                  start: datetime, observed_at: datetime, status: str = "scheduled",
                  max_lateness_seconds: int = 0) -> int:
        """Create/reconcile one fixture atomically; return its current revision ID.

        game_id is an explicit durable internal identity, never derived from team words.
        A source change of start time creates a revision, not a new game. Stale or
        contradictory same-time fixture observations are rejected.
        """
        if type(max_lateness_seconds) is not int or max_lateness_seconds < 0:
            raise ValueError("Lateness grace must be a nonnegative integer")
        away_id, home_id = team_id(away), team_id(home)
        at, tip = stamp(observed_at), stamp(start)
        if not game_id.strip() or not season.strip() or away_id == home_id:
            raise ValueError("Require game ID, season and two distinct teams")
        if status not in STATUSES:
            raise ValueError(f"Unsupported game status: {status}")
        with self._transaction():
            game = self.db.execute("SELECT * FROM games WHERE game_id=?", (game_id,)).fetchone()
            previous = self.db.execute(
                "SELECT * FROM schedule_revisions WHERE game_id=? ORDER BY revision_number DESC LIMIT 1",
                (game_id,)).fetchone()
            if game:
                if (game["season"], game["away_team_id"], game["home_team_id"]) != (season, away_id, home_id):
                    raise ValueError("Game identity conflicts with the existing fixture")
                if at < game["last_observed_at"]:
                    raise ValueError("Out-of-order fixture observation")
                if at == game["last_observed_at"] and (
                    status != game["status"] or tip != previous["scheduled_start_utc"]
                ):
                    raise ValueError("Conflicting fixture observations at the same time")
                if game["status"] in {"live", "final", "cancelled"} and status not in (
                    {"live", "final"} if game["status"] == "live" else {game["status"]}
                ):
                    raise ValueError("Cannot reopen a started/terminal game")
                self.db.execute("UPDATE games SET status=?,last_observed_at=? WHERE game_id=?",
                                (status, at, game_id))
            else:
                self.db.execute("INSERT INTO games VALUES(?,?,?,?,?,?)",
                                (game_id, season, away_id, home_id, status, at))
            if not game or game["status"] != status:
                self.db.execute("INSERT INTO game_events(game_id,status,observed_at) VALUES(?,?,?)",
                                (game_id, status, at))
            changed = (previous is None or previous["scheduled_start_utc"] != tip
                       or (game is not None and game["status"] == "postponed"
                           and status in {"scheduled", "delayed"}))
            if changed and previous:
                for slot in self.slots(game_id, revision_id=previous["revision_id"]):
                    if slot["state"] == "planned":
                        state = "missed" if slot["planned_at"] < at else "superseded"
                        self._transition(slot, state, at, "schedule_changed")
            if changed:
                number = previous["revision_number"] + 1 if previous else 1
                cursor = self.db.execute(
                    "INSERT INTO schedule_revisions(game_id,revision_number,scheduled_start_utc,observed_at,previous_revision_id) VALUES(?,?,?,?,?)",
                    (game_id, number, tip, at, previous["revision_id"] if previous else None))
                revision_id = cursor.lastrowid
                for index, planned in enumerate(planned_times(start)):
                    planned_at = stamp(planned)
                    state = self._initial_state(status, planned_at, at, max_lateness_seconds)
                    cursor = self.db.execute(
                        "INSERT INTO snapshot_slots(revision_id,slot_index,planned_at,state) VALUES(?,?,?,?)",
                        (revision_id, index, planned_at, state))
                    self.db.execute(
                        "INSERT INTO slot_events(slot_id,from_state,to_state,observed_at,reason) VALUES(?,NULL,?,?,?)",
                        (cursor.lastrowid, state, at, "fixture_discovered" if not previous else "schedule_revised"))
            else:
                revision_id = previous["revision_id"]
                for slot in self.slots(game_id, revision_id=revision_id):
                    if slot["state"] == "planned":
                        state = self._initial_state(status, slot["planned_at"], at, max_lateness_seconds)
                        self._transition(slot, state, at, "fixture_reconciled")
            return revision_id

    @staticmethod
    def _initial_state(status: str, planned_at: str, at: str, max_lateness_seconds: int = 0) -> str:
        deadline = stamp(datetime.fromisoformat(planned_at) + timedelta(seconds=max_lateness_seconds))
        if deadline < at or (status not in {"scheduled", "delayed"} and planned_at < at):
            return "missed"
        if status in {"live", "final"}:
            return "cancelled_after_start"
        if status in {"postponed", "cancelled"}:
            return "cancelled_event"
        return "planned"

    def slots(self, game_id: str, *, revision_id: int | None = None) -> list[sqlite3.Row]:
        """All retained revisions by default, including terminal and missed slots."""
        query = """SELECT s.*,r.game_id,r.revision_number,r.scheduled_start_utc
                   FROM snapshot_slots s JOIN schedule_revisions r USING(revision_id)
                   WHERE r.game_id=?"""
        args = [game_id]
        if revision_id is not None:
            query += " AND r.revision_id=?"
            args.append(revision_id)
        return self.db.execute(query + " ORDER BY r.revision_number,s.slot_index", args).fetchall()

    def record_slot_result(self, slot_id: int, *, state: str, observed_at: datetime):
        """Offline bookkeeping hook; does not create quotes or prove a collection."""
        if state not in {"complete", "partial"}:
            raise ValueError("Result must be complete or partial")
        at = stamp(observed_at)
        with self._transaction():
            slot = self.db.execute("SELECT * FROM snapshot_slots WHERE slot_id=?", (slot_id,)).fetchone()
            if slot is None:
                raise ValueError("Unknown slot")
            if at < slot["planned_at"]:
                raise ValueError("Cannot record a slot before its planned time")
            if slot["state"] == state:
                return
            if slot["state"] != "planned":
                raise ValueError("Cannot overwrite a terminal slot result")
            game = self.db.execute(
                "SELECT g.* FROM games g JOIN schedule_revisions r USING(game_id) WHERE r.revision_id=?",
                (slot["revision_id"],)).fetchone()
            if game["status"] not in {"scheduled", "delayed"}:
                raise ValueError("Game is not accepting pregame results")
            self._transition(slot, state, at, "offline_result_recorded")

    def match_game(self, *, away: str, home: str, start: datetime) -> str:
        """Exact unordered teams + current scheduled instant; ambiguity is an error.

        This finds identity candidates only, not compatible betting contracts.
        """
        a, b, tip = team_id(away), team_id(home), stamp(start)
        rows = self.db.execute("""
            SELECT g.game_id FROM games g JOIN schedule_revisions r USING(game_id)
            WHERE r.revision_number=(SELECT MAX(revision_number) FROM schedule_revisions
                                     WHERE game_id=g.game_id)
            AND r.scheduled_start_utc=? AND
            ((g.away_team_id=? AND g.home_team_id=?) OR
             (g.away_team_id=? AND g.home_team_id=?))
            """, (tip, a, b, b, a)).fetchall()
        if len(rows) != 1:
            raise ValueError(f"Expected one exact fixture match; found {len(rows)}")
        return rows[0]["game_id"]

    def bind_source_event(self, *, source: str, source_event_id: str, game_id: str,
                          observed_at: datetime, evidence: str):
        """Bind an explicitly reviewed mapping; conflicting bindings cannot overwrite."""
        if not all(isinstance(v, str) and v.strip() for v in (source, source_event_id, game_id, evidence)):
            raise ValueError("Mapping requires nonempty source, IDs and evidence")
        at = stamp(observed_at)
        with self._transaction():
            existing = self.db.execute(
                "SELECT game_id FROM source_event_mappings WHERE source=? AND source_event_id=?",
                (source, source_event_id)).fetchone()
            if existing and existing[0] != game_id:
                raise ValueError("Source event is already bound to another game")
            if not existing:
                self.db.execute("INSERT INTO source_event_mappings VALUES(?,?,?,?,?)",
                                (source, source_event_id, game_id, at, evidence))
