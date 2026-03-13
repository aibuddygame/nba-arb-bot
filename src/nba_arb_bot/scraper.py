"""
Scraper module for SportsbookReview NBA moneyline odds.

This module fetches and parses NBA moneyline odds from SportsbookReview,
extracting game information, opener odds, and current odds from multiple
sportsbooks.

Target URL: https://www.sportsbookreview.com/betting-odds/nba-basketball/money-line/full-game/

Usage:
    from nba_arb_bot.scraper import scrape_nba_odds, NBAOddsData

    # Fetch and parse odds
    odds_data = scrape_nba_odds()

    # Access structured data
    print(f"Date: {odds_data.date}")
    for game in odds_data.games:
        print(f"{game.away_team} @ {game.home_team} at {game.start_time}")
        print(f"  Opener: {game.opener_odds}")
        for book, odds in game.sportsbook_odds.items():
            print(f"  {book}: {odds}")
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

# Module logger
logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Target URL for NBA moneyline odds
SBR_NBA_MONEYLINE_URL = (
    "https://www.sportsbookreview.com/betting-odds/nba-basketball/money-line/full-game/"
)

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# User agent - simpler works better for this site (complex headers trigger JS-heavy response)
USER_AGENT = "Mozilla/5.0 (compatible; NBAArbitrageBot/1.0)"

# Known sportsbook identifiers used in SportsbookReview's HTML
# These map to the column order in the odds table
SPORTSBOOK_NAMES = [
    "opener",      # Column 0: Opening line
    "betmgm",      # Column 1: BetMGM
    "fanduel",     # Column 2: FanDuel
    "caesars",     # Column 3: Caesars
    "bet365",      # Column 4: Bet365
    "draftkings",  # Column 5: DraftKings
    "fanatics",    # Column 6: Fanatics Sportsbook
]


# =============================================================================
# Data Classes - Structured objects for parsed data
# =============================================================================

@dataclass
class TeamOdds:
    """
    Represents moneyline odds for a single team.

    Attributes:
        american: American odds format (e.g., -150, +120)
                  None if odds are not available or couldn't be parsed
    """
    american: Optional[int] = None

    def __repr__(self) -> str:
        if self.american is None:
            return "N/A"
        # Format with explicit + sign for positive odds
        return f"{self.american:+d}" if self.american >= 0 else str(self.american)

    @property
    def is_available(self) -> bool:
        """Check if odds are available."""
        return self.american is not None

    @property
    def implied_probability(self) -> Optional[float]:
        """
        Calculate implied probability from American odds.

        Returns:
            Probability as a decimal (0.0 to 1.0), or None if odds unavailable
        """
        if self.american is None:
            return None
        if self.american < 0:
            # Favorite: probability = |odds| / (|odds| + 100)
            return abs(self.american) / (abs(self.american) + 100)
        else:
            # Underdog: probability = 100 / (odds + 100)
            return 100 / (self.american + 100)


@dataclass
class GameOdds:
    """
    Represents a pair of odds for both teams in a game from one source.

    Attributes:
        away: Odds for the away team
        home: Odds for the home team
    """
    away: TeamOdds = field(default_factory=TeamOdds)
    home: TeamOdds = field(default_factory=TeamOdds)

    def __repr__(self) -> str:
        return f"Away: {self.away}, Home: {self.home}"

    @property
    def is_available(self) -> bool:
        """Check if at least one team has odds available."""
        return self.away.is_available or self.home.is_available


@dataclass
class NBAGame:
    """
    Represents a single NBA game with all associated odds data.

    Attributes:
        start_time: Game start time as string (e.g., "7:00 PM EST")
        away_team: Name of the away team
        home_team: Name of the home team
        opener_odds: Opening line odds
        sportsbook_odds: Dictionary mapping sportsbook names to their odds
    """
    start_time: str
    away_team: str
    home_team: str
    opener_odds: GameOdds = field(default_factory=GameOdds)
    sportsbook_odds: dict[str, GameOdds] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"NBAGame({self.away_team} @ {self.home_team}, "
            f"Time: {self.start_time}, "
            f"Opener: {self.opener_odds}, "
            f"Books: {list(self.sportsbook_odds.keys())})"
        )

    def get_best_away_odds(self) -> tuple[str, TeamOdds]:
        """
        Find the sportsbook offering the best odds for the away team.

        Returns:
            Tuple of (sportsbook_name, TeamOdds) with highest American odds
        """
        best_book = "opener"
        best_odds = self.opener_odds.away

        for book, odds in self.sportsbook_odds.items():
            if odds.away.american is not None:
                if best_odds.american is None or odds.away.american > best_odds.american:
                    best_book = book
                    best_odds = odds.away

        return best_book, best_odds

    def get_best_home_odds(self) -> tuple[str, TeamOdds]:
        """
        Find the sportsbook offering the best odds for the home team.

        Returns:
            Tuple of (sportsbook_name, TeamOdds) with highest American odds
        """
        best_book = "opener"
        best_odds = self.opener_odds.home

        for book, odds in self.sportsbook_odds.items():
            if odds.home.american is not None:
                if best_odds.american is None or odds.home.american > best_odds.american:
                    best_book = book
                    best_odds = odds.home

        return best_book, best_odds


@dataclass
class NBAOddsData:
    """
    Container for all scraped NBA odds data.

    Attributes:
        date: The date string shown on the page (e.g., "Friday, January 30, 2026")
        date_parsed: Parsed datetime object (if parsing succeeded)
        games: List of NBAGame objects with odds data
        scraped_at: Timestamp when the data was scraped
        source_url: URL the data was scraped from
    """
    date: str
    games: list[NBAGame] = field(default_factory=list)
    date_parsed: Optional[datetime] = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(ZoneInfo("UTC")))
    source_url: str = SBR_NBA_MONEYLINE_URL

    def __repr__(self) -> str:
        return (
            f"NBAOddsData(date='{self.date}', "
            f"games={len(self.games)}, "
            f"scraped_at={self.scraped_at.isoformat()})"
        )


# =============================================================================
# Custom Exceptions
# =============================================================================

class ScraperError(Exception):
    """Base exception for scraper-related errors."""
    pass


class FetchError(ScraperError):
    """Raised when fetching the page fails."""
    pass


class ParseError(ScraperError):
    """Raised when parsing the HTML fails."""
    pass


# =============================================================================
# Helper Functions
# =============================================================================

def parse_american_odds(odds_str: str) -> Optional[int]:
    """
    Parse an American odds string into an integer.

    Handles formats like:
    - "-150" -> -150
    - "+120" -> 120
    - "120" -> 120 (assumes positive if no sign)
    - "-" or "" -> None (no odds available)

    Args:
        odds_str: String representation of American odds

    Returns:
        Integer odds value, or None if parsing fails or odds unavailable

    Examples:
        >>> parse_american_odds("-150")
        -150
        >>> parse_american_odds("+120")
        120
        >>> parse_american_odds("-")
        None
    """
    # Clean up the string
    cleaned = odds_str.strip()

    # Handle empty or placeholder values
    if not cleaned or cleaned in ("-", "—", "N/A", ""):
        return None

    try:
        # Remove any non-numeric characters except minus/plus signs
        # This handles cases like "-150" or "+120"
        match = re.match(r"([+-]?\d+)", cleaned)
        if match:
            return int(match.group(1))
        return None
    except (ValueError, AttributeError):
        return None


def parse_odds_pair(odds_text: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse a combined odds string like "-150+120" into two odds values.

    SportsbookReview often displays odds as a single string with both
    teams' odds concatenated (away team first, home team second).

    Args:
        odds_text: Combined odds string (e.g., "-150+120", "+120-150")

    Returns:
        Tuple of (away_odds, home_odds) as integers, None for unavailable

    Examples:
        >>> parse_odds_pair("-150+120")
        (-150, 120)
        >>> parse_odds_pair("+120-150")
        (120, -150)
    """
    if not odds_text or odds_text.strip() in ("-", "—", ""):
        return None, None

    # Pattern: captures two odds values, each with optional +/- prefix
    # Examples: "-150+120", "+120-150", "-200+175"
    pattern = r"([+-]?\d+)([+-]\d+)"
    match = re.search(pattern, odds_text.replace(" ", ""))

    if match:
        away_odds = int(match.group(1))
        home_odds = int(match.group(2))
        return away_odds, home_odds

    # If pattern doesn't match, try to parse as single odds
    single_odds = parse_american_odds(odds_text)
    return single_odds, None


