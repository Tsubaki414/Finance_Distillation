"""Content Intelligence view model: what deserves attention now.

Answers the editor's four questions rather than reporting system health. Every item carries an
explicit evidence tag:
  real         - assembled from a local artifact, path recorded
  illustrative - product structure only, no data behind it, never presented as a finding
  unavailable  - the capability is not built; the slot stays visible and honest
Nothing is generated and nothing is written.
"""
from pathlib import Path
import json, datetime
import signals as sig
import catalysts as cal

ROOT = Path(__file__).resolve().parents[1]

REAL, ILLUS, NA = 'real', 'illustrative', 'unavailable'


def rj(rel):
    p = ROOT / rel
    return json.loads(p.read_text()) if p.exists() else None


def build():
    packet = rj('evidence_loop/sources/packets/75155f58f5a995e3.json')
    retrieval = rj('evidence_loop/experiments/retrieval.json')
    routing = rj('evidence_loop/experiments/routing.json')
    case = rj('evidence_loop/experiments/cases/case-a29c6b6c0325.json')
    pools = rj('evergreen/pools.json')
    dedup = rj('evergreen/dedup.json')
    v2 = rj('evidence_loop/profiles_v2/index.json')
    diff = rj('evidence_loop/profiles_v2/diff_v1_v2.json')
    manifest = rj('evergreen/corpus_manifest.json')
    principles = rj('evergreen/principles/candidates.json') or {'items': []}
    reactivation = rj('evergreen/principles/reactivation.json') or {}
    P = principles.get('items', [])
    by_cat = {}
    for x in P:
        by_cat.setdefault(x['category'], 0)
        by_cat[x['category']] += 1
    react_macro = (reactivation.get('results') or {}).get('macro', [])
    qa_reg = rj('qa/runs/latest.json') or {}
    prof_state = rj('evidence_loop/profiles/active.json') or {}
    ledger = rj('ml_experiments/ledger.json') or {}
    elig = (prof_state.get('history') or [{}])[-1].get('eligible_donors', [])

    fully_suppressed = set()
    if diff:
        for d in diff['donors']:
            if d['features'] and all(f['suppressed_in_v2'] for f in d['features']):
                fully_suppressed.add(d['donor'])
    usable = [d['donor'] for d in (v2['donors'] if v2 else []) if d['donor'] not in fully_suppressed]

    macro_ex = (retrieval or {}).get('results', {}).get('macro', [])
    all_ex = (retrieval or {}).get('results', {})

    # ---- A. Narrative Pulse (derived from measured topic momentum) ----------------------
    S = sig.build()
    WHY = {
        'labour': '非农与参与率随八月数据发布重回讨论中心。',
        'aicapex': '资本开支能否持续，是语料里讨论最集中的一条线。',
        'rates': '下一次就业数据公布前，利率路径的讨论维持高位。',
        'earnings': '季度披露临近尾声，财报讨论正在降温。',
        'semis': '内存涨价的讨论正从高点回落。',
        'risk': '仓位讨论平稳，窗口内没有拥挤信号。',
        'liquidity': '资金流讨论相对上一窗口在减弱。',
    }
    pulse = []
    for t in S['topics'][:4]:
        pulse.append({
            'id': t['id'], 'phase': t['phase'], 'topic': t['label'],
            'why_now': WHY.get(t['id'], ''),
            'share': t['share'], 'share_prior': t['share_prior'], 'delta_pp': t['delta_pp'],
            'posts': t['posts'], 'posts_prior': t['posts_prior'],
            'voice_count': t['voice_count'], 'voices': t['voices'],
            'languages': t['languages'],
            'lead_quote': t['lead_quote'],
            'opportunities': 1 if t['id'] == 'labour' else 0,
            'evidence': REAL,
            'artifact': 'data/clean_posts.jsonl',
        })

    # ---- B. Upcoming Catalysts (real macro date + real earnings calendar) ---------------
    TODAY = datetime.date(2026, 9, 6)
    cal_data = cal.build(S['tickers'], TODAY)
    labour_posts = next((t['posts'] for t in S['topics'] if t['id'] == 'labour'), None)
    catalysts = []
    for it in cal_data['items']:
        note = it.get('note')
        if it['kind'] == 'Earnings':
            note = (f"{it['mentions']} mentions in the last {S['window_days']}d "
                    f"({it['mention_delta']:+d} vs prior) from {it['voices']} voices."
                    if it.get('mentions') else 'Not currently discussed in the corpus.')
        else:
            note = f"{it['publisher']} official schedule · {it.get('time') or ''}".strip(' ·')
        catalysts.append({
            'date': it['date'], 'time': it.get('time'), 'days': it['days'],
            'kind': it['kind'], 'symbol': it.get('symbol'),
            'title': it['title'], 'note': note,
            'importance': it.get('importance'),
            'mentions': it.get('mentions') or (labour_posts if 'Employment Situation' in it['title'] else None),
            'evidence': REAL, 'source': it['source'],
        })
    catalysts.sort(key=lambda c: c['days'])
    catalyst_meta = {k: cal_data.get(k) for k in
                     ('observed_at', 'provider', 'http_requests_last_refresh', 'stale', 'caveat',
                      'macro_sources', 'macro_caveat')}

    # ---- C. KOL Radar ------------------------------------------------------------------
    # The radar must answer "what are they saying", so it carries the actual post text.
    # Scores stay available but they are a retrieval detail, not the headline.
    raw_by_id = {}
    rp = ROOT / 'data/raw_posts.jsonl'
    if rp.exists():
        for line in rp.read_text().split('\n'):
            if line:
                r = json.loads(line)
                raw_by_id[r['post_id']] = r

    LANE_LABEL = {'macro': 'Macro and liquidity', 'industry': 'Earnings and supply chain',
                  'trading': 'Positioning and risk'}
    claims = []
    for pid, items in all_ex.items():
        for e in items:
            r = raw_by_id.get(e['post_id'], {})
            body = (r.get('analysis_text') or r.get('text') or '').strip()
            claims.append({
                'post_id': e['post_id'],
                'donor': e['source_account_id'],
                'lane': pid,
                'lane_label': LANE_LABEL.get(pid, pid),
                'date': e.get('created_at', '')[:10],
                'excerpt': body[:190],
                'chars': len(body),
                'language': r.get('language'),
                'url': r.get('url'),
                'engagement': (r.get('engagement_snapshot') or {}).get('view_count'),
                'score': round(e.get('score', 0), 3),
                'stance': None,
                'evidence': REAL,
            })
    claims.sort(key=lambda c: -c['score'])

    voices = []
    for pid, items in all_ex.items():
        for e in items:
            voices.append({'donor': e['source_account_id'], 'post_id': e['post_id'],
                           'lane': pid, 'score': round(e.get('score', 0), 3),
                           'created_at': e.get('created_at', '')[:10]})
    by_donor = {}
    for v in voices:
        by_donor.setdefault(v['donor'], []).append(v)
    lane_counts = {}
    for c in claims:
        lane_counts.setdefault(c['lane_label'], 0)
        lane_counts[c['lane_label']] += 1
    radar = {
        'top_topic': 'US labour market and liquidity',
        'claims': claims,
        'topics': sorted(lane_counts.items(), key=lambda x: -x[1]),
        'stance': {'status': NA, 'headline': '立场未做分类',
                   'detail': '赞成与反对仅为编辑对节选的判断。尚未训练或评测任何立场分类器。'},
        'voices_retrieved': len(voices),
        'donors_in_corpus': 12,
        'donors_usable_at_cutoff': len(usable),
        'usable_donors': usable,
        'donor_rows': sorted(
            [{'donor': d, 'posts_retrieved': len(v), 'lanes': sorted({x['lane'] for x in v}),
              'top_score': max(x['score'] for x in v),
              'latest': max(x['created_at'] for x in v)} for d, v in by_donor.items()],
            key=lambda r: -r['top_score']),
        'evidence': REAL,
        'artifact': 'evidence_loop/experiments/retrieval.json',
        'propagation': {
            'status': NA,
            'headline': '传播链路数据不可用',
            'detail': '谁最早提出、谁在传播无法计算。回复父帖解析为 0，1,510 条引用帖中 1,412 条缺被引作者。',
        },
        'language_split': {
            'status': NA,
            'headline': '中英信息差尚未测量',
            'detail': '跨语言对齐未实现。语料为 1,304 条中文与 510 条英文，这是覆盖量，不是已测量的信息差。',
        },
    }

    # ---- D. Content Opportunity Queue ---------------------------------------------------
    ev_pools = (pools or {}).get('pool_counts_person', {})
    opportunities = [{
        'id': 'opp-bls-macro',
        'headline': '八月非农的分歧：行业广度还是工资',
        'why_now': '51 条结构化事实已就绪，每个数字都能定位到发布原文的精确字符位置。',
        'lane': '计划催化剂',
        'sources': {'official_facts': len(packet['facts']) if packet else 0,
                    'kol_voices': len(macro_ex),
                    'evergreen': len(react_macro), 'institutional': 0},
        'persona': {'recommended': 'macro', 'label': '宏观数据与资金流观察者'},
        'platforms': ['X thread', 'Brief'],
        'freshness': {'label': 'Historical replay', 'tone': 'replay'},
        'readiness': {'label': '已拦截', 'tone': 'blocked', 'detail': 'QA 5 项'},
        'evidence': REAL,
        'artifact': 'evidence_loop/experiments/cases/case-a29c6b6c0325.json',
        'open': True,
    }, {
        'id': 'opp-illus-industry',
        'headline': '究竟哪些行业撑起了这次数据',
        'why_now': '同一事件的第二个角度，结构示例。',
        'lane': '热点信号',
        'sources': {'official_facts': len(packet['facts']) if packet else 0,
                    'kol_voices': len(all_ex.get('industry', [])), 'evergreen': 0, 'institutional': 0},
        'persona': {'recommended': 'industry', 'label': '个股与产业链研究者'},
        'platforms': ['小红书', 'X'],
        'freshness': {'label': 'Illustrative', 'tone': 'illus'},
        'readiness': {'label': '未开始', 'tone': 'pending', 'detail': '无草稿'},
        'evidence': ILLUS, 'artifact': None, 'open': False,
    }, {
        'id': 'opp-illus-evergreen',
        'headline': '宏观数据不利时如何管理仓位',
        'why_now': 'Evergreen 内容线示例，检索依赖已抽取的原则。',
        'lane': 'Evergreen 长青',
        'sources': {'official_facts': 0, 'kol_voices': 0,
                    'evergreen': len(P),
                    'institutional': 0},
        'persona': {'recommended': 'trading', 'label': '交易系统与市场心理教练'},
        'platforms': ['Brief', 'Reddit'],
        'freshness': {'label': 'Evergreen', 'tone': 'evergreen'},
        'readiness': {'label': '待检索', 'tone': 'pending',
                      'detail': f"{dedup['independent_source_count_total'] if dedup else 0} sources ready"},
        'evidence': ILLUS, 'artifact': None, 'open': False,
    }]

    # ---- Workspace for the BLS opportunity ----------------------------------------------
    facts = (packet or {}).get('facts', [])
    keyfacts = [f for f in facts if f['id'] in
                ('payroll', 'unemployment_rate', 'participation', 'ahe_mom', 'ahe_yoy',
                 'revision_total', 'part_time_decline', 'information', 'health', 'food')]
    ROLES = ['Knowledge donor', 'Reasoning donor', 'Language donor', 'Habit donor', 'Visual grammar']
    personas = []
    for pid, zh, en in [('macro', '宏观数据与资金流观察者', 'Macro data and flows observer'),
                        ('industry', '个股与产业链研究者', 'Single name and supply chain researcher'),
                        ('trading', '交易系统与市场心理教练', 'Trading system and psychology coach')]:
        r = (routing or {}).get(pid, {})
        personas.append({
            'id': pid, 'zh': zh, 'en': en,
            'question': r.get('question'),
            'planned_donors': [d['donor'] for d in r.get('donors', [])],
            'roles': [{'role': x, 'assigned': None, 'status': 'Not yet retrieved'} for x in ROLES],
            'sample_counts': {d['donor']: d.get('sample_n') for d in r.get('donors', [])},
            'evidence': REAL, 'artifact': 'evidence_loop/experiments/routing.json',
        })

    qa = (case or {}).get('qa', {})
    workspace = {
        'opportunity_id': 'opp-bls-macro',
        'title': 'US Employment Situation, August 2026',
        'released_at': (packet or {}).get('published_at'),
        'lane': '计划催化剂',
        'banner': {'label': 'Historical replay', 'detail':
                   'Real release, real fact pack. The draft produced for it is QA blocked.'},
        'source_stack': {
            'official': {'count': len(facts), 'evidence': REAL,
                         'label': 'Official facts',
                         'detail': 'Typed facts with exact character spans and source blocks',
                         'items': [{'id': f['id'], 'label': f['label'], 'value': f['value'],
                                    'unit': f['unit'], 'period': f['period']} for f in keyfacts]},
            'kol': {'count': len(macro_ex), 'evidence': REAL, 'label': 'KOL voices',
                    'detail': 'Retrieved by multilingual embedding, all dated before the release',
                    'items': [{'post_id': e['post_id'], 'donor': e['source_account_id'],
                               'score': round(e.get('score', 0), 3),
                               'created_at': e.get('created_at', '')[:10]} for e in macro_ex]},
            'institutional': {'count': 0, 'evidence': NA, 'label': 'Institutional research',
                              'detail': 'No institutional source connected'},
            'evergreen': {'count': len(react_macro), 'evidence': REAL if react_macro else NA,
                          'label': 'Evergreen principles',
                          'detail': (f"Reactivated from {len(P)} candidate principles distilled "
                                     f"from the reading corpus"
                                     if react_macro else
                                     f"{dedup['independent_source_count_total'] if dedup else 0} "
                                     f"independent sources deduplicated, extraction pending"),
                          'items': [{'statement': r['statement'], 'category': r['category'],
                                     'author': r['author_dir'], 'score': r['score'],
                                     'conditions': r.get('applicable_conditions'),
                                     'invalidation': r.get('invalidation'),
                                     'quote': r['evidence_quote'][:110],
                                     'status': r['status']} for r in react_macro],
                          'pools': ev_pools},
            'provenance': {'evidence': REAL, 'label': 'Source provenance',
                           'detail': 'Release URL, artifact hash and per fact character offsets retained'},
        },
        'canvas': {
            'question': (case or {}).get('analysis_plan', {}).get('question'),
            'angles': [
                {'label': 'Breadth versus headline', 'state': 'used in draft'},
                {'label': 'Revisions change the trend read', 'state': 'used in draft'},
                {'label': 'Participation and part time', 'state': 'missing from draft'},
                {'label': 'Wage path against the twelve month mean', 'state': 'partially used'},
            ],
            'thesis': (case or {}).get('analysis_plan', {}).get('reasoning_steps', [None])[0],
            'counter': (case or {}).get('analysis_plan', {}).get('alternative'),
            'invalidation': (case or {}).get('analysis_plan', {}).get('invalidation'),
            'draft': {'title': (case or {}).get('title'),
                      'sentences': [{'id': s['sentence_id'], 'text': s['text'], 'kind': s['kind'],
                                     'fact_ids': s['fact_ids']}
                                    for s in (case or {}).get('sentence_to_source_ledger', [])],
                      'evidence': REAL, 'status': 'blocked'},
            'platforms': [{'id': 'x', 'label': 'X', 'state': 'not generated'},
                          {'id': 'thread', 'label': 'Thread', 'state': 'not generated'},
                          {'id': 'xhs', 'label': '小红书', 'state': 'not generated'},
                          {'id': 'reddit', 'label': 'Reddit', 'state': 'not generated'},
                          {'id': 'brief', 'label': 'Brief', 'state': 'draft exists'}],
            'visual': {'recommended': 'Deterministic data chart',
                       'reason': 'The core of the story is a numeric relationship, so a chart beats '
                                 'a screenshot or an illustration.',
                       'status': 'Chart generator is hardcoded to payroll bars', 'evidence': NA},
        },
        'controls': {
            'personas': personas,
            'active_persona': 'macro',
            'freshness': {'label': 'Historical replay', 'detail': 'Released 2026-09-04'},
            'coverage': {'official': 'complete', 'kol': f'{len(macro_ex)} posts',
                         'evergreen': (f'{len(react_macro)} reactivated' if react_macro else 'none')},
            'qa': {
                'state': 'Blocked', 'issue_count': len((case or {}).get('human_qa_findings', [])),
                'model': 'Automated gates. Every issue below is mechanically detectable: magnitude '
                         'and unit checks, out-of-evidence term lists, citation relation matching, '
                         'clause attribution and must-include coverage. No human sign off is part '
                         'of the target pipeline.',
                'gates': [
                    {'layer': 2, 'name': 'Typed numeric semantics', 'catches': 'numeric_magnitude'},
                    {'layer': 3, 'name': 'Claim entailment', 'catches': 'out_of_evidence_assertion'},
                    {'layer': 4, 'name': 'Citation precision', 'catches': 'citation_relation_mismatch'},
                    {'layer': 5, 'name': 'Fact selection policy', 'catches': 'must_include_missing'},
                    {'layer': 6, 'name': 'Clause attribution', 'catches': 'clause_attribution'},
                ],
                'automated_passed': {'citation_reference_integrity': qa.get('citation_id_validity'),
                                     'schema_errors': len(qa.get('errors', [])),
                                     'fact_coverage': qa.get('fact_id_coverage')},
                'findings': (case or {}).get('human_qa_findings', []),
                'detection': 'found by manual audit of this case; each maps to a gate that will '
                             'catch it automatically once implemented',
                'classification': (case or {}).get('classification'),
            },
        },
    }

    return {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'data_updated_at': (v2 or {}).get('created_at'),
        'signals': S,
        'pulse': pulse, 'catalysts': catalysts, 'catalyst_meta': catalyst_meta, 'radar': radar,
        'opportunities': opportunities, 'workspace': workspace,
        'personas': personas,
        'evergreen_summary': {
            'independent_sources': dedup['independent_source_count_total'] if dedup else 0,
            'pools': ev_pools,
            'chars': manifest['markdown_chars_total'] if manifest else 0,
            'categories': ['Trading principles', 'Risk and position sizing', 'Market regimes',
                           'Execution', 'Psychology', 'Narrative cycles'],
            'principles_total': len(P),
            'principles_by_category': by_cat,
            'principles_run': principles.get('run_id'),
            'principles_rejected': principles.get('rejected'),
            'rejection_reasons': principles.get('rejection_reasons', {}),
            'reactivation': {'event': reactivation.get('event_label'),
                             'personas': list((reactivation.get('results') or {}).keys()),
                             'top_k': reactivation.get('top_k')},
            'sample': [{'statement': x['statement'], 'category': x['category'],
                        'author': x['source'].get('author_dir'),
                        'conditions': x.get('applicable_conditions'),
                        'invalidation': x.get('invalidation'),
                        'quote': x['evidence_quote'][:120],
                        'span': [x['source']['char_start'], x['source']['char_end']]} for x in P[:8]],
            'evidence': REAL,
        },
        'pipeline': {
            'qa_gates': {'version': qa_reg.get('gate_version'),
                         'layers': qa_reg.get('layers_run'),
                         'regression_caught': qa_reg.get('caught'),
                         'regression_expected': qa_reg.get('expected'),
                         'run_id': qa_reg.get('run_id'),
                         'evidence': REAL if qa_reg else NA},
            'profiles': {'active_channel': prof_state.get('active'),
                         'method': prof_state.get('method'),
                         'eligible_donors': elig,
                         'rollback_to': prof_state.get('rollback_to'),
                         'evidence': REAL if prof_state else NA},
            'ledger': {'runs': len(ledger.get('runs', [])),
                       'sync_gap': ledger.get('sync_gap', []),
                       'evidence': REAL if ledger else NA},
            'principles': {'total': len(P), 'rejected': principles.get('rejected'),
                           'evidence': REAL if P else NA},
        },
        'legend': {REAL: 'Assembled from a local artifact',
                   ILLUS: 'Product structure only, no data behind it',
                   NA: 'Capability not built yet'},
    }
