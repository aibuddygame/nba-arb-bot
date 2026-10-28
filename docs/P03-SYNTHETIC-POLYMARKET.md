# P03 synthetic Polymarket adapter — implementation and evidence

Date: 2026-10-28. Implemented offline; no live API, WebSocket, credentials or collection.
Branch is based on P02 commit e8806ce (draft PR #2); P01/P02 dependencies remain unmerged
unless their PRs are subsequently merged. This is a synthetic contract, not an assertion
of compatibility with Polymarket's current API payloads or fee schedule.

## Run from the repository root

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.polymarket_demo \
  --fixture tests/fixtures/polymarket-synthetic.json \
  --received-at 2026-10-28T12:00:00Z \
  --max-quote-age-seconds 120
```

The demo has a separately defined fictional reference fixture and explicit market/outcome
mapping. It reads the supplied local file, uses a temporary database, prints two outcome
quotes and eight depth levels, then removes the database. The 120-second policy is a test
choice, not a selected live threshold. It neither completes a recording slot nor initiates
the legacy scraper/email paths. No packages or keys are required beyond standard Python.

## Source and mapping contract

Envelope: schema=synthetic-polymarket-v1, synthetic=true, kind=full_snapshot,
status=ok/source_error, events list, and optional safe source error code. Deltas, malformed
JSON, duplicate object keys and non-synthetic envelopes are rejected before raw persistence.

Each event supplies event_id, teams, scheduled start, status and markets. Each market has
explicit market_id, condition_id, type/period, status, rules_ref, optional fees and outcomes.
Each outcome supplies asset_id, canonical team/full alias, updated_at, bids/asks, optional
depth_complete and last_trade. Public outcome identifiers are called asset_id in this
synthetic contract; no authentication token is required or accepted. Extra unsupported
markets are retained in raw evidence, not automatically selected or compared.

bind_market explicitly pins a game, source event, market, condition and two distinct assets
to canonical teams, with observation time and review evidence. It also records the reviewed
source-event binding in P01. Existing conflicting mappings, wrong teams, reused market/
condition/assets and later silent overwrites are rejected atomically. New correction flows
must preserve this immutable evidence; the adapter does not guess corrected mappings.

Ingest requires explicit binding-to-slot assignments. Validate slot game, latest revision,
planned state and receipt/binding times before saving a capture. Within the response, match
teams and scheduled instant, then exactly the pinned market/condition/asset IDs. Reversed
display orientation and shuffled outcomes are safe; wrong game/date, swapped labels or
wrong assets are quarantined. Duplicate event/market/condition/asset IDs reject the capture.
There is no “first market” or outcome-array-order fallback.

## Stored data and depth semantics

An explicit PolymarketArchive.install(planner) adds component version 1, independently
of the optional P02 extension. Core user_version remains 1. Opening never silently installs
or upgrades it. This delivery extended only temporary test/demo databases.

Tables hold immutable bindings/outcomes, gzip raw bytes keyed by SHA256, captures, market
observations, per-team quotes and ordered book levels. Request start/end, receipt time,
source timestamps, selected slot bindings, quote-age policy and depth limit are retained.
Same capture ID is idempotent only with identical evidence/policy; unchanged raw bytes at
a different receipt remain distinct observations. Multi-game responses are stored once;
only explicitly selected slots receive normalized rows. Raw reads verify the original hash.

Validate every supplied level, then sort bids descending and asks ascending. Prices/sizes
are decimal strings; prices must be strictly between 0 and 1 and sizes positive. Invalid
or duplicate numeric prices reject the entire affected side, even beyond the saved depth
limit. Save a configurable 1–100 levels per side and flag truncation. Source-declared partial
or unknown depth remains distinct from complete depth; it never implies unlimited liquidity.

Save best bid/ask prices and sizes, a derived midpoint only for an uncrossed two-sided book,
and last-trade price/time separately. Display prices are raw-only. Missing asks, one-sided
or empty books cannot borrow from midpoint/display/last-trade data. Crossed/locked books
are ineligible; no bid/ask probabilities are renormalized to sum to one.

## Fee, rule and quality handling

Rule references must match the explicit binding; mismatch blocks research screening and
unknown rules leave it unassessed. Fee JSON is retained as received. Only the synthetic
model synthetic-parabolic-v1, a decimal rate in [0,1], synthetic-usdc currency and a valid
nonfuture metadata timestamp count as recognized fee metadata. Zero is explicitly known;
missing, unsupported or invalid fees do not become a zero fee. No fee or trade-cost
calculation is implemented, and these fixtures do not establish actual Polymarket fees.

Per-outcome flags distinguish source failure, missing event/market/outcome, unsupported
market, identity mismatch, suspended/closed/resolved status, invalid/empty/crossed books,
partial/truncated/unknown depth, stale/future/missing quote times, and unknown policies.
Positive collection lateness remains unassessed. Boundary/after-tip-off and unconfirmed/live
game status are excluded from pregame screening. No future quote or historical gap is filled.

research_eligible is a local screening field: false with blocking issues, null with unknown
freshness/lateness/rules, true only for the checks implemented here. cost_metadata_complete
additionally requires recognized fees, known rules and complete valid saved depth. Neither
field is paired-market eligibility, actual fillability, an execution guarantee or authorization
to trade. P04/P05 must assess pairing, game-state freshness and hypothetical stake coverage.

Shared pure capture/identity/time/credential-field guards moved to synthetic.py. P02's
existing imports remain compatible and its tests still pass. The guard rejects credential/
transport keys before raw persistence; it is not a general secret scanner. Use only the
explicit synthetic fixtures, never credentials or production bodies.

## Verified acceptance and limits

100 standard-library unittest cases passed on Python 3.14: 36 P03 plus 64 retained P01/P02.
P03 adapter tests block socket creation. Tests cover exact mappings, shuffled identities,
depth validation/truncation, missing/empty/crossed books, stale/invalid times, fee/rule states,
source failures, multi-game snapshots, replay/restart, immutable evidence, schema guards,
hash corruption and injected transactional rollback/retry. Demo: two quotes/eight levels.
The declared Python 3.11 minimum has not been separately exercised.

No live endpoint, SDK/REST/WebSocket contract, actual market discovery, fee/rule accuracy,
latency, provider access or live capture completeness was verified. There is no pairing
engine, job loop, attempt lease, retry transport, results pipeline or trading. Live collection
remains disabled. P04 is the next milestone; it should first integrate these offline
adapters with persistent paired scheduling using synthetic sources and explicit policies.