def fetch_page(url: str = SBR_NBA_MONEYLINE_URL) -> str:
    """
    Fetch the HTML content from SportsbookReview.

    Uses httpx for modern HTTP handling with proper headers to avoid
    being blocked by the website.

    Args:
        url: URL to fetch (defaults to NBA moneyline odds page)

    Returns:
        HTML content as string

    Raises:
        FetchError: If the request fails for any reason
    """
    logger.info(f"[SCRAPER] Fetching odds from: {url}")

    # Set up simple headers - complex headers trigger JS-heavy response without game data
    headers = {
        "User-Agent": USER_AGENT,
    }

    try:
        # Use httpx for the request with timeout and headers
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url, headers=headers)

            # Check for successful response
            response.raise_for_status()

            logger.info(f"[SCRAPER] Successfully fetched page ({len(response.text)} bytes)")
            return response.text

    except httpx.TimeoutException as e:
        raise FetchError(f"Request timed out after {REQUEST_TIMEOUT}s: {e}")
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP error {e.response.status_code}: {e}")
    except httpx.RequestError as e:
        raise FetchError(f"Request failed: {e}")


def parse_date(soup: BeautifulSoup) -> tuple[str, Optional[datetime]]:
    """
    Extract the date from the NBA Odds section header.

    The date typically appears as text like "Friday, January 30, 2026"
    following the "NBA Odds" heading.

    Args:
        soup: BeautifulSoup object of the page

    Returns:
        Tuple of (date_string, parsed_datetime)
        - date_string: The raw date text from the page
        - parsed_datetime: Parsed datetime object, or None if parsing fails

    Raises:
        ParseError: If the date section cannot be found
    """
    logger.debug("[SCRAPER] Parsing date from page")

    date_str = None

    # Method 1: Find h2 with exactly "NBA Odds" text and get the following text
    for h2 in soup.find_all("h2"):
        h2_text = h2.get_text(strip=True)
        if h2_text == "NBA Odds":
            # The date might be in a sibling element or following text
            next_sibling = h2.find_next_sibling()
            if next_sibling:
                sibling_text = next_sibling.get_text(strip=True)
                # Check if it looks like a date
                if re.match(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", sibling_text):
                    date_str = sibling_text
            break

    # Method 2: Look for date pattern in the page text
    if not date_str:
        # Search for date patterns like "Friday, January 30, 2026" or "Friday January 30 2026"
        page_text = soup.get_text()
        # More flexible pattern - commas optional
        date_pattern = r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})"
        match = re.search(date_pattern, page_text)
        if match:
            # Reconstruct date string in consistent format
            day_name, month, day, year = match.groups()
            date_str = f"{day_name}, {month} {day}, {year}"

    if not date_str:
        raise ParseError(
            "Could not find date in NBA Odds section. "
            "The page structure may have changed."
        )

    # Try to parse the date string into a datetime object
    parsed_date = None
    try:
        # Expected format: "Friday, January 30, 2026"
        parsed_date = datetime.strptime(date_str, "%A, %B %d, %Y")
        # Set timezone to EST/EDT (America/New_York)
        parsed_date = parsed_date.replace(tzinfo=ZoneInfo("America/New_York"))
    except ValueError:
        logger.warning(f"[SCRAPER] Could not parse date string: {date_str}")

    logger.info(f"[SCRAPER] Found date: {date_str}")
    return date_str, parsed_date


