# P05A Cloudflare and Supabase foundation — selected plan

Decision date: 2026-10-28, Asia/Singapore.
Status: platform selection, Supabase repurposing and free-plan Cloudflare Worker shell verified.
Recorder runtime, PostgreSQL recorder schema and unattended collection are not implemented.
P01–P05 remain the verified offline SQLite reference. Live collection is disabled.

## Owner decision and current setup

The owner selected Cloudflare hosting/compute and Supabase database services for the NBA
recorder, followed later by sampan.io and the Genie-life homepage. The owner explicitly
chose to reuse the existing Turing Supabase project for NBA first.

The existing Supabase project was resumed during the preceding audit, then renamed
nba-arb-bot. It remains healthy on the Free plan in Tokyo. Its project reference and API
address were preserved. The old Genie GitHub integration was disconnected after verifying
that it targeted the unrelated repository and had production deployment enabled.
No replacement automatic database-deployment integration was connected.

The audit found one empty legacy application table, two empty private storage buckets,
zero application users/sessions, one recorded legacy migration and no Edge Functions or
database Cron extension. The table has RLS enabled, no policies and no client-role read/write
privileges; this is not permission to add broad public grants. Organization membership and its existing access remain unchanged. No table, bucket, user, migration, project or permission was
deleted/reset. Do not treat empty current data as permission to erase legacy objects later.

Private account references, exact setup receipts and screenshots are kept in ignored
exports-private/, outside the public documentation and ChatGPT reference pack. No API key,
database password, organization-member email or production raw body belongs in this repo.

The owner created a Cloudflare account, verified email and explicitly authorized an
application. Dashboard access and the Workers Free current-plan label were verified. A Worker
named nba-arb-bot was created with Cloudflare's unchanged Hello World template. Its public
workers.dev URL returned Hello World! in an independent browser tab. Settings showed no
variables/secrets, connected bindings, Cron triggers, queue consumers or Git build connection.
The dashboard reported the deployment Ready. This is a deployed starter shell, not the NBA
collector, synthetic replay, database integration or dashboard. No paid upgrade or custom
domain/zone route was configured. Endpoint/account-specific evidence remains private.

## Proposed architecture

| Component | Responsibility | Current state |
| --- | --- | --- |
| GitHub | Canonical source, review and versioned migrations | Existing P01–P05 draft stack; no new merges claimed |
| Cloudflare Worker | Bounded scheduled dispatcher and collector, later report endpoints | Hello World shell deployed; collector compatibility/runtime unimplemented |
| Supabase PostgreSQL | Jobs, leases, observations, pairs, results and immutable audits | Existing project repurposed; NBA schema unimplemented |
| Supabase private Storage | Candidate raw-evidence and report objects | Proposed new buckets; no NBA bucket created |
| Cloudflare static hosting | Future report UI and separate project homepages/domains | Proposed; none deployed in this task |

The scheduler wakes to check persisted per-game due slots. It does not poll providers on
every scheduler tick. Preserve T−12h and the 30-minute cadence relative to each fixture;
do not replace this with a global on-the-hour assumption. Delays, game-state qualification,
quote freshness, retries and missed observations remain explicit. T0 stays fail-closed
until authoritative boundary-state evidence is implemented and reviewed.

Cloudflare scheduled execution is not a real-time timing guarantee. Measure dispatch lag
and validate explicit timing tolerances in the synthetic cloud pilot before a live decision.
Choose one authoritative dispatcher; do not simultaneously enable Cloudflare Cron and
Supabase Cron for the same work. No scheduler is enabled by selecting the architecture.

The collector Worker runtime is a decision after a compatibility spike. Retain Python
reference logic; verify Python Workers/package support or select a small Worker-side
implementation with parity tests. Supabase supplies PostgreSQL and APIs; it does not make
the existing Python SQLite code deployable without modification.

## Bounded acceptance units

| Unit | Required work and evidence | State |
| --- | --- | --- |
| A01 | Confirm platform choice; resume/audit reusable project; rename it; disconnect unrelated deployment; preserve state; create authorized credential-free Worker shell | Verified setup and starter only |
| A02 | Review versioned PostgreSQL schema, least-privilege access, lease fencing, idempotency and transaction boundaries; exercise migrations and recovery in a nonproduction test environment | Planned; not implemented |
| A03 | Implement a bounded Worker runner with explicit synthetic-only mode and no live credentials; verify compatibility against PostgreSQL | Planned; not implemented |
| A04 | Explicitly deploy and enable a bounded synthetic schedule; prove unattended runs, duplicates/retries, restarts, missed slots, timezones, daily report/export hashes and cost measurements | Planned; requires separate schedule activation |
| A05 | Apply the P07 live-pilot decisions and evidence gates before any live source calls | Deferred; live authorization not granted |

