# NBA Arbitrage Bot

A local Python application for NBA arbitrage opportunities.

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
