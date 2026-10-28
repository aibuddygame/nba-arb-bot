# Roadmap, decisions and progress

Baseline: v0.1, 2026-10-28 (Asia/Singapore).
Legacy source reviewed: 67c69d29cacf99d518d9f342cf5542e754ceeb05.
Status vocabulary: proposed / prepared / verified / implemented / live / deferred.
A published plan is not an implemented or deployed engine.

## Milestones

| ID | Deliverable | Acceptance evidence | Current state |
| --- | --- | --- | --- |
| P00 | Planning baseline and Project handoff | GitHub files fetched back and compared; local matching pack with commit/hash manifest | Verified: baseline de4c156 and matching local pack; Work source-folder path verified 2026-10-28 |
| P01 | Offline schema foundation, canonical IDs and slot planner | 29 offline tests passed; 25-slot synthetic demo; [evidence and limits](P01-OFFLINE-PLANNER.md) | Implemented and verified offline; publication/merge tracked separately |
| P02 | Synthetic bookmaker adapter | 35 P02 tests + 29 P01 tests passed; [scope/evidence](P02-SYNTHETIC-BOOKMAKER.md) | Implemented and verified offline; real provider integration remains unresolved |
| P03 | Synthetic Polymarket adapter and explicit moneyline mapping | 36 P03 + 64 retained tests passed; [scope/evidence](P03-SYNTHETIC-POLYMARKET.md) | Implemented and verified offline; live API contract/transport remain pending |
| P04 | Persistent collector and paired moneyline snapshots | Retry/crash recovery, real timing, freshness flags, no fabricated backfills, quota accounting | Not started |
| P05 | Daily report, CSV and results | Traceable differences, expected/completed/missing counts, source coverage, results/resolutions/corrections | Not started |
| P06 | Exact-line spreads and totals | Signed line/period/rule matching, push handling, unpaired-line reporting | Proposed follow-on |
| P07 | Bounded live pilot | Selected provider/access/budget/host; credential remediation; measured timing and data-quality report; private backup/restore proof | Not started; requires live activation decision |
| P08 | Forward research | Versioned methods, chronological game splits, coverage bias, game-clustered uncertainty, cost-aware paper evaluation | Not started |

The owner authorized P01 development on 2026-10-28 after the Work project source-folder
change. The app now reports /Users/barrylau/Documents/GitHub/nba-arb-bot. P01 is implemented
and verified offline. The owner subsequently authorized P02 with synthetic data only; it is
implemented and tested offline. P03 was subsequently authorized with synthetic data only
and is verified offline. Provider/hosting decisions remain open; live collection is disabled.

## Decision register

| ID | Decision | State / reason |
| --- | --- | --- |
| D01 | Cover every NBA game, T−12h, 30-minute cadence | Owner requested |
| D02 | Preserve each bookmaker's odds and matching Polymarket data | Owner requested |
| D03 | Include T0; 25 slots, with game-state qualification | Proposed |
| D04 | Moneyline first; spreads/totals through exact-line matching | Proposed staging, not a waiver of broader requested coverage |
| D05 | Python + SQLite + compressed private raw evidence | Proposed |
| D06 | Bookmaker provider, named book universe, storage rights and API budget | Unresolved |
| D07 | Runtime host, operating window, backups and retention | Unresolved |
| D08 | Freshness/lateness/pairing tolerances and consensus minimum book count | Unresolved; select and version before live pilot |
| D09 | Main lines first; alternate/prop/period/live coverage | Proposed limits; confirm first live release scope |
| D10 | GitHub canonical; Project copies versioned by commit/hash | Planning workflow selected |
| D11 | No betting/trading in recording scope | Baseline scope |
| D12 | P02 synthetic raw evidence stored as gzip blobs inside SQLite for atomic persistence | Implemented offline; production raw-file/blob-store choice remains open |

## Known risks and prerequisites

