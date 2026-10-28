"""Immutable, versioned synthetic game scores and independent market resolutions."""

from decimal import Decimal, localcontext
import gzip
import hashlib
import json
from pathlib import Path
import re

from .identities import team_id
from .planner import stamp
from .polymarket import PolymarketArchive
from .synthetic import PayloadError, _check_keys, _identifier, _no_duplicates, _timestamp

RESULTS_SOURCE='synthetic-results-v1'
RESOLUTIONS_SOURCE='synthetic-resolutions-v1'


def decode_records(body, schema):
    if not isinstance(body,bytes) or len(body)>2_000_000:
        raise PayloadError('invalid_payload_size_or_type')
    try:
        data=json.loads(body,object_pairs_hook=_no_duplicates,
                        parse_constant=lambda _: (_ for _ in ()).throw(PayloadError('nonfinite_json')))
        _check_keys(data)
        if (not isinstance(data,dict) or set(data)!={'schema','synthetic','records'} or
                data['schema']!=schema or data['synthetic'] is not True or not isinstance(data['records'],list)):
            raise PayloadError('synthetic_records_required')
        ids=set()
        for record in data['records']:
            if not isinstance(record,dict):raise PayloadError('invalid_record')
            record_id=_identifier(record.get('record_id'))
            if record_id in ids:raise PayloadError('duplicate_record_id')
            ids.add(record_id)
        return data['records']
    except PayloadError:raise
    except (ValueError,TypeError,UnicodeError,RecursionError):
        raise PayloadError('invalid_json_structure') from None


