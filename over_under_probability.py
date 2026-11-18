"""Frozen Forecast: baseline NHL total-goals probabilities.

Uses a Poisson distribution for total regulation goals with mean equal to
away + home projected goals. This is an *uncalibrated regulation-based proxy*,
not a validated full-game NHL betting probability: overtime can add a goal.
Shootout deciding goals do not count toward sportsbook game totals.
"""

import math

LINES = (5.5, 6.0, 6.5)


def calculate_total_probabilities(away_expected_goals, home_expected_goals, lines=LINES):
    """Return over/under/push probabilities (0..1) by goals line."""
    away = float(away_expected_goals)
    home = float(home_expected_goals)
    if not all(math.isfinite(x) and x >= 0 for x in (away, home)):
        raise ValueError("Expected goals must be finite and nonnegative")
    lam = away + home
    # Only thresholds up to 7 are needed for the standard NHL lines.
    max_needed = max(math.floor(line) for line in lines) if lines else 0
    if any(not math.isfinite(float(line)) or float(line) < 0 for line in lines):
        raise ValueError("Lines must be finite and nonnegative")
    probs = [math.exp(-lam)]
    for k in range(1, max_needed + 1):
        probs.append(probs[-1] * lam / k)
    output = {}
    for raw_line in lines:
        line = float(raw_line)
        under = sum(p for k, p in enumerate(probs) if k < line)
        push = probs[int(line)] if line.is_integer() else 0.0
        over = max(0.0, 1.0 - under - push)
        output[line] = {
            "over_probability": over,
            "under_probability": under,
            "push_probability": push,
        }
    return output


if __name__ == "__main__":
    for away, home in [(3.4, 2.8), (0, 0), (4.0, 2.0)]:
        results = calculate_total_probabilities(away, home)
        for line, p in results.items():
            assert abs(sum(p.values()) - 1) < 1e-10
            print(f"xG={away + home:.2f}, line={line:.1f}: "
                  f"Over={p['over_probability']:.1%}, "
                  f"Under={p['under_probability']:.1%}, "
                  f"Push={p['push_probability']:.1%}")
