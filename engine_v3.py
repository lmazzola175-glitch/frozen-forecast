"""Frozen Forecast V3 — initial dual-market challenger.

Keeps V2's goal and moneyline formulas unchanged and adds Poisson-based
regulation-total proxy probabilities for lines 5.5, 6.0 and 6.5.

IMPORTANT: These totals probabilities are not calibrated full-game NHL betting
probabilities. Overtime can add goals. No injuries, home-ice or rest adjustments
are applied in this first V3 version. V1/V2 are untouched.
"""

from engine_v2 import build_projections as build_v2_projections
from over_under_probability import calculate_total_probabilities

MODEL_VERSION = "v3_dual_market_baseline"
LINES = (5.5, 6.0, 6.5)


def build_projections(date, verify=True):
    projections, metadata = build_v2_projections(date, verify=verify)
    projections = projections.copy()
    metadata = dict(metadata)
    metadata["model_version"] = MODEL_VERSION
    metadata["total_probabilities_note"] = (
        "Uncalibrated regulation-based Poisson proxy; not full-game odds"
    )

    if projections.empty:
        return projections, metadata

    # Preserve all V2 columns for compatibility with existing consumers.
    for line in LINES:
        suffix = str(line).replace(".", "_")
        projections[f"Over {line} Probability"] = 0.0
        projections[f"Under {line} Probability"] = 0.0
        projections[f"Push {line} Probability"] = 0.0

    for index, row in projections.iterrows():
        outcomes = calculate_total_probabilities(
            row["Away xG"], row["Home xG"], lines=LINES
        )
        for line, probabilities in outcomes.items():
            projections.at[index, f"Over {line} Probability"] = round(
                probabilities["over_probability"], 6
            )
            projections.at[index, f"Under {line} Probability"] = round(
                probabilities["under_probability"], 6
            )
            projections.at[index, f"Push {line} Probability"] = round(
                probabilities["push_probability"], 6
            )

    return projections, metadata
