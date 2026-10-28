# Preliminary prototype review — 2026-10-28

Source: [legacy commit 67c69d2](https://github.com/aibuddygame/nba-arb-bot/commit/67c69d29cacf99d518d9f342cf5542e754ceeb05).
Review scope: all 10 Python modules, root configuration/build/launcher documentation,
tests package and committed injury text. No live trading or notification test performed.

## Assessment

Useful modular snapshot/report prototype. It converts odds in probability space, removes
bookmaker margin, compares opening/current lines with Polymarket, and includes a separate
injury parser. It does not contain a structured quote history, results pipeline, correlation
study, backtest or paper position ledger. Strong/VStrong labels are uncalibrated heuristics.
dry_run is not a paper-trading engine. Price disagreement is not proven arbitrage.

## Findings to retain during redesign

| Area | Evidence and implication |
| --- | --- |
| Public credential | An apparent Yahoo app credential is committed in config.yaml. Do not copy or test it; revocation unverified |
| Wrong-game matching | report.py:65–96 matches first city word without date. Offline Lakers/Boston vs Clippers/Boston collision reproduced |
| Spread parsing | polymarket_scraper.py:245 greedy adjacent numeric groups parse HOU-4.552¢ as −4.55 and 2¢ |
| Quote semantics | Page cents have no explicit bid/ask/depth or fee handling, so they do not establish purchase cost |
| Book labels | scraper.py:552–610 collects available pairs then assigns fixed book order; missing columns can shift identities |
| Best odds | scraper.py:159–193 seeds best odds with a historical opener; offline old +200 selected over current +150; helper used in CLI demonstration |
| Missing injury evidence | injury_report.py:303–336 returns empty changes on PDF HTTP error and formats “no new injuries”; reproduced with simulated failure |
| Injury integration | Old season URL; injury command is separate from scheduled odds collection; only new/worsened statuses retained |
| Calculation design | report.py averages sides before de-vig; incomplete books may yield different side populations; integer odds round-trip unnecessary |
| Model assumptions | Spread-to-moneyline assumes Normal margin with fixed sigma=12; same-venue spread is not independent validation |
| Configuration | Signal thresholds are hardcoded in report.py; opener_edge_threshold does not control them |
| Side effects | report.py:540–543 can send email before writing a report, independent of dry_run |
| Tests | tests contains only __init__.py; probability doctest: 89 examples attempted, 13 failed, including harmless representation differences and inaccurate examples |

Boundary probes also found american_to_decimal(0)=1 and decimal_to_american(1) raising
ZeroDivisionError. The Shin routine/example requires independent formula validation;
do not treat alternative de-vig methods as automatically more accurate.

## Validation limits

Checks ran against a temporary copy using Python 3.14, with third-party imports stubbed
for selected pure-function probes. No provider credentials, installed runtime, live scrape,
email delivery, source freshness or actual historical profitability was verified.
The recording engine should reuse concepts selectively, not assume legacy parsers are safe.

