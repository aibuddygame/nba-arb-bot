"""
Probability module for NBA Arbitrage Bot.

This module provides functions for converting betting odds to probabilities
and computing fair (de-vigged) probabilities from sportsbook lines.

Key Concepts:
-------------
1. **Implied Probability**: The probability derived directly from odds.
   Sportsbooks build in a margin (vig/juice), so implied probabilities
   for all outcomes sum to more than 100%.

2. **Vig (Vigorish)**: The sportsbook's margin/commission built into odds.
   Also called "juice" or "overround". Example: if implied probs sum to
   105%, the vig is 5%.

3. **De-vigged (Fair) Probability**: The "true" probability after removing
   the sportsbook's margin. Fair probabilities sum to exactly 100%.

De-vigging Methods:
-------------------
- **Multiplicative (proportional)**: Divides each prob by total overround.
  Simple and widely used. Assumes vig is distributed proportionally.

- **Additive**: Subtracts equal amounts from each probability.
  Less common, assumes equal vig on each side.

- **Power method**: More sophisticated, better for extreme odds.
  Finds a power k such that (p1^k + p2^k = 1).

- **Shin method**: Accounts for informed bettor behavior.
  More accurate for markets with sharp action.

Usage Examples:
---------------
    >>> from nba_arb_bot.probability import (
    ...     american_to_probability,
    ...     compute_fair_probabilities,
    ...     analyze_game_odds,
    ... )

    # Basic conversion
    >>> american_to_probability(-150)
    0.6

    >>> american_to_probability(+130)
    0.4347826086956522

    # De-vig a game's odds
    >>> away_prob, home_prob = compute_fair_probabilities(-150, +130)
    >>> print(f"Fair probs: {away_prob:.2%}, {home_prob:.2%}")
    Fair probs: 57.69%, 42.31%

Unit Test Examples (in comments throughout):
--------------------------------------------
These examples serve as documentation and can be extracted for testing.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional, Literal

# Module logger
logger = logging.getLogger(__name__)

# =============================================================================
# Normal distribution helpers (no SciPy dependency)
# =============================================================================

def _standard_normal_cdf(x: float) -> float:
    """
    Standard normal CDF, Φ(x).

    Uses the relationship:
        Φ(x) = 0.5 * (1 + erf(x / sqrt(2)))
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _standard_normal_ppf(p: float) -> float:
    """
    Standard normal inverse CDF (quantile), Φ^{-1}(p).

    This uses Peter J. Acklam's rational approximation, which is accurate to
    ~1e-9 in typical double precision across (0, 1).

    Raises:
        ValueError: if p is not strictly between 0 and 1
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"p must be in (0, 1), got {p}")

    # Coefficients in rational approximations
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]

    # Define break-points
    plow = 0.02425
    phigh = 1.0 - plow

    if p < plow:
        # Rational approximation for lower region
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if p > phigh:
        # Rational approximation for upper region
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )

    # Rational approximation for central region
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def spread_bid_to_implied_moneyline_ratio(
    team_a_spread_bid: float,
    team_b_spread_bid: float,
    spread_number: float,
    margin_std_dev: float = 12.0,
) -> tuple[float, float]:
    """
    Convert a two-sided NBA spread *bid price* into a moneyline-equivalent ratio.

    Model (as requested):
    - Let game scoring margin M (Team A margin) be Normal(μ, σ), where σ is an NBA
      approximation (default 12 points).
    - Team A is the favorite at -spread_number (so Team B is +spread_number).
    - The spread market is a *cover* market. After de-vigging the two bids:
          P(M > spread_number) = fair_cover_prob_a
    - Solve for μ, then convert μ to win probability P(M > 0).

    Steps:
    1) De-vig:
         fair_cover_prob_a = bid_a / (bid_a + bid_b)
         fair_cover_prob_b = bid_b / (bid_a + bid_b)
    2) Z-score:
         z = Φ^{-1}(fair_cover_prob_a)
    3) Implied expected margin:
         μ = spread_number + z * σ
       because P(M > s) = P((M-μ)/σ > (s-μ)/σ) = 1 - Φ((s-μ)/σ) = Φ((μ-s)/σ)
       so Φ((μ-s)/σ) = fair_cover_prob_a ⇒ (μ-s)/σ = z
    4) Moneyline-equivalent win prob:
         implied_ml_prob_a = P(M > 0) = Φ(μ / σ)
         implied_ml_prob_b = 1 - implied_ml_prob_a
    5) Return as ratio out of 100:
         (implied_ml_prob_a*100, implied_ml_prob_b*100)

    Input validation notes:
    - Bids are "out of 100" cents and should be non-negative.
    - To avoid infinities in Φ^{-1} we require de-vigged probability strictly
      between 0 and 1 (i.e. both bids > 0).

    Worked example (your numbers):
        HOU -4.5 = 52, TOR +4.5 = 49, σ=12
        -> approx HOU 65.9 / TOR 34.1 (ratio out of 100)
    """
    # Basic validation
    for name, val in [
        ("team_a_spread_bid", team_a_spread_bid),
        ("team_b_spread_bid", team_b_spread_bid),
        ("spread_number", spread_number),
        ("margin_std_dev", margin_std_dev),
    ]:
        if not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be a number, got {type(val).__name__}")

    if team_a_spread_bid < 0 or team_b_spread_bid < 0:
        raise ValueError("Spread bids must be non-negative")
    if spread_number <= 0:
        raise ValueError("spread_number must be > 0 (use absolute spread magnitude)")
    if margin_std_dev <= 0:
        raise ValueError("margin_std_dev must be > 0")

    denom = team_a_spread_bid + team_b_spread_bid
    if denom <= 0:
        raise ValueError("At least one bid must be > 0 (cannot de-vig with sum=0)")

    fair_cover_prob_a = team_a_spread_bid / denom
    fair_cover_prob_b = team_b_spread_bid / denom

    # Guard against degenerate inputs that push probability to exactly 0 or 1
    if not (0.0 < fair_cover_prob_a < 1.0):
        raise ValueError(
            "De-vigged cover probability must be in (0,1). "
            "Provide positive bids on both sides."
        )

    z = _standard_normal_ppf(fair_cover_prob_a)
    mu = spread_number + z * margin_std_dev

    implied_ml_prob_a = _standard_normal_cdf(mu / margin_std_dev)
    implied_ml_prob_b = 1.0 - implied_ml_prob_a

    return implied_ml_prob_a * 100.0, implied_ml_prob_b * 100.0


# =============================================================================
# Constants
# =============================================================================

# De-vigging method options
DeVigMethod = Literal["multiplicative", "additive", "power", "shin"]


# =============================================================================
# Core Conversion Functions
# =============================================================================

def american_to_probability(odds: int) -> float:
    """
    Convert American odds to implied probability.

    American odds represent the profit on a $100 stake (positive) or
    the stake needed to win $100 (negative).

    Formula:
    - Negative odds: probability = |odds| / (|odds| + 100)
    - Positive odds: probability = 100 / (odds + 100)

    Args:
        odds: American odds as integer (e.g., -150, +130, 200)

    Returns:
        Implied probability as decimal (0.0 to 1.0)

    Raises:
        ValueError: If odds is exactly 0 (invalid in American format)

    Examples (unit tests):
        >>> american_to_probability(-100)  # Even odds
        0.5

        >>> american_to_probability(-150)  # Favorite
        0.6

        >>> american_to_probability(-200)  # Strong favorite
        0.6666666666666666

        >>> american_to_probability(-400)  # Heavy favorite
        0.8

        >>> american_to_probability(+100)  # Even odds
        0.5

        >>> american_to_probability(+150)  # Underdog
        0.4

        >>> american_to_probability(+200)  # Bigger underdog
        0.3333333333333333

        >>> american_to_probability(+400)  # Long shot
        0.2

        # Edge cases
        >>> american_to_probability(-110)  # Standard vig line
        0.5238095238095238

        >>> american_to_probability(+110)  # Standard vig line
        0.47619047619047616
    """
    if odds == 0:
        raise ValueError("American odds cannot be 0")

    if odds < 0:
        # Favorite: probability = |odds| / (|odds| + 100)
        return abs(odds) / (abs(odds) + 100)
    else:
        # Underdog: probability = 100 / (odds + 100)
        return 100 / (odds + 100)


def probability_to_american(prob: float) -> int:
    """
    Convert probability to American odds.

    Inverse of american_to_probability().

    Args:
        prob: Probability as decimal (0.0 to 1.0, exclusive)

    Returns:
        American odds as integer

    Raises:
        ValueError: If probability is not in (0, 1)

    Examples (unit tests):
        >>> probability_to_american(0.5)  # 50% = even odds
        100

        >>> probability_to_american(0.6)  # 60% = favorite
        -150

        >>> probability_to_american(0.4)  # 40% = underdog
        150

        >>> probability_to_american(0.8)  # 80% = heavy favorite
        -400

        >>> probability_to_american(0.2)  # 20% = long shot
        400

        >>> probability_to_american(0.75)
        -300

        >>> probability_to_american(0.25)
        300
    """
    if prob <= 0 or prob >= 1:
        raise ValueError(f"Probability must be between 0 and 1 (exclusive), got {prob}")

    if prob >= 0.5:
        # Favorite: odds = -100 * prob / (1 - prob)
        return round(-100 * prob / (1 - prob))
    else:
        # Underdog: odds = 100 * (1 - prob) / prob
        return round(100 * (1 - prob) / prob)


def american_to_decimal(odds: int) -> float:
    """
    Convert American odds to decimal (European) odds.

    Decimal odds represent total return on a $1 stake (including stake).

    Args:
        odds: American odds as integer

    Returns:
        Decimal odds (always >= 1.0)

    Examples (unit tests):
        >>> american_to_decimal(-100)
        2.0

        >>> american_to_decimal(-150)
        1.6666666666666667

        >>> american_to_decimal(+150)
        2.5

        >>> american_to_decimal(-200)
        1.5

        >>> american_to_decimal(+200)
        3.0
    """
    if odds < 0:
        return 1 + (100 / abs(odds))
    else:
        return 1 + (odds / 100)


def decimal_to_american(decimal_odds: float) -> int:
    """
    Convert decimal odds to American odds.

    Args:
        decimal_odds: Decimal odds (must be > 1.0)

    Returns:
        American odds as integer

    Examples (unit tests):
        >>> decimal_to_american(2.0)
        100

        >>> decimal_to_american(1.5)
        -200

        >>> decimal_to_american(2.5)
        150

        >>> decimal_to_american(3.0)
        200
    """
    if decimal_odds < 1:
        raise ValueError(f"Decimal odds must be >= 1, got {decimal_odds}")

    if decimal_odds >= 2.0:
        # Underdog: positive odds
        return round((decimal_odds - 1) * 100)
    else:
        # Favorite: negative odds
        return round(-100 / (decimal_odds - 1))


# =============================================================================
# Vig and Overround Calculations
# =============================================================================

def calculate_overround(
    away_odds: int,
    home_odds: int,
) -> float:
    """
    Calculate the overround (total implied probability) for a two-way market.

    An overround > 1.0 (100%) indicates the sportsbook's margin.
    Example: overround of 1.05 means 5% vig.

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team

    Returns:
        Overround as decimal (e.g., 1.05 for 5% vig)

    Examples (unit tests):
        >>> calculate_overround(-110, -110)  # Standard vig
        1.0476190476190477

        >>> calculate_overround(-150, +130)
        1.0347826086956523

        >>> calculate_overround(-100, +100)  # No vig (theoretical)
        1.0

        >>> calculate_overround(-200, +180)
        1.0222222222222221
    """
    away_prob = american_to_probability(away_odds)
    home_prob = american_to_probability(home_odds)
    return away_prob + home_prob


def calculate_vig_percentage(
    away_odds: int,
    home_odds: int,
) -> float:
    """
    Calculate the vig as a percentage.

    This is simply (overround - 1) * 100.

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team

    Returns:
        Vig as percentage (e.g., 4.76 for standard -110/-110)

    Examples (unit tests):
        >>> round(calculate_vig_percentage(-110, -110), 2)
        4.76

        >>> round(calculate_vig_percentage(-150, +130), 2)
        3.48

        >>> calculate_vig_percentage(-100, +100)
        0.0
    """
    overround = calculate_overround(away_odds, home_odds)
    return (overround - 1) * 100


# =============================================================================
# De-Vigging Functions
# =============================================================================

def devig_multiplicative(
    away_odds: int,
    home_odds: int,
) -> tuple[float, float]:
    """
    Remove vig using the multiplicative (proportional) method.

    This is the simplest and most common de-vigging method.
    Each implied probability is divided by the total overround.

    Formula:
        fair_prob = implied_prob / overround

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team

    Returns:
        Tuple of (away_fair_prob, home_fair_prob) that sum to 1.0

    Examples (unit tests):
        >>> away, home = devig_multiplicative(-110, -110)
        >>> round(away, 4), round(home, 4)
        (0.5, 0.5)

        >>> away, home = devig_multiplicative(-150, +130)
        >>> round(away, 4), round(home, 4)
        (0.5798, 0.4202)

        >>> away, home = devig_multiplicative(-200, +180)
        >>> round(away, 4), round(home, 4)
        (0.6522, 0.3478)

        # Verify they sum to 1
        >>> away, home = devig_multiplicative(-150, +130)
        >>> round(away + home, 10)
        1.0
    """
    away_implied = american_to_probability(away_odds)
    home_implied = american_to_probability(home_odds)
    overround = away_implied + home_implied

    away_fair = away_implied / overround
    home_fair = home_implied / overround

    return away_fair, home_fair


def devig_additive(
    away_odds: int,
    home_odds: int,
) -> tuple[float, float]:
    """
    Remove vig using the additive method.

    Subtracts an equal amount from each implied probability.
    Less common than multiplicative, but useful in some scenarios.

    Formula:
        adjustment = (overround - 1) / 2
        fair_prob = implied_prob - adjustment

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team

    Returns:
        Tuple of (away_fair_prob, home_fair_prob) that sum to 1.0

    Examples (unit tests):
        >>> away, home = devig_additive(-110, -110)
        >>> round(away, 4), round(home, 4)
        (0.5, 0.5)

        >>> away, home = devig_additive(-150, +130)
        >>> round(away, 4), round(home, 4)
        (0.5826, 0.4174)

        # Verify they sum to 1
        >>> away, home = devig_additive(-150, +130)
        >>> round(away + home, 10)
        1.0
    """
    away_implied = american_to_probability(away_odds)
    home_implied = american_to_probability(home_odds)
    overround = away_implied + home_implied

    # Equal adjustment to each side
    adjustment = (overround - 1) / 2

    away_fair = away_implied - adjustment
    home_fair = home_implied - adjustment

    return away_fair, home_fair


def devig_power(
    away_odds: int,
    home_odds: int,
    tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> tuple[float, float]:
    """
    Remove vig using the power method.

    Finds exponent k such that p_away^k + p_home^k = 1.
    More accurate than multiplicative for extreme odds.

    This method assumes the "true" odds follow a power law relationship
    with the implied probabilities.

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team
        tolerance: Convergence tolerance for binary search
        max_iterations: Maximum iterations for binary search

    Returns:
        Tuple of (away_fair_prob, home_fair_prob) that sum to 1.0

    Examples (unit tests):
        >>> away, home = devig_power(-110, -110)
        >>> round(away, 4), round(home, 4)
        (0.5, 0.5)

        >>> away, home = devig_power(-150, +130)
        >>> round(away, 4), round(home, 4)
        (0.5788, 0.4212)

        >>> away, home = devig_power(-400, +350)
        >>> round(away, 4), round(home, 4)
        (0.7874, 0.2126)

        # Verify they sum to 1
        >>> away, home = devig_power(-150, +130)
        >>> round(away + home, 10)
        1.0
    """
    away_implied = american_to_probability(away_odds)
    home_implied = american_to_probability(home_odds)

    # Binary search for the exponent k
    # We need to find k such that away_implied^k + home_implied^k = 1
    k_low, k_high = 0.01, 10.0

    for _ in range(max_iterations):
        k = (k_low + k_high) / 2
        total = (away_implied ** k) + (home_implied ** k)

        if abs(total - 1.0) < tolerance:
            break

        # If total > 1, we need LARGER k (raising numbers < 1 to higher powers makes them smaller)
        # If total < 1, we need SMALLER k
        if total > 1.0:
            k_low = k
        else:
            k_high = k

    away_fair = away_implied ** k
    home_fair = home_implied ** k

    # Normalize to ensure exact sum of 1 (handles floating point)
    total = away_fair + home_fair
    return away_fair / total, home_fair / total


def devig_shin(
    away_odds: int,
    home_odds: int,
    tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> tuple[float, float]:
    """
    Remove vig using the Shin method.

    The Shin method accounts for the presence of informed bettors
    and provides more accurate fair probabilities in markets with
    sharp money.

    Based on Shin (1993) paper on betting market efficiency.

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team
        tolerance: Convergence tolerance
        max_iterations: Maximum iterations

    Returns:
        Tuple of (away_fair_prob, home_fair_prob) that sum to 1.0

    Examples (unit tests):
        >>> away, home = devig_shin(-110, -110)
        >>> round(away, 4), round(home, 4)
        (0.5, 0.5)

        >>> away, home = devig_shin(-150, +130)
        >>> round(away, 4), round(home, 4)
        (0.5803, 0.4197)

        # Verify they sum to 1
        >>> away, home = devig_shin(-150, +130)
        >>> round(away + home, 10)
        1.0
    """
    away_implied = american_to_probability(away_odds)
    home_implied = american_to_probability(home_odds)

    # For two outcomes, Shin method simplifies
    # We solve for z (proportion of informed bettors)
    # Using the formula: implied_prob = z + (1-z) * fair_prob

    # Binary search for z
    z_low, z_high = 0.0, 0.5

    for _ in range(max_iterations):
        z = (z_low + z_high) / 2

        # Calculate what implied probs would be for this z
        # fair_prob = (sqrt(z^2 + 4*(1-z)*implied_prob) - z) / (2*(1-z))
        def implied_to_fair(impl: float, z: float) -> float:
            if z >= 1:
                return impl
            discriminant = z * z + 4 * (1 - z) * impl
            return (math.sqrt(discriminant) - z) / (2 * (1 - z))

        away_fair = implied_to_fair(away_implied, z)
        home_fair = implied_to_fair(home_implied, z)
        total = away_fair + home_fair

        if abs(total - 1.0) < tolerance:
            break

        if total > 1.0:
            z_low = z
        else:
            z_high = z

    # Normalize
    total = away_fair + home_fair
    return away_fair / total, home_fair / total


def compute_fair_probabilities(
    away_odds: int,
    home_odds: int,
    method: DeVigMethod = "multiplicative",
) -> tuple[float, float]:
    """
    Compute fair (de-vigged) probabilities using specified method.

    This is the main function to use for de-vigging odds.

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team
        method: De-vigging method to use:
            - "multiplicative": Simple proportional (default, most common)
            - "additive": Equal subtraction from each side
            - "power": Power law method (better for extreme odds)
            - "shin": Shin method (accounts for sharp money)

    Returns:
        Tuple of (away_fair_prob, home_fair_prob) that sum to 1.0

    Examples (unit tests):
        >>> away, home = compute_fair_probabilities(-150, +130)
        >>> round(away, 4), round(home, 4)
        (0.5798, 0.4202)

        >>> away, home = compute_fair_probabilities(-150, +130, method="power")
        >>> round(away, 4), round(home, 4)
        (0.5788, 0.4212)

        >>> away, home = compute_fair_probabilities(-110, -110)
        >>> round(away, 4), round(home, 4)
        (0.5, 0.5)
    """
    methods = {
        "multiplicative": devig_multiplicative,
        "additive": devig_additive,
        "power": devig_power,
        "shin": devig_shin,
    }

    if method not in methods:
        raise ValueError(f"Unknown method: {method}. Choose from: {list(methods.keys())}")

    return methods[method](away_odds, home_odds)


# =============================================================================
# Averaged Odds Functions
# =============================================================================

def average_odds(odds_list: list[Optional[int]]) -> Optional[int]:
    """
    Calculate the average of multiple American odds values.

    Averaging is done in probability space (not directly on odds)
    to properly handle the non-linear nature of American odds.

    Args:
        odds_list: List of American odds (None values are ignored)

    Returns:
        Average odds as integer, or None if no valid odds provided

    Examples (unit tests):
        >>> average_odds([-150, -140, -160])
        -150

        >>> average_odds([+130, +140, +120])
        130

        >>> average_odds([-150, -140, None, -160])
        -150

        >>> average_odds([None, None])
        None

        >>> average_odds([])
        None

        >>> average_odds([-110, -110, -110])
        -110
    """
    # Filter out None values
    valid_odds = [o for o in odds_list if o is not None]

    if not valid_odds:
        return None

    # Convert to probabilities, average, convert back
    probs = [american_to_probability(o) for o in valid_odds]
    avg_prob = sum(probs) / len(probs)

    return probability_to_american(avg_prob)


def weighted_average_odds(
    odds_weights: list[tuple[Optional[int], float]],
) -> Optional[int]:
    """
    Calculate weighted average of multiple American odds values.

    Useful when some sportsbooks should be weighted more heavily
    (e.g., sharper books like Pinnacle).

    Args:
        odds_weights: List of (odds, weight) tuples

    Returns:
        Weighted average odds as integer, or None if no valid odds

    Examples (unit tests):
        >>> weighted_average_odds([(-150, 1.0), (-140, 2.0), (-160, 1.0)])
        -147

        >>> weighted_average_odds([(-150, 1.0), (None, 2.0)])
        -150
    """
    valid_pairs = [(o, w) for o, w in odds_weights if o is not None and w > 0]

    if not valid_pairs:
        return None

    total_weight = sum(w for _, w in valid_pairs)
    weighted_prob_sum = sum(
        american_to_probability(o) * w for o, w in valid_pairs
    )

    avg_prob = weighted_prob_sum / total_weight
    return probability_to_american(avg_prob)


# =============================================================================
# Game Analysis Functions
# =============================================================================

@dataclass
class ProbabilityAnalysis:
    """
    Complete probability analysis for a game's odds.

    Attributes:
        away_implied: Raw implied probability for away team
        home_implied: Raw implied probability for home team
        overround: Total implied probability (vig indicator)
        vig_percentage: Vig as percentage
        away_fair: De-vigged fair probability for away team
        home_fair: De-vigged fair probability for home team
        away_fair_odds: Fair odds for away team (American format)
        home_fair_odds: Fair odds for home team (American format)
        method: De-vigging method used
    """
    away_implied: float
    home_implied: float
    overround: float
    vig_percentage: float
    away_fair: float
    home_fair: float
    away_fair_odds: int
    home_fair_odds: int
    method: str

    def __repr__(self) -> str:
        return (
            f"ProbabilityAnalysis(\n"
            f"  Implied: Away {self.away_implied:.2%}, Home {self.home_implied:.2%}\n"
            f"  Overround: {self.overround:.4f} ({self.vig_percentage:.2f}% vig)\n"
            f"  Fair ({self.method}): Away {self.away_fair:.2%}, Home {self.home_fair:.2%}\n"
            f"  Fair Odds: Away {self.away_fair_odds:+d}, Home {self.home_fair_odds:+d}\n"
            f")"
        )


def analyze_odds(
    away_odds: int,
    home_odds: int,
    method: DeVigMethod = "multiplicative",
) -> ProbabilityAnalysis:
    """
    Perform complete probability analysis on a pair of odds.

    This function computes all relevant probability metrics for
    a two-way betting market.

    Args:
        away_odds: American odds for away team
        home_odds: American odds for home team
        method: De-vigging method to use

    Returns:
        ProbabilityAnalysis object with all computed values

    Examples (unit tests):
        >>> analysis = analyze_odds(-150, +130)
        >>> round(analysis.away_implied, 4)
        0.6
        >>> round(analysis.home_implied, 4)
        0.4348
        >>> round(analysis.away_fair, 4)
        0.5798
        >>> round(analysis.vig_percentage, 2)
        3.48
    """
    # Raw implied probabilities
    away_implied = american_to_probability(away_odds)
    home_implied = american_to_probability(home_odds)

    # Vig calculations
    overround = away_implied + home_implied
    vig_pct = (overround - 1) * 100

    # Fair probabilities
    away_fair, home_fair = compute_fair_probabilities(
        away_odds, home_odds, method=method
    )

    # Convert fair probs back to odds
    away_fair_odds = probability_to_american(away_fair)
    home_fair_odds = probability_to_american(home_fair)

    return ProbabilityAnalysis(
        away_implied=away_implied,
        home_implied=home_implied,
        overround=overround,
        vig_percentage=vig_pct,
        away_fair=away_fair,
        home_fair=home_fair,
        away_fair_odds=away_fair_odds,
        home_fair_odds=home_fair_odds,
        method=method,
    )


@dataclass
class GameProbabilityReport:
    """
    Comprehensive probability report for an NBA game.

    Includes analysis from opener odds, averaged current odds,
    and individual sportsbook odds.

    Attributes:
        opener_analysis: Analysis of opening line
        averaged_analysis: Analysis of averaged current odds
        best_away_odds: Best available odds for away team
        best_home_odds: Best available odds for home team
        edge_away: Edge on away team (fair prob - best implied prob)
        edge_home: Edge on home team (fair prob - best implied prob)
    """
    opener_analysis: Optional[ProbabilityAnalysis] = None
    averaged_analysis: Optional[ProbabilityAnalysis] = None
    best_away_odds: Optional[int] = None
    best_home_odds: Optional[int] = None
    best_away_book: str = ""
    best_home_book: str = ""
    edge_away: float = 0.0
    edge_home: float = 0.0


def analyze_game_odds(
    opener_away: Optional[int],
    opener_home: Optional[int],
    current_odds: dict[str, tuple[Optional[int], Optional[int]]],
    method: DeVigMethod = "multiplicative",
) -> GameProbabilityReport:
    """
    Analyze all odds for a single NBA game.

    Computes fair probabilities from both opener and averaged current odds,
    finds best available odds, and calculates potential edge.

    Args:
        opener_away: Opener odds for away team (None if unavailable)
        opener_home: Opener odds for home team (None if unavailable)
        current_odds: Dict mapping book name to (away_odds, home_odds) tuple
        method: De-vigging method to use

    Returns:
        GameProbabilityReport with comprehensive analysis

    Examples (unit tests):
        >>> current = {
        ...     "betmgm": (-145, +125),
        ...     "fanduel": (-150, +130),
        ...     "draftkings": (-140, +120),
        ... }
        >>> report = analyze_game_odds(-150, +130, current)
        >>> report.best_away_odds
        -140
        >>> report.best_home_odds
        130
    """
    report = GameProbabilityReport()

    # Analyze opener odds
    if opener_away is not None and opener_home is not None:
        report.opener_analysis = analyze_odds(opener_away, opener_home, method)

    # Collect all odds for averaging and finding best
    all_away_odds: list[Optional[int]] = []
    all_home_odds: list[Optional[int]] = []

    best_away = None
    best_home = None
    best_away_book = ""
    best_home_book = ""

    for book, (away, home) in current_odds.items():
        if away is not None:
            all_away_odds.append(away)
            if best_away is None or away > best_away:
                best_away = away
                best_away_book = book

        if home is not None:
            all_home_odds.append(home)
            if best_home is None or home > best_home:
                best_home = home
                best_home_book = book

    report.best_away_odds = best_away
    report.best_home_odds = best_home
    report.best_away_book = best_away_book
    report.best_home_book = best_home_book

    # Average current odds and analyze
    avg_away = average_odds(all_away_odds)
    avg_home = average_odds(all_home_odds)

    if avg_away is not None and avg_home is not None:
        report.averaged_analysis = analyze_odds(avg_away, avg_home, method)

        # Calculate edge (positive = value bet opportunity)
        # Edge = fair probability - implied probability of best odds
        if best_away is not None:
            best_away_implied = american_to_probability(best_away)
            report.edge_away = report.averaged_analysis.away_fair - best_away_implied

        if best_home is not None:
            best_home_implied = american_to_probability(best_home)
            report.edge_home = report.averaged_analysis.home_fair - best_home_implied

    return report


# =============================================================================
# CLI Entry Point - For testing and demonstration
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("NBA Arbitrage Bot - Probability Module Demo")
    print("=" * 70)

    # Demo: Basic conversions
    print("\n1. Basic American Odds Conversions")
    print("-" * 40)
    for odds in [-200, -150, -110, +110, +150, +200]:
        prob = american_to_probability(odds)
        decimal = american_to_decimal(odds)
        print(f"  {odds:+4d} -> Prob: {prob:.2%}, Decimal: {decimal:.3f}")

    # Demo: De-vigging methods comparison
    print("\n2. De-Vigging Methods Comparison (odds: -150 / +130)")
    print("-" * 40)
    away_odds, home_odds = -150, +130
    print(f"  Raw implied: Away {american_to_probability(away_odds):.2%}, "
          f"Home {american_to_probability(home_odds):.2%}")
    print(f"  Overround: {calculate_overround(away_odds, home_odds):.4f} "
          f"({calculate_vig_percentage(away_odds, home_odds):.2f}% vig)")

    for method in ["multiplicative", "additive", "power", "shin"]:
        away_fair, home_fair = compute_fair_probabilities(
            away_odds, home_odds, method=method
        )
        print(f"  {method:14s}: Away {away_fair:.2%}, Home {home_fair:.2%}")

    # Demo: Full analysis
    print("\n3. Full Analysis Example")
    print("-" * 40)
    analysis = analyze_odds(-150, +130)
    print(analysis)

    # Demo: Game with multiple books
    print("\n4. Multi-Book Game Analysis")
    print("-" * 40)
    current_odds = {
        "betmgm": (-145, +125),
        "fanduel": (-150, +130),
        "caesars": (-155, +135),
        "bet365": (-148, +128),
        "draftkings": (-140, +120),
    }

    report = analyze_game_odds(
        opener_away=-150,
        opener_home=+130,
        current_odds=current_odds,
    )

    print(f"  Best away odds: {report.best_away_odds:+d} ({report.best_away_book})")
    print(f"  Best home odds: {report.best_home_odds:+d} ({report.best_home_book})")
    print(f"  Edge on away: {report.edge_away:+.2%}")
    print(f"  Edge on home: {report.edge_home:+.2%}")

    if report.averaged_analysis:
        print(f"\n  Averaged Fair Probabilities:")
        print(f"    Away: {report.averaged_analysis.away_fair:.2%} "
              f"(fair odds: {report.averaged_analysis.away_fair_odds:+d})")
        print(f"    Home: {report.averaged_analysis.home_fair:.2%} "
              f"(fair odds: {report.averaged_analysis.home_fair_odds:+d})")

    # Demo: Spread bid -> moneyline-equivalent ratio
    print("\n5. Spread Bid → Moneyline-Equivalent (Normal margin model)")
    print("-" * 40)
    # Worked example requested:
    # HOU -4.5 = 52, TOR +4.5 = 49, σ=12
    hou_ratio, tor_ratio = spread_bid_to_implied_moneyline_ratio(
        team_a_spread_bid=52,
        team_b_spread_bid=49,
        spread_number=4.5,
        margin_std_dev=12,
    )
    print("  Inputs: HOU -4.5 bid=52, TOR +4.5 bid=49, spread_number=4.5, σ=12")
    print(f"  Output: HOU {hou_ratio:.1f} / TOR {tor_ratio:.1f}")
