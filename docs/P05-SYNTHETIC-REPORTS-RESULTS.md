# P05 daily reports, CSV exports and results — synthetic implementation

Date: 2026-10-28. Implemented offline, using the P04 synthetic collector and temporary
databases. Live collection remains disabled. No network transport, background service,
legacy report/email entrypoint, paid plan or trading was activated.

This milestone is based on P04 commit e75ec446b2caaa0f9f807f9bb4f5def6a8fced60.
Draft PR #4 remains unmerged at publication preparation; P05 targets that branch. Earlier
milestone notes are historical checkpoints; this document describes the new reporting layer.

## Delivered scope

- Read-only daily reports with an explicit local date, timezone and knowledge cutoff.
- Planned-slot coverage, receipt-day activity, source attempts, synthetic reservations,
  per-book missingness, quality flags and versioned probability differences.
- Separate immutable game-score and Polymarket-resolution archives, with raw hashes,
  publication/receipt times, correction chains, unresolved/disputed/void states and payouts.
- A reproducible Markdown/JSON/CSV bundle with hashes, stable versioned columns and
  protection against overwriting an existing destination or spreadsheet formula text.

P05 is a report builder invoked on demand. Automatically running it each day, distributing
reports, live results ingestion and live provider schemas remain future work.

## Daily grouping and historical knowledge

The default timezone is Asia/Singapore; storage/export timestamps remain aware UTC.
Day boundaries use local midnights, including 23/25-hour daylight-saving days when a
different timezone is selected. An explicit as_of is required; there is no implicit now.

The planned cohort contains slots whose planned time falls on the selected local date.
Its active denominator uses the latest schedule revision known by as_of. Older revisions
remain in slots.csv and their observations remain available. Slot state comes from audit
events known by the cutoff, not the current mutable projection. Unprocessed planned slots
are identified as not_due, due_unfinalized or overdue_unfinalized; report generation never
turns them into missed observations or dispatches a collector.

Receipt-day pair activity uses the later of the selected two receipt times, or finalization
time when neither source was captured. Only pairs finalized by as_of appear. A pair received
after midnight retains its earlier planned date while appearing in the next activity day.
Attempt activity uses the known result's receipt/record time; before that record is known,
it appears on its claim day as running_or_unknown. This is an as-of activity view, not a
count of confirmed vendor requests. Reservations are grouped separately by reservation date.

Per-book planned_outcomes is two outcomes per current registered moneyline slot.
planned_paired_outcomes = planned_eligible_outcomes + planned_ineligible_outcomes;
planned_without_pair_outcomes includes future, pending and unprocessed slots, rather than
claiming all are failures. pair_rows/eligible_rows/available_bookmaker_rows describe the
receipt-day activity, whose denominator may differ. Slot-state/phase counts explain the
planned cohort. Counts cover known fixtures and configured/discovered books only.

## Versioned scores and resolutions

ResultsArchive.install(planner) explicitly installs results component version 1, requiring
the existing Polymarket extension. It refuses active transactions and unsupported versions.
It does not automatically migrate a production database or install a live feed.

Synthetic envelopes use schema synthetic-results-v1 or synthetic-resolutions-v1,
synthetic=true and records. See tests/fixtures/results-synthetic.json and
tests/fixtures/resolutions-synthetic.json. These are invented contracts, not vendor payloads.
Import through ingest_results/ingest_resolutions with a required aware received_at.

Game records must match the canonical away/home teams and latest known scheduled start.
Final NBA scores are nonnegative integers and cannot tie; final_at must follow scheduled
start and precede publication. Pending/postponed/cancelled/void scores remain null;
in_progress can retain real zero scores. A score does not assert a market payout.

Resolution records must match the pinned event, market, condition and exact outcome assets.
Unresolved/disputed payouts are null. Resolved synthetic binary payouts are 0/1 summing to
one; synthetic void examples support fractional payouts summing to one. That convention is
not a claim about actual Polymarket void/refund rules. Live semantics must be verified later.