def parse_games(soup: BeautifulSoup) -> list[NBAGame]:
    """
    Parse all NBA games and their odds from the page.

    This function navigates the HTML structure to extract:
    - Game start times
    - Team names (away and home)
    - Opener odds
    - Current odds from each sportsbook

    Args:
        soup: BeautifulSoup object of the page

    Returns:
        List of NBAGame objects with populated odds data

    Raises:
        ParseError: If the game table cannot be found or parsed
    """
    logger.debug("[SCRAPER] Parsing games from page")
    games: list[NBAGame] = []

    # =========================================================================
    # STEP 1: Locate the odds table
    # =========================================================================
    # SportsbookReview uses various table structures. We look for the main
    # odds container which typically has a class containing "odds" or similar.

    # Find all table rows that contain game data
    # Games are typically in rows with time, teams, and odds cells
    game_rows = soup.find_all("tr", class_=re.compile(r"(game|event|matchup)", re.IGNORECASE))

    # If that doesn't work, try finding by data attributes or structure
    if not game_rows:
        # Alternative: find rows containing time patterns like "7:00 PM EST"
        all_rows = soup.find_all("tr")
        game_rows = [
            row for row in all_rows
            if re.search(r"\d{1,2}:\d{2}\s*(AM|PM)", row.get_text())
        ]

    # =========================================================================
    # STEP 2: Alternative parsing - find game containers
    # =========================================================================
    # If table rows don't work, try finding game containers by other means
    if not game_rows:
        # Look for divs or sections containing game information
        # This is a fallback for different page structures
        game_containers = soup.find_all(
            ["div", "section", "article"],
            class_=re.compile(r"(game|event|matchup|odds-row)", re.IGNORECASE)
        )

        if game_containers:
            logger.debug(f"[SCRAPER] Found {len(game_containers)} game containers")

    # =========================================================================
    # STEP 3: Extract data from each game row
    # =========================================================================
    # Parse time and team information from the text content
    # Page format:
    # "7:00 PM EST ... L.A. Lakers ... 112 (score) ... Washington ... 87 (score) ...
    #  -325 +260 (opener) ... [-474+360] (betmgm) ... [-521+400] (fanduel) ..."

    # Get all text and find game patterns
    page_text = soup.get_text(separator="\n")
    lines = [line.strip() for line in page_text.split("\n") if line.strip()]

    # Find time entries and their associated data
    time_pattern = r"(\d{1,2}:\d{2}\s*(?:AM|PM)\s*(?:EST|EDT|ET))"
    current_game = None
    current_time = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this line contains a game time
        time_match = re.search(time_pattern, line, re.IGNORECASE)
        if time_match:
            current_time = time_match.group(1).strip()
            i += 1
            continue

        # Skip non-relevant lines
        if not current_time:
            i += 1
            continue

        # Look for team names (skip "Matchup" links and scores)
        # Team names are typically title case and not purely numeric
        if (
            line not in ("Matchup", "-", "Time", "Rot", "Teams", "WAGERSOPENER")
            and not line.isdigit()
            and len(line) > 2
            and not re.match(r"^[+-]?\d+$", line)
            and not re.match(r"\[.*\]", line)
        ):
            # This might be a team name
            # Check if it looks like a team name (contains letters, reasonable length)
            if re.match(r"^[A-Za-z\.\s]+$", line) and 3 <= len(line) <= 20:
                if current_game is None:
                    # First team is away team
                    current_game = NBAGame(
                        start_time=current_time,
                        away_team=line,
                        home_team="",
                    )
                elif current_game.home_team == "":
                    # Second team is home team
                    current_game.home_team = line

                    # Now look for odds in subsequent lines
                    # We need to find VALID MONEYLINE ODDS patterns, not scores
                    # Valid odds: have +/- sign AND are typically 100-999 range
                    # Or paired odds in brackets like [-474+360]
                    j = i + 1
                    odds_pairs = []  # List of (away_odds, home_odds) tuples

                    while j < len(lines) and len(odds_pairs) < 7:  # opener + 6 books max
                        odds_line = lines[j]

                        # Break if we hit another time (next game)
                        if re.search(time_pattern, odds_line, re.IGNORECASE):
                            break

                        # Pattern 1: Combined odds in brackets like "[-474+360]" or "-474+360"
                        # This is the most reliable pattern for sportsbook odds
                        bracket_match = re.search(r"\[?([+-]\d{3,4})([+-]\d{3,4})\]?", odds_line)
                        if bracket_match:
                            away_odds = int(bracket_match.group(1))
                            home_odds = int(bracket_match.group(2))
                            odds_pairs.append((away_odds, home_odds))
                            j += 1
                            continue

                        # Pattern 2: Two separate odds with +/- signs on same line
                        # e.g., "-325 +260" or "-325+260"
                        two_odds_match = re.search(r"([+-]\d{3,4})\s*([+-]\d{3,4})", odds_line)
                        if two_odds_match:
                            away_odds = int(two_odds_match.group(1))
                            home_odds = int(two_odds_match.group(2))
                            odds_pairs.append((away_odds, home_odds))
                            j += 1
                            continue

                        # Pattern 3: Single signed odds on consecutive lines
                        # Must have explicit +/- sign to distinguish from scores
                        single_signed = re.match(r"^([+-]\d{3,4})$", odds_line)
                        if single_signed:
                            first_odds = int(single_signed.group(1))
                            # Look for the paired odds on next line
                            if j + 1 < len(lines):
                                next_line = lines[j + 1]
                                second_signed = re.match(r"^([+-]\d{3,4})$", next_line)
                                if second_signed:
                                    second_odds = int(second_signed.group(1))
                                    odds_pairs.append((first_odds, second_odds))
                                    j += 2
                                    continue

                        j += 1

                    # Assign odds to opener and sportsbooks
                    if len(odds_pairs) >= 1:
                        current_game.opener_odds = GameOdds(
                            away=TeamOdds(american=odds_pairs[0][0]),
                            home=TeamOdds(american=odds_pairs[0][1]),
                        )

                    # Remaining pairs are sportsbook odds
                    for k, (away, home) in enumerate(odds_pairs[1:]):
                        if k < len(SPORTSBOOK_NAMES) - 1:  # -1 to skip "opener"
                            book_name = SPORTSBOOK_NAMES[k + 1]  # +1 to skip "opener"
                            current_game.sportsbook_odds[book_name] = GameOdds(
                                away=TeamOdds(american=away),
                                home=TeamOdds(american=home),
                            )

                    games.append(current_game)
                    logger.debug(
                        f"[SCRAPER] Parsed game: {current_game.away_team} @ "
                        f"{current_game.home_team}"
                    )
                    current_game = None
                    current_time = None

        i += 1

    if not games:
        raise ParseError(
            "No games found on the page. "
            "The page structure may have changed or there may be no games scheduled."
        )

    logger.info(f"[SCRAPER] Successfully parsed {len(games)} games")
    return games


