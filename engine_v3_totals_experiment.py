"""Frozen Forecast V3: experimental 1.05x Poisson totals challenger.

Starts with the live V3 baseline. Only totals probabilities use 1.05 times
its projected expected goals. Team expected goals and moneyline predictions
remain unchanged. No database writes. The multiplier was chosen on historical
training data and has only a small exploratory chronological holdout test;
these are NOT validated full-game betting probabilities.
"""
import math

from engine_v3 import build_projections as build_baseline
from over_under_probability import calculate_total_probabilities

MODEL_VERSION = "v3_totals_scaled105_experiment"
TOTALS_SCALE = 1.05
LINES = (5.5, 6.0, 6.5)


def apply_scaled_totals(baseline):
    """Return a copy with experimental totals probabilities; never mutate input."""
    df = baseline.copy(deep=True)
    # Make output schema stable even when no games are eligible.
    df["Totals Probability Mean"] = df["Projected Total"].astype(float) * TOTALS_SCALE if "Projected Total" in df else float("nan")
    df["Totals Probability Scale"] = TOTALS_SCALE
    if df.empty:
        return df

    for idx, row in df.iterrows():
        away, home = float(row["Away xG"]), float(row["Home xG"])
        if not all(math.isfinite(v) and v >= 0 for v in (away, home)):
            raise ValueError("Expected goals must be finite and nonnegative")
        scaled_mean = (away + home) * TOTALS_SCALE
        df.at[idx, "Totals Probability Mean"] = scaled_mean
        outcomes = calculate_total_probabilities(
            away * TOTALS_SCALE, home * TOTALS_SCALE, lines=LINES
        )
        for line, probabilities in outcomes.items():
            for side in ("Over", "Under", "Push"):
                df.at[idx, f"{side} {line} Probability"] = round(
                    probabilities[f"{side.lower()}_probability"], 6
                )
    return df


def build_projections(date, verify=True):
    baseline, metadata = build_baseline(date, verify=verify)
    df = apply_scaled_totals(baseline)
    metadata = dict(metadata)
    metadata.update({
        "model_version": MODEL_VERSION,
        "totals_probability_scale": TOTALS_SCALE,
        "total_probabilities_note": (
            "Experimental 1.05x regulation-based Poisson proxy; "
            "not calibrated full-game sportsbook probabilities"
        ),
    })
    return df, metadata