class ResultsArchive:
    @staticmethod
    def install(planner):
        if planner.db.in_transaction:raise ValueError('Install outside active transactions')
        PolymarketArchive(planner) # Explicit prerequisite; never auto-install another component.
        if planner.db.execute("SELECT name FROM sqlite_master WHERE name='results_component'").fetchone():
            ResultsArchive(planner);return
        try:planner.db.executescript(Path(__file__).with_name('results_schema.sql').read_text())
        except Exception:
            if planner.db.in_transaction:planner.db.execute('ROLLBACK')
            raise

    def __init__(self,planner):
        self.planner,self.db=planner,planner.db
        if not self.db.execute("SELECT name FROM sqlite_master WHERE name='results_component'").fetchone():
            raise ValueError('Call ResultsArchive.install explicitly first')
        if [r[0] for r in self.db.execute('SELECT version FROM results_component')]!=[1]:
            raise ValueError('Unsupported results component version')

    def ingest_results(self,body,*,received_at):
        return self._ingest(body,received_at,False)

    def ingest_resolutions(self,body,*,received_at):
        return self._ingest(body,received_at,True)

    def _ingest(self,body,received_at,resolution):
        source=RESOLUTIONS_SOURCE if resolution else RESULTS_SOURCE
        records=decode_records(body,source);received=stamp(received_at)
        digest=hashlib.sha256(body).hexdigest();inserted=0
        with self.planner._transaction():
            for record in records:
                canonical=json.dumps(record,sort_keys=True,separators=(',',':'))
                table='resolution_versions' if resolution else 'game_result_versions'
                old=self.db.execute(f'SELECT * FROM {table} WHERE record_id=?',(record['record_id'],)).fetchone()
                if old:
                    if old['input_json']!=canonical or received<old['received_at']:
                        raise ValueError('Record ID conflicts with retained evidence')
                    continue # Preserve the first receipt; a repeated download is not a correction.
                published=stamp(_timestamp(record.get('published_at')))
                if published>received:raise ValueError('Publication cannot be after receipt')
                if type(record.get('version')) is not int or record['version']<1:
                    raise ValueError('Require a positive integer correction version')
                self.db.execute('INSERT OR IGNORE INTO result_raw_responses VALUES(?,?)',(digest,gzip.compress(body,mtime=0)))
                self.raw_response(digest)
                if resolution:self._resolution(record,source,published,received,digest,canonical)
                else:self._result(record,source,published,received,digest,canonical)
                inserted+=1
        return inserted

    def _chain(self,table,key,value,record,published,received):
        previous=self.db.execute(f'SELECT * FROM {table} WHERE {key}=? ORDER BY version DESC LIMIT 1',(value,)).fetchone()
        expected=previous['version']+1 if previous else 1
        parent=previous['record_id'] if previous else None
        if record['version']!=expected or record.get('supersedes_record_id')!=parent:
            raise ValueError('Corrections must extend the retained version chain')
        if previous and (published<previous['published_at'] or received<previous['received_at']):
            raise ValueError('Correction chronology cannot move backwards')
        return parent

    def _result(self,r,source,published,received,digest,canonical):
        fields={'record_id','game_id','away','home','scheduled_start_utc','version','supersedes_record_id',
                'status','away_score','home_score','published_at','final_at'}
        if set(r)!=fields:raise ValueError('Unexpected or missing result fields')
        _identifier(r['game_id'])
        game=self.db.execute('SELECT * FROM games WHERE game_id=?',(r['game_id'],)).fetchone()
        revision=self.db.execute('SELECT * FROM schedule_revisions WHERE game_id=? AND observed_at<=? ORDER BY revision_number DESC LIMIT 1',
                                 (r['game_id'],received)).fetchone()
        if (game is None or revision is None or team_id(r['away'])!=game['away_team_id'] or
            team_id(r['home'])!=game['home_team_id'] or stamp(_timestamp(r['scheduled_start_utc']))!=revision['scheduled_start_utc']):
            raise ValueError('Result fixture identity mismatch')
        status=r['status'];a,h=r['away_score'],r['home_score'];final=None;winner=None
        if status not in {'pending','in_progress','final','postponed','cancelled','void'}:
            raise ValueError('Unsupported game result status')
        if status in {'final','in_progress'}:
            if not all(type(v) is int and 0<=v<=2147483647 for v in (a,h)):
                raise ValueError('Scores require nonnegative integers')
        elif a is not None or h is not None:raise ValueError('Unknown/void scores must be null')
        if status=='final':
            if a==h:raise ValueError('A final NBA game cannot be tied')
            final=stamp(_timestamp(r['final_at']))
            if not revision['scheduled_start_utc']<=final<=published:
                raise ValueError('Invalid game completion chronology')
            winner=game['away_team_id'] if a>h else game['home_team_id']
        elif r['final_at'] is not None:raise ValueError('Non-final game cannot have final_at')
        parent=self._chain('game_result_versions','game_id',r['game_id'],r,published,received)
        self.db.execute('INSERT INTO game_result_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (r['record_id'],r['game_id'],revision['revision_id'],source,r['version'],parent,status,a,h,winner,
             published,received,final,digest,canonical))

    def _resolution(self,r,source,published,received,digest,canonical):
        fields={'record_id','binding_id','event_id','market_id','condition_id','version','supersedes_record_id',
                'status','payouts','published_at','resolved_at'}
        if set(r)!=fields:raise ValueError('Unexpected or missing resolution fields')
        binding=self.db.execute('SELECT * FROM polymarket_bindings WHERE binding_id=?',(r['binding_id'],)).fetchone()
        if binding is None or binding['observed_at']>received or any(r[key]!=binding[key] for key in ('event_id','market_id','condition_id')):
            raise ValueError('Resolution market identity mismatch')
        outcomes=self.db.execute('SELECT * FROM polymarket_bound_outcomes WHERE binding_id=?',(r['binding_id'],)).fetchall()
        if not isinstance(r['payouts'],dict) or set(r['payouts'])!={o['asset_id'] for o in outcomes}:
            raise ValueError('Resolution must name exactly the pinned outcome assets')
        status=r['status'];resolved=None;payouts={}
        if status not in {'unresolved','disputed','resolved','void'}:raise ValueError('Unsupported resolution status')
        for asset,value in r['payouts'].items():
            if status in {'resolved','void'}:
                if not isinstance(value,str) or len(value)>64 or not re.fullmatch(r'\d+(?:\.\d+)?',value):
                    raise ValueError('Payouts require exact decimal text')
                amount=Decimal(value)
                if not 0<=amount<=1 or (status=='resolved' and amount not in {Decimal(0),Decimal(1)}):
                    raise ValueError('Invalid binary payout')
                payouts[asset]=value
            else:
                if value is not None:raise ValueError('Unresolved payouts must remain null')
                payouts[asset]=None
        if status in {'resolved','void'}:
            with localcontext() as context:
                context.prec=80
                if sum(Decimal(v) for v in payouts.values())!=1:raise ValueError('Binary payouts must sum to one')
            resolved=stamp(_timestamp(r['resolved_at']))
            if not binding['observed_at']<=resolved<=published:raise ValueError('Invalid resolution chronology')
        elif r['resolved_at'] is not None:raise ValueError('Unresolved market cannot have resolved_at')
        parent=self._chain('resolution_versions','binding_id',r['binding_id'],r,published,received)
        self.db.execute('INSERT INTO resolution_versions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (r['record_id'],r['binding_id'],source,r['version'],parent,status,published,received,resolved,digest,canonical))
        self.db.executemany('INSERT INTO resolution_payouts VALUES(?,?,?,?,?)',
            [(r['record_id'],r['binding_id'],o['team_id'],o['asset_id'],payouts[o['asset_id']]) for o in outcomes])

    def raw_response(self,digest):
        row=self.db.execute('SELECT body_gzip FROM result_raw_responses WHERE sha256=?',(digest,)).fetchone()
        if row is None:raise ValueError('Unknown result response hash')
        body=gzip.decompress(row[0])
        if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('Raw result evidence hash mismatch')
        return body
