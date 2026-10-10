#!/usr/bin/env python3
"""Compute per-language perf priors (format / hour / topic) from perf.jsonl."""

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_args():
    p = argparse.ArgumentParser(description="Compute perf priors from perf.jsonl")
    p.add_argument("--perf-jsonl", default="/workspace/x/perf/perf.jsonl",
                   help="Input JSONL file with perf rows")
    p.add_argument("--out", default="live/store/feedback/perf_priors.json",
                   help="Output path for perf_priors.json")
    p.add_argument("--days", type=int, default=14,
                   help="Rolling window in days (default 14)")
    p.add_argument("--n0", type=int, default=8,
                   help="EB prior strength (default 8)")
    return p.parse_args()


def to_bjt_hour(ts_str):
    """Convert an ISO timestamp string to the hour in Asia/Shanghai."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SHANGHAI).hour
    except Exception:
        return None


def compute_metric(row):
    """Return per-row engagement metric, or None if views is missing."""
    views = row.get("views")
    followers = row.get("followers")
    if views is None:
        return None
    if followers is not None and views >= 0:
        return math.log(max(views, 1) / max(followers, 1) * 1000)
    return math.log(max(views, 1))


def get_topic_key(row):
    """Return the best available topic key for a row."""
    if row.get("angle") is not None:
        return row["angle"]
    if row.get("beat") is not None:
        return row["beat"]
    return row.get("motif_type") or "other"


def eb_weight(bucket_scores, global_mean, n0):
    """Compute EB-shrunk weight for a bucket. Returns 1.0 if no data."""
    n = len(bucket_scores)
    if n == 0 or global_mean == 0:
        return 1.0
    bucket_mean = sum(bucket_scores) / n
    w = (n * bucket_mean + n0 * global_mean) / ((n + n0) * global_mean)
    return max(0.75, min(1.30, w))


def apply_dod_clamp(w, prev_w):
    """Clamp day-over-day change to ±10%."""
    return max(prev_w * 0.9, min(prev_w * 1.1, w))


def main():
    args = parse_args()

    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=args.days)

    # ── Load rows ──────────────────────────────────────────────────────────────
    rows = []
    perf_path = Path(args.perf_jsonl)
    if perf_path.exists():
        with open(perf_path) as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # ── Filter window ─────────────────────────────────────────────────────────
    def in_window(row):
        day_str = row.get("day")
        if not day_str:
            return False
        try:
            return datetime.fromisoformat(day_str).date() > cutoff
        except Exception:
            return False

    rows = [r for r in rows if in_window(r)]

    # ── Accumulate scored rows per (lang, dim, bucket) ────────────────────────
    # Structure: lang -> dim -> bucket -> [scores]
    buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    days_seen = set()
    lang_all_scores = defaultdict(list)

    for row in rows:
        metric = compute_metric(row)
        if metric is None:
            continue

        lang = row.get("lang")
        if lang not in ("zh", "en"):
            continue

        days_seen.add(row.get("day"))
        lang_all_scores[lang].append(metric)

        # format bucket
        fmt = row.get("format")
        if fmt:
            buckets[lang]["format"][fmt].append(metric)

        # hour bucket
        ts = row.get("posted_at") or row.get("suggested_london")
        bjt_hour = to_bjt_hour(ts)
        if bjt_hour is not None:
            hour_key = str((bjt_hour // 3) * 3)
            buckets[lang]["hour"][hour_key].append(metric)

        # topic bucket
        topic_key = get_topic_key(row)
        buckets[lang]["topic"][topic_key].append(metric)

    # ── Load previous priors for day-over-day clamp ───────────────────────────
    out_path = Path(args.out)
    prev_weights = {}
    if out_path.exists():
        try:
            with open(out_path) as fh:
                prev_data = json.load(fh)
            prev_weights = prev_data.get("weights", {})
        except Exception:
            prev_weights = {}

    # ── Compute weights ───────────────────────────────────────────────────────
    weights = {}
    n_counts = {}
    means = {}

    for lang in ("zh", "en"):
        all_scores = lang_all_scores[lang]
        global_mean = (sum(all_scores) / len(all_scores)) if all_scores else 0.0

        weights[lang] = {}
        n_counts[lang] = {}
        means[lang] = {"global": round(global_mean, 6)}

        for dim in ("format", "hour", "topic"):
            weights[lang][dim] = {}
            n_counts[lang][dim] = {}
            means[lang][dim] = {}
            prev_dim = prev_weights.get(lang, {}).get(dim, {})

            for bucket, scores in buckets[lang][dim].items():
                w = eb_weight(scores, global_mean, args.n0)
                prev_w = prev_dim.get(bucket)
                if prev_w is not None:
                    w = apply_dod_clamp(w, prev_w)
                weights[lang][dim][bucket] = round(w, 6)
                n_counts[lang][dim][bucket] = len(scores)
                means[lang][dim][bucket] = round(sum(scores) / len(scores), 6) if scores else 0.0

    # ── Write output ──────────────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_scored = sum(len(v) for v in lang_all_scores.values())
    result = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "days": len([d for d in days_seen if d]),
        "rows": total_scored,
        "weights": weights,
        "n": n_counts,
        "means": means,
    }

    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)

    zh_rows = len(lang_all_scores["zh"])
    en_rows = len(lang_all_scores["en"])
    print(
        f"perf_priors: zh {zh_rows} rows, en {en_rows} rows, "
        f"days_window={args.days}, weights computed"
    )


if __name__ == "__main__":
    main()
