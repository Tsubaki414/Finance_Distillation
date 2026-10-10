"""Perf-based priors for selection: load weights from perf_priors.json (written by scripts/perf_priors.py).

hour_weight(priors, lang, bjt_hour) is the only externally exposed per-slot function; topic and format weights
are consumed directly in selection via the 'weights' dict. All weights default to 1.0 when absent.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STORE = ROOT / "live" / "store" / "feedback" / "perf_priors.json"


def load(store=None) -> dict:
    """Read perf_priors.json and return parsed dict, or {} on missing/error.

    store overrides the default path. FD_FEEDBACK_STORE env var is also checked
    when store is None.
    """
    if store is not None:
        path = Path(store)
    else:
        env_store = os.environ.get("FD_FEEDBACK_STORE")
        path = Path(env_store) if env_store else _DEFAULT_STORE

    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def hour_weight(priors: dict, lang: str, bjt_hour: int) -> float:
    """Return the weight for a given BJT hour slot (bucketed to 3-hour bands).

    Looks up priors['weights'][lang]['hour'][str((bjt_hour // 3) * 3)].
    Returns 1.0 when absent.
    """
    bucket = str((bjt_hour // 3) * 3)
    try:
        return float(priors["weights"][lang]["hour"][bucket])
    except (KeyError, TypeError, ValueError):
        return 1.0


def topic_weight(
    priors: dict,
    lang: str,
    angle: "str | None",
    beat: "str | None",
    motif_type: "str | None",
) -> float:
    """Return the weight for the best available topic key.

    Priority: angle > beat > motif_type > 'other'. Returns 1.0 when absent.
    """
    key = angle if angle is not None else (beat if beat is not None else (motif_type or "other"))
    try:
        return float(priors["weights"][lang]["topic"][key])
    except (KeyError, TypeError, ValueError):
        return 1.0


def format_weight(priors: dict, lang: str, fmt: "str | None") -> float:
    """Return the weight for a given post format string.

    Returns 1.0 when fmt is None or not found.
    """
    if fmt is None:
        return 1.0
    try:
        return float(priors["weights"][lang]["format"][fmt])
    except (KeyError, TypeError, ValueError):
        return 1.0


def combined(
    priors: dict,
    lang: str,
    angle: "str | None" = None,
    beat: "str | None" = None,
    motif_type: "str | None" = None,
    fmt: "str | None" = None,
    clamp: "tuple[float, float]" = (0.7, 1.4),
) -> float:
    """Return topic_weight * format_weight, clamped to clamp=(lo, hi).

    Hour weight is intentionally excluded here — callers apply it separately
    because it depends on the candidate slot time, not the content itself.
    """
    w = topic_weight(priors, lang, angle, beat, motif_type) * format_weight(priors, lang, fmt)
    lo, hi = clamp
    return max(lo, min(hi, w))
