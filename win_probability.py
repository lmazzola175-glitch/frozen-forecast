
"""Frozen Forecast — NHL Win Probability Engine.

Estimates regulation scoring using independent Poisson distributions.

Regulation ties are split 50/50 as an initial approximation
for overtime and shootout outcomes.

This model is not yet calibrated against historical NHL results.
"""

import math


def poisson_probabilities(expected_goals, max_goals=30):
    """Return a normalized Poisson goal distribution."""

    expected_goals = float(expected_goals)

    if not math.isfinite(expected_goals) or expected_goals < 0:
        raise ValueError(
            "Expected goals must be finite and nonnegative."
        )

    probabilities = [math.exp(-expected_goals)]

    for goals in range(1, max_goals + 1):
        probabilities.append(
            probabilities[-1] * expected_goals / goals
        )

    total = sum(probabilities)

    if total <= 0:
        raise ValueError(
            "Could not construct goal distribution."
        )

    return [
        probability / total
        for probability in probabilities
    ]


def calculate_win_probabilities(
    away_expected_goals,
    home_expected_goals,
    away_team,
    home_team,
):
    """Estimate full-game win probabilities.

    Uses Poisson scoring probabilities and a neutral
    50/50 overtime/shootout approximation.
    """

    away_distribution = poisson_probabilities(
        away_expected_goals
    )

    home_distribution = poisson_probabilities(
        home_expected_goals
    )

    away_regulation_win = 0.0
    home_regulation_win = 0.0
    regulation_tie = 0.0

    # Calculate regulation outcomes.
    for away_goals, away_probability in enumerate(
        away_distribution
    ):
        for home_goals, home_probability in enumerate(
            home_distribution
        ):
            probability = (
                away_probability * home_probability
            )

            if away_goals > home_goals:
                away_regulation_win += probability

            elif home_goals > away_goals:
                home_regulation_win += probability

            else:
                regulation_tie += probability

    # Neutral overtime/shootout approximation.
    away_win_probability = (
        away_regulation_win
        + 0.5 * regulation_tie
    )

    home_win_probability = (
        home_regulation_win
        + 0.5 * regulation_tie
    )

    # Normalize probabilities.
    total = (
        away_win_probability
        + home_win_probability
    )

    away_win_probability /= total
    home_win_probability /= total

    # FIX: Handle equal probabilities safely.
    # Floating-point calculations can produce tiny
    # differences even when expected goals are equal.
    if math.isclose(
        away_win_probability,
        home_win_probability,
        rel_tol=0,
        abs_tol=1e-10,
    ):
        projected_winner = "TOSS-UP"

    elif away_win_probability > home_win_probability:
        projected_winner = away_team

    else:
        projected_winner = home_team

    winner_confidence = max(
        away_win_probability,
        home_win_probability,
    )

    return {
        "away_win_probability": round(
            away_win_probability, 6
        ),
        "home_win_probability": round(
            home_win_probability, 6
        ),
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
            winner_confidence, 6
        ),
    }


# ============================================================
# TEST THE ENGINE
# ============================================================

if __name__ == "__main__":

    test_cases = [
        (3.4, 2.8, "NYR", "BOS"),
        (2.5, 2.5, "TOR", "MTL"),
        (4.0, 2.0, "COL", "CHI"),
        (1.5, 3.5, "ANA", "DAL"),
    ]

    print("=" * 55)
    print("FROZEN FORECAST — WIN PROBABILITY ENGINE TEST")
    print("=" * 55)

    for away_xg, home_xg, away, home in test_cases:

        result = calculate_win_probabilities(
            away_expected_goals=away_xg,
            home_expected_goals=home_xg,
            away_team=away,
            home_team=home,
        )

        away_p = result["away_win_probability"]
        home_p = result["home_win_probability"]

        # Validate probabilities.
        assert 0 <= away_p <= 1
        assert 0 <= home_p <= 1

        assert abs(
            away_p + home_p - 1
        ) < 0.00001

        # Validate projected winner.
        if away_xg > home_xg:
            assert result["projected_winner"] == away

        elif home_xg > away_xg:
            assert result["projected_winner"] == home

        else:
            assert result["projected_winner"] == "TOSS-UP"

        print(
            f"{away} @ {home} | "
            f"Away: {away_p:.1%} | "
            f"Home: {home_p:.1%} | "
            f"Winner: {result['projected_winner']}"
        )

    print("=" * 55)
    print("ALL WIN PROBABILITY TESTS PASSED")
    print("=" * 55)
