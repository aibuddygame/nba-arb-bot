"""P05 acceptance checks using local bytes and temporary databases only."""

from copy import deepcopy
import csv
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nba_arb_bot.recorder.collector import PairedCollector,CollectionPolicy
from nba_arb_bot.recorder.collector_demo import replay
from nba_arb_bot.recorder.planner import Planner,stamp
from nba_arb_bot.recorder.reporting import COLUMNS,DailyReporter,day_bounds,export_bundle,_csv_value,report_database
from nba_arb_bot.recorder.results import ResultsArchive
from nba_arb_bot.recorder.synthetic import Capture

FIXTURES=Path(__file__).parent/'fixtures'
AT=datetime(2026,10,28,12,tzinfo=timezone.utc)
RESULT_AT=datetime(2026,10,29,4,tzinfo=timezone.utc)
RESOLUTION_AT=RESULT_AT+timedelta(hours=1)
CUT=RESULT_AT+timedelta(hours=2)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.network=patch('socket.socket',side_effect=AssertionError('P05 must stay offline'));self.network.start()
        self.addCleanup(self.network.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.path=self.folder/'synthetic.sqlite'
        replay(self.path,(FIXTURES/'bookmaker-synthetic.json').read_bytes(),(FIXTURES/'polymarket-synthetic.json').read_bytes())
        self.p=Planner(self.path);self.addCleanup(lambda:self.p.close())
        ResultsArchive.install(self.p);self.archive=ResultsArchive(self.p)
        self.result=json.loads((FIXTURES/'results-synthetic.json').read_bytes())
        self.resolution=json.loads((FIXTURES/'resolutions-synthetic.json').read_bytes())

    def ingest(self,data=None,at=RESULT_AT):
        return self.archive.ingest_results(json.dumps(data or self.result).encode(),received_at=at)

    def resolve(self,data=None,at=RESOLUTION_AT):
        return self.archive.ingest_resolutions(json.dumps(data or self.resolution).encode(),received_at=at)

    def report(self,cut=CUT,day='2026-10-28',zone='Asia/Singapore'):
        return DailyReporter(self.p).build(day=day,as_of=cut,zone=zone)

    def count(self,table):return self.p.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def correction(self,data):
        data=deepcopy(data);r=data['records'][0]
        r.update(record_id=r['record_id']+'-correction',version=2,supersedes_record_id=r['record_id'],published_at='2026-10-29T06:00:00Z')
        return data

    def test_demo_coverage_and_independent_labels(self):
        self.ingest();self.resolve();r=self.report()
        self.assertEqual(r.summary['scheduled_slots'],8)
        self.assertEqual(r.summary['slot_state_counts'],{'partial':1,'planned':7})
        self.assertEqual(r.summary['slot_phase_counts'],{'partial':1,'overdue_unfinalized':7})
        self.assertEqual((r.summary['pair_rows'],r.summary['eligible_pair_rows'],r.summary['attempt_rows']),(8,2,2))
        self.assertEqual(r.summary['bookmaker_coverage']['synthetic-d']['planned_outcomes'],16)
        self.assertTrue(all(p['result_resolution_mismatch']==0 for p in r.tables['pairs']))

    def test_result_replay_retains_first_receipt(self):
        self.assertEqual(self.ingest(),1);self.assertEqual(self.ingest(at=CUT),0)
        self.assertEqual(self.report().tables['results'][0]['received_at'],stamp(RESULT_AT))
        self.assertEqual(self.count('result_raw_responses'),1)

    def test_changed_record_id_evidence_rejected(self):
        self.ingest();self.result['records'][0]['away_score']=111
        with self.assertRaises(ValueError):self.ingest()
        self.assertEqual(self.count('game_result_versions'),1)

    def test_correction_history_and_asof_no_future_leakage(self):
        self.ingest();old=self.report()
        data=self.correction(self.result);data['records'][0]['home_score']=120
        self.ingest(data,at=CUT+timedelta(hours=1))
        self.assertEqual(old,self.report())
        new=self.report(cut=CUT+timedelta(hours=2))
        self.assertEqual(len(new.tables['result_history']),2)
        self.assertEqual(new.tables['results'][0]['winner_team_id'],'BOS')
        self.assertEqual(new.tables['pairs'][0]['game_result_version'],2)

    def test_resolution_correction_independent_from_scores(self):
        self.ingest();self.resolve();data=self.correction(self.resolution)
        data['records'][0]['payouts']={'synthetic-asset-lal':'0','synthetic-asset-bos':'1'}
        self.resolve(data,at=CUT+timedelta(hours=1))
        self.assertEqual(self.report().tables['pairs'][0]['result_resolution_mismatch'],0)
        r=self.report(cut=CUT+timedelta(hours=2))
        self.assertEqual(len(r.tables['resolution_history']),4)
        self.assertTrue(all(p['result_resolution_mismatch']==1 for p in r.tables['pairs']))

    def test_score_never_implies_market_payout(self):
        self.ingest();rows=self.report().tables['pairs']
        self.assertTrue(all(r['outcome_payout'] is None and r['resolution_status']=='unresolved' for r in rows))
        self.assertEqual({r['game_outcome'] for r in rows},{'win','loss'})

    def test_resolution_can_arrive_without_score(self):
        self.resolve();rows=self.report().tables['pairs']
        self.assertTrue(all(r['game_outcome']=='unresolved' and r['result_resolution_mismatch'] is None for r in rows))
        self.assertEqual({r['outcome_payout'] for r in rows},{'0','1'})

    def test_unknown_disputed_and_void_payouts(self):
        for status in ('unresolved','disputed','void'):
            with self.subTest(status=status):
                data=deepcopy(self.resolution);record=data['records'][0]
                record['status']=status
                record['payouts']={k:('0.5' if status=='void' else None) for k in record['payouts']}
                if status!='void':record['resolved_at']=None
                if status=='unresolved':self.resolve(data)
                else:
                    data=self.correction(data)
                    if status=='void':data['records'][0]['version']=3;data['records'][0]['supersedes_record_id']='synthetic-resolution-1-correction';data['records'][0]['record_id']='synthetic-resolution-3'
                    self.resolve(data,at=CUT)
                self.assertEqual(self.report().tables['resolutions'][0]['status'],status)

    def test_bad_scores_fixture_and_chronology_fail_atomic(self):
        mutations=[{'away_score':True},{'away_score':-1},{'away_score':100},{'home':'NYK'},
                   {'scheduled_start_utc':'2026-10-29T01:00:00Z'},
                   {'final_at':'2026-10-28T23:59:00Z'},{'published_at':'2026-10-30T00:00:00Z'},
                   {'status':'pending'},{'away_score':1.1}]
        for fields in mutations:
            data=deepcopy(self.result);data['records'][0].update(fields)
            with self.subTest(fields=fields),self.assertRaises((ValueError,TypeError)):self.ingest(data)
            self.assertEqual(self.count('game_result_versions'),0);self.assertEqual(self.count('result_raw_responses'),0)

    def test_bad_resolution_identity_assets_and_payouts(self):
        mutations=[{'market_id':'wrong'},{'condition_id':'wrong'}, {'payouts':{'wrong':'1'}},
            {'payouts':{'synthetic-asset-lal':'1','synthetic-asset-bos':'1'}},
            {'payouts':{'synthetic-asset-lal':'0.5','synthetic-asset-bos':'0.5'}},
            {'payouts':{'synthetic-asset-lal':1,'synthetic-asset-bos':0}},
            {'status':'unresolved'},{'resolved_at':'2026-10-29T04:00:00Z'}]
        for fields in mutations:
            data=deepcopy(self.resolution);data['records'][0].update(fields)
            with self.subTest(fields=fields),self.assertRaises((ValueError,TypeError)):self.resolve(data)
            self.assertEqual(self.count('resolution_versions'),0)

    def test_chain_must_be_contiguous_and_correct_parent(self):
        self.ingest()
        for fields in ({'version':3},{'supersedes_record_id':None},{'published_at':'2026-10-29T03:04:00Z'}):
            data=self.correction(self.result);data['records'][0].update(fields)
            with self.subTest(fields=fields),self.assertRaises(ValueError):self.ingest(data,at=CUT)
        with self.assertRaises(ValueError):self.ingest(at=RESULT_AT-timedelta(seconds=1))

    def test_pending_and_in_progress_results_preserve_null_and_zero(self):
        data=deepcopy(self.result);r=data['records'][0]
        r.update(status='pending',away_score=None,home_score=None,final_at=None)
        self.ingest(data)
        data=self.correction(data);data['records'][0].update(status='in_progress',away_score=0,home_score=0)
        self.ingest(data,at=CUT)
        self.assertEqual(self.report().tables['results'][0]['away_score'],0)
        self.assertEqual(self.report().tables['pairs'][0]['game_outcome'],'in_progress')

    def test_batch_validation_failure_rolls_back_every_record(self):
        data=deepcopy(self.result);bad=deepcopy(data['records'][0]);bad.update(record_id='bad',game_id='unknown')
        data['records'].append(bad)
        with self.assertRaises(ValueError):self.ingest(data)
        self.assertEqual(self.count('game_result_versions'),0);self.assertEqual(self.count('result_raw_responses'),0)

    def test_injected_payout_failure_rolls_back_archive_and_retry(self):
        self.p.db.execute("CREATE TRIGGER fail_payout BEFORE INSERT ON resolution_payouts BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.resolve()
        self.assertEqual(self.count('resolution_versions'),0);self.assertEqual(self.count('result_raw_responses'),0)
        self.p.db.execute('DROP TRIGGER fail_payout');self.assertEqual(self.resolve(),1)

    def test_immutable_evidence_and_raw_hash_roundtrip(self):
        self.ingest();self.resolve()
        raw=self.p.db.execute('SELECT response_sha256 FROM game_result_versions').fetchone()[0]
        self.assertEqual(hashlib.sha256(self.archive.raw_response(raw)).hexdigest(),raw)
        for table in ('game_result_versions','resolution_versions','resolution_payouts','result_raw_responses'):
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):self.p.db.execute('DELETE FROM '+table)

    def test_install_is_explicit_idempotent_and_version_guarded(self):
        ResultsArchive.install(self.p);self.assertEqual(self.count('results_component'),1)
        with Planner(':memory:') as p:
            with self.assertRaises(ValueError):ResultsArchive(p)
            with self.assertRaises(ValueError):ResultsArchive.install(p)
        self.p.db.execute('DROP TABLE results_component');self.p.db.execute('CREATE TABLE results_component(version)')
        self.p.db.execute('INSERT INTO results_component VALUES(2)')
        with self.assertRaises(ValueError):ResultsArchive(self.p)

    def test_install_failure_rollback(self):
        with Planner(':memory:') as p:
            PairedCollector.install(p);p.db.execute('CREATE TABLE resolution_versions(existing)')
            with self.assertRaises(sqlite3.OperationalError):ResultsArchive.install(p)
            self.assertIsNone(p.db.execute("SELECT name FROM sqlite_master WHERE name='results_component'").fetchone())
            p.db.execute('DROP TABLE resolution_versions');ResultsArchive.install(p)

    def test_install_and_report_do_not_commit_callers_transaction(self):
        with self.assertRaises(RuntimeError):
            with self.p._transaction():
                with self.assertRaises(ValueError):ResultsArchive.install(self.p)
                with self.assertRaises(ValueError):self.report()
                self.assertTrue(self.p.db.in_transaction)
                raise RuntimeError('rollback')

    def test_synthetic_marker_credentials_and_duplicate_json_rejected(self):
        data=deepcopy(self.result);data['synthetic']=False
        bodies=[json.dumps(data).encode(),b'{"schema":1,"schema":2}',b'[]',b'NaN',b'x'*2_000_001]
        data=deepcopy(self.result);data['records'][0]['api_key']='synthetic-forbidden';bodies.append(json.dumps(data).encode())
        for body in bodies:
            with self.subTest(size=len(body)),self.assertRaises(ValueError):self.archive.ingest_results(body,received_at=RESULT_AT)
        self.assertEqual(self.count('result_raw_responses'),0)

    def test_reopen_keeps_results_and_deterministic_report(self):
        self.ingest();self.resolve();old=self.report();self.p.close();self.p=Planner(self.path);self.archive=ResultsArchive(self.p)
        self.assertEqual(old,self.report());self.assertEqual(self.ingest(at=CUT),0)

    def test_asof_excludes_unknown_schedule_captures_and_results(self):
        self.ingest();self.resolve();r=self.report(cut=AT-timedelta(microseconds=1))
        self.assertEqual(r.summary['scheduled_slots'],0);self.assertEqual(r.tables['pairs'],[])
        self.assertEqual(r.tables['results'],[]);self.assertEqual(r.tables['attempts'],[])

    def test_source_receipt_controls_result_knowledge(self):
        self.ingest();self.resolve();r=self.report(cut=RESULT_AT-timedelta(microseconds=1))
        self.assertEqual(r.tables['results'],[]);self.assertEqual(r.tables['resolutions'],[])
        self.assertTrue(all(p['game_outcome']=='unresolved' for p in r.tables['pairs']))

    def test_slot_history_survives_later_schedule_revision(self):
        original=self.report(cut=AT)
        self.p.reconcile(game_id='fictional-lal-bos',season='synthetic-season',away='LAL',home='BOS',
            start=datetime(2026,10,30,tzinfo=timezone.utc),observed_at=AT+timedelta(hours=1))
        self.assertEqual(original,self.report(cut=AT))
        r=self.report();self.assertEqual(r.summary['scheduled_slots'],0)
        self.assertEqual(r.summary['older_revision_slots'],8);self.assertEqual(r.summary['pair_rows'],8)

    def test_dst_days_are_23_and_25_hours(self):
        for day,hours in [('2026-03-08',23),('2026-11-01',25)]:
            a,b=day_bounds(day,'America/New_York')
            self.assertEqual((datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds(),hours*3600)

    def test_local_midnight_and_receipt_cohorts(self):
        today=self.report();tomorrow=self.report(day='2026-10-29')
        self.assertEqual(today.summary['scheduled_slots'],8);self.assertEqual(tomorrow.summary['scheduled_slots'],17)
        self.assertEqual(tomorrow.summary['pair_rows'],0)
        self.assertEqual(self.report(zone='UTC').summary['scheduled_slots'],24)
        self.ingest();self.assertEqual(len(self.report(day='2026-10-29').tables['results']),1)

    def test_per_book_fair_probability_and_differences(self):
        rows=[r for r in self.report().tables['pairs'] if r['research_eligible']]
        self.assertEqual({r['book_id'] for r in rows},{'synthetic-a'})
        self.assertAlmostEqual(sum(Decimal(r['bookmaker_fair_probability']) for r in rows),Decimal(1),places=26)
        lal=next(r for r in rows if r['team_id']=='LAL')
        self.assertAlmostEqual(Decimal(lal['bookmaker_fair_probability']),Decimal(1)/Decimal('2.3')/(Decimal(1)/Decimal('2.3')+Decimal('0.6')),places=26)
        self.assertEqual(Decimal(lal['fair_minus_midpoint_pp']),(Decimal(lal['bookmaker_fair_probability'])-Decimal('.565'))*100)
        self.assertLess(Decimal(lal['fair_minus_ask_pp']),Decimal(lal['fair_minus_midpoint_pp']))

    def test_missing_and_suspended_are_not_zero_or_comparisons(self):
        rows=self.report().tables['pairs'];missing=[r for r in rows if r['book_id']=='synthetic-d']
        self.assertTrue(all(r['bookmaker_decimal_odds'] is None for r in missing))
        self.assertTrue(all(r['fair_minus_midpoint_pp'] is None for r in rows if not r['research_eligible']))
        self.assertEqual(len({r['bookmaker_raw_sha256'] for r in rows}),1)
        self.assertTrue(all(r['bookmaker_capture_id'] and r['polymarket_capture_id'] for r in rows))

    def test_report_is_read_only(self):
        before=self.p.db.total_changes;first=self.report();second=self.report()
        self.assertEqual(first,second);self.assertEqual(self.p.db.total_changes,before)
        self.assertEqual(self.p.slots('fictional-lal-bos')[1]['state'],'planned')

    def test_csv_hashes_columns_nulls_and_repeatability(self):
        self.ingest();self.resolve();r=self.report();a=self.folder/'a';b=self.folder/'b'
        manifest=export_bundle(r,a);self.assertEqual(manifest,export_bundle(r,b))
        self.assertEqual(len(list(a.iterdir())),10)
        for name,digest in manifest['files_sha256'].items():
            self.assertEqual(hashlib.sha256((a/name).read_bytes()).hexdigest(),digest)
        for name,cols in COLUMNS.items():
            with (a/(name+'.csv')).open(newline='') as f:self.assertEqual(next(csv.reader(f)),cols)
        with (a/'pairs.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        missing=next(row for row in rows if row['book_id']=='synthetic-d')
        self.assertEqual(missing['bookmaker_decimal_odds'],'');self.assertEqual(missing['schema_version'],'1')
        self.assertFalse(manifest['raw_payloads_included'])

    def test_export_refuses_existing_destination(self):
        folder=self.folder/'existing';folder.mkdir();(folder/'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):export_bundle(self.report(),folder)
        self.assertEqual((folder/'keep.txt').read_text(),'keep')

    def test_failed_export_removes_only_own_partial_bundle(self):
        r=self.report();r.tables['pairs'][0]['polymarket_ask']='NaN'
        out=self.folder/'failed'
        with self.assertRaises(ValueError):export_bundle(r,out)
        self.assertFalse(out.exists())

    def test_csv_formula_text_escape_and_negative_numeric(self):
        for text in ('=1+1','+cmd','-cmd','@cmd',' \t=1','\ufeff@cmd'):
            self.assertEqual(_csv_value(text,'worker_id'),"'"+text)
        self.assertEqual(_csv_value('-12.5','fair_minus_ask_pp'),'-12.5')
        self.assertEqual(_csv_value(None,'payout'),'');self.assertEqual(_csv_value('0','payout'),'0')

    def test_markdown_contains_cutoff_limits_and_missingness(self):
        body=self.report().markdown()
        for term in ('synthetic','known as of','overdue_unfinalized','research-eligible','not profit','unresolved'):
            self.assertIn(term,body)

    def test_naive_cutoff_and_invalid_date_zone_rejected(self):
        for kwargs in ({'cut':datetime(2026,10,29)},{'day':'bad'},{'zone':'Invalid/Zone'}):
            with self.subTest(kwargs=kwargs),self.assertRaises((ValueError,KeyError)):self.report(**kwargs)

    def test_existing_database_report_uses_readonly_connection(self):
        self.ingest();before=self.path.read_bytes()
        r=report_database(self.path,day='2026-10-28',as_of=CUT)
        self.assertEqual(r,self.report());self.assertEqual(before,self.path.read_bytes())
        missing=self.folder/'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError):report_database(missing,day='2026-10-28',as_of=CUT)
        self.assertFalse(missing.exists())

    def boundary_collection(self,failed=False):
        delta=timedelta(hours=3,minutes=59,seconds=59);at=AT+delta
        def shift(value):
            if isinstance(value,dict):return {k:shift(v) for k,v in value.items()}
            if isinstance(value,list):return [shift(v) for v in value]
            if isinstance(value,str) and value.endswith('Z') and 'T' in value:
                return (datetime.fromisoformat(value)+delta).isoformat().replace('+00:00','Z')
            return value
        p=Planner(self.folder/'boundary.sqlite');self.addCleanup(p.close)
        p.reconcile(game_id='boundary',season='synthetic',away='LAL',home='BOS',start=at+timedelta(hours=12),observed_at=at-timedelta(hours=1))
        PairedCollector.install(p);c=PairedCollector(p)
        c.polymarket.bind_market(binding_id='boundary',game_id='boundary',event_id='fictional-lal-bos',
            market_id='synthetic-moneyline-1',condition_id='synthetic-condition-1',
            assets_by_team={'LAL':'synthetic-asset-lal','BOS':'synthetic-asset-bos'},
            rules_ref='synthetic-including-overtime-v1',observed_at=at-timedelta(hours=1),evidence='synthetic boundary test')
        policy=CollectionPolicy('boundary-policy',60,5,120,120,10,1,2,8,1000)
        c.register(game_id='boundary',bookmaker_event_id='fictional-lal-bos',binding_id='boundary',expected_books=('synthetic-a',),policy=policy,observed_at=at-timedelta(hours=1))
        c.reconcile_fixture(policy=policy,game_id='boundary',season='synthetic',away='LAL',home='BOS',start=at+timedelta(hours=12),observed_at=at)
        for source,seconds in [('bookmaker',0),('polymarket',2)]:
            claim=c.claim(worker_id='boundary',now=at,source=source);finish=at+timedelta(seconds=seconds)
            data=shift(json.loads((FIXTURES/(source+'-synthetic.json')).read_bytes()))
            if source=='bookmaker':data['events'][0]['bookmakers']=data['events'][0]['bookmakers'][:1]
            c.finish(claim,capture=Capture(claim.capture_id,at,finish,finish),finished_at=finish,
                     body=None if failed else json.dumps(data).encode(),error_code='synthetic_timeout' if failed else None)
        ResultsArchive.install(p)
        return DailyReporter(p),at

    def test_receipt_after_midnight_does_not_change_planned_denominator(self):
        reporter,at=self.boundary_collection()
        today=reporter.build(day='2026-10-28',as_of=at+timedelta(seconds=3))
        tomorrow=reporter.build(day='2026-10-29',as_of=at+timedelta(seconds=3))
        self.assertEqual(today.summary['scheduled_slots'],1);self.assertEqual(today.summary['pair_rows'],0)
        self.assertEqual(today.summary['slot_state_counts'],{'complete':1})
        self.assertEqual(today.summary['bookmaker_coverage']['synthetic-a']['planned_eligible_outcomes'],2)
        self.assertEqual(tomorrow.summary['pair_rows'],2);self.assertEqual(tomorrow.summary['scheduled_slots'],24)
        self.assertTrue(all(p['planned_date_local']=='2026-10-28' for p in tomorrow.tables['pairs']))

    def test_asof_attempt_result_and_slot_state_do_not_leak(self):
        reporter,at=self.boundary_collection()
        r=reporter.build(day='2026-10-28',as_of=at)
        self.assertEqual(r.summary['attempt_status_counts'],{'succeeded':1,'running_or_unknown':1})
        self.assertEqual(r.summary['slot_state_counts'],{'planned':1});self.assertEqual(r.summary['pair_rows'],0)
        pending=next(a for a in r.tables['attempts'] if a['source']=='polymarket')
        self.assertIsNone(pending['received_at']);self.assertIsNone(pending['body_sha256'])

    def test_missed_slot_and_failed_attempts_preserve_null_quotes(self):
        reporter,at=self.boundary_collection(failed=True)
        r=reporter.build(day='2026-10-29',as_of=at+timedelta(seconds=3))
        self.assertEqual(r.summary['pair_rows'],2);self.assertEqual(r.summary['eligible_pair_rows'],0)
        self.assertTrue(all(p['bookmaker_decimal_odds'] is None and p['polymarket_ask'] is None for p in r.tables['pairs']))
        previous=reporter.build(day='2026-10-28',as_of=at+timedelta(seconds=3))
        self.assertEqual(previous.summary['slot_state_counts'],{'missed':1})
        self.assertEqual(sum(x['units'] for x in previous.summary['synthetic_reservations']),2)

    def test_future_planned_slots_remain_not_due(self):
        reporter,at=self.boundary_collection()
        r=reporter.build(day='2026-10-28',as_of=at-timedelta(seconds=1))
        self.assertEqual(r.summary['slot_phase_counts'],{'not_due':1})
        self.assertEqual(r.summary['attempt_rows'],0)


if __name__=='__main__':unittest.main()
