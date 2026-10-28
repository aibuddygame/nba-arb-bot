# NBA Arbitrage Bot / NBA odds research recorder

This repository contains the original Python snapshot/report prototype and a proposed
2026–27 paired odds recording engine. **P01 and the P02/P03 synthetic bookmaker/Polymarket adapters are
implemented and tested offline; live transports and collection are not implemented.**
The goal is a research history of bookmaker and Polymarket quotes every 30 minutes starting
12 hours before every NBA game. Twenty-five slots including scheduled tip-off is proposed;
actual source coverage, provider, budget and live deployment remain unresolved.

## Planning baseline

- [Recording engine proposal](docs/RECORDING-ENGINE-PROPOSAL.md)
- [Data specification](docs/DATA-SPEC.md)
- [Roadmap, decisions and progress](docs/ROADMAP-AND-PROGRESS.md)
- [Preliminary code review](docs/PRELIMINARY-CODE-REVIEW.md)
- [Repository agent instructions](AGENTS.md)
- [ChatGPT Project instructions](docs/CHATGPT-PROJECT-INSTRUCTIONS.md)
- [Matching-file upload and refresh guide](docs/CHATGPT-PROJECT-SETUP.md)

GitHub is canonical. ChatGPT Project files are explicit commit/hash snapshots.
The owner authorized P01 and then P02/P03 with synthetic data only on 2026-10-28.
Live activation remains outside the current scope.

## Legacy prototype status

The prototype scrapes SportsbookReview and Polymarket, computes probability differences,
and produces heuristic signals and reports. It has no implemented quote-history database,
results study, backtest or paper-trading ledger. Signal labels do not establish a trading edge.

An apparent email app credential was observed in the existing public legacy configuration.
Revocation has not been verified. Do not reproduce/test it. Legacy report generation can
send email even when dry_run=true; review local configuration before running anything.
The legacy code and configuration are preserved by the P01 implementation.

## P01 offline planner

- [Implemented scope, behaviour and acceptance evidence](docs/P01-OFFLINE-PLANNER.md)
- Source: src/nba_arb_bot/recorder/; tests: tests/test_recorder.py

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder --demo
```

P01 uses the Python standard library and temporary synthetic databases. No legacy config,
provider credentials or legacy dependencies are needed. The demo does not start collection.
Private raw responses, databases and exports belong outside Git.

## P02 synthetic bookmaker adapter

- [Contract, schema installation, demo and evidence](docs/P02-SYNTHETIC-BOOKMAKER.md)
- Synthetic fixture: tests/fixtures/bookmaker-synthetic.json

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.bookmaker_demo \
  --fixture tests/fixtures/bookmaker-synthetic.json \
  --received-at 2026-10-28T12:00:00Z \
  --expected-books synthetic-a synthetic-b synthetic-c synthetic-d \
  --max-quote-age-seconds 120
```

This replays local synthetic bytes into a temporary database. No provider is selected;
there is no live transport. The P02 checkpoint had 64 passing offline tests; all remain passing after P03.

## P03 synthetic Polymarket adapter

- [Explicit mappings, book depth, fee/rule metadata and evidence](docs/P03-SYNTHETIC-POLYMARKET.md)
- Synthetic fixture: tests/fixtures/polymarket-synthetic.json

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nba_arb_bot.recorder.polymarket_demo \
  --fixture tests/fixtures/polymarket-synthetic.json \
  --received-at 2026-10-28T12:00:00Z \
  --max-quote-age-seconds 120
```

This replays a synthetic full snapshot against an explicitly pinned fictional mapping.
The full suite contains 100 passing offline tests. No live Polymarket transport exists.

## Legacy setup reference

The following instructions describe the existing prototype, not the proposed engine.
P01 has a dependency-free offline test suite and synthetic demo. See the commands below;
the remaining setup instructions describe only the legacy application.

## Requirements

- Python 3.11+

## Installing Python 3.11 (macOS)

If you don't have Python 3.11 installed, use Homebrew:

```bash
brew install python@3.11
```

After installation, the command will be available as `python3.11` or you can create an alias.

## Setup

### 1. Create a virtual environment

```bash
python3.11 -m venv venv
```

### 2. Activate the virtual environment

**macOS/Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Running the Application

```bash
python src/nba_arb_bot/main.py
```

Or as a module:
```bash
cd src && python -m nba_arb_bot.main
```

## Running Tests

```bash
pytest
```

## Project Structure

```
nba-arb-bot/
├── src/
│   └── nba_arb_bot/
│       ├── __init__.py
│       └── main.py
├── tests/
│   └── __init__.py
├── .gitignore
├── pyproject.toml
├── README.md
└── requirements.txt
```