# =============================================================================
# Main Scraper Function
# =============================================================================

def scrape_nba_odds(url: str = SBR_NBA_MONEYLINE_URL) -> NBAOddsData:
    """
    Scrape NBA moneyline odds from SportsbookReview.

    This is the main entry point for the scraper. It fetches the page,
    parses the HTML, and returns structured data containing all games
    and their associated odds.

    Args:
        url: URL to scrape (defaults to NBA moneyline full game odds)

    Returns:
        NBAOddsData object containing:
        - date: The date shown on the page
        - games: List of NBAGame objects with odds from all sportsbooks

    Raises:
        FetchError: If fetching the page fails
        ParseError: If parsing the HTML fails

    Example:
        >>> data = scrape_nba_odds()
        >>> print(f"Found {len(data.games)} games for {data.date}")
        Found 9 games for Friday, January 30, 2026

        >>> for game in data.games:
        ...     print(f"{game.away_team} @ {game.home_team}: {game.opener_odds}")
    """
    logger.info("[SCRAPER] Starting NBA odds scrape")

    # Step 1: Fetch the page HTML
    html_content = fetch_page(url)

    # Step 2: Parse HTML with BeautifulSoup
    # Using 'html.parser' (built-in) for simplicity; 'lxml' is faster if needed
    soup = BeautifulSoup(html_content, "html.parser")

    # Step 3: Extract the date
    date_str, date_parsed = parse_date(soup)

    # Step 4: Extract all games and odds
    games = parse_games(soup)

    # Step 5: Build and return the result
    result = NBAOddsData(
        date=date_str,
        date_parsed=date_parsed,
        games=games,
        source_url=url,
    )

    logger.info(
        f"[SCRAPER] Scrape complete: {len(games)} games for {date_str}"
    )

    return result


