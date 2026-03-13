"""
Report generation module for NBA Arbitrage Bot.

This module generates analysis reports and exports them to text files.
Each report is named with the date and time of creation.

Reports include:
1. Table 1: SportsbookReview odds (6 sportsbooks averaged)
2. Table 2: Polymarket prediction market prices

Usage:
    from nba_arb_bot.report import generate_report, export_report

    # Generate and export report
    filepath = export_report()
    print(f"Report saved to: {filepath}")
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nba_arb_bot.config import load_config
from nba_arb_bot.scraper import scrape_nba_odds, NBAOddsData
from nba_arb_bot.polymarket_scraper import scrape_polymarket_odds, PolymarketOddsData
from nba_arb_bot.probability import (
    average_odds,
    compute_fair_probabilities,
    spread_bid_to_implied_moneyline_ratio,
)
from nba_arb_bot.email_notifier import send_strong_signal_alert

# Module logger
logger = logging.getLogger(__name__)

# Default output directory for reports
DEFAULT_REPORTS_DIR = "reports"


def normalize_team_for_matching(name: str) -> str:
    """
    Normalize team name for matching between data sources.
    
    Args:
        name: Team name from any source
        
    Returns:
        Normalized lowercase name for comparison
    """
    # Mapping for common variations
    mappings = {
        "l.a. lakers": "los angeles lakers",
        "l.a. clippers": "los angeles clippers",
        "la lakers": "los angeles lakers",
        "la clippers": "los angeles clippers",
    }
    
    normalized = name.lower().strip()
    return mappings.get(normalized, normalized)


def find_polymarket_match(sbr_game, poly_games: list) -> tuple[object | None, float | None, float | None]:
    """
    Find matching Polymarket game for a SportsbookReview game.
    
    Args:
        sbr_game: Game from SportsbookReview
        poly_games: List of Polymarket games
        
    Returns:
        Tuple of (matched_poly_game, away_prob, home_prob) or (None, None, None) if no match
    """
    sbr_away = normalize_team_for_matching(sbr_game.away_team)
    sbr_home = normalize_team_for_matching(sbr_game.home_team)
    
    for poly_game in poly_games:
        poly_away = normalize_team_for_matching(poly_game.away_team)
        poly_home = normalize_team_for_matching(poly_game.home_team)
        
        # Match by team names (both away and home must match)
        if sbr_away == poly_away and sbr_home == poly_home:
            return (poly_game, poly_game.away_prob, poly_game.home_prob)
        
        # Also try partial matching (city name only)
        sbr_away_city = sbr_away.split()[0]
        sbr_home_city = sbr_home.split()[0]
        poly_away_city = poly_away.split()[0]
        poly_home_city = poly_home.split()[0]
        
        if sbr_away_city == poly_away_city and sbr_home_city == poly_home_city:
            return (poly_game, poly_game.away_prob, poly_game.home_prob)
    
    return (None, None, None)


def generate_combined_table(sbr_data: NBAOddsData, poly_data: PolymarketOddsData) -> tuple[list[str], list[dict]]:
    """
    Generate combined table with SportsbookReview and Polymarket data.

    Args:
        sbr_data: Scraped NBA odds data from SportsbookReview
        poly_data: Scraped Polymarket odds data

    Returns:
        Tuple of (list of formatted lines, list of analysis data for conclusion)
    """
    lines = []
    analysis_data = []  # Collect data for proposed actions
    
    # Table Header
    lines.append("")
    header = (
        f"{'#':<3} {'Time':<12} {'Away Team':<15} {'Home Team':<15} "
        f"{'Opener Fair %':<18} {'Current Fair %':<18} {'Spread→ML %':<20} {'Polymarket %':<18} "
        f"{'Diff % (opener)':<18} {'Diff % (current)':<18} {'Diff % Spread':<18} {'Signal':<14} {'Score':<18}"
    )
    lines.append(header)
    lines.append("-" * 234)
    
    # Table rows
    for i, game in enumerate(sbr_data.games, 1):
        # Get opener odds
        opener_away = game.opener_odds.away.american
        opener_home = game.opener_odds.home.american
        
        # Calculate opener fair probabilities
        opener_away_fair = None
        opener_home_fair = None
        if opener_away and opener_home:
            opener_away_fair, opener_home_fair = compute_fair_probabilities(opener_away, opener_home)
            opener_fair_str = f"{opener_away_fair:.2%}/{opener_home_fair:.2%}"
        else:
            opener_fair_str = "-"
        
        # Collect current odds for averaging
        away_odds_list = []
        home_odds_list = []
        
        for book, odds in game.sportsbook_odds.items():
            if odds.away.american:
                away_odds_list.append(odds.away.american)
            if odds.home.american:
                home_odds_list.append(odds.home.american)
        
        avg_away = average_odds(away_odds_list) if away_odds_list else None
        avg_home = average_odds(home_odds_list) if home_odds_list else None
        
        # Find matching Polymarket data
        poly_game, poly_away, poly_home = find_polymarket_match(game, poly_data.games)
        if poly_away is not None and poly_home is not None:
            poly_str = f"{poly_away:.2%}/{poly_home:.2%}"
        else:
            poly_str = "-"
        
        # Calculate diff: Polymarket % minus Opener Fair %
        diff_away = None
        diff_home = None
        if opener_away_fair is not None and poly_away is not None:
            diff_away = poly_away - opener_away_fair
            diff_home = poly_home - opener_home_fair
            # Format with sign (+ or -)
            diff_away_str = f"{diff_away:+.2%}"
            diff_home_str = f"{diff_home:+.2%}"
            diff_str = f"{diff_away_str}/{diff_home_str}"
        else:
            diff_str = "-"
        
        if avg_away and avg_home:
            away_fair, home_fair = compute_fair_probabilities(avg_away, avg_home)
            current_fair_str = f"{away_fair:.2%}/{home_fair:.2%}"
            
            # Calculate Diff % (current): Polymarket % minus Current Fair %
            # Negative = Polymarket undervalues compared to current books (potential value)
            diff_current_away = None
            diff_current_home = None
            if poly_away is not None and poly_home is not None:
                diff_current_away = poly_away - away_fair
                diff_current_home = poly_home - home_fair
                diff_current_away_str = f"{diff_current_away:+.2%}"
                diff_current_home_str = f"{diff_current_home:+.2%}"
                diff_current_str = f"{diff_current_away_str}/{diff_current_home_str}"
            else:
                diff_current_str = "-"

            # Convert Polymarket spread bids (if present) into a moneyline-equivalent ratio.
            # Displayed as Away/Home, e.g. "65.99%/34.01%". This is model-based (Normal margin).
            spread_ml_str = "-"
            spread_ml_away_prob: float | None = None
            spread_ml_home_prob: float | None = None
            diff_spread_away: float | None = None
            diff_spread_home: float | None = None
            try:
                if (
                    poly_game is not None
                    and getattr(poly_game, "spread_number", None) is not None
                    and getattr(poly_game, "away_spread_line", None) is not None
                    and getattr(poly_game, "home_spread_line", None) is not None
                    and getattr(poly_game, "away_spread_bid", None) is not None
                    and getattr(poly_game, "home_spread_bid", None) is not None
                ):
                    spread_number = float(poly_game.spread_number)
                    away_line = float(poly_game.away_spread_line)
                    home_line = float(poly_game.home_spread_line)
                    away_bid = float(poly_game.away_spread_bid)
                    home_bid = float(poly_game.home_spread_bid)

                    # Determine favorite/underdog as required by the model:
                    # Team A is favorite at -spread_number, Team B is dog at +spread_number.
                    if away_line < 0 and home_line > 0:
                        fav_ratio, dog_ratio = spread_bid_to_implied_moneyline_ratio(
                            team_a_spread_bid=away_bid,
                            team_b_spread_bid=home_bid,
                            spread_number=spread_number,
                        )
                        spread_ml_away_prob = fav_ratio / 100.0
                        spread_ml_home_prob = dog_ratio / 100.0
                        spread_ml_str = f"{fav_ratio:.2f}%/{dog_ratio:.2f}%"
                    elif home_line < 0 and away_line > 0:
                        fav_ratio, dog_ratio = spread_bid_to_implied_moneyline_ratio(
                            team_a_spread_bid=home_bid,
                            team_b_spread_bid=away_bid,
                            spread_number=spread_number,
                        )
                        # Convert back to Away/Home display order
                        spread_ml_away_prob = dog_ratio / 100.0
                        spread_ml_home_prob = fav_ratio / 100.0
                        spread_ml_str = f"{dog_ratio:.2f}%/{fav_ratio:.2f}%"
            except Exception:
                # Keep report resilient if Polymarket layout changes or inputs are degenerate.
                spread_ml_str = "-"
                spread_ml_away_prob = None
                spread_ml_home_prob = None

            # Diff % Spread: Polymarket % minus Spread→ML %
            diff_spread_str = "-"
            if (
                spread_ml_away_prob is not None
                and spread_ml_home_prob is not None
                and poly_away is not None
                and poly_home is not None
            ):
                diff_spread_away = poly_away - spread_ml_away_prob
                diff_spread_home = poly_home - spread_ml_home_prob
                diff_spread_str = f"{diff_spread_away:+.2%}/{diff_spread_home:+.2%}"
            
            # Calculate line movement: Current Fair % - Opener Fair %
            away_line_move = away_fair - opener_away_fair if opener_away_fair is not None else None
            home_line_move = home_fair - opener_home_fair if opener_home_fair is not None else None
            
            # Determine Signal for each team based on rules:
            # DNT: abs(Current - Opener) >= 5%
            # VStrong: Diff % (opener) <= -3% AND Diff % (current) <= -1.5% AND Diff % (spread) <= -1%
            # Strong: Diff % (opener) <= -3% AND Diff % (current) <= -0.5% AND Diff % (spread) <= -0.5%
            # Fair: Diff % (opener) <= -3% AND Diff % (current) <= 0% AND Diff % (spread) <= 0%
            # Weak: Diff % (opener) <= -2.0% AND Diff % (spread) <= 0
            away_signal = "-"
            home_signal = "-"
            if diff_away is not None and diff_current_away is not None:
                # DNT: line move >= 5%
                if away_line_move is not None and abs(away_line_move) >= 0.05:
                    away_signal = "DNT"
                elif (
                    diff_spread_away is not None
                    and diff_away <= -0.03
                    and diff_current_away <= -0.015
                    and diff_spread_away <= -0.01
                ):
                    away_signal = "VStrong"
                elif (
                    diff_spread_away is not None
                    and diff_away <= -0.03
                    and diff_current_away <= -0.005
                    and diff_spread_away <= -0.005
                ):
                    away_signal = "Strong"
                elif (
                    diff_spread_away is not None
                    and diff_away <= -0.03
                    and diff_current_away <= 0
                    and diff_spread_away <= 0
                ):
                    away_signal = "Fair"
                elif diff_spread_away is not None and diff_away <= -0.02 and diff_spread_away <= 0:
                    away_signal = "Weak"
            
            if diff_home is not None and diff_current_home is not None:
                if home_line_move is not None and abs(home_line_move) >= 0.05:
                    home_signal = "DNT"
                elif (
                    diff_spread_home is not None
                    and diff_home <= -0.03
                    and diff_current_home <= -0.015
                    and diff_spread_home <= -0.01
                ):
                    home_signal = "VStrong"
                elif (
                    diff_spread_home is not None
                    and diff_home <= -0.03
                    and diff_current_home <= -0.005
                    and diff_spread_home <= -0.005
                ):
                    home_signal = "Strong"
                elif (
                    diff_spread_home is not None
                    and diff_home <= -0.03
                    and diff_current_home <= 0
                    and diff_spread_home <= 0
                ):
                    home_signal = "Fair"
                elif diff_spread_home is not None and diff_home <= -0.02 and diff_spread_home <= 0:
                    home_signal = "Weak"
            
            signal_str = f"{away_signal}/{home_signal}"

            # Score (Away/Home):
            # score = 1.0*Diff%(current) + 0.7*Diff%(spread) + 0.4*Diff%(opener)
            #       + max(0, abs(Current Fair% − Opener Fair%) − 3%) × 0.5
            score_str = "-"
            score_away: float | None = None
            score_home: float | None = None
            if (
                diff_current_away is not None
                and diff_current_home is not None
                and diff_away is not None
                and diff_home is not None
                and diff_spread_away is not None
                and diff_spread_home is not None
            ):
                score_away = 1.0 * diff_current_away + 0.7 * diff_spread_away + 0.4 * diff_away
                score_home = 1.0 * diff_current_home + 0.7 * diff_spread_home + 0.4 * diff_home

                if away_line_move is not None:
                    score_away += max(0.0, abs(away_line_move) - 0.03) * 0.5
                if home_line_move is not None:
                    score_home += max(0.0, abs(home_line_move) - 0.03) * 0.5

                # Display as plain numbers (percentage-points), no '%' symbol.
                score_str = f"{score_away * 100:+.2f}/{score_home * 100:+.2f}"
            
            # Collect analysis data for conclusion
            analysis_data.append({
                "away_team": game.away_team,
                "home_team": game.home_team,
                "away_signal": away_signal,
                "home_signal": home_signal,
                "diff_current_away": diff_current_away,
                "diff_current_home": diff_current_home,
                "diff_away": diff_away,
                "diff_home": diff_home,
                "score_away": score_away,
                "score_home": score_home,
            })
            
            row = (
                f"{i:<3} {game.start_time:<12} {game.away_team:<15} {game.home_team:<15} "
                f"{opener_fair_str:<18} {current_fair_str:<18} {spread_ml_str:<20} {poly_str:<18} "
                f"{diff_str:<18} {diff_current_str:<18} {diff_spread_str:<18} {signal_str:<14} {score_str:<18}"
            )
            lines.append(row)
    
    lines.append("-" * 214)
    
    return lines, analysis_data


def generate_proposed_actions(analysis_data: list[dict]) -> tuple[list[str], list[str]]:
    """
    Generate proposed actions based on Signal column.
    
    Rules:
    - DNT: abs(Current - Opener) >= 5%
    - VStrong: Diff % (opener) <= -3% AND Diff % (current) <= -1.5% AND Diff % (spread) <= -1%
    - Strong: Diff % (opener) <= -3% AND Diff % (current) <= -0.5% AND Diff % (spread) <= -0.5%
    - Fair: Diff % (opener) <= -3% AND Diff % (current) <= 0% AND Diff % (spread) <= 0%
    - Weak: Diff % (opener) <= -2.0% AND Diff % (spread) <= 0
    
    Args:
        analysis_data: List of analysis dictionaries from generate_combined_table
        
    Returns:
        Tuple of (list of formatted lines, list of strong teams for email alert)
    """
    dnt_teams = []
    vstrong_teams = []
    strong_teams = []
    fair_teams = []
    weak_teams = []
    
    for data in analysis_data:
        # Check away team signal
        if data.get("away_signal") == "DNT":
            dnt_teams.append(data["away_team"])
        elif data.get("away_signal") == "VStrong":
            vstrong_teams.append(data["away_team"])
        elif data.get("away_signal") == "Strong":
            strong_teams.append(data["away_team"])
        elif data.get("away_signal") == "Fair":
            fair_teams.append(data["away_team"])
        elif data.get("away_signal") == "Weak":
            weak_teams.append(data["away_team"])
        
        # Check home team signal
        if data.get("home_signal") == "DNT":
            dnt_teams.append(data["home_team"])
        elif data.get("home_signal") == "VStrong":
            vstrong_teams.append(data["home_team"])
        elif data.get("home_signal") == "Strong":
            strong_teams.append(data["home_team"])
        elif data.get("home_signal") == "Fair":
            fair_teams.append(data["home_team"])
        elif data.get("home_signal") == "Weak":
            weak_teams.append(data["home_team"])
    
    lines = []
    lines.append("")
    lines.append("=" * 190)
    lines.append("PROPOSED ACTION")
    lines.append("=" * 190)
    lines.append("")
    lines.append(f"DNT     : {', '.join(dnt_teams) if dnt_teams else 'None'}")
    lines.append(f"VStrong : {', '.join(vstrong_teams) if vstrong_teams else 'None'}")
    lines.append(f"Strong  : {', '.join(strong_teams) if strong_teams else 'None'}")
    lines.append(f"Fair    : {', '.join(fair_teams) if fair_teams else 'None'}")
    lines.append(f"Weak    : {', '.join(weak_teams) if weak_teams else 'None'}")

    # Top 5 Score summary (ascending order)
    team_scores: list[tuple[str, float]] = []
    for data in analysis_data:
        if data.get("score_away") is not None:
            team_scores.append((data["away_team"], data["score_away"]))
        if data.get("score_home") is not None:
            team_scores.append((data["home_team"], data["score_home"]))
    team_scores.sort(key=lambda x: x[1])
    top5 = team_scores[:5]
    if top5:
        top5_str = " < ".join(f"{team} ({score * 100:+.2f})" for team, score in top5)
        lines.append(f"Top 5  : {top5_str}")
    else:
        lines.append("Top 5  : None")

    lines.append("")
    lines.append("Criteria:")
    lines.append("  DNT     = abs(Current - Opener) >= 5%")
    lines.append("  VStrong = Diff % (opener) <= -3% AND Diff % (current) <= -1.5% AND Diff % (spread) <= -1%")
    lines.append("  Strong  = Diff % (opener) <= -3% AND Diff % (current) <= -0.5% AND Diff % (spread) <= -0.5%")
    lines.append("  Fair    = Diff % (opener) <= -3% AND Diff % (current) <= 0% AND Diff % (spread) <= 0%")
    lines.append("  Weak    = Diff % (opener) <= -2.0% AND Diff % (spread) <= 0")
    
    return lines, vstrong_teams + strong_teams


def generate_report(sbr_data: NBAOddsData, poly_data: PolymarketOddsData) -> tuple[str, list[str]]:
    """
    Generate the complete analysis report with combined table.

    Args:
        sbr_data: Scraped NBA odds data from SportsbookReview
        poly_data: Scraped data from Polymarket

    Returns:
        Tuple of (formatted report string, list of strong teams for email alert)
    """
    lines = []
    
    # Report Header
    lines.append("=" * 190)
    lines.append("NBA Moneyline Odds - Fair Probability Analysis")
    lines.append("=" * 190)
    lines.append(f"Date: {sbr_data.date}")
    lines.append(f"Games: {len(sbr_data.games)}")
    lines.append(f"Generated at: {sbr_data.scraped_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("=" * 190)
    
    # Combined Table
    table_lines, analysis_data = generate_combined_table(sbr_data, poly_data)
    lines.extend(table_lines)
    
    # Report Footer with legend
    lines.append("")
    lines.append("Format: Away/Home")
    lines.append("Opener Fair %    : De-vigged opening line from SportsbookReview")
    lines.append("Current Fair %   : De-vigged average of 6 sportsbooks (BetMGM, FanDuel, Caesars, Bet365, DraftKings, Fanatics)")
    lines.append("Polymarket %     : Prediction market implied probability from polymarket.com")
    lines.append("Diff % (opener)  : Polymarket % minus Opener Fair %")
    lines.append("Diff % (current) : Polymarket % minus Current Fair %")
    lines.append("Spread→ML %      : Model-implied moneyline % from Polymarket spread bids (de-vigged), Normal margin (σ≈12)")
    lines.append("Diff % Spread    : Polymarket % minus Spread→ML %")
    lines.append("Score            : 1.0*Diff%(current) + 0.7*Diff%(spread) + 0.4*Diff%(opener) + max(0, abs(Current−Opener)−3%)×0.5, Away/Home")
    lines.append("Line move        : Current Fair % minus Opener Fair % (line movement since open)")
    
    # Proposed Actions conclusion
    action_lines, strong_teams = generate_proposed_actions(analysis_data)
    lines.extend(action_lines)
    
    lines.append("=" * 190)
    
    return "\n".join(lines), strong_teams


def export_report(
    sbr_data: NBAOddsData | None = None,
    poly_data: PolymarketOddsData | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """
    Generate and export the analysis report to a text file.

    The filename includes the date and time of creation:
    nba_odds_report_YYYY-MM-DD_HH-MM-SS.txt

    Args:
        sbr_data: Optional pre-scraped SportsbookReview data.
        poly_data: Optional pre-scraped Polymarket data.
        output_dir: Directory to save report. Defaults to 'reports/' in project root.

    Returns:
        Path to the saved report file
    """
    config = load_config()
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    
    # Scrape SportsbookReview data if not provided
    if sbr_data is None:
        logger.info("[REPORT] Scraping SportsbookReview odds data...")
        sbr_data = scrape_nba_odds()
    
    # Get Polymarket data if not provided
    if poly_data is None:
        logger.info("[REPORT] Getting Polymarket odds data...")
        poly_data = scrape_polymarket_odds()
    
    # Generate report content
    logger.info("[REPORT] Generating report...")
    report_content, strong_teams = generate_report(sbr_data, poly_data)
    
    # Send email alert if there are VStrong or Strong signals
    if strong_teams:
        logger.info(f"[REPORT] VStrong/Strong signals detected: {', '.join(strong_teams)}")
        send_strong_signal_alert(report_content, strong_teams)
    
    # Determine output directory
    if output_dir is None:
        # Use project root / reports
        project_root = Path(__file__).resolve().parent.parent.parent
        output_dir = project_root / DEFAULT_REPORTS_DIR
    else:
        output_dir = Path(output_dir)
    
    # Create directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"nba_odds_report_{timestamp}.txt"
    filepath = output_dir / filename
    
    # Write report to file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    logger.info(f"[REPORT] Report saved to: {filepath}")
    
    return filepath


def run_report_job() -> None:
    """
    Run the report generation job.
    
    This function is called by the scheduler to generate and export a report.
    It handles all errors gracefully and logs the outcome.
    """
    logger.info("[REPORT] Starting report generation job...")
    
    try:
        filepath = export_report()
        logger.info(f"[REPORT] Job completed successfully. Report: {filepath}")
    except Exception as e:
        logger.error(f"[REPORT] Job failed: {e}")
        raise


# CLI entry point
if __name__ == "__main__":
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    
    print("Generating NBA Odds Report...")
    try:
        filepath = export_report()
        print(f"\nReport saved to: {filepath}")
        
        # Also print to console
        print("\n" + "=" * 50)
        print("Report Preview:")
        print("=" * 50)
        with open(filepath, "r") as f:
            print(f.read())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
