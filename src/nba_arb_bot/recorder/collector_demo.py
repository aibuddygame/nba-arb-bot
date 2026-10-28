"""Offline paired replay with an explicit synthetic policy; no background/live IO."""

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile

from .planner import Planner
from .collector import PairedCollector,CollectionPolicy,SyntheticSource


def replay(path,book_body,poly_body):
    at=datetime(2026,10,28,12,tzinfo=timezone.utc)
    start=datetime(2026,10,29,0,tzinfo=timezone.utc)
    policy=CollectionPolicy('synthetic-demo-v1',60,5,120,120,10,2,2,8,1000)
    sources={'bookmaker':SyntheticSource([book_body]),'polymarket':SyntheticSource([poly_body])}
    with Planner(path) as p:
        p.reconcile(game_id='fictional-lal-bos',season='synthetic-season',away='LAL',home='BOS',start=start,observed_at=at)
        PairedCollector.install(p);c=PairedCollector(p)
        c.polymarket.bind_market(binding_id='synthetic-binding',game_id='fictional-lal-bos',event_id='fictional-lal-bos',
            market_id='synthetic-moneyline-1',condition_id='synthetic-condition-1',
            assets_by_team={'LAL':'synthetic-asset-lal','BOS':'synthetic-asset-bos'},
            rules_ref='synthetic-including-overtime-v1',observed_at=at,evidence='explicit synthetic demo binding')
        c.register(game_id='fictional-lal-bos',bookmaker_event_id='fictional-lal-bos',binding_id='synthetic-binding',
                   expected_books=('synthetic-a','synthetic-b','synthetic-c','synthetic-d'),policy=policy,observed_at=at)
        c.run_once(worker_id='synthetic-demo',clock=lambda:at,sources=sources)
    # Reopen the same durable file to demonstrate resuming the other source only.
    with Planner(path) as p:
        c=PairedCollector(p)
        c.run_once(worker_id='synthetic-demo-resumed',clock=lambda:at,sources=sources)
        slot=p.slots('fictional-lal-bos')[0]
        return {'synthetic':True,'live_collection':'disabled; concrete local sources only',
                'slot_state':slot['state'],'registered_slots':p.db.execute('SELECT COUNT(*) FROM collector_slots').fetchone()[0],
                'registered_jobs':p.db.execute('SELECT COUNT(*) FROM collector_jobs').fetchone()[0],
                'pair_count':len(c.pairs(slot['slot_id'])),
                'eligible_pairs':sum(r['research_eligible'] for r in c.pairs(slot['slot_id'])),
                'usage':[dict(r) for r in c.usage()],
                'source_calls_this_run':{k:v.calls for k,v in sources.items()},
                'note':'Fixture intentionally includes missing/suspended books; partial is expected.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bookmaker-fixture',type=Path,required=True)
    parser.add_argument('--polymarket-fixture',type=Path,required=True)
    parser.add_argument('--database',type=Path,help='Optional synthetic database; prefer ignored data-private/')
    args=parser.parse_args()
    book,poly=args.bookmaker_fixture.read_bytes(),args.polymarket_fixture.read_bytes()
    if args.database is not None:
        args.database.parent.mkdir(parents=True,exist_ok=True)
        result=replay(args.database,book,poly)
        result['database']='persistent synthetic file; rerun is idempotent'
    else:
        with tempfile.TemporaryDirectory(prefix='nba-p04-demo-') as directory:
            result=replay(Path(directory)/'synthetic.sqlite',book,poly)
        result['database']='temporary; removed on exit'
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
