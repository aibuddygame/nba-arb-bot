# P01 offline foundation — implementation and verification

Historical P01 delivery note; subsequent synthetic adapter work is documented in
[P02 implementation notes](P02-SYNTHETIC-BOOKMAKER.md).

Date: 2026-10-28. Runtime verified: Python 3.14; project minimum remains Python 3.11.
Scope: canonical identities, persistent fixture/schedule/slot foundation, synthetic demo.
No bookmaker or Polymarket adapters, network loop, notifications, live capture or trades.

## Run from the repository root

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder --demo
```

These commands use the Python standard library. They do not need the legacy requirements,
config.yaml or credentials. Tests use temporary synthetic databases. The demo plans a
fictional LAL/BOS fixture, prints 25 UTC slots, and removes its temporary database on exit.
This is not an actual NBA fixture or odds report. Python 3.11 itself was not tested here.

## Implemented schema boundary

Schema version 1 contains teams, games, explicit source-event mappings, schedule revisions,
snapshot slots and append-only slot/game audit events. Identity foreign keys and unique
slot keys are enforced. Schema/application IDs prevent opening an unrelated database as
the planner store. Unsupported schema versions are rejected; no silent migration occurs.

The broader data specification is a target, not a claim that all its entities exist.
Raw responses, quotes, order-book levels, collection attempts/leases, pairings, metrics,
results and injury events remain P02–P05/later work. No dependency on legacy parsers exists.

## Planner behaviour

- All 30 team IDs and reviewed full-name/abbreviation aliases are explicit. Bare cities,
  partial words and unlisted nicknames are rejected. Adapters may add reviewed aliases.
- A game ID is supplied as a durable internal identity. It survives start-time revisions.
  Identity matching requires exact team IDs and the current scheduled UTC instant; reversed
  display orientation is supported. Zero/multiple candidates fail closed. Mapping source
  event IDs requires explicit evidence; conflicting mappings cannot overwrite history.
- Each schedule revision has 25 slots at T−12h, T−11h30m, …, T. UTC arithmetic preserves
  half-hour elapsed intervals across both Eastern DST transitions. Naive and nonexistent
  local times are rejected. Repeated fall-back times use the caller's explicit fold.
- Repeated fixture delivery and reopening the database do not duplicate slots/audit events.
  SQLite write transactions serialize mutations. Failed revision creation rolls back the
  game projection, old slot changes, new revision, new slots and audit records together.
- Slots strictly earlier than observation time, if still unobserved, become missed. They
  are not backfilled. This is offline bookkeeping, not a live lateness/retry policy.
- Rescheduling preserves prior completed/partial/missed records and supersedes outstanding
  future slots. Returning to an older start time still creates a new numbered revision.
- Postponement without a replacement time closes outstanding future slots. Resuming the
  same start time creates a replacement revision. Cancellation cannot be reopened through
  this API. Started/final games cannot be reverted to scheduled by a stale fixture update.
- Authoritative live/final status cancels pending future slots; past unobserved slots are
  missed. A delay alone never extends the 25-slot schedule.
- T0 is a planned boundary slot, not proof of pregame eligibility. Observed game-state
  evidence and quality policy must gate collection/analysis in later milestones.
- record_slot_result is an explicit offline bookkeeping hook for complete/partial states.
  It records the supplied real observation time, rejects premature/missed/terminal rewrites,
  and cannot establish that any provider data was collected. Production completion must
  be tied to attempt/response evidence in P04; this hook is not a collection runner.

## Verified acceptance evidence

29 unittest cases passed: team identity safety; 25 slots and equivalent timezones;
spring/fall DST and fold; naive/nonexistent-time rejection; restart and second connection;
duplicate delivery; late discovery and elapsed gaps; revised/postponed/restored schedules;
cancellations, delays and early start; exact/ambiguous/wrong-date matching; source mapping
constraints; immutable audit/identity fields; result idempotency and missed-slot protection;
foreign/unrecognized schemas; injected mid-revision database failure and retry recovery.

The synthetic demo produced exactly 25 slots, from 2026-10-28T12:00Z to 2026-10-29T00:00Z.
Private raw/, data-private/ and exports-private/ paths are now ignored by Git.

## Remaining work

Next milestone: P02 bookmaker adapter, initially using synthetic fixtures. Select a provider
and confirm book coverage, rights and budget before real collection. P03 handles Polymarket
quotes. P04 adds attempt persistence, leases, bounded retries, quote freshness, T0 eligibility
and the running collector. Decisions on hosting/retention and live activation remain open.
The exposed legacy email credential remains unremediated; no legacy entrypoint was run.

Publication and refreshed handoff manifests record actual commit/status externally to avoid
self-referential commit hashes. Do not treat a local branch as merged into main.
