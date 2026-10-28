"""Reproducible as-of daily research reports and non-overwriting CSV bundles."""

from collections import Counter
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal,localcontext
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .collector import PairedCollector
from .planner import stamp
from .results import ResultsArchive
from .synthetic import _timestamp

REPORT_VERSION='synthetic-daily-report-v1'
CALCULATION_VERSION='per-book-proportional-v1'
COLUMNS={
 'slots':'''slot_id game_id revision_id revision_number slot_index planned_at planned_date_local
 current_revision_asof state_asof phase_asof registered expected_books_json'''.split(),
 'pairs':'''report_version calculation_version slot_id game_id revision_id planned_at planned_date_local
 fixture_date_et activity_at activity_date_local finalized_at book_id team_id policy_id pairing_version
 bookmaker_capture_id polymarket_capture_id binding_id market_id condition_id asset_id
 bookmaker_raw_sha256 polymarket_raw_sha256 bookmaker_received_at polymarket_received_at
 bookmaker_source_updated_at polymarket_source_updated_at bookmaker_availability polymarket_availability
 receipt_gap_seconds research_eligible cost_metadata_complete flags_json bookmaker_flags_json polymarket_flags_json
 bookmaker_original_price_json bookmaker_decimal_odds bookmaker_implied_probability bookmaker_fair_probability
 polymarket_bid polymarket_ask polymarket_midpoint polymarket_bid_size polymarket_ask_size
 fair_minus_midpoint_pp fair_minus_ask_pp game_result_record_id game_result_version game_result_status game_outcome
 resolution_record_id resolution_version resolution_status outcome_payout result_resolution_mismatch'''.split(),
 'attempts':'''attempt_id job_id slot_id game_id source retry_number worker_id claimed_at lease_until
 capture_id status_asof request_started_at request_finished_at received_at body_sha256 error_code recorded_at activity_at'''.split(),
 'results':'''record_id game_id revision_id source version supersedes_record_id status away_score home_score
 winner_team_id published_at received_at final_at response_sha256'''.split(),
 'result_history':'''record_id game_id revision_id source version supersedes_record_id status away_score home_score
 winner_team_id published_at received_at final_at response_sha256'''.split(),
 'resolutions':'''record_id binding_id game_id event_id market_id condition_id source version supersedes_record_id
 status team_id asset_id payout published_at received_at resolved_at response_sha256'''.split(),
 'resolution_history':'''record_id binding_id game_id event_id market_id condition_id source version supersedes_record_id
 status team_id asset_id payout published_at received_at resolved_at response_sha256'''.split(),
}
COLUMNS['pairs']+='bookmaker_quote_age_seconds polymarket_quote_age_seconds bookmaker_lateness_seconds polymarket_lateness_seconds bookmaker_rules_ref polymarket_rules_ref polymarket_fees_json polymarket_depth_complete'.split()
COLUMNS={name:['schema_version']+(['report_version','calculation_version'] if name!='pairs' else [])+cols for name,cols in COLUMNS.items()}
NUMERIC_FIELDS={'bookmaker_decimal_odds','bookmaker_implied_probability','bookmaker_fair_probability',
 'polymarket_bid','polymarket_ask','polymarket_midpoint','polymarket_bid_size','polymarket_ask_size',
 'fair_minus_midpoint_pp','fair_minus_ask_pp','receipt_gap_seconds','payout','outcome_payout',
 'bookmaker_quote_age_seconds','polymarket_quote_age_seconds','bookmaker_lateness_seconds','polymarket_lateness_seconds'}


def day_bounds(day,zone='Asia/Singapore'):
    local_day=date.fromisoformat(day);tz=ZoneInfo(zone)
    start=datetime.combine(local_day,time.min,tzinfo=tz)
    end=datetime.combine(local_day+timedelta(days=1),time.min,tzinfo=tz)
    return stamp(start),stamp(end)


def _local_day(at,zone):return _timestamp(at).astimezone(ZoneInfo(zone)).date().isoformat()


