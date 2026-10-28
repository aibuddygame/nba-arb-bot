"""P03 synthetic acceptance checks. Socket creation is blocked in adapter tests."""

from contextlib import redirect_stdout
from copy import deepcopy
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
from nba_arb_bot.recorder.polymarket import PolymarketArchive, decode_fixture, VERSION
from nba_arb_bot.recorder.synthetic import Capture, PayloadError

FIXTURE = Path(__file__).parent / "fixtures/polymarket-synthetic.json"
AT = datetime(2026,10,28,12,tzinfo=timezone.utc)
START = AT+timedelta(hours=12)


class PolymarketTests(unittest.TestCase):
    def setUp(self):
        guard=patch("socket.socket", side_effect=AssertionError("network disabled"))
        guard.start(); self.addCleanup(guard.stop)
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/"synthetic.sqlite"
        self.p=Planner(self.path); self.addCleanup(lambda:self.p.close())
        self.p.reconcile(game_id="g1",season="2026-27",away="LAL",home="BOS",start=START,observed_at=AT-timedelta(hours=1))
        self.slot=self.p.slots("g1")[0]["slot_id"]
        PolymarketArchive.install(self.p);self.a=PolymarketArchive(self.p)
        self.binding=dict(binding_id="b1",game_id="g1",event_id="fictional-lal-bos",
            market_id="synthetic-moneyline-1",condition_id="synthetic-condition-1",
            assets_by_team={"LAL":"synthetic-asset-lal","BOS":"synthetic-asset-bos"},
            rules_ref="synthetic-including-overtime-v1",observed_at=AT-timedelta(hours=1),evidence="synthetic explicit review")
        self.a.bind_market(**self.binding)
        self.body=FIXTURE.read_bytes();self.data=json.loads(self.body)

    def capture(self,name="c1",at=AT):
        return Capture(name,at-timedelta(seconds=2),at-timedelta(seconds=1),at)

    def ingest(self,data=None,**changes):
        args=dict(capture=self.capture(),slots={"b1":self.slot},max_quote_age_seconds=120,max_levels=10)
        args.update(changes)
        return self.a.ingest(self.body if data is None else json.dumps(data).encode(),**args)

    def market(self,data=None):return (data or self.data)["events"][0]["markets"][0]
    def outcome(self,data=None):return self.market(data)["outcomes"][0]
    def count(self,table):return self.p.db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
    def lal(self,rows):return next(r for r in rows if r["team_id"]=="LAL")

    def test_explicit_ids_sorted_books_and_no_display_price_substitution(self):
        rows=self.ingest();q=self.lal(rows)
        self.assertEqual(q["asset_id"],"synthetic-asset-lal")
        self.assertEqual((q["best_bid"],q["best_ask"],q["midpoint"]),("0.55","0.58","0.565"))
        self.assertEqual((q["best_bid_size"],q["best_ask_size"]),("100","100"))
        self.assertEqual(q["last_trade_price"],"0.56")
        self.assertEqual(Decimal(q["quote_age_seconds"]),30)
        self.assertEqual(q["research_eligible"],1);self.assertEqual(q["cost_metadata_complete"],1)
        self.assertEqual(len(self.a.levels("c1")),8)
        self.assertEqual(self.a.raw_response(hashlib.sha256(self.body).hexdigest()),self.body)
        self.assertTrue(all(r["state"]=="planned" for r in self.p.slots("g1")))

    def test_reordering_markets_outcomes_and_levels_does_not_change_identity(self):
        self.market()["outcomes"].reverse()
        for o in self.market()["outcomes"]:o["asks"].reverse();o["bids"].reverse()
        self.data["events"][0]["markets"].reverse()
        q=self.lal(self.ingest(self.data))
        self.assertEqual((q["best_bid"],q["best_ask"],q["asset_id"]),("0.55","0.58","synthetic-asset-lal"))

    def test_missing_ask_never_filled_from_last_trade_or_display(self):
        self.outcome()["asks"]=[]
        q=self.lal(self.ingest(self.data))
        self.assertIsNone(q["best_ask"]);self.assertIsNone(q["midpoint"])
        self.assertEqual(q["last_trade_price"],"0.56")
        self.assertEqual(q["research_eligible"],0);self.assertEqual(q["availability"],"partial")

    def test_empty_book_and_missing_outcome_are_different(self):
        self.outcome()["asks"]=[];self.outcome()["bids"]=[]
        q=self.lal(self.ingest(self.data));self.assertEqual(q["availability"],"empty")
        self.market()["outcomes"].pop(0)
        q=self.lal(self.ingest(self.data,capture=self.capture("missing")))
        self.assertEqual(q["availability"],"outcome_missing")
        self.assertIsNone(q["best_bid"])

    def test_crossed_and_locked_books_are_not_research_eligible(self):
        for i,price in enumerate(["0.55","0.50"]):
            data=deepcopy(self.data);self.outcome(data)["asks"]=[{"price":price,"size":"10"}]
            q=self.lal(self.ingest(data,capture=self.capture(f"cross-{i}")))
            self.assertIn("crossed_or_locked_book",json.loads(q["flags_json"]))
            self.assertIsNone(q["midpoint"]);self.assertEqual(q["research_eligible"],0)

    def test_invalid_or_duplicate_price_levels_reject_whole_side(self):
        values=[{"price":"NaN","size":"1"},{"price":0.5,"size":"1"},
                {"price":"0.5","size":"0"},{"price":"1","size":"1"},
                {"price":"0.55","size":"2"}]
        for i,value in enumerate(values):
            data=deepcopy(self.data);self.outcome(data)["bids"].append(value)
            q=self.lal(self.ingest(data,capture=self.capture(f"bad-{i}")))
            self.assertIsNone(q["best_bid"]);self.assertEqual(q["research_eligible"],0)
            self.assertIn("invalid_bid_levels",json.loads(q["flags_json"]))

    def test_depth_truncation_validates_all_levels_and_disables_cost_metadata(self):
        q=self.lal(self.ingest(max_levels=1))
        self.assertIn("depth_truncated",json.loads(q["flags_json"]))
        self.assertEqual(q["research_eligible"],1);self.assertEqual(q["cost_metadata_complete"],0)
        self.assertEqual(q["depth_complete"],0);self.assertEqual(len(self.a.levels("c1")),4)
        self.outcome()["asks"].append({"price":"bad","size":"1"})
        q=self.lal(self.ingest(self.data,capture=self.capture("bad-depth"),max_levels=1))
        self.assertIsNone(q["best_ask"])

    def test_partial_and_unknown_depth_preserve_price_but_not_cost_readiness(self):
        for i,depth in enumerate([False,None,"true"]):
            data=deepcopy(self.data);self.outcome(data)["depth_complete"]=depth
            q=self.lal(self.ingest(data,capture=self.capture(f"depth-{i}")))
            self.assertEqual(q["best_ask"],"0.58");self.assertEqual(q["cost_metadata_complete"],0)

    def test_unknown_invalid_and_zero_fees_are_distinguished(self):
        for i,fees in enumerate([None,{}, {"model":"unknown"},
            {"model":"synthetic-parabolic-v1","rate":"0","currency":"synthetic-usdc","updated_at":"2026-10-28T11:00:00Z"}]):
            data=deepcopy(self.data);self.market(data)["fees"]=fees
            q=self.lal(self.ingest(data,capture=self.capture(f"fees-{i}")))
            self.assertEqual(q["research_eligible"],1)
            self.assertEqual(q["cost_metadata_complete"],int(i==3))

    def test_rule_mismatch_blocks_research_unknown_rules_are_unassessed(self):
        for i,rule in enumerate(["another-rule",None]):
            data=deepcopy(self.data);self.market(data)["rules_ref"]=rule
            q=self.lal(self.ingest(data,capture=self.capture(f"rule-{i}")))
            self.assertEqual(q["research_eligible"],0 if i==0 else None)
            self.assertEqual(q["cost_metadata_complete"],0)

    def test_stale_future_missing_and_unassessed_quote_times(self):
        cases=[("2026-10-28T11:00:00Z",120,"stale",0),
               ("2026-10-28T12:01:00Z",120,"unexpected_future_timestamp",0),
               (None,120,"source_timestamp_missing_or_invalid",0),
               ("bad",120,"source_timestamp_missing_or_invalid",0),
               ("2026-10-28T11:59:30Z",None,"freshness_unassessed",None)]
        for i,(updated,policy,flag,eligible) in enumerate(cases):
            data=deepcopy(self.data);self.outcome(data)["updated_at"]=updated
            q=self.lal(self.ingest(data,capture=self.capture(f"time-{i}"),max_quote_age_seconds=policy))
            self.assertIn(flag,json.loads(q["flags_json"]));self.assertEqual(q["research_eligible"],eligible)

    def test_lateness_is_unassessed_and_boundary_or_live_is_blocked(self):
        q=self.lal(self.ingest(capture=self.capture("late",AT+timedelta(microseconds=1))))
        self.assertEqual(Decimal(q["lateness_seconds"]),Decimal("0.000001"))
        self.assertIsNone(q["research_eligible"])
        q=self.lal(self.ingest(capture=self.capture("boundary",START)))
        self.assertIn("boundary_or_after_start",json.loads(q["flags_json"]));self.assertEqual(q["research_eligible"],0)
        self.data["events"][0]["status"]="live"
        self.assertEqual(self.lal(self.ingest(self.data,capture=self.capture("live")))["research_eligible"],0)

    def test_invalid_or_future_last_trade_is_not_used_for_book_prices(self):
        for i,last in enumerate([{"price":"bad","at":"bad"},
                                {"price":"0.6","at":"2026-10-28T13:00:00Z"}]):
            data=deepcopy(self.data);self.outcome(data)["last_trade"]=last
            q=self.lal(self.ingest(data,capture=self.capture(f"last-{i}")))
            self.assertEqual(q["best_ask"],"0.58");self.assertEqual(q["midpoint"],"0.565")
            self.assertEqual(q["research_eligible"],1);self.assertEqual(q["cost_metadata_complete"],0)

    def test_suspended_closed_and_resolved_markets_never_eligible(self):
        for i,status in enumerate(["suspended","closed","resolved","unknown"]):
            data=deepcopy(self.data);self.market(data)["status"]=status
            q=self.lal(self.ingest(data,capture=self.capture(f"status-{i}")))
            self.assertEqual(q["research_eligible"],0)

    def test_wrong_team_date_condition_and_market_type_are_quarantined(self):
        changes=[("event","away","LAC"),("event","starts_at","2026-10-30T00:00:00Z"),
                 ("market","condition_id","wrong-condition"),("market","type","spreads")]
        for i,(kind,key,value) in enumerate(changes):
            data=deepcopy(self.data)
            target=data["events"][0] if kind=="event" else self.market(data);target[key]=value
            q=self.lal(self.ingest(data,capture=self.capture(f"identity-{i}")))
            self.assertEqual(q["research_eligible"],0);self.assertIsNone(q["best_ask"])

    def test_reversed_event_orientation_is_safe(self):
        self.data["events"][0]["away"],self.data["events"][0]["home"]="BOS","LAL"
        self.assertEqual(self.lal(self.ingest(self.data))["research_eligible"],1)

    def test_swapped_labels_or_wrong_assets_do_not_reassign_prices(self):
        for i,mode in enumerate(["label","asset"]):
            data=deepcopy(self.data)
            if mode=="label":
                self.market(data)["outcomes"][0]["team"]="BOS"
                self.market(data)["outcomes"][1]["team"]="LAL"
            else:self.outcome(data)["asset_id"]="unbound-asset"
            q=self.lal(self.ingest(data,capture=self.capture(f"swap-{i}")))
            self.assertIn("outcome_mapping_mismatch",json.loads(q["flags_json"]))
            self.assertEqual(q["research_eligible"],0);self.assertIsNone(q["best_bid"])

    def test_source_error_event_missing_market_missing_remain_distinct(self):
        variants=[({"schema":VERSION,"synthetic":True,"kind":"full_snapshot","status":"source_error","error_code":"synthetic_timeout","events":[]},"source_error")]
        data=deepcopy(self.data);data["events"]=[];variants.append((data,"event_missing"))
        data=deepcopy(self.data);data["events"][0]["markets"]=[];variants.append((data,"market_missing"))
        for i,(data,state) in enumerate(variants):
            q=self.lal(self.ingest(data,capture=self.capture(f"missing-{i}")))
            self.assertEqual(q["availability"],state);self.assertEqual(q["research_eligible"],0)

    def test_idempotent_replay_and_restart_with_distinct_new_receipt(self):
        self.ingest();self.p.close();self.p=Planner(self.path);self.a=PolymarketArchive(self.p)
        self.ingest();self.assertEqual(self.count("polymarket_quotes"),2)
        self.ingest(capture=self.capture("c2",AT+timedelta(seconds=1)))
        self.assertEqual(self.count("polymarket_quotes"),4);self.assertEqual(self.count("polymarket_raw_responses"),1)

    def test_capture_identity_conflicts_are_rejected(self):
        self.ingest()
        for changes in [dict(max_levels=1),dict(max_quote_age_seconds=60),dict(capture=self.capture(at=AT+timedelta(seconds=1)))]:
            with self.assertRaises(ValueError):self.ingest(**changes)
        self.outcome()["asks"][0]["size"]="999"
        with self.assertRaises(ValueError):self.ingest(self.data)

    def test_future_missed_superseded_and_wrong_game_slots_rejected(self):
        with self.assertRaises(ValueError):self.ingest(slots={"b1":self.p.slots("g1")[1]["slot_id"]})
        self.p.reconcile(game_id="g2",season="2026-27",away="LAC",home="NYK",start=START,observed_at=AT-timedelta(hours=1))
        with self.assertRaises(ValueError):self.ingest(slots={"b1":self.p.slots("g2")[0]["slot_id"]})
        self.p.reconcile(game_id="g1",season="2026-27",away="LAL",home="BOS",start=START,observed_at=AT+timedelta(seconds=1))
        with self.assertRaises(ValueError):self.ingest(capture=self.capture(at=AT+timedelta(seconds=2)))
        self.assertEqual(self.count("polymarket_captures"),0)

    def test_explicit_binding_idempotent_and_conflicts_never_overwrite(self):
        self.a.bind_market(**self.binding)
        for changes in [dict(condition_id="another"),dict(assets_by_team={"LAL":"new","BOS":"synthetic-asset-bos"}),
                        dict(assets_by_team={"LAL":"same","BOS":"same"}),dict(evidence="")]:
            with self.assertRaises(ValueError):self.a.bind_market(**{**self.binding,**changes})
        self.assertEqual(self.count("polymarket_bindings"),1)

    def test_market_and_asset_reuse_cannot_bind_another_game(self):
        self.p.reconcile(game_id="g2",season="2026-27",away="LAL",home="BOS",start=START,observed_at=AT-timedelta(hours=1))
        with self.assertRaises(ValueError):self.a.bind_market(**{**self.binding,"binding_id":"b2","game_id":"g2"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.a.bind_market(**{**self.binding,"binding_id":"b2","event_id":"another-event","market_id":"another-market","condition_id":"another-condition"})
        self.assertEqual(self.count("source_event_mappings"),1)

    def test_ingestion_failure_rolls_back_all_evidence_and_recovers(self):
        self.p.db.execute("""CREATE TRIGGER synthetic_failure BEFORE INSERT ON polymarket_levels
                            BEGIN SELECT RAISE(ABORT,'synthetic failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.ingest()
        for table in ["polymarket_raw_responses","polymarket_captures","polymarket_markets","polymarket_quotes","polymarket_levels"]:
            self.assertEqual(self.count(table),0)
        self.p.db.execute("DROP TRIGGER synthetic_failure");self.ingest()
        self.assertEqual(self.count("polymarket_quotes"),2)

    def test_normal_sql_cannot_edit_or_delete_evidence_or_bindings(self):
        self.ingest()
        for table in ["polymarket_bindings","polymarket_bound_outcomes","polymarket_raw_responses", "polymarket_captures","polymarket_markets","polymarket_quotes","polymarket_levels"]:
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):self.p.db.execute("DELETE FROM "+table)
        with self.assertRaises(sqlite3.IntegrityError):self.p.db.execute("UPDATE polymarket_quotes SET best_ask='0.1'")

    def test_raw_corruption_detected(self):
        self.ingest();self.p.db.execute("DROP TRIGGER polymarket_raw_responses_no_update")
        self.p.db.execute("UPDATE polymarket_raw_responses SET body_gzip=?",(gzip.compress(b'corrupt'),))
        with self.assertRaises(ValueError):self.a.raw_response(hashlib.sha256(self.body).hexdigest())

    def test_extension_is_explicit_independent_of_p02_and_idempotent(self):
        with Planner(":memory:") as p:
            with self.assertRaises(ValueError):PolymarketArchive(p)
            PolymarketArchive.install(p);PolymarketArchive.install(p)
            self.assertEqual(p.db.execute("PRAGMA user_version").fetchone()[0],1)
            self.assertIsNone(p.db.execute("SELECT name FROM sqlite_master WHERE name='bookmaker_component'").fetchone())

    def test_failed_extension_install_rolls_back_and_unknown_version_rejected(self):
        with Planner(":memory:") as p:
            p.db.execute("CREATE TABLE polymarket_quotes(existing)")
            with self.assertRaises(sqlite3.OperationalError):PolymarketArchive.install(p)
            self.assertIsNone(p.db.execute("SELECT name FROM sqlite_master WHERE name='polymarket_component'").fetchone())
        self.p.db.execute("DROP TABLE polymarket_component");self.p.db.execute("CREATE TABLE polymarket_component(version)")
        self.p.db.execute("INSERT INTO polymarket_component VALUES(2)")
        with self.assertRaises(ValueError):PolymarketArchive(self.p)

    def test_p02_and_p03_coexist_without_touching_each_others_rows(self):
        from nba_arb_bot.recorder.bookmaker import BookmakerArchive
        BookmakerArchive.install(self.p);self.ingest()
        self.assertEqual(self.count("bookmaker_captures"),0)
        self.assertEqual(self.count("polymarket_captures"),1)

    def test_credential_payload_rejected_before_persistence(self):
        self.data["api_key"]="synthetic-sensitive-marker"
        with self.assertRaises(PayloadError) as error:self.ingest(self.data)
        self.assertNotIn("synthetic-sensitive-marker",str(error.exception))
        self.assertEqual(self.count("polymarket_raw_responses"),0)

    def test_demo_has_no_network_and_reports_real_book_fields(self):
        from nba_arb_bot.recorder.polymarket_demo import main
        output=io.StringIO()
        args=["polymarket_demo","--fixture",str(FIXTURE),"--received-at",AT.isoformat(),"--max-quote-age-seconds","120"]
        with patch("sys.argv",args),redirect_stdout(output):main()
        data=json.loads(output.getvalue());self.assertTrue(data["synthetic"])
        self.assertEqual((data["quote_count"],data["level_count"]),(2,8))

    def test_multiple_games_share_one_raw_body_but_only_selected_bindings_are_ingested(self):
        self.p.reconcile(game_id="g2",season="2026-27",away="LAC",home="NYK",start=START,observed_at=AT-timedelta(hours=1))
        self.a.bind_market(**{**self.binding,"binding_id":"b2","game_id":"g2","event_id":"fictional-lac-nyk",
            "market_id":"moneyline-2","condition_id":"condition-2",
            "assets_by_team":{"LAC":"asset-lac","NYK":"asset-nyk"}})
        second=deepcopy(self.data["events"][0])
        second.update(event_id="fictional-lac-nyk",away="LAC",home="NYK")
        second["markets"]=second["markets"][:1]
        second["markets"][0].update(market_id="moneyline-2",condition_id="condition-2")
        second["markets"][0]["outcomes"][0].update(team="LAC",asset_id="asset-lac")
        second["markets"][0]["outcomes"][1].update(team="NYK",asset_id="asset-nyk")
        self.data["events"].append(second)
        rows=self.ingest(self.data)
        self.assertEqual(len(rows),2)
        rows=self.ingest(self.data,capture=self.capture("batch"),slots={"b1":self.slot,"b2":self.p.slots("g2")[0]["slot_id"]})
        self.assertEqual(len(rows),4)
        self.assertEqual(self.count("polymarket_raw_responses"),1)
        self.assertEqual(self.count("polymarket_captures"),2)

    def test_invalid_binding_slot_depth_and_policy_arguments_fail_before_raw_persistence(self):
        for changes in [dict(slots={"unknown":self.slot}),dict(max_levels=0),dict(max_levels=True),
                        dict(max_quote_age_seconds=-1),dict(slots={"b1":True})]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.ingest(**changes)
        self.assertEqual(self.count("polymarket_raw_responses"),0)

    def test_invalid_future_fee_metadata_never_reports_cost_metadata_complete(self):
        for i,changes in enumerate([dict(rate="-0.1"),dict(rate="NaN"),dict(currency="unknown"),
                                    dict(updated_at="2026-10-28T13:00:00Z")]):
            data=deepcopy(self.data);self.market(data)["fees"].update(changes)
            q=self.lal(self.ingest(data,capture=self.capture(f"badfee-{i}")))
            self.assertEqual(q["cost_metadata_complete"],0)
            self.assertIn("fees_unknown_or_invalid",json.loads(q["flags_json"]))


class EnvelopeTests(unittest.TestCase):
    def test_malformed_non_synthetic_nonfinite_and_delta_inputs_rejected(self):
        for body in [b'bad json',b'[]',b'{"x":1,"x":2}',b'{"x":NaN}',b'\xff']:
            with self.assertRaises(PayloadError):decode_fixture(body)
        for changes in [dict(synthetic=False),dict(kind="delta"),dict(schema="live-api")]:
            data=json.loads(FIXTURE.read_bytes());data.update(changes)
            with self.assertRaises(PayloadError):decode_fixture(json.dumps(data).encode())

    def test_duplicate_market_condition_asset_and_event_ids_rejected(self):
        variants=[];base=json.loads(FIXTURE.read_bytes())
        data=deepcopy(base);data["events"]*=2;variants.append(data)
        data=deepcopy(base);data["events"][0]["markets"].append(deepcopy(data["events"][0]["markets"][0]));variants.append(data)
        data=deepcopy(base);data["events"][0]["markets"][1]["condition_id"]="synthetic-condition-1";variants.append(data)
        data=deepcopy(base);data["events"][0]["markets"][0]["outcomes"][1]["asset_id"]="synthetic-asset-lal";variants.append(data)
        for data in variants:
            with self.assertRaises(PayloadError):decode_fixture(json.dumps(data).encode())


if __name__ == "__main__":unittest.main()
