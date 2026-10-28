"""Persistent paired scheduling for local synthetic sources only; no live transport."""

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .bookmaker import BookmakerArchive
from .polymarket import PolymarketArchive
from .planner import Planner, stamp
from .synthetic import Capture, PayloadError, _identifier, _seconds, _timestamp

SOURCES = ("bookmaker", "polymarket")
TERMINAL = {"succeeded", "exhausted", "cancelled"}


@dataclass(frozen=True)
class CollectionPolicy:
    policy_id: str
    max_lateness_seconds: int
    max_pair_gap_seconds: int
    max_quote_age_seconds: int
    max_game_state_age_seconds: int
    lease_seconds: int
    max_attempts: int
    retry_delay_seconds: int
    max_retry_delay_seconds: int
    max_source_calls: int
    max_depth_levels: int = 10

    def validate(self):
        _identifier(self.policy_id)
        for key, value in asdict(self).items():
            if key != "policy_id" and (type(value) is not int or value < 0):
                raise ValueError("Policy values must be nonnegative integers")
        if min(self.lease_seconds,self.max_attempts,self.retry_delay_seconds) < 1:
            raise ValueError("Lease, attempts and retry delay must be positive")
        if self.max_attempts > 20 or not 1 <= self.max_depth_levels <= 100:
            raise ValueError("Attempts/depth exceed supported bounds")
        if self.max_retry_delay_seconds < self.retry_delay_seconds:
            raise ValueError("Retry cap is below base delay")
        return self


@dataclass(frozen=True)
class Claim:
    attempt_id: int
    worker_id: str
    source: str
    capture_id: str


class LeaseLost(ValueError):
    pass


class SyntheticFailure(Exception):
    """Fixed safe error codes, never raw exception text from a service."""
    def __init__(self, code="synthetic_unavailable"):
        if code not in {"synthetic_unavailable", "synthetic_timeout"}:
            raise ValueError("Unsupported synthetic failure")
        self.code = code
        super().__init__(code)


class SyntheticSource:
    """In-memory local response sequence, deliberately no callback/URL/transport."""
    def __init__(self, responses):
        self.responses = tuple(responses)
        if any(type(item) not in (bytes, SyntheticFailure) for item in self.responses):
            raise ValueError("Synthetic sources accept only bytes or fixed failures")
        self.calls = 0

    def read(self):
        index = self.calls
        self.calls += 1
        if index >= len(self.responses):
            raise SyntheticFailure()
        item = self.responses[index]
        if type(item) is SyntheticFailure:
            raise item
        return item