P06 spreads/totals remains a separate feature milestone. P05A does not claim its acceptance,
replace P07's live decision or retroactively migrate earlier SQLite databases.

## PostgreSQL and evidence requirements

- Preserve canonical game/team/market/outcome identities, exact decimal source prices,
  receipt/source/planned timestamps, schedule revisions and immutable correction history.
- Keep original SQLite databases unchanged. A future export/import must be explicit,
  validated by counts/hashes and tested for rollback; creating empty cloud tables is not
  historical-data migration.
- Enforce uniqueness and fencing in the database. Claims, reservations, attempt outcomes,
  observation inserts and pair finalization must retain atomic behavior under two workers,
  lease expiry and injected failures. Do not split a transaction into independent REST calls.
- Prefer a private recorder schema and narrow backend credentials. Any exposed tables or
  callable database functions need explicit grants and reviewed RLS/authorization. Keep
  service/secret keys out of browsers, repository files and logs. A publishable key alone
  does not establish safe access.
- If an RPC boundary is selected, design claim/finish operations as bounded database
  transactions and restrict invocation. Review function privileges, security-definer usage,
  fixed search paths and duplicate delivery; an RPC is not automatically safe.
- Moving raw bodies from transactional SQL blobs into object storage changes atomicity.
  Specify upload staging, content hashes, pending/committed references, retry/idempotency
  and orphan reconciliation. Do not call a slot complete with missing evidence. A database
  backup alone must not be presented as backup of all evidence objects.
- Reproduce P05 as-of views and correction chains without leaking later results into earlier
  cutoffs. Keep planned coverage separate from receipt-day activity and nulls from zeros.
- Keep report output private initially. Dashboard authentication and narrowly authorized
  reads are separate work; a custom domain is not required to run the collector.

## Deployment controls and cost

Use separate configuration for local synthetic tests, deployed synthetic pilots and any
future live environment. Live mode defaults off. A missing/unknown mode must refuse work.
Do not load legacy config.yaml, invoke legacy reporting/email or store provider keys for
an offline task. No automatic production migration or scheduled data collection is enabled
by the repository updates in this change.

Supabase and Cloudflare Workers remain Free for this setup. Free-tier capacity, availability, pausing and backup
limits must be assessed before live use. Cloudflare Workers Paid has a published account
minimum of US$5/month plus usage, but no paid purchase was authorized or performed here.
No total operating cost is guaranteed: Supabase compute/storage, raw retention, provider
credits, AI calls and domain registrations are separate budget decisions.

The selected Supabase project is for NBA now. Future SAMPAN/Genie databases can be separate
projects in the same organization/account, subject to capacity and billing. Separate project
databases do not by themselves restrict organization-wide dashboard membership. Website
domains are configured in Cloudflare; a paid custom Supabase API hostname is not required
just because a website has its own domain.

## Validation and next step

This is setup and planning, with no recorder-code or database-schema change. The sole
deployed Worker code is the vendor Hello World template, not code from the Python recorder. Project name
and healthy state were read back through Supabase; the integration page showed no selected
GitHub repository after disconnection. The legacy application table remained present with
zero rows. Documentation links, privacy/ignore rules and published-file equality are checked
with the handoff. Earlier P05 evidence remains 183 passing offline tests; no new runtime or
cloud test result is claimed by this document.

Next: implement A02/A03 as a reviewable synthetic cloud foundation using the verified
accounts and existing starter shell. Keep automatic production migration, schedules and live transports off
until their explicit activation steps. Do not purchase plans or apply all milestones merely
because the platforms have been chosen.

References, checked 2026-10-28:

- [Cloudflare scheduled Workers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
- [Python Workers](https://developers.cloudflare.com/workers/languages/python/)
- [Supabase database](https://supabase.com/docs/guides/database/overview)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase Storage](https://supabase.com/docs/guides/storage)
- [Supabase pricing](https://supabase.com/pricing)
- [P05 reference implementation](P05-SYNTHETIC-REPORTS-RESULTS.md)
