"""P01 acceptance tests: synthetic fixtures, temporary SQLite, no provider calls."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from nba_arb_bot.recorder import Planner, TEAMS, planned_times, team_id

UTC = timezone.utc
START = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
EARLY = START - timedelta(hours=13)


class IdentityTests(unittest.TestCase):
    def test_all_thirty_teams_and_exact_aliases(self):
        self.assertEqual(len(TEAMS), 30)
        self.assertEqual(len({t.team_id for t in TEAMS}), 30)
        for team in TEAMS:
            self.assertEqual(team_id(team.name), team.team_id)
        self.assertEqual(team_id("  l.a.   lakers  "), "LAL")
        self.assertEqual(team_id("LA Clippers"), "LAC")
        for name in ["Los Angeles", "L.A.", "Los", "New", "Boston", "Lakers", "UNKNOWN"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                team_id(name)


class TimeTests(unittest.TestCase):
    def test_twenty_five_slots_cross_midnight_and_timezones(self):
        for zone in [UTC, ZoneInfo("America/New_York"), ZoneInfo("Asia/Singapore")]:
            slots = planned_times(START.astimezone(zone))
            self.assertEqual(len(slots), 25)
            self.assertEqual(slots[0], START - timedelta(hours=12))
            self.assertEqual(slots[-1], START)
            self.assertEqual(len(set(slots)), 25)
            self.assertTrue(all(b-a == timedelta(minutes=30) for a,b in zip(slots,slots[1:])))

    def test_elapsed_time_across_both_dst_transitions(self):
        ny = ZoneInfo("America/New_York")
        for start in [datetime(2026,3,8,9,tzinfo=ny), datetime(2026,11,1,9,tzinfo=ny)]:
            slots = planned_times(start)
            self.assertEqual((slots[-1]-slots[0]).total_seconds(), 43200)
            self.assertEqual(len(set(slots)), 25)
            self.assertNotEqual(slots[0].astimezone(ny).utcoffset(), slots[-1].astimezone(ny).utcoffset())

    def test_naive_and_nonexistent_local_times_rejected(self):
        for start in [datetime(2026,10,29), datetime(2026,3,8,2,30,tzinfo=ZoneInfo("America/New_York"))]:
            with self.assertRaises(ValueError):
                planned_times(start)

    def test_fall_back_fold_selects_an_explicit_instant(self):
        ny = ZoneInfo("America/New_York")
        a = planned_times(datetime(2026,11,1,1,30,tzinfo=ny,fold=0))[-1]
        b = planned_times(datetime(2026,11,1,1,30,tzinfo=ny,fold=1))[-1]
        self.assertEqual(b-a, timedelta(hours=1))


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"synthetic.sqlite"
        self.p = Planner(self.path)

    def tearDown(self):
        self.p.close()
        self.tmp.cleanup()

    def fixture(self, **changes):
        args = dict(game_id="game-1", season="2026-27", away="LAL", home="BOS",
                    start=START, observed_at=EARLY)
        args.update(changes)
        return self.p.reconcile(**args)

    def count(self, table):
        return self.p.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_first_plan_and_duplicate_delivery_are_idempotent(self):
        revision = self.fixture()
        before = (self.count("slot_events"), self.count("game_events"))
        self.assertEqual(self.fixture(), revision)
        self.assertEqual(self.count("snapshot_slots"),25)
        self.assertEqual(before,(self.count("slot_events"),self.count("game_events")))

    def test_restart_preserves_slots_ids_and_audit(self):
        self.fixture()
        rows = [tuple(r) for r in self.p.slots("game-1")]
        self.p.close()
        self.p = Planner(self.path)
        self.fixture()
        self.assertEqual(rows,[tuple(r) for r in self.p.slots("game-1")])
        self.assertEqual(self.count("slot_events"),25)

    def test_second_connection_does_not_duplicate_a_plan(self):
        self.fixture()
        with Planner(self.path) as other:
            other.reconcile(game_id="game-1",season="2026-27",away="LAL",home="BOS",
                            start=START,observed_at=EARLY)
        self.assertEqual(self.count("snapshot_slots"),25)

    def test_discovery_inside_window_records_missed_not_backfilled(self):
        self.fixture(observed_at=START-timedelta(hours=6))
        rows = self.p.slots("game-1")
        self.assertEqual(sum(r["state"]=="missed" for r in rows),12)
        self.assertEqual(sum(r["state"]=="planned" for r in rows),13)
        self.assertEqual(rows[12]["planned_at"],(START-timedelta(hours=6)).isoformat(timespec="microseconds"))

    def test_expired_slots_remain_visible_after_gap(self):
        self.fixture()
        self.fixture(observed_at=START-timedelta(hours=11,minutes=45))
        self.assertEqual(self.p.slots("game-1")[0]["state"],"missed")
        self.assertEqual(self.count("snapshot_slots"),25)
        self.assertEqual(self.count("slot_events"),26)

    def test_reschedule_retains_completed_and_missed_history(self):
        old = self.fixture()
        first = self.p.slots("game-1")[0]
        self.p.record_slot_result(first["slot_id"],state="complete",observed_at=START-timedelta(hours=12))
        revised = self.fixture(start=START+timedelta(days=1),observed_at=START-timedelta(hours=10))
        self.assertNotEqual(old,revised)
        old_rows=self.p.slots("game-1",revision_id=old)
        self.assertEqual(old_rows[0]["state"],"complete")
        self.assertEqual(old_rows[1]["state"],"missed")
        self.assertEqual(old_rows[-1]["state"],"superseded")
        self.assertEqual(self.count("snapshot_slots"),50)
        self.assertEqual(len(self.p.slots("game-1",revision_id=revised)),25)

    def test_schedule_returning_to_prior_time_gets_new_revision(self):
        self.fixture()
        self.fixture(start=START+timedelta(days=1),observed_at=EARLY+timedelta(minutes=1))
        self.fixture(observed_at=EARLY+timedelta(minutes=2))
        self.assertEqual(self.count("schedule_revisions"),3)
        self.assertEqual(self.count("snapshot_slots"),75)

    def test_postponement_without_new_time_then_resume(self):
        old=self.fixture()
        self.fixture(status="postponed",observed_at=EARLY+timedelta(minutes=1))
        self.assertTrue(all(r["state"]=="cancelled_event" for r in self.p.slots("game-1")))
        new=self.fixture(observed_at=EARLY+timedelta(minutes=2))
        self.assertNotEqual(old,new)
        self.assertTrue(all(r["state"]=="planned" for r in self.p.slots("game-1",revision_id=new)))

    def test_early_start_cancels_outstanding_future_slots(self):
        self.fixture()
        self.fixture(status="live",observed_at=START-timedelta(minutes=15))
        rows=self.p.slots("game-1")
        self.assertEqual(rows[-1]["state"],"cancelled_after_start")
        self.assertEqual(sum(r["state"]=="missed" for r in rows),24)
        self.assertNotIn("planned",[r["state"] for r in rows])

    def test_cancellation_retains_all_slots_and_cannot_reopen(self):
        self.fixture()
        self.fixture(status="cancelled",observed_at=EARLY+timedelta(minutes=1))
        self.assertEqual(self.count("snapshot_slots"),25)
        self.assertTrue(all(r["state"]=="cancelled_event" for r in self.p.slots("game-1")))
        with self.assertRaises(ValueError):self.fixture(observed_at=EARLY+timedelta(minutes=2))

    def test_delayed_game_does_not_extend_twenty_five_slots(self):
        self.fixture()
        self.fixture(status="delayed",observed_at=START+timedelta(hours=1))
        self.assertEqual(self.count("snapshot_slots"),25)
        self.assertEqual(self.count("schedule_revisions"),1)
        self.assertTrue(all(r["state"]=="missed" for r in self.p.slots("game-1")))

    def test_t0_is_planned_but_does_not_prove_pregame_eligibility(self):
        self.fixture(observed_at=START)
        rows=self.p.slots("game-1")
        self.assertEqual(rows[-1]["state"],"planned")
        self.assertEqual(sum(r["state"]=="missed" for r in rows),24)

    def test_wrong_identity_stale_and_conflicting_updates_rollback(self):
        self.fixture()
        for changes in [dict(away="LAC"),dict(home="LAL"),
                        dict(observed_at=EARLY-timedelta(seconds=1)),
                        dict(start=START+timedelta(hours=1)),dict(status="bogus")]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.fixture(**changes)
        self.assertEqual(self.count("snapshot_slots"),25)
        self.assertEqual(self.count("game_events"),1)

    def test_started_game_cannot_reopen_and_final_is_terminal(self):
        self.fixture(status="live")
        with self.assertRaises(ValueError):self.fixture(observed_at=EARLY+timedelta(seconds=1))
        self.fixture(status="final",observed_at=EARLY+timedelta(seconds=2))
        with self.assertRaises(ValueError):self.fixture(status="live",observed_at=EARLY+timedelta(seconds=3))

    def test_exact_matching_allows_reversed_orientation_not_wrong_team_or_date(self):
        self.fixture()
        self.assertEqual(self.p.match_game(away="BOS",home="LAL",start=START),"game-1")
        for away,tip in [("LAC",START),("LAL",START+timedelta(days=1))]:
            with self.assertRaises(ValueError):self.p.match_game(away=away,home="BOS",start=tip)

    def test_ambiguous_fixture_match_fails_closed(self):
        self.fixture()
        self.fixture(game_id="game-2")
        with self.assertRaises(ValueError):self.p.match_game(away="LAL",home="BOS",start=START)

    def test_source_mapping_unique_stable_and_foreign_key_checked(self):
        self.fixture()
        args=dict(source="synthetic",source_event_id="event-1",game_id="game-1",
                  observed_at=EARLY,evidence="synthetic schedule and exact teams")
        self.p.bind_source_event(**args)
        self.p.bind_source_event(**args)
        self.assertEqual(self.count("source_event_mappings"),1)
        self.fixture(game_id="game-2")
        with self.assertRaises(ValueError):self.p.bind_source_event(**{**args,"game_id":"game-2"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.p.bind_source_event(**{**args,"source_event_id":"new","game_id":"absent"})
        self.assertEqual(self.count("source_event_mappings"),1)

    def test_result_deduplicated_and_terminal_result_cannot_be_rewritten(self):
        self.fixture()
        slot=self.p.slots("game-1")[0]
        at=START-timedelta(hours=12)
        with self.assertRaises(ValueError):self.p.record_slot_result(slot["slot_id"],state="complete",observed_at=EARLY)
        self.p.record_slot_result(slot["slot_id"],state="partial",observed_at=at)
        self.p.record_slot_result(slot["slot_id"],state="partial",observed_at=at)
        self.assertEqual(self.count("slot_events"),26)
        with self.assertRaises(ValueError):self.p.record_slot_result(slot["slot_id"],state="complete",observed_at=at)

    def test_missed_slot_cannot_be_filled_retrospectively(self):
        self.fixture(observed_at=START-timedelta(hours=6))
        slot=self.p.slots("game-1")[0]
        with self.assertRaises(ValueError):
            self.p.record_slot_result(slot["slot_id"],state="complete",observed_at=START)

    def test_audits_and_schedule_identity_are_immutable(self):
        self.fixture()
        for sql in ["DELETE FROM slot_events","DELETE FROM game_events",
                    "UPDATE schedule_revisions SET revision_number=2",
                    "DELETE FROM snapshot_slots",
                    "UPDATE snapshot_slots SET slot_index=2",
                    "UPDATE games SET away_team_id='LAC'"]:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError):self.p.db.execute(sql)
        self.assertEqual(self.count("snapshot_slots"),25)

    def test_unknown_schema_and_nonempty_unrelated_database_rejected(self):
        for version in [0,1,2]:
            path=Path(self.tmp.name)/f"unrelated-{version}.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE unrelated(value)")
                connection.execute(f"PRAGMA user_version={version}")
            with self.subTest(version=version),self.assertRaises(ValueError):Planner(path)

    def test_failure_mid_revision_rolls_back_every_projection_and_audit(self):
        self.fixture()
        before_slots=[tuple(r) for r in self.p.slots("game-1")]
        before_events=self.count("slot_events")
        self.p.db.execute("""CREATE TRIGGER synthetic_failure BEFORE INSERT ON snapshot_slots
                            WHEN NEW.slot_index=12
                            BEGIN SELECT RAISE(ABORT, 'synthetic crash'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.fixture(start=START+timedelta(days=1),observed_at=EARLY+timedelta(minutes=1))
        self.assertEqual(self.count("schedule_revisions"),1)
        self.assertEqual(self.count("slot_events"),before_events)
        self.assertEqual([tuple(r) for r in self.p.slots("game-1")],before_slots)
        self.p.db.execute("DROP TRIGGER synthetic_failure")
        self.fixture(start=START+timedelta(days=1),observed_at=EARLY+timedelta(minutes=1))
        self.assertEqual(self.count("schedule_revisions"),2)

    def test_invalid_mapping_input_and_unknown_slot_fail_closed(self):
        self.fixture()
        with self.assertRaises(ValueError):
            self.p.bind_source_event(source="",source_event_id="x",game_id="game-1",
                                     observed_at=EARLY,evidence="test")
        with self.assertRaises(ValueError):
            self.p.record_slot_result(99999,state="complete",observed_at=START)

    def test_naive_observation_rejected_before_writes(self):
        with self.assertRaises(ValueError):self.fixture(observed_at=EARLY.replace(tzinfo=None))
        self.assertEqual(self.count("games"),0)


if __name__ == "__main__":
    unittest.main()