class PairedCollector:
    @staticmethod
    def install(planner):
        """Explicit installation; no production database is implicitly migrated."""
        if planner.db.in_transaction:
            raise ValueError("Install collector extensions outside active transactions")
        BookmakerArchive.install(planner)
        PolymarketArchive.install(planner)
        if planner.db.execute("SELECT name FROM sqlite_master WHERE name='collector_component'").fetchone():
            PairedCollector(planner)
            return
        try:
            planner.db.executescript(Path(__file__).with_name("collector_schema.sql").read_text())
        except Exception:
            if planner.db.in_transaction:
                planner.db.execute("ROLLBACK")
            raise

    def __init__(self, planner: Planner):
        self.planner, self.db = planner, planner.db
        if not self.db.execute("SELECT name FROM sqlite_master WHERE name='collector_component'").fetchone():
            raise ValueError("Call PairedCollector.install explicitly first")
        if [r[0] for r in self.db.execute("SELECT version FROM collector_component")] != [1]:
            raise ValueError("Unsupported collector component version")
        self.bookmaker, self.polymarket = BookmakerArchive(planner), PolymarketArchive(planner)

    def register(self, *, game_id, bookmaker_event_id, binding_id, expected_books,
                 policy: CollectionPolicy, observed_at):
        policy.validate()
        _identifier(bookmaker_event_id); _identifier(binding_id)
        if not expected_books or len(set(expected_books)) != len(expected_books):
            raise ValueError("Require a nonempty unique bookmaker universe")
        for book in expected_books:
            _identifier(book)
        at, body = stamp(observed_at), json.dumps(asdict(policy), sort_keys=True)
        books = json.dumps(sorted(expected_books))
        with self.planner._transaction():
            binding = self.db.execute("SELECT * FROM polymarket_bindings WHERE binding_id=?", (binding_id,)).fetchone()
            if binding is None or binding["game_id"] != game_id or binding["observed_at"] > at:
                raise ValueError("Require a reviewed binding for this game before registration")
            old = self.db.execute("SELECT body_json FROM collector_policies WHERE policy_id=?", (policy.policy_id,)).fetchone()
            if old and old[0] != body:
                raise ValueError("Policy ID cannot silently change")
            if not old:
                self.db.execute("INSERT INTO collector_policies VALUES(?,?)", (policy.policy_id, body))
            revision = self.db.execute("SELECT MAX(revision_id) FROM schedule_revisions WHERE game_id=?", (game_id,)).fetchone()[0]
            if revision is None:
                raise ValueError("Unknown fixture")
            for slot in self.planner.slots(game_id, revision_id=revision):
                values = (slot["slot_id"], policy.policy_id, bookmaker_event_id, binding_id, books, at)
                existing = self.db.execute("SELECT * FROM collector_slots WHERE slot_id=?", (slot["slot_id"],)).fetchone()
                if existing:
                    if tuple(existing)[:5] != values[:5]:
                        raise ValueError("Slot registration cannot silently change")
                    continue
                self.db.execute("INSERT INTO collector_slots VALUES(?,?,?,?,?,?)", values)
                for source in SOURCES:
                    cursor = self.db.execute("INSERT INTO collector_jobs(slot_id,source,state,next_at) VALUES(?,?,'pending',?)",
                                             (slot["slot_id"], source, slot["planned_at"]))
                    self._event(cursor.lastrowid,"pending",at,"registered")

    def reconcile_fixture(self, *, policy: CollectionPolicy, **fixture):
        """Refresh a fixture without expiring a slot inside this explicit grace window."""
        policy.validate()
        return self.planner.reconcile(**fixture,max_lateness_seconds=policy.max_lateness_seconds)

    def _event(self, job_id, state, at, reason):
        self.db.execute("INSERT INTO collector_job_events(job_id,state,observed_at,reason) VALUES(?,?,?,?)",
                        (job_id,state,at,reason))

    def _row(self, slot_id):
        return self.db.execute("""SELECT s.*,c.policy_id,c.bookmaker_event_id,c.binding_id,c.expected_books_json,c.registered_at,
            r.game_id,r.scheduled_start_utc,r.revision_number,g.status AS game_status,g.last_observed_at,
            g.away_team_id,g.home_team_id,
            (SELECT MAX(revision_number) FROM schedule_revisions WHERE game_id=r.game_id) AS latest
            FROM collector_slots c JOIN snapshot_slots s USING(slot_id)
            JOIN schedule_revisions r USING(revision_id) JOIN games g USING(game_id) WHERE s.slot_id=?""",(slot_id,)).fetchone()

    def _policy(self, slot):
        return CollectionPolicy(**json.loads(self.db.execute("SELECT body_json FROM collector_policies WHERE policy_id=?",
                                                           (slot["policy_id"],)).fetchone()[0])).validate()

    @staticmethod
    def _valid(slot):
        return (slot["state"] == "planned" and slot["revision_number"] == slot["latest"]
                and slot["game_status"] in {"scheduled","delayed"})

    @staticmethod
    def _fresh(observed, at, limit):
        age = _seconds(_timestamp(at)-_timestamp(observed))
        return 0 <= age <= limit

    def _end_job(self, job, state, at, reason):
        if job["state"] == "running":
            self.db.execute("INSERT INTO collector_attempt_results(attempt_id,status,error_code,recorded_at) VALUES(?,?,?,?)",
                            (job["active_attempt_id"],reason,reason,at))
        self.db.execute("UPDATE collector_jobs SET state=?,lease_until=NULL WHERE job_id=?", (state,job["job_id"]))
        self._event(job["job_id"],state,at,reason)

    def _retry_or_end(self, job, policy, at, reason):
        exhausted = job["attempt_count"] >= policy.max_attempts
        delay = min(policy.max_retry_delay_seconds,policy.retry_delay_seconds * 2**max(0,job["attempt_count"]-1))
        state = "exhausted" if exhausted else "pending"
        self.db.execute("UPDATE collector_jobs SET state=?,next_at=?,lease_until=NULL WHERE job_id=?",
                        (state,stamp(_timestamp(at)+timedelta(seconds=delay)),job["job_id"]))
        self._event(job["job_id"],state,at,reason)

    def _maintain(self, at):
        # Avoid revisiting all completed history and far-future season slots on every tick.
        candidates=self.db.execute("""SELECT DISTINCT j.slot_id FROM collector_jobs j
            JOIN snapshot_slots s USING(slot_id)
            WHERE (j.state IN ('pending','running') AND
                   (j.next_at<=? OR s.state!='planned' OR j.state='running'))
               OR (s.state='planned' AND s.planned_at<=?) ORDER BY j.slot_id""",(at,at)).fetchall()
        for registration in candidates:
            slot = self._row(registration[0]);policy=self._policy(slot)
            if at < slot["registered_at"]:
                continue
            jobs = self.db.execute("SELECT * FROM collector_jobs WHERE slot_id=?", (slot["slot_id"],)).fetchall()
            deadline = stamp(_timestamp(slot["planned_at"])+timedelta(seconds=policy.max_lateness_seconds))
            invalid = not self._valid(slot)
            expired = at > deadline or at >= slot["scheduled_start_utc"]
            for job in jobs:
                if job["state"] in TERMINAL:
                    continue
                if invalid or expired:
                    self._end_job(job,"cancelled" if invalid else "exhausted",at,
                                  "slot_invalidated" if invalid else "collection_window_closed")
                elif job["state"] == "running" and job["lease_until"] <= at:
                    self.db.execute("INSERT INTO collector_attempt_results(attempt_id,status,error_code,recorded_at) VALUES(?,?,?,?)",
                                    (job["active_attempt_id"],"lease_expired","lease_expired",at))
                    self._retry_or_end(job,policy,at,"lease_expired")
            if not invalid:
                self._finalize(slot["slot_id"],at)

    def claim(self, *, worker_id, now, source=None):
        _identifier(worker_id);at=stamp(now)
        if source is not None and source not in SOURCES:
            raise ValueError("Unknown source")
        with self.planner._transaction():
            self._maintain(at)
            jobs=self.db.execute("SELECT * FROM collector_jobs WHERE state='pending' AND next_at<=? ORDER BY next_at,job_id",(at,)).fetchall()
            for job in jobs:
                if source is not None and job["source"] != source:
                    continue
                slot=self._row(job["slot_id"]);policy=self._policy(slot)
                if at < slot["registered_at"]:
                    continue
                if not self._fresh(slot["last_observed_at"],at,policy.max_game_state_age_seconds):
                    next_at=stamp(_timestamp(at)+timedelta(seconds=policy.retry_delay_seconds))
                    self.db.execute("UPDATE collector_jobs SET next_at=? WHERE job_id=?",(next_at,job["job_id"]))
                    self._event(job["job_id"],"pending",at,"game_state_not_fresh")
                    continue
                used=self.db.execute("SELECT COALESCE(SUM(units),0) FROM collector_quota WHERE policy_id=? AND source=?",
                                     (policy.policy_id,job["source"])).fetchone()[0]
                if used >= policy.max_source_calls:
                    self._end_job(job,"exhausted",at,"synthetic_quota_exhausted")
                    self._finalize(slot["slot_id"],at)
                    continue
                lease=stamp(_timestamp(at)+timedelta(seconds=policy.lease_seconds))
                capture_id="p04-"+uuid4().hex
                cursor=self.db.execute("INSERT INTO collector_attempts(job_id,retry_number,worker_id,claimed_at,lease_until,capture_id,game_observed_at) VALUES(?,?,?,?,?,?,?)",
                    (job["job_id"],job["attempt_count"],worker_id,at,lease,capture_id,slot["last_observed_at"]))
                attempt_id=cursor.lastrowid
                self.db.execute("INSERT INTO collector_quota VALUES(?,?,?,?,?)",(attempt_id,policy.policy_id,job["source"],1,at))
                self.db.execute("UPDATE collector_jobs SET state='running',attempt_count=attempt_count+1,active_attempt_id=?,lease_until=? WHERE job_id=?",
                                (attempt_id,lease,job["job_id"]))
                self._event(job["job_id"],"running",at,"claimed")
                return Claim(attempt_id,worker_id,job["source"],capture_id)
            return None

    def finish(self, claim: Claim, *, capture: Capture, finished_at, body=None, error_code=None):
        """Fence first; atomically archive response, append result, update job and pair slot."""
        times,at=capture.times(),stamp(finished_at)
        if capture.capture_id != claim.capture_id or times[2] > at:
            raise ValueError("Capture identity or receipt chronology mismatch")
        if error_code not in {None,"synthetic_timeout","synthetic_unavailable"} or (body is None) == (error_code is None):
            raise ValueError("Provide synthetic bytes or a fixed source failure")
        if body is not None and type(body) is not bytes:
            raise ValueError("Only local response bytes are accepted")
        digest=hashlib.sha256(body).hexdigest() if body is not None else None
        with self.planner._transaction():
            attempt=self.db.execute("SELECT * FROM collector_attempts WHERE attempt_id=?",(claim.attempt_id,)).fetchone()
            if attempt is None or attempt["worker_id"] != claim.worker_id or attempt["capture_id"] != claim.capture_id:
                raise LeaseLost("Unknown or mismatched attempt")
            job=self.db.execute("SELECT * FROM collector_jobs WHERE job_id=?",(attempt["job_id"],)).fetchone()
            if job["source"] != claim.source or times[0] < attempt["claimed_at"]:
                raise ValueError("Source or request chronology mismatch")
            prior=self.db.execute("SELECT * FROM collector_attempt_results WHERE attempt_id=?",(claim.attempt_id,)).fetchone()
            if prior:
                if (prior["received_at"] is not None and prior["body_sha256"] == digest
                        and tuple(prior[k] for k in ("request_started_at","request_finished_at","received_at")) == times
                        and (prior["error_code"] == error_code or (body is not None and error_code is None))):
                    return prior["status"]
                raise LeaseLost("Attempt already ended")
            if job["state"] != "running" or job["active_attempt_id"] != claim.attempt_id or at >= job["lease_until"]:
                raise LeaseLost("Lease no longer owns this job")
            slot=self._row(job["slot_id"]);policy=self._policy(slot)
            if not self._valid(slot):
                self.db.execute("INSERT INTO collector_attempt_results VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (claim.attempt_id,"slot_invalidated",None,*times,digest,"slot_invalidated",at,slot["last_observed_at"]))
                self.db.execute("UPDATE collector_jobs SET state='cancelled',lease_until=NULL WHERE job_id=?",(job["job_id"],))
                self._event(job["job_id"],"cancelled",at,"slot_invalidated")
                return "slot_invalidated"
            status,capture_id,code="transport_error",None,error_code
            if body is not None:
                try:
                    if claim.source == "bookmaker":
                        self.bookmaker.ingest(body,capture=capture,slots={slot["bookmaker_event_id"]:slot["slot_id"]},
                            expected_books=tuple(json.loads(slot["expected_books_json"])),max_quote_age_seconds=policy.max_quote_age_seconds)
                    else:
                        self.polymarket.ingest(body,capture=capture,slots={slot["binding_id"]:slot["slot_id"]},
                            max_quote_age_seconds=policy.max_quote_age_seconds,max_levels=policy.max_depth_levels)
                    capture_id=claim.capture_id
                    table="bookmaker_captures" if claim.source=="bookmaker" else "polymarket_captures"
                    source_status=self.db.execute(f"SELECT source_status FROM {table} WHERE capture_id=?",(capture_id,)).fetchone()[0]
                    status="succeeded" if source_status=="ok" else "source_error"
                    code=None if status=="succeeded" else "source_error"
                except (PayloadError,ValueError,TypeError):
                    status,code="parse_error","invalid_synthetic_payload"
            self.db.execute("INSERT INTO collector_attempt_results VALUES(?,?,?,?,?,?,?,?,?,?)",
                (claim.attempt_id,status,capture_id,*times,digest,code,at,slot["last_observed_at"]))
            if status == "succeeded":
                self.db.execute("UPDATE collector_jobs SET state='succeeded',lease_until=NULL WHERE job_id=?",(job["job_id"],))
                self._event(job["job_id"],"succeeded",at,"response_archived")
            else:
                self._retry_or_end(job,policy,at,code)
            self._finalize(slot["slot_id"],at)
            return status

    def run_once(self, *, worker_id, clock, sources):
        """One bounded step. Caller drives ticks; no daemon, sleep or live source hooks."""
        if set(sources) != set(SOURCES) or any(type(s) is not SyntheticSource for s in sources.values()):
            raise ValueError("Only the two concrete local SyntheticSource objects are permitted")
        claim=self.claim(worker_id=worker_id,now=clock())
        if claim is None:
            return None
        start=clock();body=error=None
        try:
            body=sources[claim.source].read()
        except SyntheticFailure as exc:
            error=exc.code
        end,receipt=clock(),clock()
        return self.finish(claim,capture=Capture(claim.capture_id,start,end,receipt),
                           finished_at=clock(),body=body,error_code=error)

    def _successful(self, slot_id, source):
        return self.db.execute("""SELECT r.*,a.attempt_id FROM collector_attempt_results r
            JOIN collector_attempts a USING(attempt_id) JOIN collector_jobs j USING(job_id)
            WHERE j.slot_id=? AND j.source=? AND r.status='succeeded' ORDER BY a.retry_number LIMIT 1""",(slot_id,source)).fetchone()

    def _finalize(self, slot_id, at):
        slot=self._row(slot_id)
        if not self._valid(slot) or self.db.execute("SELECT 1 FROM collector_jobs WHERE slot_id=? AND state IN ('pending','running')",(slot_id,)).fetchone():
            return
        policy=self._policy(slot)
        b,p=self._successful(slot_id,"bookmaker"),self._successful(slot_id,"polymarket")
        # A clock moving backwards must never create a join with future evidence.
        if any(result and max(result["received_at"],result["recorded_at"]) > at for result in (b,p)):
            return
        bc,pc=(b["capture_id"] if b else None),(p["capture_id"] if p else None)
        markets={r["book_id"]:r for r in self.db.execute("SELECT * FROM bookmaker_markets WHERE capture_id=? AND slot_id=?",(bc,slot_id))}
        books=set(json.loads(slot["expected_books_json"]))|set(markets)
        all_good=True
        for book in sorted(books):
            for team in (slot["away_team_id"],slot["home_team_id"]):
                bq=self.db.execute("SELECT * FROM bookmaker_quotes WHERE capture_id=? AND slot_id=? AND book_id=? AND team_id=?",(bc,slot_id,book,team)).fetchone()
                pq=self.db.execute("SELECT * FROM polymarket_quotes WHERE capture_id=? AND binding_id=? AND team_id=?",(pc,slot["binding_id"],team)).fetchone()
                pm=self.db.execute("SELECT * FROM polymarket_markets WHERE capture_id=? AND binding_id=?",(pc,slot["binding_id"])).fetchone()
                flags=[];gap=None
                if bq is None:flags.append("bookmaker_observation_missing")
                if pq is None:flags.append("polymarket_observation_missing")
                for label,result in (("bookmaker",b),("polymarket",p)):
                    if result:
                        if not self._fresh(result["game_observed_at"],result["received_at"],policy.max_game_state_age_seconds):
                            flags.append(label+"_game_state_not_fresh")
                        late=_seconds(_timestamp(result["received_at"])-_timestamp(slot["planned_at"]))
                        if not 0 <= late <= policy.max_lateness_seconds:
                            flags.append(label+"_outside_collection_window")
                        if result["received_at"] >= slot["scheduled_start_utc"]:
                            flags.append(label+"_boundary_or_after_start")
                if b and p:
                    gap=str(abs(_seconds(_timestamp(b["received_at"])-_timestamp(p["received_at"]))))
                    if Decimal(gap)>policy.max_pair_gap_seconds:flags.append("receipt_gap_exceeded")
                if bq and pq:
                    bf=set(json.loads(markets[book]["flags_json"]))-{"lateness_unassessed","freshness_unassessed"}
                    pf=set(json.loads(pq["flags_json"]))-{"lateness_unassessed","freshness_unassessed",
                        "fees_unknown_or_invalid","partial_depth","depth_unknown","depth_truncated","invalid_last_trade","future_last_trade"}
                    flags += ["bookmaker_"+f for f in sorted(bf)]+["polymarket_"+f for f in sorted(pf)]
                    if bq["availability"]!="available" or bq["implied_probability"] is None:flags.append("bookmaker_quote_unavailable")
                    if pq["availability"]!="available" or pq["midpoint"] is None:flags.append("polymarket_quote_unavailable")
                    if not markets[book]["rules_ref"] or not pm["source_rules_ref"] or markets[book]["rules_ref"]!=pm["source_rules_ref"]:
                        flags.append("settlement_rules_not_matched")
                eligible=int(not flags);all_good=all_good and bool(eligible)
                # P03 leaves lateness unassessed; P04 can assess it with this policy.
                only_timing_advisories = (pq is not None and set(json.loads(pq["flags_json"])).issubset(
                    {"lateness_unassessed","freshness_unassessed"}))
                cost=int(bool(eligible and pq is not None and (pq["cost_metadata_complete"] or
                    (only_timing_advisories and pq["depth_complete"] == 1))))
                self.db.execute("INSERT INTO collector_pairs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (slot_id,policy.policy_id,"synthetic-pairing-v1",book,team,bc if bq else None,pc if pq else None,slot["binding_id"],gap,
                     eligible,cost,json.dumps(sorted(set(flags))),at))
        state="complete" if all_good else ("partial" if b or p else "missed")
        self.planner._transition(slot,state,at,"paired_collection_finalized")

    def pairs(self, slot_id):
        return self.db.execute("SELECT * FROM collector_pairs WHERE slot_id=? ORDER BY book_id,team_id",(slot_id,)).fetchall()

    def usage(self):
        return self.db.execute("SELECT policy_id,source,SUM(units) AS units FROM collector_quota GROUP BY policy_id,source").fetchall()
