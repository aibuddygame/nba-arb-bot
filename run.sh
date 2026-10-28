#!/bin/bash
# =============================================================================
# NBA Arbitrage Bot - Quick Run Script
# =============================================================================
# Usage:
#   ./run.sh           - Generate a report (default)
#   ./run.sh report    - Generate a report
#   ./run.sh injuries  - Compare 12:00 a.m vs 1:00 a.m ET injury reports, update data/injuries_latest.txt
#   ./run.sh start     - Start the scheduler (runs hourly)
# =============================================================================

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Set Python path
export PYTHONPATH=src

case "${1:-report}" in
    report)
        echo "Generating NBA Odds Report..."
        python src/nba_arb_bot/report.py
        ;;
    injuries)
        echo "Comparing NBA injury reports (12:00 a.m vs 1:00 a.m ET)..."
        python -m nba_arb_bot.injury_report
        ;;
    start)
        echo "Starting NBA Arbitrage Bot Scheduler..."
        echo "Press Ctrl+C to stop."
        python src/nba_arb_bot/main.py
        ;;
    *)
        echo "Usage: ./run.sh [report|injuries|start]"
        echo "  report   - Generate a report (default)"
        echo "  injuries - Compare injury reports, update data/injuries_latest.txt"
        echo "  start    - Start the scheduler"
        exit 1
        ;;
esac
