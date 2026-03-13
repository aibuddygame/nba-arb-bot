"""
Polymarket scraper module for NBA moneyline odds.

Polymarket displays odds as prices in cents, which represent implied probabilities.
For example: 62¢ = 62% implied win probability.

This module uses Playwright to scrape the JavaScript-rendered page.

Target URL: https://polymarket.com/sports/nba/games

Usage:
    from nba_arb_bot.polymarket_scraper import scrape_polymarket_odds

    data = scrape_polymarket_odds()
    for game in data.games:
        print(f"{game.away_team}: {game.away_price}¢ ({game.away_prob:.2%})")
        print(f"{game.home_team}: {game.home_price}¢ ({game.home_prob:.2%})")
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

# Module logger
logger = logging.getLogger(__name__)

# Target URL
POLYMARKET_NBA_URL = "https://polymarket.com/sports/nba/games"

# Team abbreviation to full name mapping
TEAM_ABBREV_TO_NAME = {
    "sas": "San Antonio",
    "cha": "Charlotte",
    "atl": "Atlanta",
    "ind": "Indiana",
    "nop": "New Orleans",
    "phi": "Philadelphia",
    "chi": "Chicago",
    "mia": "Miami",
    "min": "Minnesota",
    "mem": "Memphis",
    "dal": "Dallas",
    "hou": "Houston",
    "mil": "Milwaukee",
    "bos": "Boston",
    "orl": "Orlando",
    "sac": "Sacramento",
    "was": "Washington",
    "bkn": "Brooklyn",
    "det": "Detroit",
    "uta": "Utah",
    "tor": "Toronto",
    "lal": "L.A. Lakers",
    "nyk": "New York",
    "lac": "L.A. Clippers",
    "phx": "Phoenix",
    "cle": "Cleveland",
    "por": "Portland",
    "okc": "Oklahoma City",
    "den": "Denver",
    "gsw": "Golden State",
}

# Full team names for matching
TEAM_NAMES = [
    "Spurs", "Hornets", "Hawks", "Pacers", "Pelicans", "76ers",
    "Bulls", "Heat", "Timberwolves", "Grizzlies", "Mavericks", "Rockets",
    "Bucks", "Celtics", "Magic", "Kings", "Wizards", "Nets", "Pistons",
    "Jazz", "Raptors", "Lakers", "Knicks", "Clippers", "Suns",
    "Cavaliers", "Trail Blazers", "Thunder", "Nuggets", "Warriors"
]

# Team nickname to city mapping
NICKNAME_TO_CITY = {
    "Spurs": "San Antonio",
    "Hornets": "Charlotte",
    "Hawks": "Atlanta",
    "Pacers": "Indiana",
    "Pelicans": "New Orleans",
    "76ers": "Philadelphia",
    "Bulls": "Chicago",
    "Heat": "Miami",
    "Timberwolves": "Minnesota",
    "Grizzlies": "Memphis",
    "Mavericks": "Dallas",
    "Rockets": "Houston",
    "Bucks": "Milwaukee",
    "Celtics": "Boston",
    "Magic": "Orlando",
    "Kings": "Sacramento",
    "Wizards": "Washington",
    "Nets": "Brooklyn",
    "Pistons": "Detroit",
    "Jazz": "Utah",
    "Raptors": "Toronto",
    "Lakers": "L.A. Lakers",
    "Knicks": "New York",
    "Clippers": "L.A. Clippers",
    "Suns": "Phoenix",
    "Cavaliers": "Cleveland",
    "Trail Blazers": "Portland",
    "Thunder": "Oklahoma City",
    "Nuggets": "Denver",
    "Warriors": "Golden State",
}


@dataclass
class PolymarketGame:
    """
    Represents a single NBA game from Polymarket.

    Attributes:
        date: Game date string
        time: Game time string
        away_team: Away team name
        home_team: Home team name
        away_price: Away team price in cents (e.g., 62 for 62¢)
        home_price: Home team price in cents
        volume: Trading volume string
    """
    date: str
    time: str
    away_team: str
    home_team: str
    away_price: int
    home_price: int
    # Optional: main spread market (bid prices) scraped from the same page.
    # Example: HOU -4.5 = 52, TOR +4.5 = 49
    spread_number: float | None = None  # absolute spread magnitude (e.g., 4.5)
    away_spread_line: float | None = None  # signed line for away team (e.g., -4.5 or +4.5)
    home_spread_line: float | None = None
    away_spread_bid: int | None = None  # cents out of 100 (bid price)
    home_spread_bid: int | None = None
    volume: str = ""

    @property
    def away_prob(self) -> float:
        """Away team implied probability (price / 100)."""
        return self.away_price / 100

    @property
    def home_prob(self) -> float:
        """Home team implied probability (price / 100)."""
        return self.home_price / 100

    def __repr__(self) -> str:
        return (
            f"PolymarketGame({self.away_team} {self.away_price}¢ @ "
            f"{self.home_team} {self.home_price}¢, {self.date} {self.time})"
        )


@dataclass
class PolymarketOddsData:
    """
    Container for all scraped Polymarket NBA odds data.

    Attributes:
        games: List of PolymarketGame objects
        scraped_at: Timestamp when the data was scraped
        source_url: URL the data was scraped from
    """
    games: list[PolymarketGame] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))
    source_url: str = POLYMARKET_NBA_URL

    def __repr__(self) -> str:
        return f"PolymarketOddsData(games={len(self.games)}, scraped_at={self.scraped_at.isoformat()})"


class PolymarketScraperError(Exception):
    """Base exception for Polymarket scraper errors."""
    pass


def normalize_team_name(name: str) -> str:
    """
    Normalize team name for matching with SportsbookReview data.

    Args:
        name: Raw team name from Polymarket

    Returns:
        Normalized team name (city name)
    """
    # Remove records like "32-15"
    name = re.sub(r"\d+-\d+", "", name).strip()
    
    # Check if it's a nickname
    if name in NICKNAME_TO_CITY:
        return NICKNAME_TO_CITY[name]
    
    return name


def scrape_with_playwright() -> list[PolymarketGame]:
    """
    Scrape Polymarket NBA games using Playwright.
    
    Returns:
        List of PolymarketGame objects
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("[POLYMARKET] Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []
    
    logger.info("[POLYMARKET] Starting Playwright browser...")
    games = []
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Use very tall viewport to capture all games without scrolling
            # Scrolling can cause content to be lost in SPAs
            context = browser.new_context(
                viewport={'width': 1920, 'height': 4000},  # Very tall to capture all games
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            logger.info(f"[POLYMARKET] Navigating to {POLYMARKET_NBA_URL}")
            page.goto(POLYMARKET_NBA_URL, wait_until='domcontentloaded', timeout=60000)
            
            # Wait for React to fully hydrate and load all games
            page.wait_for_timeout(10000)
            
            # Get page text
            text = page.inner_text('body')
            logger.info(f"[POLYMARKET] Page loaded, {len(text)} chars")
            
            # Parse the text to extract games
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            
            # Pattern for price: ABC##¢ (team abbreviation + price in cents) - UPPERCASE
            price_pattern = re.compile(r'^([A-Z]{3})(\d+)¢$')
            # Pattern for spread bid: ABC(+/-)x.y<price>¢  e.g. "HOU-4.552¢" or "TOR+4.549¢"
            spread_pattern = re.compile(r'^([A-Z]{3})([+\-−]\d+(?:\.\d+)?)(\d+(?:\.\d+)?)¢$')
            # In the current Polymarket layout, spread is often split across multiple lines:
            #   HOU
            #   -4.5
            #   50¢
            abbrev_only_pattern = re.compile(r'^([A-Z]{3})$')
            spread_only_pattern = re.compile(r'^([+\-−]\d+(?:\.\d+)?)$')
            cents_only_pattern = re.compile(r'^(\d+(?:\.\d+)?)¢$')
            
            # We'll parse using a simple state machine that collects one game block at a time.
            current_teams: list[str] = []  # nicknames in order (away, home)
            moneyline_by_city: dict[str, int] = {}
            spread_by_city: dict[str, tuple[float, int]] = {}  # city -> (signed_line, bid_cents)
            pending_spread_abbrev: str | None = None
            pending_spread_line: float | None = None

            def finalize_current_game() -> None:
                nonlocal current_teams, moneyline_by_city, spread_by_city, games
                if len(current_teams) < 2:
                    return

                away_city = normalize_team_name(current_teams[0])
                home_city = normalize_team_name(current_teams[1])

                if away_city not in moneyline_by_city or home_city not in moneyline_by_city:
                    return

                # Compute spread fields if we have both sides
                spread_number: float | None = None
                away_spread_line: float | None = None
                home_spread_line: float | None = None
                away_spread_bid: int | None = None
                home_spread_bid: int | None = None

                if away_city in spread_by_city and home_city in spread_by_city:
                    away_spread_line, away_spread_bid = spread_by_city[away_city]
                    home_spread_line, home_spread_bid = spread_by_city[home_city]

                    # Use absolute magnitude as the "spread_number" input to downstream math.
                    # Typical markets have symmetric lines (e.g., -4.5 / +4.5).
                    if away_spread_line is not None and home_spread_line is not None:
                        spread_number = abs(away_spread_line) if abs(away_spread_line) > 0 else abs(home_spread_line)

                game = PolymarketGame(
                    date="Today",
                    time="",
                    away_team=away_city,
                    home_team=home_city,
                    away_price=moneyline_by_city[away_city],
                    home_price=moneyline_by_city[home_city],
                    spread_number=spread_number,
                    away_spread_line=away_spread_line,
                    home_spread_line=home_spread_line,
                    away_spread_bid=away_spread_bid,
                    home_spread_bid=home_spread_bid,
                )

                is_duplicate = any(
                    g.away_team == game.away_team and g.home_team == game.home_team
                    for g in games
                )
                if not is_duplicate:
                    games.append(game)
            
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Check if line is a team name
                is_team = False
                for team_name in TEAM_NAMES:
                    if line == team_name or line.startswith(team_name):
                        is_team = True
                        # When we encounter a new team's nickname and we already have 2 teams,
                        # we assume we've reached the next game block and finalize the prior one.
                        if len(current_teams) >= 2:
                            finalize_current_game()
                            current_teams = []
                            moneyline_by_city = {}
                            spread_by_city = {}

                        current_teams.append(team_name)
                        break
                
                # Check if line is a price (uppercase like MIL16¢, BOS85¢)
                price_match = price_pattern.match(line)
                if price_match:
                    abbrev = price_match.group(1).lower()
                    price = int(price_match.group(2))

                    city = TEAM_ABBREV_TO_NAME.get(abbrev)
                    if city:
                        moneyline_by_city[city] = price

                # Check if line is a spread bid token (e.g., HOU-4.552¢)
                spread_match = spread_pattern.match(line)
                if spread_match:
                    abbrev = spread_match.group(1).lower()
                    spread_line = float(spread_match.group(2))
                    bid_price = int(round(float(spread_match.group(3))))

                    city = TEAM_ABBREV_TO_NAME.get(abbrev)
                    if city:
                        spread_by_city[city] = (spread_line, bid_price)

                # Check for split spread format: ABBREV / SPREAD / PRICE
                abbrev_only_match = abbrev_only_pattern.match(line)
                if abbrev_only_match:
                    pending_spread_abbrev = abbrev_only_match.group(1).lower()
                    pending_spread_line = None
                    i += 1
                    continue

                if pending_spread_abbrev is not None:
                    spread_only_match = spread_only_pattern.match(line)
                    if spread_only_match:
                        # Normalize unicode minus to ASCII for float()
                        pending_spread_line = float(spread_only_match.group(1).replace("−", "-"))
                        i += 1
                        continue

                    cents_only_match = cents_only_pattern.match(line)
                    if cents_only_match and pending_spread_line is not None:
                        bid_price = int(round(float(cents_only_match.group(1))))
                        city = TEAM_ABBREV_TO_NAME.get(pending_spread_abbrev)
                        if city:
                            spread_by_city[city] = (pending_spread_line, bid_price)
                        pending_spread_abbrev = None
                        pending_spread_line = None
                
                i += 1

            # Finalize last block if present
            finalize_current_game()
            
            browser.close()
            
    except Exception as e:
        logger.error(f"[POLYMARKET] Playwright error: {e}")
        raise PolymarketScraperError(f"Failed to scrape Polymarket: {e}")
    
    logger.info(f"[POLYMARKET] Scraped {len(games)} games")
    return games


def scrape_polymarket_odds(url: str = POLYMARKET_NBA_URL) -> PolymarketOddsData:
    """
    Scrape NBA moneyline odds from Polymarket.

    Uses Playwright to render the JavaScript page and extract game data.

    Args:
        url: URL reference

    Returns:
        PolymarketOddsData object with games
    """
    logger.info("[POLYMARKET] Starting Polymarket NBA odds scrape")

    games = scrape_with_playwright()

    result = PolymarketOddsData(
        games=games,
        source_url=url,
    )

    logger.info(f"[POLYMARKET] Scrape complete: {len(games)} games")
    return result


# CLI entry point
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print("Polymarket NBA Moneyline Odds Scraper")
    print("=" * 70)

    try:
        data = scrape_polymarket_odds()

        print(f"\nGames found: {len(data.games)}")
        print(f"Scraped at: {data.scraped_at.isoformat()}")
        print("-" * 70)

        for i, game in enumerate(data.games, 1):
            print(f"\nGame {i}: {game.away_team} @ {game.home_team}")
            print(f"  {game.away_team}: {game.away_price}¢ ({game.away_prob:.1%})")
            print(f"  {game.home_team}: {game.home_price}¢ ({game.home_prob:.1%})")

    except PolymarketScraperError as e:
        print(f"\n✗ Scraper error: {e}", file=sys.stderr)
        sys.exit(1)