Each correction increments version by one and names the previous record ID. Backward
publication/receipt chronology and changed content under an existing record ID are rejected.
Repeated identical records retain their first receipt. Scores, resolutions, payouts and raw
gzip evidence are immutable; a batch, raw archive and its correction rows commit atomically.
Queries choose versions received by as_of, retaining every known version in history CSVs.
Final score and resolution can disagree; pairs flag disagreements instead of overwriting either.
Score/resolution labels are known at report cutoff, never presented as known at quote receipt.

## Comparisons and exports

Calculation version per-book-proportional-v1 uses q=1/decimal_odds and p=q/sum(q) for a
complete eligible two-sided book. It calculates (p-midpoint)*100 and (p-ask)*100 in percentage
points, with Decimal precision 28. Ineligible comparisons remain null even when source
prices exist. There is no cross-slot carry-forward, book consensus, fill simulation,
P&L, ROI, backtest or claim of arbitrage. Cost metadata completeness remains a separate flag.

Every pair row references original captures, raw hashes, schedule revision, binding,
policy/pairing/calculation versions, availability, source/receipt times, ages, lateness,
rules, synthetic fees, depth completeness, original odds and selected score/payout versions.

The bundle has report.md, summary.json, slots.csv, pairs.csv, attempts.csv, results.csv,
result_history.csv, resolutions.csv, resolution_history.csv and manifest.json. CSVs carry
schema_version/report_version/calculation_version. Nulls use empty cells with status fields;
zero remains zero. Text starting with spreadsheet formula prefixes is apostrophe-escaped;
numeric columns retain negative numbers as numeric text. IDs/times are stable within a
retained database; independent replays may create different attempt/capture IDs.

The destination must be new. The completion manifest is written last, hashes the other
nine files and excludes itself. Validate both its JSON and hashes before consuming a bundle;
a crash can leave an incomplete directory. Ordinary failures remove files created by that
export. Raw payloads and private databases are excluded from exports and Git.

## Reproduce offline

Run from the canonical repository root; no legacy dependencies/configuration are needed:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.reporting_demo \
  --bookmaker-fixture tests/fixtures/bookmaker-synthetic.json \
  --polymarket-fixture tests/fixtures/polymarket-synthetic.json \
  --results-fixture tests/fixtures/results-synthetic.json \
  --resolutions-fixture tests/fixtures/resolutions-synthetic.json \
  --output exports-private/p05-synthetic-demo
```

The demo uses a temporary database and exports eight pair rows, two eligible, with a final
fictional score and separate synthetic payout. Its Oct 28 Singapore planned cohort has eight
slots: one partial and seven overdue/unfinalized. Oct 29 has the remaining seventeen slots.
The demo intentionally reuses just the first P04 slot; it does not simulate full-day coverage.
Use a new output directory on rerun.

For an existing recorder database with the results extension explicitly installed:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.reporting \
  --database data-private/p04-synthetic.sqlite --day 2026-10-28 \
  --as-of 2026-10-29T06:00:00Z --timezone Asia/Singapore \
  --output exports-private/p05-existing-database
```

That CLI opens SQLite mode=ro: it does not create a missing database, install schema or
ingest results. An unextended P04 database requires an explicit ResultsArchive.install first.

## Acceptance evidence and limits

183 standard-library unittest cases passed on Python 3.14: 39 P05 + 144 retained P01–P04.
P05 tests block socket creation. They cover correction/idempotency/restart, wrong fixture or
asset, chronology, null/zero/void/disputed states, immutable evidence, raw hashes, atomic
batch/insert rollback, extension guards, historical slot/attempt/result views, schedule
revisions, midnight/DST grouping, partial/missed coverage, no fabricated quotes, per-book
calculations, read-only database access, deterministic bundles, formula text, null columns,
hashes, overwrite refusal and failed-export cleanup. Test-only SQLite handles in one retained
P01 schema-guard test were explicitly closed to avoid Python 3.14 resource warnings.

No production database was migrated. Python 3.11 runtime compatibility remains unverified.
Live source identities, access/rights, fees/rules, timing, quotas, provider choice, deployment,
retention/backups and the exposed legacy credential's revocation remain unresolved.
P06 exact-line spreads/totals is the next proposed milestone; P07 live activation and P08
chronological, game-aware research are separate work. A local reference pack does not prove
installation into a separate ChatGPT Project. GitHub remains canonical.
