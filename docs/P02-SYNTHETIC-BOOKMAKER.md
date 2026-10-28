# P02 synthetic bookmaker adapter — implementation and evidence

Date: 2026-10-28. Scope: local synthetic full-game moneyline parsing and archival.
Status: implemented and tested offline. No live bookmaker/provider integration exists.
Depends on P01 (commit 8106c09; draft PR #1 until merged).

## Run the checks and replay demo

From the repository root, using only Python's standard library:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.bookmaker_demo \
  --fixture tests/fixtures/bookmaker-synthetic.json \
  --received-at 2026-10-28T12:00:00Z \
  --expected-books synthetic-a synthetic-b synthetic-c synthetic-d \
  --max-quote-age-seconds 120
```

The demo reads an explicitly synthetic file, creates fictional fixtures in a temporary
database, ingests one response against two selected slots, prints a summary, and removes
the database on exit. It yields 8 book/market rows and 16 outcome rows, including explicit
missing placeholders. These are not 16 available quotes or actual games.
The 120-second freshness limit is a demo/test choice, not an approved production policy.
All 64 tests pass: 29 retained P01 cases plus 35 P02 cases. Verified on Python 3.14;
the declared Python 3.11 minimum has not been separately exercised.

## Synthetic contract and actual implemented coverage

The adapter accepts local bytes with schema=synthetic-bookmaker-v1, synthetic=true,
status=ok/source_error and an events list. It does not claim compatibility with any
commercial API. No provider has been selected, queried, authenticated or purchased.
There is no HTTP client, live mode flag, live-fetch method, background task or email path.

Each event has event_id, away, home, starts_at, status and bookmakers. Each book has a
stable book_id, explicit open/suspended status and markets. The moneyline market requires
type=moneyline, period=full_game, status, updated_at, odds_format and outcomes. rules_ref
may be null/unknown; it is not inferred. Each outcome names a canonical team/full alias
and provides its price as a string. See the committed synthetic fixture for the exact shape.

American odds require integer text with magnitude >=100; decimal odds require finite
text >1. Native floats/bools, missing prices, invalid odds and unsupported formats are
not silently coerced. Original values and exact raw bytes remain available. Decimal text
and implied probabilities use precision 28; no consensus or signal calculation is added.
Spreads, totals, props and alternate markets remain raw-only and are not mislabeled as
moneylines. Normalized spread/total comparisons remain P06.

## Explicit schema installation and provenance

BookmakerArchive.install(planner) is an explicit, additive, transactional extension.
Opening Planner or BookmakerArchive does not silently install/upgrade it. Core schema
user_version remains 1; bookmaker_component version 1 is independently checked. Existing
P01 fixture, slot, revision and audit rows remain intact. Unknown extension versions fail.
Only temporary test/demo databases have been extended in this delivery.

The extension adds bookmaker_raw_responses, bookmaker_captures, bookmaker_markets and
bookmaker_quotes. Raw bytes are SHA256-addressed and gzip-compressed inside SQLite so
raw/normalized evidence commits atomically. This is a P02 storage choice rather than the
proposed external raw-file layout; future production storage may use a separate blob store.
Reading raw evidence decompresses and verifies its hash. Records cannot be updated/deleted
through normal SQL; corrections/new receipts create new captures.

Each capture stores a caller-supplied unique capture ID, adapter/source version, response
hash, request start/end, receipt time, explicit event-to-slot bindings, expected-book set,
freshness policy and source-error status/code. Same ID with changed evidence is rejected.
Same response bytes at a new receipt time remain distinct observations; only the raw body
is deduplicated. A source response containing other games is saved once, but only explicitly
bound slots receive normalized observations. No slot is marked complete by this adapter.
Collection attempts, leases, retries and completion orchestration remain P04.

## Matching and quality rules

- Supplied slots must exist, be planned, belong to the current revision, and not be in the
  future relative to receipt. Missed/terminal/superseded slots cannot be backfilled.
- Event teams and scheduled start must match the selected game exactly. Reversed display
  orientation is allowed; another LA team/date or conflicting existing source mapping is
  quarantined as identity_mismatch. No implicit source-event binding is installed.
- Book IDs, not list positions, control attribution. All returned books are preserved and
  expected-but-absent books get explicit missing states. Both expected team rows exist;
  absent prices remain null, with a reason, rather than being copied from another book.
- Source errors, event_missing, book_missing, market_missing, suspended, unknown_status,
  partial and invalid_price remain distinguishable. Structural ambiguity (duplicate JSON,
  event, book or market keys) rejects the capture atomically. Duplicate/unknown outcomes
  flag the affected market rather than allowing an eligible two-sided benchmark.
- Store source timestamps, exact quote age and collection lateness separately. Missing or
  future source times, stale odds, incomplete books and underrounds are flagged. Large
  overround cutoffs are still undecided; values are not automatically declared trustworthy.
- benchmark_eligible is a local screening field: false for blocking issues, null for unset
  freshness policy or unassessed positive lateness, and true only when the implemented
  checks pass. It is not paired-market eligibility, proof of correct odds, or permission
  to trade. Unknown rules are flagged and cannot establish execution compatibility.
- Boundary/after-tip-off or unconfirmed/live source game status cannot be eligible as
  pregame evidence. P04 must add authoritative game-state freshness and lateness policy.

Malformed/non-synthetic envelopes and credential/transport-key-bearing JSON are rejected
before raw persistence. Errors use safe codes without body/value echoes. This guard is not
a general secret scanner: never submit real provider bodies or credentials. HTTP URLs,
headers and credential handling belong to a later explicitly authorized provider integration.

## Verification and remaining scope

P02 tests block socket creation. Cases cover shuffled and missing books/outcomes; suspended
and invalid odds; timestamps and unassessed policies; source failures; wrong game/date and
mapping conflicts; duplicate/replayed captures; shared bodies across multiple games/receipts;
restart persistence; immutable evidence; raw hash corruption; explicit extension version/
installation guards; injected insert failures with full rollback/retry; and the local demo.
All retained P01 tests pass. No live odds, endpoint access, source latency, bookmaker coverage,
subscription rights, actual API quota or real capture completeness has been verified.

Next planned milestone is P03 (Polymarket adapter). A selected bookmaker API will still need
its own documented contract/transport implementation, account/rights/budget decisions and
live validation before P07. This synthetic milestone does not waive those gates.