@dataclass
class DailyReport:
    summary:dict
    tables:dict

    def markdown(self):
        s=self.summary
        lines=[f"# Synthetic NBA daily research report — {s['day']}",'',
            f"Timezone: {s['timezone']}; known as of: {s['as_of']}",
            'Live collection: disabled. This report contains synthetic research evidence only.','',
            '## Planned-slot coverage',
            f"Current-revision slots: {s['scheduled_slots']}; known games: {s['scheduled_games']}.",
            f"States as of cutoff: {json.dumps(s['slot_state_counts'],sort_keys=True)}",
            f"Phases as of cutoff: {json.dumps(s['slot_phase_counts'],sort_keys=True)}",
            f"Older-revision slots (outside active denominator): {s['older_revision_slots']}",'',
            '## Receipt-day activity',
            f"Pair rows: {s['pair_rows']}; research-eligible: {s['eligible_pair_rows']}; ineligible: {s['ineligible_pair_rows']}.",
            f"Attempt rows: {s['attempt_rows']}; outcomes: {json.dumps(s['attempt_status_counts'],sort_keys=True)}",
            f"Synthetic reservations: {json.dumps(s['synthetic_reservations'],sort_keys=True)}",
            'Reservations include unknown/failed attempts; these are not provider bills or confirmed request counts.','',
            '## Bookmaker coverage']
        for book,counts in sorted(s['bookmaker_coverage'].items()):lines.append(f"- {book}: {json.dumps(counts,sort_keys=True)}")
        if not s['bookmaker_coverage']:lines.append('No registered bookmaker coverage for this cohort/activity.')
        lines+=['','## Quality and probability differences',
                json.dumps(s['quality_flag_counts'],sort_keys=True),
                'Differences are per-book fair probability minus Polymarket midpoint/ask, in percentage points.',
                'They are model-based price differences, not profit, ROI, consensus, or executable arbitrage.']
        ranked=sorted((r for r in self.tables['pairs'] if r['fair_minus_midpoint_pp'] is not None),
                      key=lambda r:(-abs(Decimal(r['fair_minus_midpoint_pp'])),r['slot_id'],r['book_id'],r['team_id']))[:10]
        for r in ranked:lines.append(f"- slot {r['slot_id']}, {r['book_id']}, {r['team_id']}: midpoint difference {r['fair_minus_midpoint_pp']} pp; ask difference {r['fair_minus_ask_pp']} pp")
        if not ranked:lines.append('No eligible probability comparisons.')
        lines+=['','## Scores and market resolution',
                f"Latest known game-result rows: {len(self.tables['results'])}; outcome-resolution rows: {len(self.tables['resolutions'])}.",
                'Scores and market payouts are independent. Missing/unresolved payouts remain null.',
                'Corrections are retained in the history CSVs; later receipts never enter an earlier as-of view.',
                'Unprocessed overdue slots are not silently relabeled as missed. Reports do not mutate collection state.','']
        for r in self.tables['results']:
            score=f"{r['away_score']}–{r['home_score']}" if r['away_score'] is not None else 'scores unknown'
            lines.append(f"- {r['game_id']}: {r['status']}, away/home {score}, version {r['version']}, received {r['received_at']}")
        for r in self.tables['resolutions']:
            payout=r['payout'] if r['payout'] is not None else 'unknown'
            lines.append(f"- {r['binding_id']}, {r['team_id']}: {r['status']}, payout {payout}, version {r['version']}")
        lines.append(f"Score/resolution disagreement rows: {sum(r['result_resolution_mismatch']==1 for r in self.tables['pairs'])}")
        return '\n'.join(lines)+'\n'


