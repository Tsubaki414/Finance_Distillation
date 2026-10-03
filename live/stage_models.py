"""Per-stage model configuration (plan 1.4 subset, pulled into P0-4).

The table maps each stage to a requested model and temperature, and each
requested model to the response model names the relay may report for it.
A response model outside that list is an error, never a silent fallback.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

PATH = Path(__file__).with_name('stage_models.json')


def validate(table):
    if not isinstance(table, dict):
        raise ValueError('stage model table must be an object')
    accepted = table.get('accepted_response_models')
    if not isinstance(accepted, dict):
        raise ValueError('accepted_response_models must be an object')
    entries = [('default', table.get('default'))] + list((table.get('stages') or {}).items())
    for stage, entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('model'), str) or not entry['model']:
            raise ValueError(f'stage {stage}: model is required')
        temperature = entry.get('temperature', 0.0)
        if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError(f'stage {stage}: temperature must be within [0, 2]')
        names = accepted.get(entry['model'])
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError(f'stage {stage}: model {entry["model"]} has no accepted response mapping')
    return table


def load(path=PATH):
    return validate(json.loads(Path(path).read_text()))


def for_stage(table, stage):
    entry = (table.get('stages') or {}).get(stage) or table['default']
    return {'model': entry['model'], 'temperature': float(entry.get('temperature', 0.0))}


def accepted(table, model):
    return list(table['accepted_response_models'][model])


def models(table):
    return sorted({e['model'] for e in [table['default'], *(table.get('stages') or {}).values()]})


def copy_of(table):
    return copy.deepcopy(table)
