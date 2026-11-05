
"""Frozen Forecast — NHL win probability engine.

Estimates regulation scoring with independent Poisson distributions.
A regulation tie is split 50/50 as a neutral approximation for
overtime/shootout outcomes.

This is an initial probability model, not yet calibrated to
historical NHL game results.
"""

import math


def poisson_probabilities(expected_goals, max_goals=30):
    """Return a normalized Poisson goal distribution."""
    expected_goals = float(expected_goals)

    if not math.isfinite(expected_goals) or expected_goals < 0:
        raise ValueError("Expected goals must be finite and nonnegative.")

    probabilities = [math.exp(-expected_goals)]

    for goals in range(1, max_goals + 1):
        probabilities.append(
            probabilities[-1] * expected_goals / goals
        )

    total = sum(probabilities)

    if total <= 0:
        raise ValueError("Could not construct goal distribution.")

    return [probability / total for probability in probabilities]


def calculate_win_probabilities(
    away_expected_goals,
    home_expected_goals,
    away_team,
    home_team,
):
    """Estimate full-game win probabilities including a tie approximation."""

    away_distribution = poisson_probabilities(away_expected_goals)
    home_distribution = poisson_probabilities(home_expected_goals)

    away_regulation_win = 0.0
    home_regulation_win = 0.0
    regulation_tie = 0.0

    for away_goals, away_probability in enumerate(away_distribution):
        for home_goals, home_probability in enumerate(home_distribution):
            probability = away_probability * home_probability

            if away_goals > home_goals:
                away_regulation_win += probability

            elif home_goals > away_goals:
                home_regulation_win += probability

            else:
                regulation_tie += probability

    # Neutral overtime/shootout approximation.
    away_win_probability = (
        away_regulation_win + 0.5 * regulation_tie
    )

    home_win_probability = (
        home_regulation_win + 0.5 * regulation_tie
    )

    total = away_win_probability + home_win_probability

    away_win_probability /= total
    home_win_probability /= total

    projected_winner = (
        away_team
        if away_win_probability > home_win_probability
        else home_team
        if home_win_probability > away_win_probability
        else "TOSS-UP"
    )

    return {
        "away_win_probability": round(away_win_probability, 6),
        "home_win_probability": round(home_win_probability, 6),
        "away_regulation_win_probability": round(
            away_regulation_win, 6
        ),
        "home_regulation_win_probability": round(
            home_regulation_win, 6
        ),
        "regulation_tie_probability": round(
            regulation_tie, 6
        ),
        "projected_winner": projected_winner,
        "winner_confidence": round(
            max(away_win_probability, home_win_probability), 6
        ),
    }


if __name__ == "__main__":
    example = calculate_win_probabilities(
        away_expected_goals=3.4,
        home_expected_goals=2.8,
        away_team="NYR",
        home_team="BOS",
    )

    print("FROZEN FORECAST — WIN PROBABILITY TEST")
    print("=" * 45)

    for key, value in example.items():
        print(f"{key}: {value}")

    assert abs(
        example["away_win_probability"]
        + example["home_win_probability"]
        - 1.0
    ) < 0.00001

    assert example["projected_winner"] == "NYR"

    print("=" * 45)
    print("WIN PROBABILITY TEST PASSED")
