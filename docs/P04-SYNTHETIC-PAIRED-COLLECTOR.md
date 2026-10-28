# P04 persistent paired scheduler — synthetic implementation

Date: 2026-10-28. Implemented offline on P03 commit 46123c2 (draft PR #3 dependency).
Live collection remains disabled. There is no REST/WebSocket transport or installed daemon.

## Run and inspect

From the repository root, using Python's standard library:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.collector_demo \
  --bookmaker-fixture tests/fixtures/bookmaker-synthetic.json \
  --polymarket-fixture tests/fixtures/polymarket-synthetic.json
```

The default demo uses a temporary database. To retain and rerun a synthetic database,
add --database data-private/p04-synthetic.sqlite. The demo closes/reopens the file after
the first source to demonstrate restart recovery. Rerunning the retained database does
not refetch a terminal slot or reset its usage/evidence. Do not use a production database.

Expected demo: 25 registered slots, 50 source jobs, 8 pair rows, 2 research-eligible rows,
one synthetic unit per source, and a partial first slot. Missing/suspended/partial books in
the fixture deliberately prevent complete coverage. These are fictional fixture observations.
Demo timestamps are simulated inputs, not live historical captures.

## Explicit configuration, installation and driving

PairedCollector.install(planner) explicitly installs both source archive extensions and
collector component version 1. Opening never installs/upgrades it. Installation is refused
inside an existing transaction. Each component installs atomically; if the collector schema
fails after adapter installation, adapter components remain installed and retry is explicit.
Core schema user_version stays 1. Only temporary test/demo databases were changed here.

CollectionPolicy has no implicit live profile. It requires an immutable ID and explicit
maximum lateness, receipt gap, quote age, game-state age, lease duration, attempt limit,
base/capped retry delays, per-source synthetic call budget, and saved depth limit.
The demo profile is illustrative and is not an approved production policy.

register pins the current revision's 25 slots to one bookmaker event, one reviewed
Polymarket binding, a named bookmaker universe and that policy. It creates two persistent
source jobs per slot. Repeated registration is idempotent; conflicting configuration fails.
After a schedule revision, explicitly register the new revision. Obsolete jobs are cancelled
by maintenance while prior responses/attempts remain intact.

Use reconcile_fixture(policy=..., ...) for fixture/status refreshes during P04 operation.
It opts into that policy's lateness grace. Direct Planner.reconcile retains its strict
zero-grace P01 default. A status refresh cannot revive missed data or reopen a terminal slot.
Grace allows genuinely late observations within the chosen window, with real times retained;
it does not manufacture on-time historical data or copy a previous slot's quote.

run_once performs one bounded tick: maintain due/invalidated jobs, claim at most one source,
read a concrete local SyntheticSource, timestamp the request/receipt via the supplied clock,
archive it through P02/P03, and update its job/pairing. It neither sleeps nor polls forever.
The caller drives subsequent ticks; a host scheduler/service and live transports are later
deployment work. Only exact SyntheticSource objects holding bytes/fixed safe failures are
accepted; arbitrary fetch callbacks/URLs/live source objects are refused.

## Persistence, leases and failure recovery

Tables: collector_policies, collector_slots, collector_jobs, collector_attempts,
collector_quota, collector_attempt_results, collector_job_events and collector_pairs.
Policies/configuration, claims, results, usage reservations, audits and pair rows are immutable.
Job/slot states are mutable projections with append-only transition evidence.

Claims use SQLite write transactions, a unique attempt identity, worker identity and fixed
lease expiry. Two connections cannot own the same source job. Expired workers are fenced
before response persistence; an unknown/lost request is conservatively charged and retried
under a new attempt after bounded exponential backoff. Successful sides are retained across
restart and only unfinished sides are dispatched. Finished attempt replay is idempotent
only with matching capture identity, request times and response hash.

P01 transactions now support nested savepoints. Source archival, attempt result, job update,
pair rows and final slot transition commit atomically under a lease check. An injected
pair-insert failure rolls back that source's archive/result as well; a previously committed
other-source response remains. Retry within the lease can finish the same response safely.
Database errors surface to the caller rather than being disguised as source timeouts.

Transport failures, source-error envelopes and parse failures are distinct. Source-error
bodies are archived; malformed/credential-field-bearing bodies are rejected by adapters,
with only safe error codes and a response hash in the attempt result. Raw values are not
echoed. If a fixture becomes invalid during a request, discard its normalized observation
and retain actual request/receipt times and the response hash in the invalidation result.
Stale-lease responses cannot overwrite the attempt that superseded them.

Retries apply to source/parse failures, not to every stale/suspended bookmaker quote.
Partial source payloads are successful captures with quality flags; their slot can be partial.
At deadline, stop outstanding jobs and finalize available evidence. With no successful
source, mark missed; with incomplete/ineligible pairs, mark partial; only complete eligible
book/outcome coverage is complete. Collection success is separate from price quality.

## Pairing and timing rules

Version synthetic-pairing-v1 records policy ID, slot/book/team, exact capture references,
Polymarket binding, receipt gap, blocking reasons and finalization time. Choose each source's
earliest successful attempt for this slot; source-error attempts are not candidate quotes.
No cross-slot/nearest-future joins or silent forward fills are allowed. All expected and
additionally returned books remain visible. Missing sources produce explicit null references.
Already missed/superseded/cancelled slots retain their P01 state and cancelled job evidence.

Research screening requires compatible source identities, available two-sided bookmaker
odds, valid Polymarket midpoint, matched nonempty rule references, fresh source/game-state
times, receipts inside the slot's lateness window, and a receipt gap within policy. The P04
policy assesses P02/P03's previously unassessed timing flags without rewriting those rows.
Unknown fees/partial depth can still allow descriptive research; cost_metadata_complete
remains false without recognized fees, known rules and valid complete depth. Neither field
proves fillability, actual rule equivalence or profit; stake coverage/cost studies remain P05.

Request start/end, receipt and result-recording times come from the runner's clock, separately
from source quote timestamps. No attempt is made before a slot/configuration is due. Stale
or future planner game-state evidence prevents dispatch. Live/cancelled/postponed/revised
fixtures prevent dispatch and cannot be completed by an old worker. All receipts at/after
scheduled tip-off are excluded. P04 deliberately suppresses T0 rather than infer pregame
status from a schedule; authoritative live boundary qualification remains future work.

## Synthetic accounting and evidence

Each claim reserves one synthetic unit before IO. Limits apply per policy ID and source
for this database's lifetime, including failed/expired attempts; no automatic daily reset or
refund occurs. These are conservative reservations, not a claim of actual requests made,
provider API credits, billing, or batch optimization. Actual provider quota semantics remain
unselected and must be implemented/verified before live operation.

144 unittest cases passed on Python 3.14 (44 P04 + 100 retained). P04 tests block socket
creation and exercise restart, duplicate delivery, two connections, leases/fencing, retry
caps, partial/source/parse failures, quota exhaustion, receipt gap, stale/game-state/rule
checks, schedule changes, T0, no forward fill, real clock fields, transactional rollback,
immutable evidence, explicit installation and repeated persistent demo runs.
The declared Python 3.11 minimum was not separately exercised. No live account access,
API compatibility, actual provider coverage, source latency or deployment was tested.

P05 (daily reports/CSV/results) is next. Live-provider contracts, terms/access/budget,
authoritative game-state sourcing, production policy, backups and host deployment remain
pending. Known legacy credential revocation is unverified; no legacy entrypoint ran.