class DailyReporter:
    def __init__(self,planner):
        self.planner,self.db=planner,planner.db
        PairedCollector(planner);ResultsArchive(planner)

    @contextmanager
    def _snapshot(self):
        if self.db.in_transaction:raise ValueError('Report requires a separate read snapshot')
        self.db.execute('BEGIN')
        try:yield
        finally:self.db.execute('ROLLBACK')

    def build(self,*,day,as_of,zone='Asia/Singapore'):
        start,end=day_bounds(day,zone);cut=stamp(as_of)
        with self._snapshot():
            slots=self._slots(start,end,cut,zone)
            histories=[dict(r) for r in self.db.execute('SELECT * FROM game_result_versions WHERE received_at<=? ORDER BY game_id,version',(cut,))]
            resolutions=[dict(r) for r in self.db.execute('''SELECT v.*,b.game_id,b.event_id,b.market_id,b.condition_id,
                o.team_id,o.asset_id,o.payout FROM resolution_versions v JOIN resolution_payouts o USING(record_id)
                JOIN polymarket_bindings b ON b.binding_id=v.binding_id WHERE v.received_at<=?
                ORDER BY v.binding_id,v.version,o.team_id''',(cut,))]
            latest={r['game_id']:r for r in histories}
            latest_payouts={(r['binding_id'],r['team_id']):r for r in resolutions}
            pairs=self._pairs(start,end,cut,zone,latest,latest_payouts)
            attempts=self._attempts(start,end,cut)
            games={r['game_id'] for r in slots}|{r['game_id'] for r in pairs}
            games|={r['game_id'] for r in histories if start<=r['received_at']<end}
            games|={r['game_id'] for r in resolutions if start<=r['received_at']<end}
            current=[r for r in slots if r['current_revision_asof']]
            coverage={}
            def book_counts():
                return {'planned_outcomes':0,'planned_paired_outcomes':0,'planned_eligible_outcomes':0,
                        'planned_ineligible_outcomes':0,'planned_without_pair_outcomes':0,
                        'pair_rows':0,'eligible_rows':0,'available_bookmaker_rows':0}
            for slot in current:
                for book in json.loads(slot['expected_books_json']):
                    row=coverage.setdefault(book,book_counts())
                    row['planned_outcomes']+=2
                    paired=self.db.execute('SELECT research_eligible FROM collector_pairs WHERE slot_id=? AND book_id=? AND finalized_at<=?',
                        (slot['slot_id'],book,cut)).fetchall()
                    row['planned_paired_outcomes']+=len(paired)
                    row['planned_eligible_outcomes']+=sum(p[0] for p in paired)
                    row['planned_ineligible_outcomes']+=sum(not p[0] for p in paired)
                    row['planned_without_pair_outcomes']+=2-len(paired)
            for pair in pairs:
                row=coverage.setdefault(pair['book_id'],book_counts())
                row['pair_rows']+=1;row['eligible_rows']+=pair['research_eligible']
                row['available_bookmaker_rows']+=int(pair['bookmaker_availability']=='available')
            units=[dict(r) for r in self.db.execute('''SELECT policy_id,source,SUM(units) AS units FROM collector_quota
                WHERE reserved_at>=? AND reserved_at<? AND reserved_at<=? GROUP BY policy_id,source ORDER BY policy_id,source''',(start,end,cut))]
            flags=Counter(flag for row in pairs for flag in json.loads(row['flags_json']))
            summary={'report_version':REPORT_VERSION,'calculation_version':CALCULATION_VERSION,'synthetic':True,
                'day':day,'timezone':zone,'as_of':cut,'day_start_utc':start,'day_end_utc':end,
                'scheduled_slots':len(current),'scheduled_games':len({r['game_id'] for r in current}),
                'older_revision_slots':len(slots)-len(current),
                'slot_state_counts':dict(Counter(r['state_asof'] for r in current)),
                'slot_phase_counts':dict(Counter(r['phase_asof'] for r in current)),
                'pair_rows':len(pairs),'eligible_pair_rows':sum(r['research_eligible'] for r in pairs),
                'ineligible_pair_rows':sum(not r['research_eligible'] for r in pairs),
                'attempt_rows':len(attempts),'attempt_status_counts':dict(Counter(r['status_asof'] for r in attempts)),
                'synthetic_reservations':units,'bookmaker_coverage':coverage,'quality_flag_counts':dict(flags)}
            return DailyReport(summary,{'slots':slots,'pairs':pairs,'attempts':attempts,
                'results':[latest[g] for g in sorted(games) if g in latest],
                'result_history':[r for r in histories if r['game_id'] in games],
                'resolutions':[r for key,r in sorted(latest_payouts.items()) if r['game_id'] in games],
                'resolution_history':[r for r in resolutions if r['game_id'] in games]})

    def _slots(self,start,end,cut,zone):
        rows=self.db.execute('''SELECT s.*,r.game_id,r.revision_number,r.observed_at,r.scheduled_start_utc
            FROM snapshot_slots s JOIN schedule_revisions r USING(revision_id)
            WHERE s.planned_at>=? AND s.planned_at<? AND r.observed_at<=? ORDER BY s.planned_at,r.game_id,r.revision_number''',(start,end,cut)).fetchall()
        latest=dict(self.db.execute('SELECT game_id,MAX(revision_number) FROM schedule_revisions WHERE observed_at<=? GROUP BY game_id',(cut,)))
        result=[]
        for row in rows:
            event=self.db.execute('SELECT to_state FROM slot_events WHERE slot_id=? AND observed_at<=? ORDER BY observed_at DESC,event_id DESC LIMIT 1',(row['slot_id'],cut)).fetchone()
            if event is None:continue
            config=self.db.execute('''SELECT c.*,p.body_json FROM collector_slots c JOIN collector_policies p USING(policy_id)
                WHERE c.slot_id=? AND c.registered_at<=?''',(row['slot_id'],cut)).fetchone()
            phase=event[0]
            if phase=='planned':
                if row['planned_at']>cut:phase='not_due'
                else:
                    grace=json.loads(config['body_json'])['max_lateness_seconds'] if config else 0
                    deadline=stamp(_timestamp(row['planned_at'])+timedelta(seconds=grace))
                    phase='overdue_unfinalized' if cut>deadline else 'due_unfinalized'
            result.append({'slot_id':row['slot_id'],'game_id':row['game_id'],'revision_id':row['revision_id'],
                'revision_number':row['revision_number'],'slot_index':row['slot_index'],'planned_at':row['planned_at'],
                'planned_date_local':_local_day(row['planned_at'],zone),'current_revision_asof':int(row['revision_number']==latest[row['game_id']]),
                'state_asof':event[0],'phase_asof':phase,'registered':int(config is not None),
                'expected_books_json':config['expected_books_json'] if config else '[]'})
        return result

    def _pairs(self,start,end,cut,zone,results,resolutions):
        rows=self.db.execute('''SELECT p.*,s.planned_at,s.revision_id,r.game_id,r.scheduled_start_utc,
            bc.received_at AS b_received,pc.received_at AS p_received,
            bc.response_sha256 AS b_sha,pc.response_sha256 AS p_sha
            FROM collector_pairs p JOIN snapshot_slots s USING(slot_id) JOIN schedule_revisions r USING(revision_id)
            LEFT JOIN bookmaker_captures bc ON bc.capture_id=p.bookmaker_capture_id
            LEFT JOIN polymarket_captures pc ON pc.capture_id=p.polymarket_capture_id
            WHERE p.finalized_at>=? AND p.finalized_at<=? ORDER BY p.slot_id,p.book_id,p.team_id''',(start,cut)).fetchall()
        output=[]
        for row in rows:
            activity=max(t for t in (row['b_received'],row['p_received']) if t is not None) if row['b_received'] or row['p_received'] else row['finalized_at']
            if not start<=activity<end:continue
            b=self.db.execute('SELECT * FROM bookmaker_quotes WHERE capture_id=? AND slot_id=? AND book_id=? AND team_id=?',
                (row['bookmaker_capture_id'],row['slot_id'],row['book_id'],row['team_id'])).fetchone()
            bm=self.db.execute('SELECT * FROM bookmaker_markets WHERE capture_id=? AND slot_id=? AND book_id=?',
                (row['bookmaker_capture_id'],row['slot_id'],row['book_id'])).fetchone()
            p=self.db.execute('SELECT * FROM polymarket_quotes WHERE capture_id=? AND binding_id=? AND team_id=?',
                (row['polymarket_capture_id'],row['binding_id'],row['team_id'])).fetchone()
            binding=self.db.execute('SELECT * FROM polymarket_bindings WHERE binding_id=?',(row['binding_id'],)).fetchone()
            fair=diff_mid=diff_ask=None
            if row['research_eligible']:
                quotes=self.db.execute('SELECT implied_probability FROM bookmaker_quotes WHERE capture_id=? AND slot_id=? AND book_id=?',
                    (row['bookmaker_capture_id'],row['slot_id'],row['book_id'])).fetchall()
                if len(quotes)!=2 or any(q[0] is None for q in quotes):raise ValueError('Eligible pair lacks two-sided evidence')
                with localcontext() as context:
                    context.prec=28
                    fair=str(Decimal(b['implied_probability'])/sum(Decimal(q[0]) for q in quotes))
                    diff_mid=str((Decimal(fair)-Decimal(p['midpoint']))*100)
                    diff_ask=str((Decimal(fair)-Decimal(p['best_ask']))*100)
            result=results.get(row['game_id']);resolution=resolutions.get((row['binding_id'],row['team_id']))
            outcome='unresolved'
            if result:
                outcome=('win' if result['winner_team_id']==row['team_id'] else 'loss') if result['status']=='final' else result['status']
            mismatch=None
            if result and result['status']=='final' and resolution and resolution['status']=='resolved':
                mismatch=int(Decimal(resolution['payout'])!=(1 if outcome=='win' else 0))
            record={key:row[key] for key in ('slot_id','game_id','revision_id','planned_at','finalized_at','book_id','team_id',
                'policy_id','pairing_version','bookmaker_capture_id','polymarket_capture_id','binding_id',
                'receipt_gap_seconds','research_eligible','cost_metadata_complete','flags_json')}
            record.update(report_version=REPORT_VERSION,calculation_version=CALCULATION_VERSION,
                planned_date_local=_local_day(row['planned_at'],zone),fixture_date_et=_local_day(row['scheduled_start_utc'],'America/New_York'),
                activity_at=activity,activity_date_local=_local_day(activity,zone),market_id=binding['market_id'],condition_id=binding['condition_id'],
                asset_id=p['asset_id'] if p else None,bookmaker_raw_sha256=row['b_sha'],polymarket_raw_sha256=row['p_sha'],
                bookmaker_received_at=row['b_received'],polymarket_received_at=row['p_received'],
                bookmaker_source_updated_at=bm['source_updated_at'] if bm else None,polymarket_source_updated_at=p['source_updated_at'] if p else None,
                bookmaker_availability=b['availability'] if b else 'not_observed',polymarket_availability=p['availability'] if p else 'not_observed',
                bookmaker_flags_json=bm['flags_json'] if bm else '[]',polymarket_flags_json=p['flags_json'] if p else '[]',
                bookmaker_original_price_json=b['original_price_json'] if b else None,bookmaker_decimal_odds=b['decimal_odds'] if b else None,
                bookmaker_implied_probability=b['implied_probability'] if b else None,bookmaker_fair_probability=fair,
                polymarket_bid=p['best_bid'] if p else None,polymarket_ask=p['best_ask'] if p else None,
                polymarket_midpoint=p['midpoint'] if p else None,polymarket_bid_size=p['best_bid_size'] if p else None,
                polymarket_ask_size=p['best_ask_size'] if p else None,fair_minus_midpoint_pp=diff_mid,fair_minus_ask_pp=diff_ask,
                game_result_record_id=result['record_id'] if result else None,game_result_version=result['version'] if result else None,
                game_result_status=result['status'] if result else 'unresolved',game_outcome=outcome,
                resolution_record_id=resolution['record_id'] if resolution else None,resolution_version=resolution['version'] if resolution else None,
                resolution_status=resolution['status'] if resolution else 'unresolved',outcome_payout=resolution['payout'] if resolution else None,
                result_resolution_mismatch=mismatch)
            pm=self.db.execute('SELECT * FROM polymarket_markets WHERE capture_id=? AND binding_id=?',
                (row['polymarket_capture_id'],row['binding_id'])).fetchone()
            record.update(bookmaker_quote_age_seconds=bm['quote_age_seconds'] if bm else None,
                polymarket_quote_age_seconds=p['quote_age_seconds'] if p else None,
                bookmaker_lateness_seconds=bm['lateness_seconds'] if bm else None,
                polymarket_lateness_seconds=p['lateness_seconds'] if p else None,
                bookmaker_rules_ref=bm['rules_ref'] if bm else None,polymarket_rules_ref=pm['source_rules_ref'] if pm else None,
                polymarket_fees_json=pm['fees_json'] if pm else None,polymarket_depth_complete=p['depth_complete'] if p else None)
            output.append(record)
        return sorted(output,key=lambda r:(r['activity_at'],r['slot_id'],r['book_id'],r['team_id']))

    def _attempts(self,start,end,cut):
        output=[]
        for a in self.db.execute('''SELECT a.*,j.source,j.slot_id,r.game_id FROM collector_attempts a
            JOIN collector_jobs j USING(job_id) JOIN snapshot_slots s USING(slot_id)
            JOIN schedule_revisions r USING(revision_id) WHERE a.claimed_at<=? ORDER BY a.attempt_id''',(cut,)).fetchall():
            result=self.db.execute('SELECT * FROM collector_attempt_results WHERE attempt_id=? AND recorded_at<=?',(a['attempt_id'],cut)).fetchone()
            activity=(result['received_at'] or result['recorded_at']) if result else a['claimed_at']
            if not start<=activity<end:continue
            record={k:a[k] for k in ('attempt_id','job_id','slot_id','game_id','source','retry_number','worker_id','claimed_at','lease_until','capture_id')}
            record.update(status_asof=result['status'] if result else 'running_or_unknown',activity_at=activity)
            for key in ('request_started_at','request_finished_at','received_at','body_sha256','error_code','recorded_at'):
                record[key]=result[key] if result else None
            output.append(record)
        return output