# =============================================================================
# CLI Entry Point - For testing the scraper directly
# =============================================================================

if __name__ == "__main__":
    import sys

    # Set up logging for CLI usage
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print("SportsbookReview NBA Moneyline Odds Scraper")
    print("=" * 70)

    try:
        # Run the scraper
        data = scrape_nba_odds()

        print(f"\nDate: {data.date}")
        print(f"Games found: {len(data.games)}")
        print(f"Scraped at: {data.scraped_at.isoformat()}")
        print("-" * 70)

        # Display each game
        for i, game in enumerate(data.games, 1):
            print(f"\nGame {i}: {game.away_team} @ {game.home_team}")
            print(f"  Start time: {game.start_time}")
            print(f"  Opener odds: {game.opener_odds}")

            if game.sportsbook_odds:
                print("  Sportsbook odds:")
                for book, odds in game.sportsbook_odds.items():
                    print(f"    {book:12s}: {odds}")

            # Show best odds
            best_away_book, best_away = game.get_best_away_odds()
            best_home_book, best_home = game.get_best_home_odds()
            print(f"  Best {game.away_team} odds: {best_away} ({best_away_book})")
            print(f"  Best {game.home_team} odds: {best_home} ({best_home_book})")

    except ScraperError as e:
        print(f"\n✗ Scraper error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}", file=sys.stderr)
        raise
