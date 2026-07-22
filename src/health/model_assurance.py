"""Training-domain applicability checks and explicit model abstention."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def assess_model_applicability(model: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Check missing values and training-domain bounds before accepting ML output."""

    metadata = getattr(model, "health_model_metadata_", {})
    profile = metadata.get("training_profile")
    reasons: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        reasons.append({"code": "TRAINING_PROFILE_MISSING", "message": "Model artifact lacks a training-domain profile."})
    else:
        for field, bounds in profile.get("numerical", {}).items():
            value = row.get(field)
            if value is None or pd.isna(value):
                reasons.append({"code": "MODEL_FEATURE_MISSING", "field": field, "message": f"{field} is missing."})
                continue
            number = float(value)
            minimum = float(bounds["minimum"])
            maximum = float(bounds["maximum"])
            tolerance = max((maximum - minimum) * 0.05, 1e-9)
            if number < minimum - tolerance or number > maximum + tolerance:
                reasons.append({
                    "code": "NUMERICAL_OUT_OF_TRAINING_DOMAIN",
                    "field": field,
                    "value": number,
                    "training_minimum": minimum,
                    "training_maximum": maximum,
                    "message": f"{field} lies outside the profiled training domain.",
                })
        for field, allowed in profile.get("categorical", {}).items():
            value = row.get(field)
            if value is None or pd.isna(value):
                reasons.append({"code": "MODEL_FEATURE_MISSING", "field": field, "message": f"{field} is missing."})
            elif str(value) not in allowed:
                reasons.append({
                    "code": "CATEGORY_OUT_OF_TRAINING_DOMAIN",
                    "field": field,
                    "value": str(value),
                    "message": f"{field} contains a category not observed during training.",
                })
    accepted = not reasons
    return {
        "decision": "accepted" if accepted else "abstained",
        "accepted": accepted,
        "method": "training_profile_bounds_v1",
        "reasons": reasons,
    }
