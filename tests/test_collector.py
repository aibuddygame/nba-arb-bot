"""P04 acceptance: persistent paired scheduling with socket creation blocked."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nba_arb_bot.recorder import Planner
from nba_arb_bot.recorder.collector import (
    PairedCollector, CollectionPolicy, Claim, LeaseLost, SyntheticSource, SyntheticFailure,
)
from nba_arb_bot.recorder.polymarket import PolymarketArchive
from nba_arb_bot.recorder.synthetic import Capture

AT=datetime(2026,10,28,12,tzinfo=timezone.utc)
START=AT+timedelta(hours=12)
FIXTURES=Path(__file__).parent/'fixtures'


class Clock:
    def __init__(self,at=AT):self.at=at
    def __call__(self):return self.at
    def advance(self,seconds):self.at+=timedelta(seconds=seconds)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        guard=patch('socket.socket',side_effect=AssertionError('network disabled'))
        guard.start();self.addCleanup(guard.stop)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'synthetic.sqlite'
        self.p=Planner(self.path);self.addCleanup(lambda:self.p.close())
        self.p.reconcile(game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,observed_at=AT)
        PairedCollector.install(self.p);self.c=PairedCollector(self.p)
        self.c.polymarket.bind_market(binding_id='b1',game_id='g1',event_id='fictional-lal-bos',
            market_id='synthetic-moneyline-1',condition_id='synthetic-condition-1',
            assets_by_team={'LAL':'synthetic-asset-lal','BOS':'synthetic-asset-bos'},
            rules_ref='synthetic-including-overtime-v1',observed_at=AT,evidence='synthetic explicit mapping')
        self.policy=CollectionPolicy('test-policy',60,5,120,30,10,2,2,8,2)
        self.clock=Clock();self.slot=self.p.slots('g1')[0]['slot_id']
        self.book_data=json.loads((FIXTURES/'bookmaker-synthetic.json').read_bytes())
        self.book_data['events'][0]['bookmakers']=self.book_data['events'][0]['bookmakers'][:1]
        self.book_body=json.dumps(self.book_data).encode()
        self.poly_data=json.loads((FIXTURES/'polymarket-synthetic.json').read_bytes())
        self.poly_body=json.dumps(self.poly_data).encode()
        self.register()

    def register(self,**changes):
        args=dict(game_id='g1',bookmaker_event_id='fictional-lal-bos',binding_id='b1',
                  expected_books=('synthetic-a',),policy=self.policy,observed_at=self.clock())
        args.update(changes);self.c.register(**args)

    def sources(self,book=None,poly=None):
        return {'bookmaker':SyntheticSource([self.book_body] if book is None else book),
                'polymarket':SyntheticSource([self.poly_body] if poly is None else poly)}

    def step(self,sources,worker='worker-1'):
        return self.c.run_once(worker_id=worker,clock=self.clock,sources=sources)

    def finish(self,claim,body=None,error=None,at=None):
        at=at or self.clock()
        return self.c.finish(claim,capture=Capture(claim.capture_id,at,at,at),finished_at=at,
                             body=body,error_code=error)

    def count(self,table):return self.p.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def state(self):return self.p.slots('g1')[0]['state']
    def jobs(self):return self.p.db.execute('SELECT * FROM collector_jobs WHERE slot_id=? ORDER BY job_id',(self.slot,)).fetchall()

    def test_registers_twenty_five_slots_and_two_jobs_each_idempotently(self):
        self.register()
        self.assertEqual(self.count('collector_slots'),25)
        self.assertEqual(self.count('collector_jobs'),50)
        self.assertEqual(self.count('collector_job_events'),50)

    def test_two_sources_produce_traceable_pairs_and_atomic_completion(self):
        sources=self.sources();self.assertEqual(self.step(sources),'succeeded')
        self.assertEqual(self.state(),'planned');self.assertEqual(len(self.c.pairs(self.slot)),0)
        self.assertEqual(self.step(sources),'succeeded')
        pairs=self.c.pairs(self.slot)
        self.assertEqual(self.state(),'complete');self.assertEqual(len(pairs),2)
        self.assertTrue(all(r['research_eligible']==1 and r['cost_metadata_complete']==1 for r in pairs))
        self.assertTrue(all(r['bookmaker_capture_id'] and r['polymarket_capture_id'] for r in pairs))
        self.assertIsNone(self.step(sources))
        self.assertEqual((sources['bookmaker'].calls,sources['polymarket'].calls),(1,1))
        self.assertEqual([r['units'] for r in self.c.usage()],[1,1])

    def test_restart_after_first_source_does_not_refetch_successful_side(self):
        sources=self.sources();self.step(sources)
        self.p.close();self.p=Planner(self.path);self.c=PairedCollector(self.p)
        self.step(sources)
        self.assertEqual(self.state(),'complete')
        self.assertEqual((sources['bookmaker'].calls,sources['polymarket'].calls),(1,1))

    def test_not_due_slots_do_not_consume_requests_or_quota(self):
        self.clock.at=AT-timedelta(seconds=1);sources=self.sources()
        self.assertIsNone(self.step(sources));self.assertEqual(self.count('collector_attempts'),0)
        self.assertEqual(self.count('collector_quota'),0)

    def test_two_connections_cannot_claim_the_same_source_job(self):
        first=self.c.claim(worker_id='one',now=AT,source='bookmaker')
        with Planner(self.path) as p:
            other=PairedCollector(p)
            self.assertIsNone(other.claim(worker_id='two',now=AT,source='bookmaker'))
            second=other.claim(worker_id='two',now=AT,source='polymarket')
            self.assertNotEqual(first.attempt_id,second.attempt_id)

    def test_expired_worker_is_fenced_then_retry_has_new_attempt(self):
        old=self.c.claim(worker_id='old',now=AT,source='bookmaker')
        self.clock.advance(10)
        self.assertIsNone(self.c.claim(worker_id='new',now=self.clock(),source='bookmaker'))
        with self.assertRaises(LeaseLost):self.finish(old,self.book_body)
        self.clock.advance(2)
        new=self.c.claim(worker_id='new',now=self.clock(),source='bookmaker')
        self.assertNotEqual(old.attempt_id,new.attempt_id)
        self.assertEqual(self.count('collector_quota'),2)
        self.assertEqual(self.finish(new,self.book_body),'succeeded')

    def test_late_finish_rejected_even_before_recovery_tick(self):
        claim=self.c.claim(worker_id='w',now=AT)
        self.clock.advance(10)
        with self.assertRaises(LeaseLost):self.finish(claim,self.book_body)
        self.assertEqual(self.count('bookmaker_captures'),0)

    def test_same_finish_replayed_is_idempotent_and_changed_body_rejected(self):
        claim=self.c.claim(worker_id='w',now=AT)
        self.finish(claim,self.book_body);self.finish(claim,self.book_body)
        self.assertEqual(self.count('bookmaker_captures'),1);self.assertEqual(self.count('collector_attempt_results'),1)
        with self.assertRaises(LeaseLost):self.finish(claim,self.book_body+b' ')

    def test_claim_worker_capture_and_chronology_are_checked(self):
        claim=self.c.claim(worker_id='w',now=AT)
        with self.assertRaises(LeaseLost):self.finish(replace(claim,worker_id='other'),self.book_body)
        with self.assertRaises(ValueError):
            self.c.finish(claim,capture=Capture('wrong',AT,AT,AT),finished_at=AT,body=self.book_body)
        with self.assertRaises(ValueError):self.finish(claim,self.book_body,at=AT-timedelta(seconds=1))
        self.assertEqual(self.count('bookmaker_captures'),0)

    def test_bounded_retry_after_transport_failure_with_no_sleep(self):
        sources=self.sources(book=[SyntheticFailure('synthetic_timeout'),self.book_body])
        self.assertEqual(self.step(sources),'transport_error')
        self.assertEqual(self.step(sources),'succeeded') # independent other source
        self.assertIsNone(self.step(sources));self.clock.advance(2)
        self.assertEqual(self.step(sources),'succeeded');self.assertEqual(self.state(),'complete')
        self.assertEqual(self.count('collector_attempts'),3)

    def test_source_error_payload_retained_and_retried_not_empty_success(self):
        data={'schema':'synthetic-bookmaker-v1','synthetic':True,'status':'source_error','error_code':'synthetic_timeout','events':[]}
        sources=self.sources(book=[json.dumps(data).encode(),self.book_body])
        self.assertEqual(self.step(sources),'source_error')
        self.assertEqual(self.count('bookmaker_captures'),1)
        self.step(sources);self.clock.advance(2);self.step(sources)
        self.assertEqual(self.state(),'complete');self.assertEqual(self.count('bookmaker_captures'),2)

    def test_parse_and_credential_failures_record_safe_errors_without_raw_bodies(self):
        data=deepcopy(self.book_data);data['api_key']='synthetic-sensitive-marker'
        sources=self.sources(book=[json.dumps(data).encode(),b'invalid json'])
        self.assertEqual(self.step(sources),'parse_error');self.step(sources)
        self.clock.advance(2);self.assertEqual(self.step(sources),'parse_error')
        self.assertEqual(self.state(),'partial');self.assertEqual(self.count('bookmaker_raw_responses'),0)
        rows=self.p.db.execute('SELECT error_code FROM collector_attempt_results').fetchall()
        self.assertNotIn('synthetic-sensitive-marker',str([tuple(r) for r in rows]))

    def test_attempt_limit_preserves_partial_slot_and_missing_pair_rows(self):
        sources=self.sources(book=[SyntheticFailure(),SyntheticFailure()])
        self.step(sources);self.step(sources);self.clock.advance(2);self.step(sources)
        self.assertEqual(self.state(),'partial')
        self.assertTrue(all(r['research_eligible']==0 for r in self.c.pairs(self.slot)))
        self.assertEqual(sources['bookmaker'].calls,2)

    def test_both_failed_sources_mark_missed_without_zero_quotes(self):
        sources=self.sources(book=[SyntheticFailure(),SyntheticFailure()],poly=[SyntheticFailure(),SyntheticFailure()])
        self.step(sources);self.step(sources);self.clock.advance(2);self.step(sources);self.step(sources)
        self.assertEqual(self.state(),'missed')
        self.assertTrue(all(r['bookmaker_capture_id'] is None and r['polymarket_capture_id'] is None for r in self.c.pairs(self.slot)))

    def test_window_expiry_marks_missed_without_backfill_calls(self):
        self.clock.advance(61);sources=self.sources()
        self.assertIsNone(self.step(sources));self.assertEqual(self.state(),'missed')
        self.assertEqual(self.count('collector_quota'),0)
        self.assertEqual(sources['bookmaker'].calls,0)

    def test_no_cross_slot_forward_fill(self):
        sources=self.sources();self.step(sources);self.step(sources)
        self.clock.advance(1800)
        self.p.reconcile(game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,observed_at=self.clock())
        failures=self.sources(book=[SyntheticFailure(),SyntheticFailure()],poly=[SyntheticFailure(),SyntheticFailure()])
        self.step(failures);self.step(failures);self.clock.advance(2);self.step(failures);self.step(failures)
        second=self.p.slots('g1')[1]
        self.assertEqual(second['state'],'missed')
        self.assertTrue(all(r['bookmaker_capture_id'] is None for r in self.c.pairs(second['slot_id'])))

    def test_receipt_gap_exceeded_keeps_pair_ineligible(self):
        sources=self.sources();self.step(sources);self.clock.advance(6);self.step(sources)
        pairs=self.c.pairs(self.slot);self.assertEqual(self.state(),'partial')
        self.assertTrue(all('receipt_gap_exceeded' in json.loads(r['flags_json']) for r in pairs))
        self.assertEqual(Decimal(pairs[0]['receipt_gap_seconds']),6)

    def test_partial_book_coverage_is_not_complete(self):
        data=json.loads((FIXTURES/'bookmaker-synthetic.json').read_bytes())
        sources=self.sources(book=[json.dumps(data).encode()]);self.step(sources);self.step(sources)
        self.assertEqual(self.state(),'partial');self.assertEqual(len(self.c.pairs(self.slot)),6)
        self.assertEqual(sum(r['research_eligible'] for r in self.c.pairs(self.slot)),2)

    def test_unknown_fees_allow_research_but_not_cost_metadata(self):
        self.poly_data['events'][0]['markets'][0]['fees']=None
        sources=self.sources(poly=[json.dumps(self.poly_data).encode()]);self.step(sources);self.step(sources)
        self.assertEqual(self.state(),'complete')
        self.assertTrue(all(r['research_eligible']==1 and r['cost_metadata_complete']==0 for r in self.c.pairs(self.slot)))

    def test_settlement_rules_must_match_between_sources(self):
        self.book_data['events'][0]['bookmakers'][0]['markets'][0]['rules_ref']='other-rule'
        sources=self.sources(book=[json.dumps(self.book_data).encode()]);self.step(sources);self.step(sources)
        self.assertEqual(self.state(),'partial')
        self.assertTrue(all('settlement_rules_not_matched' in json.loads(r['flags_json']) for r in self.c.pairs(self.slot)))

    def test_stale_quote_not_paired_as_eligible(self):
        self.book_data['events'][0]['bookmakers'][0]['markets'][0]['updated_at']='2026-10-28T10:00:00Z'
        sources=self.sources(book=[json.dumps(self.book_data).encode()]);self.step(sources);self.step(sources)
        self.assertEqual(self.state(),'partial');self.assertTrue(all(not r['research_eligible'] for r in self.c.pairs(self.slot)))

    def test_game_state_freshness_required_before_calls(self):
        self.clock.advance(31);sources=self.sources()
        self.assertIsNone(self.step(sources));self.assertEqual(self.count('collector_attempts'),0)
        self.assertEqual(self.state(),'planned')
        self.c.reconcile_fixture(policy=self.policy,game_id='g1',season='2026-27',away='LAL',home='BOS',
                                 start=START,observed_at=self.clock())
        self.assertEqual(self.state(),'planned')
        self.clock.advance(2);self.assertEqual(self.step(sources),'succeeded')

    def test_live_status_during_request_fences_observation_and_records_actual_times(self):
        claim=self.c.claim(worker_id='w',now=AT)
        self.p.reconcile(game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,observed_at=AT+timedelta(seconds=1),status='live')
        self.clock.advance(1)
        self.assertEqual(self.finish(claim,self.book_body),'slot_invalidated')
        self.assertEqual(self.count('bookmaker_captures'),0)
        row=self.p.db.execute('SELECT * FROM collector_attempt_results').fetchone()
        self.assertIsNotNone(row['received_at']);self.assertIsNotNone(row['body_sha256'])

    def test_superseded_and_cancelled_slots_never_dispatch(self):
        self.p.reconcile(game_id='g1',season='2026-27',away='LAL',home='BOS',start=START+timedelta(days=1),observed_at=AT+timedelta(seconds=1))
        self.clock.advance(1);sources=self.sources();self.assertIsNone(self.step(sources))
        self.assertEqual(self.count('collector_attempts'),0)

    def test_t0_is_not_automatically_treated_as_pregame(self):
        self.clock.at=START;sources=self.sources();self.assertIsNone(self.step(sources))
        self.assertEqual(self.count('collector_attempts'),0)
        self.assertEqual(self.p.slots('g1')[-1]['state'],'missed')

    def test_synthetic_quota_is_persistent_and_reserved_before_io(self):
        claim=self.c.claim(worker_id='w',now=AT,source='bookmaker')
        self.assertEqual(self.count('collector_quota'),1)
        self.p.close();self.p=Planner(self.path);self.c=PairedCollector(self.p)
        self.assertEqual(self.c.usage()[0]['units'],1)
        self.finish(claim,self.book_body)

    def test_no_quota_refund_for_unknown_crash_or_failed_attempt(self):
        sources=self.sources(book=[SyntheticFailure(),self.book_body])
        self.step(sources);self.step(sources);self.clock.advance(2);self.step(sources)
        self.assertEqual({r['source']:r['units'] for r in self.c.usage()},{'bookmaker':2,'polymarket':1})

    def test_payload_archive_and_pair_failure_roll_back_as_one_transaction(self):
        sources=self.sources();self.step(sources)
        claim=self.c.claim(worker_id='w',now=AT,source='polymarket')
        self.p.db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON collector_pairs BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.finish(claim,self.poly_body)
        self.assertEqual(self.count('polymarket_captures'),0)
        self.assertEqual(self.count('collector_attempt_results'),1)
        self.assertEqual(self.state(),'planned')
        self.p.db.execute('DROP TRIGGER synthetic_failure');self.finish(claim,self.poly_body)
        self.assertEqual(self.state(),'complete')

    def test_evidence_and_pair_rows_are_immutable(self):
        sources=self.sources();self.step(sources);self.step(sources)
        for table in ['collector_policies','collector_slots','collector_attempts','collector_quota','collector_attempt_results','collector_job_events','collector_pairs']:
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):self.p.db.execute('DELETE FROM '+table)

    def test_live_source_objects_and_callbacks_are_refused(self):
        class Other:
            def read(self):raise AssertionError('must never call')
        with self.assertRaises(ValueError):self.step({'bookmaker':Other(),'polymarket':SyntheticSource([])})
        with self.assertRaises(ValueError):SyntheticSource([lambda:b'bad'])
        self.assertEqual(self.count('collector_attempts'),0)

    def test_policy_and_slot_configuration_cannot_silently_change(self):
        with self.assertRaises(ValueError):self.register(policy=replace(self.policy,max_attempts=3))
        with self.assertRaises(ValueError):self.register(expected_books=('synthetic-other',))
        with self.assertRaises(ValueError):replace(self.policy,lease_seconds=0).validate()

    def test_install_is_explicit_idempotent_and_checks_version(self):
        PairedCollector.install(self.p);self.assertEqual(self.count('collector_component'),1)
        with Planner(':memory:') as p:
            with self.assertRaises(ValueError):PairedCollector(p)
        self.p.db.execute('DROP TABLE collector_component');self.p.db.execute('CREATE TABLE collector_component(version)')
        self.p.db.execute('INSERT INTO collector_component VALUES(2)')
        with self.assertRaises(ValueError):PairedCollector(self.p)

    def test_quota_exhaustion_stops_retries_without_extra_io(self):
        sources=self.sources();self.step(sources);self.step(sources)
        self.clock.advance(1800)
        self.c.reconcile_fixture(policy=self.policy,game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,observed_at=self.clock())
        failures=self.sources(book=[SyntheticFailure()],poly=[SyntheticFailure()])
        self.step(failures);self.step(failures);self.clock.advance(2)
        self.assertIsNone(self.step(failures))
        self.assertEqual((failures['bookmaker'].calls,failures['polymarket'].calls),(1,1))
        self.assertEqual({r['source']:r['units'] for r in self.c.usage()},{'bookmaker':2,'polymarket':2})
        self.assertEqual(self.p.slots('g1')[1]['state'],'missed')

    def test_retry_backoff_is_exponential_and_capped(self):
        self.p.reconcile(game_id='g2',season='2026-27',away='LAL',home='BOS',start=START,observed_at=AT)
        self.c.polymarket.bind_market(binding_id='b2',game_id='g2',event_id='g2-source',market_id='g2-market',condition_id='g2-condition',
            assets_by_team={'LAL':'g2-lal','BOS':'g2-bos'},rules_ref='synthetic-including-overtime-v1',observed_at=AT,evidence='synthetic g2')
        policy=replace(self.policy,policy_id='backoff-policy',max_attempts=4,max_retry_delay_seconds=3,max_source_calls=10)
        self.c.register(game_id='g2',bookmaker_event_id='g2-book',binding_id='b2',expected_books=('synthetic-a',),policy=policy,observed_at=AT)
        # Existing first-game jobs are claimed independently; isolate the g2 job here.
        old=self.c.claim(worker_id='hold',now=AT,source='bookmaker')
        for delay in [2,3,3,None]:
            claim=self.c.claim(worker_id='retry',now=self.clock(),source='bookmaker')
            self.assertIsNotNone(claim)
            self.finish(claim,error='synthetic_timeout')
            job=self.p.db.execute('SELECT j.* FROM collector_jobs j JOIN collector_attempts a USING(job_id) WHERE a.attempt_id=?',(claim.attempt_id,)).fetchone()
            if delay is None:self.assertEqual(job['state'],'exhausted')
            else:
                self.assertEqual(Decimal(str((datetime.fromisoformat(job['next_at'])-self.clock()).total_seconds())),delay)
                self.clock.advance(delay)
        self.assertIsNotNone(old)

    def test_window_expiry_after_one_source_preserves_partial_evidence(self):
        sources=self.sources();self.step(sources);self.clock.advance(61)
        self.assertIsNone(self.step(sources));self.assertEqual(self.state(),'partial')
        self.assertEqual(sources['polymarket'].calls,0)
        self.assertTrue(all(r['bookmaker_capture_id'] is not None and r['polymarket_capture_id'] is None for r in self.c.pairs(self.slot)))

    def test_allowed_lateness_can_be_assessed_for_cost_metadata(self):
        claim=self.c.claim(worker_id='w',now=AT,source='bookmaker')
        self.clock.advance(9)
        self.assertEqual(self.finish(claim,self.book_body),'succeeded')
        # The second source is collected later but still in the allowed lateness window.
        sources=self.sources();self.step(sources)
        self.assertEqual(self.state(),'complete')
        self.assertTrue(all(r['cost_metadata_complete']==1 for r in self.c.pairs(self.slot)))

    def test_overrun_response_retained_but_pair_is_ineligible(self):
        self.p.reconcile(game_id='g2',season='2026-27',away='LAL',home='BOS',start=START,observed_at=AT)
        self.c.polymarket.bind_market(binding_id='b2',game_id='g2',event_id='g2-source',market_id='g2-market',condition_id='g2-condition',
            assets_by_team={'LAL':'g2-lal','BOS':'g2-bos'},rules_ref='synthetic-including-overtime-v1',observed_at=AT,evidence='synthetic g2')
        policy=replace(self.policy,policy_id='short-window',max_lateness_seconds=2)
        self.c.register(game_id='g2',bookmaker_event_id='fictional-lal-bos',binding_id='b2',expected_books=('synthetic-a',),policy=policy,observed_at=AT)
        self.c.claim(worker_id='hold',now=AT,source='bookmaker')
        claim=self.c.claim(worker_id='late',now=AT,source='bookmaker')
        self.clock.advance(3);self.finish(claim,self.book_body)
        self.c.claim(worker_id='maintenance',now=self.clock(),source='bookmaker')
        slot=self.p.slots('g2')[0]
        self.assertEqual(slot['state'],'partial');self.assertEqual(self.count('bookmaker_captures'),1)
        self.assertTrue(all('bookmaker_outside_collection_window' in json.loads(r['flags_json']) for r in self.c.pairs(slot['slot_id'])))

    def test_early_start_and_delayed_schedule_updates_keep_audit(self):
        self.c.reconcile_fixture(policy=self.policy,game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,
                                 observed_at=AT+timedelta(seconds=1),status='delayed')
        self.assertEqual(self.state(),'planned')
        self.c.reconcile_fixture(policy=self.policy,game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,
                                 observed_at=AT+timedelta(seconds=2),status='live')
        self.clock.advance(2);sources=self.sources();self.assertIsNone(self.step(sources))
        self.assertEqual(sources['bookmaker'].calls,0)

    def test_core_planner_default_stays_strict_without_collector_grace(self):
        self.p.reconcile(game_id='g1',season='2026-27',away='LAL',home='BOS',start=START,observed_at=AT+timedelta(seconds=1))
        self.assertEqual(self.state(),'missed')

    def test_runner_records_clock_times_not_source_quote_timestamps(self):
        ticks=iter(AT+timedelta(milliseconds=i) for i in range(5))
        sources=self.sources()
        self.c.run_once(worker_id='timed',clock=lambda:next(ticks),sources=sources)
        capture=self.p.db.execute('SELECT * FROM bookmaker_captures').fetchone()
        result=self.p.db.execute('SELECT * FROM collector_attempt_results').fetchone()
        self.assertEqual(datetime.fromisoformat(capture['request_started_at']),AT+timedelta(milliseconds=1))
        self.assertEqual(datetime.fromisoformat(capture['request_finished_at']),AT+timedelta(milliseconds=2))
        self.assertEqual(datetime.fromisoformat(capture['received_at']),AT+timedelta(milliseconds=3))
        self.assertEqual(datetime.fromisoformat(result['recorded_at']),AT+timedelta(milliseconds=4))

    def test_persistent_demo_rerun_does_not_refetch_or_reset_usage(self):
        from nba_arb_bot.recorder.collector_demo import replay
        path=self.path.with_name('demo.sqlite')
        book=(FIXTURES/'bookmaker-synthetic.json').read_bytes()
        poly=(FIXTURES/'polymarket-synthetic.json').read_bytes()
        first=replay(path,book,poly);second=replay(path,book,poly)
        self.assertEqual(first['slot_state'],'partial')
        self.assertEqual(first['pair_count'],8);self.assertEqual(first['eligible_pairs'],2)
        self.assertEqual(second['source_calls_this_run'],{'bookmaker':0,'polymarket':0})
        self.assertEqual(first['usage'],second['usage'])

    def test_collector_install_failure_is_rolled_back_and_recoverable(self):
        with Planner(':memory:') as p:
            p.db.execute('CREATE TABLE collector_pairs(existing)')
            with self.assertRaises(sqlite3.OperationalError):PairedCollector.install(p)
            self.assertIsNone(p.db.execute("SELECT name FROM sqlite_master WHERE name='collector_component'").fetchone())
            p.db.execute('DROP TABLE collector_pairs');PairedCollector.install(p)
            self.assertEqual(p.db.execute('SELECT COUNT(*) FROM collector_component').fetchone()[0],1)

    def test_install_cannot_implicitly_commit_a_callers_transaction(self):
        with Planner(':memory:') as p:
            with self.assertRaises(RuntimeError):
                with p._transaction():
                    p.db.execute('CREATE TABLE synthetic_outer(value)')
                    with self.assertRaises(ValueError):PairedCollector.install(p)
                    self.assertTrue(p.db.in_transaction)
                    raise RuntimeError('synthetic rollback')
            self.assertIsNone(p.db.execute("SELECT name FROM sqlite_master WHERE name='synthetic_outer'").fetchone())

    def test_backward_clock_cannot_finalize_with_future_evidence(self):
        book=self.c.claim(worker_id='book',now=AT,source='bookmaker')
        self.finish(book,self.book_body,at=AT+timedelta(seconds=1))
        poly=self.c.claim(worker_id='poly',now=AT,source='polymarket')
        self.finish(poly,self.poly_body,at=AT)
        self.assertEqual(self.state(),'planned');self.assertEqual(len(self.c.pairs(self.slot)),0)
        self.clock.advance(1);sources=self.sources();self.assertIsNone(self.step(sources))
        self.assertEqual(self.state(),'complete');self.assertEqual(sources['bookmaker'].calls,0)


if __name__=='__main__':unittest.main()