def _csv_value(value,key):
    if value is None:return ''
    text=str(value)
    if key in NUMERIC_FIELDS:
        number=Decimal(text)
        if not number.is_finite():raise ValueError('Nonfinite numeric CSV field')
        return str(number)
    # Escape spreadsheet formula prefixes in text; trusted numeric columns stay numeric.
    if text.lstrip(' \t\r\n\ufeff').startswith(('=','+','-','@')):return "'"+text
    return text


def export_bundle(report:DailyReport,destination):
    """Create a new bundle only; manifest is written last as its completion marker."""
    out=Path(destination);out.parent.mkdir(parents=True,exist_ok=True);out.mkdir(exist_ok=False)
    owned=[]
    try:
        for name,body in [('summary.json',json.dumps(report.summary,sort_keys=True,indent=2)+'\n'),('report.md',report.markdown())]:
            path=out/name
            with path.open('x',encoding='utf-8',newline='') as f:
                owned.append(path);f.write(body)
        for name,columns in COLUMNS.items():
            path=out/(name+'.csv')
            with path.open('x',encoding='utf-8',newline='') as f:
                owned.append(path)
                writer=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');writer.writeheader()
                for row in report.tables[name]:
                    values=dict(row,schema_version='1',report_version=REPORT_VERSION,calculation_version=CALCULATION_VERSION)
                    writer.writerow({k:_csv_value(values.get(k),k) for k in columns})
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in owned}
        manifest={'schema_version':'1','report_version':REPORT_VERSION,'calculation_version':CALCULATION_VERSION,
            'synthetic':True,'day':report.summary['day'],'timezone':report.summary['timezone'],'as_of':report.summary['as_of'],
            'csv_null':'empty cell; consult availability/status fields','csv_text_escape':'apostrophe for formula-prefix text',
            'files_sha256':hashes,'raw_payloads_included':False}
        path=out/'manifest.json'
        with path.open('x',encoding='utf-8') as f:
            owned.append(path);f.write(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        return manifest
    except Exception:
        for path in owned:
            if path.is_file():path.unlink()
        try:out.rmdir()
        except OSError:pass
        raise


def report_database(database,*,day,as_of,zone='Asia/Singapore'):
    """Read an existing installed recorder database without creating or migrating it."""
    from contextlib import closing
    import sqlite3
    from types import SimpleNamespace
    uri=Path(database).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,isolation_level=None)) as db:
        db.row_factory=sqlite3.Row
        if db.execute('PRAGMA application_id').fetchone()[0]!=1312964944 or db.execute('PRAGMA user_version').fetchone()[0]!=1:
            raise ValueError('Unsupported recorder database')
        return DailyReporter(SimpleNamespace(db=db)).build(day=day,as_of=as_of,zone=zone)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--day',required=True,help='Local planned/receipt date YYYY-MM-DD')
    parser.add_argument('--as-of',required=True,help='Explicit timezone-aware knowledge cutoff')
    parser.add_argument('--timezone',default='Asia/Singapore')
    parser.add_argument('--output',type=Path,required=True,help='New directory, preferably exports-private/')
    args=parser.parse_args()
    report=report_database(args.database,day=args.day,as_of=_timestamp(args.as_of),zone=args.timezone)
    export_bundle(report,args.output)
    print(json.dumps({'output':str(args.output.resolve()),'synthetic':True,'live_collection':'disabled'}))


if __name__=='__main__':main()