- Existing public legacy config contains an apparent email app credential. Owner revocation
  is unverified. Do not reproduce/test it. Sanitize legacy configuration in a separately
  authorized change; history removal is a separate decision. Documentation publication
  itself neither uses the credential nor remediates the old exposure.
- Legacy report export may send email; dry_run does not guard that side effect.
- Provider snapshots can already be delayed; receipt simultaneity does not prove source
  simultaneity or an executable opportunity.
- Book/market coverage can change. Publish coverage denominators and missingness.
- New-season injury source and result ingestion require implementation and verification.
- No current result archive in this repository establishes the prototype's performance.

## Evidence log

2026-10-28: read-only prototype review at the legacy commit; all 10 Python modules reviewed.
Offline Python AST parsing succeeded for 10 modules. Targeted probes reproduced wrong-team
matching, combined-token spread misparse, historical opener as best odds, and false no-change
injury message after simulated HTTP failure. Probability doc examples: 89 attempted,
13 failed; not all failures indicate formula defects. These were focused checks with
external dependencies stubbed where needed, not a full installed application test.

2026-10-28: planning documents prepared for GitHub publication and a matching Project handoff.
The delivery manifest records the actual published commit and verification outcome.
Project upload, Project instruction installation, engine implementation and live capture
remain unverified/not started. Update this log after subsequent evidence, not expectations.


## P01 evidence update — 2026-10-28

Work Project source-folder path and clean GitHub checkout verified before development.
P01 adds a standard-library SQLite foundation, explicit identities for 30 teams, exact fixture
matching, source-event bindings, revision history, immutable audits and 25-slot UTC planning.
29 synthetic unittest cases passed under Python 3.14, including injected transaction failure
and retry recovery. Demo returned 25 slots. No legacy entrypoint, network feed, notification,
paid plan or live capture ran. The full quote/attempt/analysis schema remains later work.
See [P01 implementation notes](P01-OFFLINE-PLANNER.md). P02–P08 are not implemented.
The baseline Project upload pack remains a historical snapshot; the P01 handoff records its
own commit/hash provenance. Public credential revocation remains unverified.

## P02 evidence update — 2026-10-28

Synthetic-only bookmaker contract and archive implemented on top of P01. All 64 standard-
library unittest cases passed (35 P02 + 29 P01) under Python 3.14. P02 tests block socket
creation. Replay demo returned 8 book/market records and 16 outcome records, including missing
placeholders, for two fictional fixtures. No recording slot is completed automatically.
An explicit optional schema extension archives gzip raw bytes with SHA256 and preserves
per-book source odds, request/receipt/source times, missing/suspended states and quality flags.
Install/ingest rollback, restart and idempotency checks passed. No production database was
migrated. P01 remains a dependency until its draft PR is merged. P03–P08 are unimplemented.
A real bookmaker provider contract/transport, access, rights and budget remain unresolved.
See [P02 notes](P02-SYNTHETIC-BOOKMAKER.md). Live collection/notifications remain disabled.

## P03 evidence update — 2026-10-28

Synthetic Polymarket full-snapshot archive with explicit reviewed event/market/condition/asset
bindings is implemented on top of P02. All 100 unittest cases passed under Python 3.14:
36 P03 and 64 retained P01/P02. P03 adapter tests block socket creation. Demo returned two
outcome quotes and eight ordered depth levels. Missing, crossed, stale, suspended and
misidentified data do not become eligible observations. Fees/rules are preserved/validated
against synthetic metadata only; no real fee schedule or API payload was verified.
Schema extension is explicit; temporary synthetic databases only. Evidence, bindings and
levels are immutable and insert-failure rollback/retry was tested. P02 now shares pure
capture guards from synthetic.py without changing its interface. P01/P02 PRs remain stack
dependencies until merged. P04–P08 remain unimplemented; live collection is disabled.
See [P03 notes](P03-SYNTHETIC-POLYMARKET.md). Known legacy credential revocation is unverified.
