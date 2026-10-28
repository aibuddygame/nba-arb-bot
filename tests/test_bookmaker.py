"""P02 acceptance: synthetic local bytes and temporary SQLite only."""

from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nba_arb_bot.recorder import Planner
from nba_arb_bot.recorder.bookmaker import (
    BookmakerArchive, Capture, PayloadError, VERSION, decode_fixture, normalize_odds,
)

FIXTURE = Path(__file__).parent / "fixtures/bookmaker-synthetic.json"
RECEIVED = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
START = RECEIVED + timedelta(hours=12)
BOOKS = ("synthetic-a", "synthetic-b", "synthetic-c", "synthetic-d")


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.network_guard = patch("socket.socket", side_effect=AssertionError("network disabled"))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.sqlite"
        self.p = Planner(self.path)
        self.addCleanup(lambda: self.p.close())
        self.p.reconcile(game_id="g1", season="2026-27", away="LAL", home="BOS",
                         start=START, observed_at=RECEIVED-timedelta(hours=1))
        self.slot = self.p.slots("g1")[0]["slot_id"]
        self.body = FIXTURE.read_bytes()
        self.data = json.loads(self.body)
        BookmakerArchive.install(self.p)
        self.archive = BookmakerArchive(self.p)

    def capture(self, name="capture-1", at=RECEIVED):
        return Capture(name, at-timedelta(seconds=2), at-timedelta(seconds=1), at)

    def ingest(self, data=None, **changes):
        body = self.body if data is None else json.dumps(data).encode()
        args = dict(capture=self.capture(), slots={"fictional-lal-bos":self.slot},
                    expected_books=BOOKS, max_quote_age_seconds=120)
        args.update(changes)
        return self.archive.ingest(body, **args)

    def count(self, table):
        return self.p.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def market(self, data=None):
        return (data or self.data)["events"][0]["bookmakers"][0]["markets"][0]

    def test_preserves_each_book_two_sides_source_times_and_raw_evidence(self):
        markets = {row["book_id"]: row for row in self.ingest()}
        self.assertEqual(set(markets), set(BOOKS))
        self.assertEqual(markets["synthetic-a"]["availability"], "available")
        self.assertEqual(Decimal(markets["synthetic-a"]["quote_age_seconds"]), Decimal(30))
        self.assertEqual(markets["synthetic-b"]["availability"], "suspended")
        self.assertEqual(markets["synthetic-c"]["availability"], "partial")
        self.assertEqual(markets["synthetic-d"]["availability"], "book_missing")
        self.assertEqual(len(self.archive.quotes("capture-1")), 8)
        self.assertEqual(self.archive.raw_response(hashlib.sha256(self.body).hexdigest()),self.body)
        row=self.p.db.execute("SELECT * FROM bookmaker_captures").fetchone()
        self.assertLess(row["request_started_at"], row["request_finished_at"])
        self.assertLess(row["request_finished_at"], row["received_at"])
        self.assertTrue(all(row["state"]=="planned" for row in self.p.slots("g1")))

    def test_missing_side_remains_null_not_zero_or_other_books_price(self):
        self.ingest()
        quotes={row["team_id"]:row for row in self.archive.quotes("capture-1") if row["book_id"]=="synthetic-c"}
        self.assertEqual(quotes["LAL"]["availability"],"outcome_missing")
        self.assertIsNone(quotes["LAL"]["decimal_odds"])
        self.assertEqual(quotes["LAL"]["original_price_json"],"null")
        self.assertEqual(quotes["BOS"]["decimal_odds"],"1.6800")

    def test_shuffled_books_and_outcomes_do_not_shift_attribution(self):
        self.data["events"][0]["bookmakers"].reverse()
        self.market()["outcomes"].reverse()
        self.ingest(self.data)
        quote=next(row for row in self.archive.quotes("capture-1") if row["book_id"]=="synthetic-a" and row["team_id"]=="LAL")
        self.assertEqual(json.loads(quote["original_price_json"]),"+130")
        self.assertEqual(quote["decimal_odds"],"2.3")

    def test_multiple_games_share_raw_response_but_only_explicit_slots_recorded(self):
        self.ingest()
        self.assertEqual(self.count("bookmaker_markets"),4)
        self.p.reconcile(game_id="g2",season="2026-27",away="LAC",home="NYK",
                         start=START,observed_at=RECEIVED-timedelta(hours=1))
        other=self.p.slots("g2")[0]["slot_id"]
        rows=self.ingest(capture=self.capture("batch"),slots={"fictional-lal-bos":self.slot,"fictional-lac-nyk":other})
        self.assertEqual(len(rows),8)
        self.assertEqual(self.count("bookmaker_raw_responses"),1)
        self.assertEqual(self.count("bookmaker_captures"),2)

    def test_identical_capture_replay_and_restart_are_idempotent(self):
        self.ingest()
        self.p.close()
        self.p=Planner(self.path)
        self.archive=BookmakerArchive(self.p)
        self.ingest()
        self.assertEqual(self.count("bookmaker_captures"),1)
        self.assertEqual(self.count("bookmaker_quotes"),8)

    def test_identical_body_new_receipt_is_distinct_observation(self):
        self.ingest()
        self.ingest(capture=self.capture("capture-2",RECEIVED+timedelta(seconds=30)))
        self.assertEqual(self.count("bookmaker_raw_responses"),1)
        self.assertEqual(self.count("bookmaker_quotes"),16)

    def test_capture_id_reuse_with_changed_payload_or_policy_rejected(self):
        self.ingest()
        self.market()["outcomes"][0]["price"]="+140"
        for args in [dict(data=self.data),dict(max_quote_age_seconds=60),dict(expected_books=("synthetic-a",))]:
            with self.subTest(args=args),self.assertRaises(ValueError):self.ingest(**args)
        self.assertEqual(self.count("bookmaker_quotes"),8)

    def test_source_failure_is_not_an_empty_success(self):
        data={"schema":VERSION,"synthetic":True,"status":"source_error","error_code":"synthetic_timeout","events":[]}
        rows=self.ingest(data)
        self.assertTrue(all(r["availability"]=="source_error" for r in rows))
        self.assertTrue(all(r["benchmark_eligible"]==0 for r in rows))
        self.assertEqual(self.p.db.execute("SELECT source_error_code FROM bookmaker_captures").fetchone()[0],"synthetic_timeout")

    def test_missing_event_book_and_market_are_separate_states(self):
        self.data["events"][0]["bookmakers"][0]["markets"]=[]
        rows={r["book_id"]:r for r in self.ingest(self.data)}
        self.assertEqual(rows["synthetic-a"]["availability"],"market_missing")
        self.assertEqual(rows["synthetic-d"]["availability"],"book_missing")
        self.data["events"]=[]
        rows=self.ingest(self.data,capture=self.capture("missing"))
        self.assertTrue(all(r["availability"]=="event_missing" for r in rows))

    def test_stale_future_missing_and_unknown_freshness_policy(self):
        cases=[("2026-10-28T11:00:00Z",120,"stale",0),
               ("2026-10-28T12:01:00Z",120,"unexpected_future_timestamp",0),
               (None,120,"source_timestamp_missing_or_invalid",0),
               ("bad-date",120,"source_timestamp_missing_or_invalid",0),
               ("2026-10-28T11:59:30Z",None,"freshness_unassessed",None)]
        for i,(updated,policy,flag,eligible) in enumerate(cases):
            data=deepcopy(self.data);self.market(data)["updated_at"]=updated
            row=next(r for r in self.ingest(data,capture=self.capture(f"time-{i}"),max_quote_age_seconds=policy) if r["book_id"]=="synthetic-a")
            self.assertIn(flag,json.loads(row["flags_json"]))
            self.assertEqual(row["benchmark_eligible"],eligible)

    def test_wrong_team_date_and_source_mapping_fail_closed(self):
        for i,change in enumerate([("away","LAC"),("starts_at","2026-10-30T00:00:00Z")]):
            data=deepcopy(self.data);data["events"][0][change[0]]=change[1]
            rows=self.ingest(data,capture=self.capture(f"wrong-{i}"))
            self.assertTrue(all(r["availability"]=="identity_mismatch" for r in rows))
            self.assertTrue(all(r["decimal_odds"] is None for r in self.archive.quotes(f"wrong-{i}")))
        self.p.reconcile(game_id="other",season="2026-27",away="LAC",home="NYK",start=START,observed_at=RECEIVED-timedelta(hours=1))
        self.p.bind_source_event(source=VERSION,source_event_id="fictional-lal-bos",game_id="other",observed_at=RECEIVED,evidence="synthetic conflicting mapping")
        self.assertTrue(all(r["availability"]=="identity_mismatch" for r in self.ingest(capture=self.capture("mapping"))))

    def test_reversed_event_orientation_is_safe(self):
        self.data["events"][0]["away"],self.data["events"][0]["home"]="BOS","LAL"
        rows=self.ingest(self.data)
        self.assertEqual(rows[0]["availability"],"available")

    def test_invalid_prices_preserved_but_never_normalized(self):
        for i,price in enumerate([0,True,1.9,"0","1","NaN","Infinity","-50",None,"n/a"]):
            data=deepcopy(self.data);market=self.market(data)
            market["outcomes"][0]["price"]=price
            row=next(r for r in self.ingest(data,capture=self.capture(f"bad-{i}")) if r["book_id"]=="synthetic-a")
            self.assertEqual(row["availability"],"partial")
            quote=next(r for r in self.archive.quotes(f"bad-{i}") if r["book_id"]=="synthetic-a" and r["team_id"]=="LAL")
            self.assertEqual(json.loads(quote["original_price_json"]),price)
            self.assertIsNone(quote["decimal_odds"])

    def test_duplicate_and_unknown_outcomes_quarantine_market(self):
        for i,team in enumerate(["LAL","LAC","Los Angeles"]):
            data=deepcopy(self.data);self.market(data)["outcomes"].append({"team":team,"price":"+100"})
            row=self.ingest(data,capture=self.capture(f"outcome-{i}"))[0]
            self.assertIn("ambiguous_or_unknown_outcome",json.loads(row["flags_json"]))
            self.assertEqual(row["benchmark_eligible"],0)

    def test_boundary_and_live_data_not_pregame_eligible(self):
        rows=self.ingest(capture=self.capture("boundary",START))
        self.assertTrue(all(r["benchmark_eligible"]==0 for r in rows))
        self.assertIn("boundary_or_after_start",json.loads(rows[0]["flags_json"]))
        self.data["events"][0]["status"]="live"
        rows=self.ingest(self.data,capture=self.capture("live"))
        self.assertIn("source_game_not_confirmed_pregame",json.loads(rows[0]["flags_json"]))

    def test_future_missed_and_old_revision_slots_rejected(self):
        future=self.p.slots("g1")[1]["slot_id"]
        with self.assertRaises(ValueError):self.ingest(slots={"fictional-lal-bos":future})
        self.p.reconcile(game_id="g1",season="2026-27",away="LAL",home="BOS",start=START,observed_at=RECEIVED+timedelta(seconds=1))
        with self.assertRaises(ValueError):self.ingest(capture=self.capture("missed",RECEIVED+timedelta(seconds=2)))
        self.p.reconcile(game_id="g1",season="2026-27",away="LAL",home="BOS",start=START+timedelta(days=1),observed_at=RECEIVED+timedelta(seconds=3))
        with self.assertRaises(ValueError):self.ingest(capture=self.capture("old",RECEIVED+timedelta(seconds=4)))
        self.assertEqual(self.count("bookmaker_captures"),0)

    def test_duplicate_slot_bindings_rejected(self):
        with self.assertRaises(ValueError):self.ingest(slots={"fictional-lal-bos":self.slot,"fictional-lac-nyk":self.slot})

    def test_invalid_request_chronology_or_naive_receipt_rejected(self):
        for capture in [Capture("x",RECEIVED,RECEIVED-timedelta(seconds=1),RECEIVED),
                        Capture("x",RECEIVED,RECEIVED,RECEIVED.replace(tzinfo=None))]:
            with self.assertRaises(ValueError):self.ingest(capture=capture)
        self.assertEqual(self.count("bookmaker_raw_responses"),0)

    def test_unexpected_books_retained_separately(self):
        rows=self.ingest(expected_books=("synthetic-a",))
        self.assertEqual({r["book_id"] for r in rows},{"synthetic-a","synthetic-b","synthetic-c"})

    def test_unsupported_market_is_retained_in_raw_not_mislabeled_moneyline(self):
        self.market()["type"]="spreads"
        rows=self.ingest(self.data)
        self.assertEqual(rows[0]["availability"],"market_missing")
        self.assertIn(b'"spreads"',self.archive.raw_response(hashlib.sha256(json.dumps(self.data).encode()).hexdigest()))

    def test_quote_insert_failure_rolls_back_raw_capture_and_market_rows(self):
        self.p.db.execute("""CREATE TRIGGER synthetic_failure BEFORE INSERT ON bookmaker_quotes
                            BEGIN SELECT RAISE(ABORT,'synthetic failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.ingest()
        for table in ["bookmaker_quotes","bookmaker_markets","bookmaker_captures","bookmaker_raw_responses"]:
            self.assertEqual(self.count(table),0)
        self.p.db.execute("DROP TRIGGER synthetic_failure")
        self.ingest()
        self.assertEqual(self.count("bookmaker_quotes"),8)

    def test_evidence_and_quotes_cannot_be_edited_or_deleted(self):
        self.ingest()
        for table in ["bookmaker_quotes","bookmaker_markets","bookmaker_captures","bookmaker_raw_responses"]:
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):self.p.db.execute("DELETE FROM "+table)
        with self.assertRaises(sqlite3.IntegrityError):
            self.p.db.execute("UPDATE bookmaker_quotes SET decimal_odds='2.0'")

    def test_corrupt_raw_evidence_fails_hash_check(self):
        self.ingest()
        self.p.db.execute("DROP TRIGGER bookmaker_raw_no_update")
        self.p.db.execute("UPDATE bookmaker_raw_responses SET body_gzip=?",(gzip.compress(b'corrupt'),))
        with self.assertRaises(ValueError):self.archive.raw_response(hashlib.sha256(self.body).hexdigest())

    def test_explicit_extension_install_preserves_core_and_is_idempotent(self):
        self.assertEqual(self.p.db.execute("PRAGMA user_version").fetchone()[0],1)
        BookmakerArchive.install(self.p)
        self.assertEqual(len(self.p.slots("g1")),25)
        self.assertEqual(self.count("bookmaker_component"),1)
        with Planner(":memory:") as p:
            with self.assertRaises(ValueError):BookmakerArchive(p)

    def test_unassessed_lateness_never_looks_fully_eligible(self):
        row=self.ingest(capture=self.capture("late",RECEIVED+timedelta(microseconds=1)))[0]
        self.assertEqual(Decimal(row["lateness_seconds"]),Decimal("0.000001"))
        self.assertIn("lateness_unassessed",json.loads(row["flags_json"]))
        self.assertIsNone(row["benchmark_eligible"])

    def test_suspended_book_without_quotes_keeps_suspended_state(self):
        self.data["events"][0]["bookmakers"][1]["markets"]=[]
        row=next(r for r in self.ingest(self.data) if r["book_id"]=="synthetic-b")
        self.assertEqual(row["availability"],"suspended")
        self.assertEqual(row["benchmark_eligible"],0)

    def test_underround_retained_but_flagged_for_review(self):
        market=self.market();market["odds_format"]="decimal"
        for outcome in market["outcomes"]:outcome["price"]="2.5"
        row=self.ingest(self.data)[0]
        self.assertIn("overround_below_one",json.loads(row["flags_json"]))
        self.assertEqual(row["benchmark_eligible"],0)

    def test_credential_payload_rejection_leaves_no_raw_copy(self):
        self.data["events"][0]["apiKey"]="synthetic-sensitive-marker"
        with self.assertRaises(PayloadError):self.ingest(self.data)
        self.assertEqual(self.count("bookmaker_raw_responses"),0)

    def test_failed_extension_install_rolls_back_partial_schema(self):
        with Planner(":memory:") as p:
            p.db.execute("CREATE TABLE bookmaker_raw_responses(existing)")
            with self.assertRaises(sqlite3.OperationalError):BookmakerArchive.install(p)
            self.assertIsNone(p.db.execute("SELECT name FROM sqlite_master WHERE name='bookmaker_component'").fetchone())
            self.assertEqual(p.db.execute("PRAGMA user_version").fetchone()[0],1)

    def test_unknown_component_version_rejected(self):
        self.p.db.execute("DROP TABLE bookmaker_component")
        self.p.db.execute("CREATE TABLE bookmaker_component(version)")
        self.p.db.execute("INSERT INTO bookmaker_component VALUES(2)")
        with self.assertRaises(ValueError):BookmakerArchive(self.p)

    def test_replay_demo_runs_with_network_blocked_and_prints_synthetic_summary(self):
        from nba_arb_bot.recorder.bookmaker_demo import main
        output=io.StringIO()
        argv=["bookmaker_demo","--fixture",str(FIXTURE),"--received-at",RECEIVED.isoformat(),
              "--expected-books",*BOOKS,"--max-quote-age-seconds","120"]
        with patch("sys.argv",argv),redirect_stdout(output):main()
        result=json.loads(output.getvalue())
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["market_count"],8)
        self.assertEqual(result["quote_count"],16)


class EnvelopeTests(unittest.TestCase):
    def test_malformed_duplicate_nonfinite_and_non_synthetic_payloads_rejected(self):
        for body in [b'bad json',b'[]',b'{"x":1,"x":2}',b'{"x":NaN}',b'\xff',
                     b'{"schema":"synthetic-bookmaker-v1","synthetic":false,"status":"ok","events":[]}']:
            with self.subTest(body=body),self.assertRaises(PayloadError):decode_fixture(body)

    def test_credential_fields_rejected_without_value_in_exception(self):
        data=json.loads(FIXTURE.read_bytes())
        for field in ["api_key","Authorization","endpoint_url","sender_password"]:
            data[field]="synthetic-sensitive-marker"
            with self.assertRaises(PayloadError) as context:decode_fixture(json.dumps(data).encode())
            self.assertNotIn("synthetic-sensitive-marker",str(context.exception))
            del data[field]

    def test_duplicate_event_book_and_market_ids_rejected(self):
        data=json.loads(FIXTURE.read_bytes())
        variants=[]
        a=deepcopy(data);a["events"].append(deepcopy(a["events"][0]));variants.append(a)
        a=deepcopy(data);a["events"][0]["bookmakers"].append(deepcopy(a["events"][0]["bookmakers"][0]));variants.append(a)
        a=deepcopy(data);a["events"][0]["bookmakers"][0]["markets"]*=2;variants.append(a)
        for data in variants:
            with self.assertRaises(PayloadError):decode_fixture(json.dumps(data).encode())

    def test_supported_odds_formats_preserve_decimal_precision(self):
        self.assertEqual(normalize_odds("+130","american"),("2.3",str(Decimal(1)/Decimal('2.3'))))
        self.assertEqual(normalize_odds("1.6800","decimal")[0],"1.6800")
        self.assertEqual(normalize_odds("-100","american"),("2","0.5"))
        for price,fmt in [("1","decimal"),("-50","american"),("2.5","unknown"),(True,"american")]:
            with self.assertRaises(ValueError):normalize_odds(price,fmt)


if __name__ == "__main__":
    unittest.main()
