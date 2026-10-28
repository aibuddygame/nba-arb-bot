# NBA odds recording project — agent instructions

## Read first

Read README.md, docs/RECORDING-ENGINE-PROPOSAL.md, docs/DATA-SPEC.md,
docs/ROADMAP-AND-PROGRESS.md and docs/PRELIMINARY-CODE-REVIEW.md before changes.
GitHub is the canonical source; ChatGPT Project uploads are versioned reference copies.

## Current boundary

The owner authorized planning publication and then P01 offline development on 2026-10-28.
P01–P05 are implemented and verified offline. The owner authorized P02/P03/P04/P05
using synthetic data only; see docs/P01-OFFLINE-PLANNER.md,
docs/P02-SYNTHETIC-BOOKMAKER.md, docs/P03-SYNTHETIC-POLYMARKET.md,
docs/P04-SYNTHETIC-PAIRED-COLLECTOR.md and docs/P05-SYNTHETIC-REPORTS-RESULTS.md.
The owner subsequently selected Cloudflare and Supabase and authorized reusing the
existing Turing project for NBA. The project was renamed and its unrelated Genie deployment
integration disconnected. See docs/P05A-CLOUD-FOUNDATION-PLAN.md. Cloud runtime/schema
implementation and unattended collection are not yet complete.
The owner then authorized creating the NBA Cloudflare application. A free-plan Worker
named nba-arb-bot now serves only the vendor Hello World starter; it has no credentials,
bindings, Cron triggers or queue consumers. This does not implement A02/A03 or collection.
Paid subscriptions, collector/schedule activation, notifications, betting and trading
remain outside this application-shell task.
Work on the next development milestone when requested. Record proposals separately from
confirmed owner requirements.

## Working practices

- Inspect checkout, instructions, source and existing changes before editing.
- Preserve the prototype and unrelated work. Use codex/ branches for future development
  unless the owner specifies otherwise. Do not reset history or force-push.
- Implement a small roadmap acceptance unit and report the exact checks performed.
- Use canonical team/event/outcome IDs and explicit UTC times. Reject ambiguous matches.
- Retain source odds and raw provenance; version derived calculations separately.
- Missing, failed, stale, suspended and live observations must remain distinguishable.
  Never fabricate a historical observation or silently carry a quote forward.
- Test meaningful failure cases: duplicate jobs, restarts, missed slots, schedule changes,
  wrong games/lines, time boundaries, stale quotes, partial feeds and source failures.
- Keep credentials, local databases, raw provider responses and private exports out of Git.
  Redact API keys from request URLs and logs. Check provider storage/export rights before
  live collection. Do not purchase a plan or activate collection as part of offline work.
- A Yahoo app credential was observed in the public legacy config during review.
  Never reproduce or test it. Revocation has not been verified. Do not run legacy report
  or email entrypoints casually: report generation can send email even with dry_run=true.
  Do not rewrite public history without explicit authorization.
- Update roadmap status only from evidence. Offline tests do not establish live coverage,
  a deployed collector, complete historical data, or profitable execution.
- Collection/research is separate from execution. A price difference is not arbitrage.

## Project handoff

After material documentation changes, refresh the flat ChatGPT upload pack using
docs/CHATGPT-PROJECT-SETUP.md. Include exact GitHub commit and hashes. Never claim
the Project was updated until that action and its contents have been verified.

