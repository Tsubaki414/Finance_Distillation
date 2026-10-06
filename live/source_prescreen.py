"""Cheap persona pre-screen of evidence packets BEFORE paying for a stance call (Oct 6 v9).

Oct 6 live runs: zh_industry stance rejected 5 packets (Khanna AI-audit policy x2, Zendesk CFO hire,
OpenAI safety resignation, White House "AI czar" task force, Son superintelligence warning) and
en_industry one (an options straddle idea); zh_macro rejected a sell-side "second and final hike"
path. Each reject cost ~$0.17-0.21 of opus. These rules mirror the persona focus / rejects:

  industry (semis / industry; "从实体需求和行业差异切入", rejects promotion_without_evidence):
    - policy / safety / regulation / personnel framing with no industry evidence -> demote
    - options trade ideas -> demote
  macro ("先辨认数据修订与方向", zh rejects unconditional_long_term_forecasts):
    - no macro data/policy signal at all -> demote
    - zh_macro: terminal-path forecast phrasing ("final hike", 终点利率) -> demote

Keyword/tag only, no model call. Demoted packets are never dropped: they rank after every packet
that passes, so a slot still has a candidate when nothing passes. Soft by construction.
"""
from __future__ import annotations

import re

POLICY_SAFETY = re.compile(
    r'regulat|\bpolicy (?:position|proposal)|\bsafety\b|superintelligen|\bczar\b|task ?force|congress|senator|'
    r'lawmaker|executive order|white house|auditor|hearing|resign|\bappoint|\bhire[sd]?\b|\bhiring\b|'
    r'\bCFO\b|\bCEO succession|\bwarn(?:s|ed|ing)?\b|existential|'
    r'监管|超级智能|安全|白宫|国会|议员|众议员|法案|工作组|沙皇|辞职|死谏|任命|聘任|换帅|警告|伦理|审计机构', re.I)
INDUSTRY_EVIDENCE = re.compile(
    r'revenue|sales|shipment|capex|capital (?:expenditure|spending)|\border|backlog|pricing|\bprices?\b|\bASP\b|'
    r'margin|capacity|utiliz|wafer|\bfab\b|HBM|DRAM|NAND|memory|bandwidth|\bGPU|server|data ?cent|guidance|'
    r'lease|inventor|lead time|bookings|units? sold|'
    r'营收|收入|出货|资本开支|订单|价格|涨价|降价|毛利|产能|晶圆|存储|内存|服务器|数据中心|租赁|库存|指引|算力|带宽', re.I)
OPTIONS_IDEA = re.compile(r'straddle|strangle|call skew|put skew|option ideas?|implied vol|\bIV\b|期权', re.I)
MACRO_SIGNAL = re.compile(
    r'\bfed\b|federal reserve|fomc|\brates?\b|inflation|\bcpi\b|\bpce\b|\bpmi\b|payroll|\bjobs?\b|unemploy|'
    r'yield|treasur|\bgdp\b|\becb\b|\bboj\b|pboc|liquidity|monetary|fiscal|'
    r'美联储|联储|利率|通胀|物价|就业|非农|失业|收益率|国债|采购经理|GDP|央行|降息|加息|降准|流动性|货币政策|财政|社融|信贷|工业', re.I)
TERMINAL_PATH = re.compile(r'final hike|last hike|terminal rate|second and final|end of the (?:hiking )?cycle|'
                           r'最后一次加息|终点利率|加息周期结束', re.I)

INDUSTRY = ('zh_industry', 'en_industry')
MACRO = ('zh_macro', 'en_macro')


def _texts(group):
    views, facts, title = [], [], ''
    for record in group or []:
        unit = record.get('unit') or {}
        src = record.get('source') or {}
        title = title or str(src.get('title') or '')
        view = unit.get('view') if isinstance(unit.get('view'), dict) else None
        if view:
            views.append(' '.join(str(x) for x in (view.get('subject'), unit.get('statement'),
                                                    ' '.join(map(str, view.get('reasoning') or [])))))
        elif unit.get('kind') == 'fact':
            facts.append(str(unit.get('statement') or ''))
    return title, ' '.join(views), ' '.join(facts)


def prescreen(account, group):
    """{'ok': bool, 'reasons': [...]} for one packet; ok=True means 'no cheap reason to expect a reject'."""
    title, views, facts = _texts(group)
    head = title + ' ' + views
    reasons = []
    if account in INDUSTRY:
        if OPTIONS_IDEA.search(head):
            reasons.append('options_trade_idea')
        policy = POLICY_SAFETY.search(head)
        evidence = INDUSTRY_EVIDENCE.search(views + ' ' + facts)
        if policy and not evidence:
            reasons.append('policy_or_personnel_without_industry_evidence:' + policy.group(0))
    elif account in MACRO:
        if not MACRO_SIGNAL.search(head + ' ' + facts):
            reasons.append('no_macro_signal')
        if account == 'zh_macro' and TERMINAL_PATH.search(views):
            reasons.append('terminal_path_forecast:' + TERMINAL_PATH.search(views).group(0))
    return {'ok': not reasons, 'reasons': reasons}


def order(account, groups):
    """Stable re-order: passing packets first (original rank kept), demoted after. Returns
    (ordered_groups, screens) with screens aligned to ordered_groups."""
    screened = [(g, prescreen(account, g)) for g in groups]
    screened.sort(key=lambda gs: not gs[1]['ok'])
    return [g for g, _ in screened], [s for _, s in screened]
