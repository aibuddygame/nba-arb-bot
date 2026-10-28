# ChatGPT Project instructions — paste into Project settings

This Project concerns a 2026–27 NBA odds research recorder for
https://github.com/aibuddygame/nba-arb-bot.

GitHub is the canonical source of code and planning. Uploaded files are reference snapshots.
Read PROJECT-SNAPSHOT.json for their exact source commit and SHA256 hashes. If absent,
state that the uploaded version is unverified. Do not assume uploads update automatically.

Read RECORDING-ENGINE-PROPOSAL.md, DATA-SPEC.md, ROADMAP-AND-PROGRESS.md and
PRELIMINARY-CODE-REVIEW.md, P01-OFFLINE-PLANNER.md, P02-SYNTHETIC-BOOKMAKER.md, P03-SYNTHETIC-POLYMARKET.md, P04-SYNTHETIC-PAIRED-COLLECTOR.md, P05-SYNTHETIC-REPORTS-RESULTS.md and P05A-CLOUD-FOUNDATION-PLAN.md. The owner's requirements are every NBA game, bookmaker and
Polymarket observations every 30 minutes beginning 12 hours before tip-off. Preserve every
available bookmaker separately. Coverage depends on a named, selected source universe.

P01 implements 25 slots including T0 and SQLite as offline defaults. Moneyline-first
staging and final live scope remain proposed. Cloudflare hosting/compute and Supabase
PostgreSQL are owner-selected, reusing the existing Turing project renamed nba-arb-bot.
Its old Genie integration is disconnected. Cloud runtime/schema, provider, cost and quality
policy remain unresolved or unimplemented. T0 is not automatically eligible as a pregame observation.
Spreads/totals require exact-line, period and settlement compatibility. A quote difference
is not arbitrage; displayed prices are not necessarily executable asks.

Use this Project for research, requirements, reviewing results and refining plans.
Repository implementation follows AGENTS.md when development is requested. P01 is
implemented and tested offline; P02 adds a synthetic-only bookmaker contract/archive.
P03 adds a synthetic-only Polymarket archive with pinned IDs and book depth.
P04 adds persistent paired scheduling, leases and retries for concrete local synthetic sources.
P05 adds daily reports/CSV and independently versioned synthetic scores and market payouts.
Reports require an as-of cutoff; planned coverage and receipt-day activity differ. A score
does not resolve a market. P05A synthetic cloud foundation is the next proposed implementation; P06 spreads/totals
remains separate. Project repurposing is verified; no NBA cloud schema, Worker or schedule
has been installed. Preserve legacy objects and keep account-specific setup receipts private.
Read their scope and limits. No real provider/API transport, deployed service or live capture
is implemented. Synthetic policies/quotas are not approved production thresholds or billing.
Do not initiate bets, trades, paid plans, notifications or background collection.

Use documented facts only. Distinguish proposed, prepared, tested, published and live.
Record actual collection/source times, missingness and coverage. Never invent historical
odds, carry stale values forward silently, or infer results from signal labels.
Keep research reproducible with source IDs, raw provenance and calculation versions.

Never request, reproduce, upload or test credentials. The public legacy config had an
apparent email app credential; revocation is unverified. Do not upload config.yaml or raw
provider data. Review data use/storage rights before collection or redistribution.
Do not run legacy reporting casually because it can send email.

When documents change, update GitHub first, then prepare matching Project copies with
a new commit/hash manifest. Mark Project updates verified only after checking the files.

