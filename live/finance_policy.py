"""Finance policy and compatibility for the four pre-domain account profiles.

These names are deployment history, not the account schema or router taxonomy.
New accounts should set domain/fidelity_policy explicitly.
"""
LEGACY_ACCOUNT_IDS=frozenset({'zh_macro','en_macro','zh_industry','en_industry'})
METRIC_ALIASES={'operating margin':'margin','营业利润率':'margin','经营利润率':'margin',
    'revenue':'revenue','revenues':'revenue','营收':'revenue','营业收入':'revenue',
    'profit':'profit','利润':'profit','renewal rate':'renewal','续约率':'renewal',
    'policy rate':'policy_rate','政策利率':'policy_rate'}

REVIEW_GUIDANCE='''Finance fidelity policy (private constraints, never public QA prose):
Keep currencies, percentages versus percentage points/basis points, fiscal/time periods,
revenue/margins/valuation and other metric-value bindings. Preserve existing calculations;
do not invent a financial percentage, explanation or forecast from combinable numbers.
Personal holdings, long/short positions, own book, fund management, fees and performance
belong to their original speaker. These are not merely rhetorical first-person stance.
Bare cashtags do not disclose a long or short position. Forecasts retain their force and
uncertainty; a source opinion is not an independently verified market fact. Policy checks
preserve financial meaning, not add investment advice, warnings or a standardized voice.'''


def deterministic(*args,**kwargs):
    # Preserve the existing production finance guards rather than removing them
    # while extracting the generic orchestration layer.
    from live.fidelity import deterministic as existing
    return existing(*args,**kwargs)
