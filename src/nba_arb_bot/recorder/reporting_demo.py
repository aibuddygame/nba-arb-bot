"""Generate a synthetic P05 report bundle; never fetches data or sends notifications."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from .collector_demo import replay
from .planner import Planner
from .reporting import DailyReporter, export_bundle
from .results import ResultsArchive


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bookmaker','polymarket','results','resolutions'):
        parser.add_argument('--'+name+'-fixture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='New directory; prefer exports-private/')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nba-p05-demo-') as folder:
        path=Path(folder)/'synthetic.sqlite'
        replay(path,args.bookmaker_fixture.read_bytes(),args.polymarket_fixture.read_bytes())
        with Planner(path) as p:
            ResultsArchive.install(p);archive=ResultsArchive(p)
            archive.ingest_results(args.results_fixture.read_bytes(),received_at=datetime(2026,10,29,4,tzinfo=timezone.utc))
            archive.ingest_resolutions(args.resolutions_fixture.read_bytes(),received_at=datetime(2026,10,29,5,tzinfo=timezone.utc))
            report=DailyReporter(p).build(day='2026-10-28',as_of=datetime(2026,10,29,6,tzinfo=timezone.utc))
            manifest=export_bundle(report,args.output)
    print(json.dumps({'output':str(args.output.resolve()),'synthetic':True,'live_collection':'disabled',
                      'pair_rows':report.summary['pair_rows'],'eligible_pair_rows':report.summary['eligible_pair_rows'],
                      'export_files':len(manifest['files_sha256'])+1},indent=2))


if __name__=='__main__':main()
