# NBA paired odds recording engine — proposal v0.1

Planning date: 2026-10-28 (Asia/Singapore). Target season: 2026–27.
Status: documentation baseline; implementation and live collection not started.

## Purpose

Create an auditable history of bookmaker odds and Polymarket quotes before every NBA
game. Study agreement, price changes, lead–lag behaviour, injury responses and hypothetical
opportunities after execution costs. This is a research recorder, not a trading system.

## Owner requirements and proposed choices

| Item | Status |
| --- | --- |
| Record bookmaker odds and matching Polymarket observations for every NBA game | Owner requested; actual source coverage must be reported |
| Begin 12 hours before each game and record every 30 minutes | Owner requested |
| Preserve individual bookmaker observations for future studies | Owner requested |
| Publish planning to GitHub and provide matching ChatGPT Project files first | Owner authorized |
| Include scheduled tip-off, giving 25 planned slots | Proposed boundary convention |
| Cover all feed-supported books; moneyline first, exact-line spreads/totals next | Proposed staged delivery; provider and first live release scope unresolved |
| Python, SQLite and compressed private raw responses | Proposed starting architecture |
| REST snapshots for the half-hour cadence; streaming optional later | Proposed approach, subject to adapter capability |
| Daily report in Singapore time, research storage in UTC | Proposed reporting convention |

“All bookmakers” means a named coverage universe offered by the selected source, not a
claim of worldwide completeness. “All odds” initially means full-game moneyline, main
spread and total quotes returned by that source. Alternate lines may be retained when
returned and licensed, but complete alternate-line coverage is not promised. Player props,
period markets, futures and live monitoring are later scope decisions.

## Schedule

For scheduled start T, generate slots T−12h + k×30m for k=0…24.
Store each planned slot, schedule revision, actual attempts and source times separately.
Collectors request both sources concurrently when practical; two requests are not atomic.
One bookmaker response may serve multiple due games only if freshness rules are met.

Refresh fixtures periodically and reconcile changes. Keep an internal game identity
through postponements, with a revision history of source IDs and scheduled starts.
Cancel obsolete future slots without deleting them; create replacement slots under the
new revision. Historical observations are retained and attributed to their original schedule.
A new discovery inside the window records earlier slots as missed/not observed.

T0 is a boundary observation, not automatically pregame. Stop pregame collection on
authoritative live/started status. Mark later slots cancelled_after_start. If a game is
delayed, do not add unscheduled extension slots in v0.1; record the delay.
If status is unknown around T0, quarantine the observation rather than assume pregame.

## Coverage and calculations

Record both outcomes from every available book, not only the best or an average.
Record Polymarket bids, asks, sizes, midpoint/last trade when available, and a configurable
number of book levels. Preserve fee/rule metadata or mark it unavailable.

Match moneyline outcomes to the same game, period and settlement semantics.
For spreads/totals require the same signed handicap/total and rules, including push,
overtime, cancellation and postponement treatment. Mismatches remain visible, unpaired.

Compute bookmaker implied probabilities, then de-vig complete two-sided markets per book.
Form a versioned consensus from eligible books. Compare with Polymarket midpoint for
market agreement and ask/depth for hypothetical buying cost; preserve the bid for exits.
Use “percentage-point difference,” not profit or arbitrage. Do not normalize executable
asks as if removing bookmaker vig. The spread-to-moneyline model is a separate experiment.

## Operation and delivery

Pipeline: fixture discovery → slot planner → source adapters → immutable observations
and raw evidence → validation/matching → versioned calculations → daily report/export.
Persist job state and retry with bounded backoff. Append attempts, record real times and
do not disguise retries as on-time observations. Surface stale, missing and failed sources.

Daily reports show planned/valid/late/missed/cancelled counts, game/book/market coverage,
quote ages, source timing gaps, match failures and observed differences. Organize daily
views by receipt date in Asia/Singapore; keep fixture date in Eastern Time separately.
The primary research table is one row per slot × book × market × outcome, with paired
Polymarket observation references. Distinct comparison rows can share one source response.

After games, attach final score, game status and separately the Polymarket resolution,
payout and resolution time. Record corrections and unresolved/void outcomes explicitly.

## Research plan

Start with plots and descriptive differences by time to tip-off, book, probability band
and liquidity. Study within-game probability changes and lead–lag, not just pooled price
levels. Only use information received by the analysis cutoff; never join a future quote.
Evaluate chronologically by game/date. Repeated snapshots from one game are dependent.
Report coverage bias, game-clustered uncertainty, calibration, closing-price movement and
cost-aware paper outcomes. Historical midpoints cannot prove fillability or depth.

## Live-readiness decisions

Choose source/provider, named books, permissible storage/export use, API quota and budget,
runtime host, backup/retention policy, freshness thresholds, pairing tolerance and final live
market scope before activation. Offline schema/planner work need not wait for paid access.
Do not infer authorization to buy services or deploy from this documentation task.

## References

- [Data specification](DATA-SPEC.md)
- [Roadmap and decisions](ROADMAP-AND-PROGRESS.md)
- [Prototype review](PRELIMINARY-CODE-REVIEW.md)
- [Polymarket market discovery](https://docs.polymarket.com/market-data/discover-markets)
- [Polymarket prices](https://docs.polymarket.com/concepts/prices-orderbook)
- [Polymarket fees](https://docs.polymarket.com/trading/fees)
- [The Odds API NBA coverage](https://the-odds-api.com/sports/nba-odds.html)
- [The Odds API update intervals](https://the-odds-api.com/sports-odds-data/update-intervals.html)
- [NBA 2026–27 injury reports](https://official.nba.com/nba-injury-report-2026-27-season/)

External interfaces and terms must be rechecked when implementing adapters. References
are candidates/background, not evidence of account access or selected subscriptions.

