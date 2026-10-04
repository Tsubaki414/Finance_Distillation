"""Offline source trust policy shared by extraction, stance and composition."""
import json
from pathlib import Path
from live import registry

POLICY = json.loads(Path(__file__).with_name('trusted_sources.json').read_text())


def is_trusted(source_or_unit) -> bool:
    if isinstance(source_or_unit, str):
        source_or_unit = {'source_id': source_or_unit}
    if not isinstance(source_or_unit, dict):
        return False
    row = source_or_unit
    tier = registry.source_licence_tier(row.get('source_id'))
    if (tier or row.get('licence_tier')) == 'A':
        return True
    for key in ('source_id', 'adapter'):
        name = str(row.get(key) or '').casefold()
        if name in POLICY['allowlist'] or any(name.startswith(p) for p in POLICY['source_id_prefixes']):
            return True
    for key in ('trust_score', 'donor_score'):
        score = row.get(key)
        if type(score) in (int, float) and score >= POLICY['minimum_score']:
            return True
    return is_trusted(row.get('source')) if isinstance(row.get('source'), dict) else False


def trusted_inputs(source, units):
    return is_trusted(source) or bool(units) and all(is_trusted(u) for u in units)
