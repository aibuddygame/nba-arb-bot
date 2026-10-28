# NBA Arbitrage Bot / NBA odds research recorder

This repository contains the original Python snapshot/report prototype and a proposed
2026–27 paired odds recording engine. The new engine is **planned, not implemented or live**.
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
The planning publication does not authorize engine development or live activation.

## Legacy prototype status

The prototype scrapes SportsbookReview and Polymarket, computes probability differences,
and produces heuristic signals and reports. It has no implemented quote-history database,
results study, backtest or paper-trading ledger. Signal labels do not establish a trading edge.

An apparent email app credential was observed in the existing public legacy configuration.
Revocation has not been verified. Do not reproduce/test it. Legacy report generation can
send email even when dry_run=true; review local configuration before running anything.
The original code and configuration are preserved by this documentation-only update.

## Legacy setup reference

The following instructions describe the existing prototype, not the proposed engine.
The documented pytest command currently has no collected test cases; tests contains only
its package initializer. Future engine checks are defined in the roadmap.

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

