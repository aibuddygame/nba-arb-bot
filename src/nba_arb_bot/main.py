"""
NBA Arbitrage Bot - Entry Point

How to run this project:
------------------------
1. Create a virtual environment:
   python3.11 -m venv venv

2. Activate the virtual environment:
   - macOS/Linux: source venv/bin/activate
   - Windows: venv\\Scripts\\activate

3. Install dependencies:
   pip install -r requirements.txt

4. Run the application:
   python -m nba_arb_bot.main
   
   Or from the project root:
   python src/nba_arb_bot/main.py

5. The scheduler will start and run scans at the configured intervals.
   Press Ctrl+C to stop.
"""

from nba_arb_bot.scheduler import start_scheduler


def main() -> None:
    """Main entry point for the NBA Arbitrage Bot."""
    start_scheduler()


if __name__ == "__main__":
    main()
