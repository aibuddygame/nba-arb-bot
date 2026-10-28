# Paired odds research data specification v0.1

Status: proposed schema and semantics, not implemented. Date: 2026-10-28.
Companion: [proposal](RECORDING-ENGINE-PROPOSAL.md).

## Conventions and identities

Use timezone-aware UTC timestamps at full available precision. Keep source precision and
clock uncertainty; UTC receipt time is the research availability cutoff. Store provider
timestamps without implying they measure bookmaker-to-provider latency.
Keep prices/odds in exact decimal text or scaled integers, not binary float as raw truth.
Use explicit nulls with reason codes; zero is not a missing-data marker.
Canonical team IDs distinguish Lakers/Clippers and all city-name collisions.
Map source events to an internal game ID using league, teams, start date/time and fixture
evidence. Venue orientation may differ; map outcomes explicitly rather than assume array order.

## Logical entities

| Entity | Required contents / identity |
| --- | --- |
| games | game_id, season, league, canonical teams, fixture source, lifecycle status |
| source_event_mappings | source, source_event_id, game_id, matching evidence/status, valid interval |
| schedule_revisions | game_id, revision_id, scheduled_start_utc, observed_at, prior revision, reason |
| snapshot_slots | slot_id, game_id, revision_id, slot_index 0…24, planned_at, lifecycle state |
| collection_attempts | attempt_id, slot/source, request start/end/receipt, result, retry number, sanitized error, response reference |
| raw_responses | response_id, source, sanitized endpoint/parameters, receipt_at, SHA256, private file path, schema/content type |
| markets | internal/source market IDs, outcome IDs, game_id, type, period, handicap/total, settlement-rule version/reference |
| bookmaker_quotes | observation_id, attempt/response IDs, book, market/outcome, original odds, odds format, decimal odds, source_updated_at, availability |
| polymarket_quotes | observation_id, attempt/response IDs, market/outcome/asset identifiers, bid/ask and sizes, midpoint, last trade, volume if provided, source timestamp, fee metadata |
| book_levels | observation_id, side, level, exact price and size; saved depth limit and completeness flag |
| pairings | slot, book market/outcome, both observation IDs, matching version, timing/quality flags and eligibility |
| derived_metrics | pairing_id, calculation version, method, per-book fair probability, consensus membership/weights, differences and hypothetical costs |
| game_results | game_id, source, status, scores, observed_at, final_at, correction version |
| market_resolutions | market_id, source, resolved/void/unresolved status, per-outcome payout, observed_at, resolution_at |
| injury_events (later) | game/team/player IDs, old/new status, report publication and first receipt, raw evidence |

A bookmaker source response can contain multiple games. Store it once and link observations
to their actual slots. It does not make all games in the response scheduled observations.

## Slot and retry semantics

Unique logical slot key: (game_id, schedule_revision_id, slot_index).
Unique attempt key: (slot_id, source, retry_number). Multiple observations/market outcomes
belong to an attempt; preserve all attempts. Source-provided observation IDs may supplement
deduplication but must not collapse repeated unchanged quotes from distinct slots.
Persist claims/leases to prevent duplicate workers. A crash after saving a response must be
recoverable without duplicating a logical success. Attempt states include pending, running,
succeeded, failed; slot states include planned, complete, partial, missed, superseded,
cancelled_after_start, cancelled_event. Separate validation flags from lifecycle states.

Do not require a write-once slot-state row: maintain state transitions in an audit trail.
Raw observations and attempt outcomes are immutable; corrections create new records.
A pairing version identifies selected observation IDs deterministically. Prefer the earliest
eligible attempt pair within policy; preserve later retries without rewriting the originals.

## Quality and eligibility

Record these separately for each observation/pair:

- collection_lateness_seconds = receipt_at − planned_at.
- quote_age_seconds = receipt_at − source_updated_at, when source time exists.
- receipt_gap_seconds = absolute difference between paired receipt times.
- Observed game state and its evidence/receipt time.
- Source timestamp missing, stale, unexpected_future_timestamp, suspended, invalid_price,
  incomplete_two_sided_book, ambiguous_game, unmatched_line, rule_mismatch, partial_depth.

Thresholds are configurable and versioned. Starting values are deliberately undecided;
calibrate against observed source refresh intervals and collector timings before live use.
Until a policy is chosen, retain measurements but mark eligibility unassessed.
Separate research_pair_eligible from execution_cost_estimate_eligible. Unknown fee/depth or
rules can block the latter even if a descriptive price comparison is allowed.
A live/unknown-boundary observation never silently enters the pregame sample.
No cross-slot forward fill or nearest future join. Preserve a missing pair with its reason.

## Calculations

For decimal bookmaker odds d, implied probability q = 1/d.
Default proposed de-vig: p_i = q_i / sum(q), using a complete compatible two-outcome book.
Reject malformed odds and flag abnormal overround rather than force a result.
Keep de-vigged probabilities in probability space. Proposed initial consensus: median of
eligible per-book probabilities for a canonical outcome; record book count and dispersion,
and set the complementary outcome to 1−p for this binary consensus. Benchmark is an estimate.
Minimum book count, freshness and weighting remain policy decisions.

Report consensus minus Polymarket midpoint and consensus minus best ask as percentage
points. If midpoint is derived, save how; absent one side, do not invent it.
For C shares, hypothetical cost is sum(price_j × filled_shares_j) + applicable fees.
If saved asks cannot cover C, label insufficient_depth; do not extrapolate the top level.
Expected net payout using estimated p is C×p − cost, conditional on the payout/rules.
That expectation is not guaranteed profit. Fees are evaluated by fill/market policy version.
Do not count rebates as certain income. Record any currency/collateral conversion assumptions.

## Export and privacy

Private raw evidence layout proposal: raw/YYYY/MM/DD/source/response_id.json.gz.
Private normalized store: data-private/odds.sqlite; exports: exports-private/.
These are proposed paths; future implementation must add ignore rules before generating data.
CSV exports use stable columns, UTC ISO8601 strings, schema_version and calculation_version.
Export normalized data only within the provider's permitted use; a public Git repository
holds specifications and synthetic fixtures, not production response bodies or credentials.
Redact authorization headers and API keys from URLs/logs before persistence.
Backups, retention duration and recovery objectives must be selected before live operation.

