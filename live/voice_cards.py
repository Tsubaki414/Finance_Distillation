"""Deterministic donor-weighted style evidence. Never a source of facts or phrases."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re

HOOKS = ('question', 'number-led', 'claim-led', 'breaking', 'emoji-led', 'quote')
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF]')
PROMO = re.compile(r'\b(?:giveaway|sponsored|paid partnership)\b|(?:^|\s)#ad\b|subscribe now|paid subscription|(?:my |our )discount code|use (?:my |our )?(?:promo|discount) code|抽奖|付费推广|广告合作', re.I)


def load_posts(handle, posts_dir):
    root = Path(posts_dir)
    for suffix in ('.json', '.jsonl'):
        path = root / (handle.lower() + suffix)
        if not path.exists():
            path = next(iter(sorted(root.glob(handle + suffix))), path)
        if path.exists():
            if suffix == '.jsonl':
                return [json.loads(line) for line in path.read_text().split('\n') if line.strip()]
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else data.get('posts', [])
    return []


def load_tags(handle, tags_dir):
    path = Path(tags_dir) / (handle.lower() + '.json')
    if not path.exists():
        path = Path(tags_dir) / (handle + '.json')
    return json.loads(path.read_text()) if path.exists() else {}


def excluded(post, tag):
    return bool(post.get('ad') or post.get('is_ad') or post.get('giveaway') or
                tag.get('ad') or tag.get('is_ad') or tag.get('giveaway') or tag.get('is_promotion') or
                post.get('is_promotion') or
                tag.get('post_type') in ('ad', 'ads', 'advertisement', 'promo', 'promotion', 'giveaway') or
                PROMO.search(post.get('text', '')))


def promo_heavy(info):
    return bool(info.get('promo_heavy') or info.get('donor_fit') == 'promo_heavy' or
                'promo_heavy' in (info.get('flags') or []) or info.get('tone') == 'promo_heavy')


def timestamp(post):
    value = post.get('created') or post.get('created_at') or post.get('timestamp')
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def hook(line):
    if re.match(r'^(?:breaking|突发|快讯)\b', line, re.I):
        return 'breaking'
    if EMOJI.match(line):
        return 'emoji-led'
    if line.startswith(('"', '“', '「', '‘', "'")):
        return 'quote'
    if '?' in line or '？' in line:
        return 'question'
    if re.match(r'^[$€£¥]?\d', line):
        return 'number-led'
    return 'claim-led'


def quantile(values, q):
    """Weighted empirical quantile; each donor contributes its roster mass."""
    if not values:
        return None
    ordered = sorted(values)
    target = sum(w for _, w in ordered) * q
    running = 0
    for value, weight in ordered:
        running += weight
        if running >= target:
            return round(value, 4)
    return ordered[-1][0]


def grams(text, lang):
    text = re.sub(r'https?://\S+', '', text)
    tokens = re.findall(r'[\u4e00-\u9fff]', text) if lang == 'zh' else re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    n = 4 if lang == 'zh' else 3
    return {('' if lang == 'zh' else ' ').join(tokens[i:i+n]) for i in range(len(tokens)-n+1)}


def build_cards(posts_dir, tags_dir, roster):
    roster = json.loads(Path(roster).read_text()) if not isinstance(roster, dict) else roster
    corpus = {}
    background = Counter()
    bg_posts = 0
    for handle, info in sorted(roster['donors'].items()):
        if promo_heavy(info):
            continue
        tags = load_tags(handle, tags_dir)
        rows = [(p, tags.get(str(p.get('id')), {})) for p in load_posts(handle, posts_dir)
                if not p.get('reply') and not p.get('rt') and not p.get('pinned') and p.get('text', '').strip()]
        rows = [(p,t) for p,t in rows if not excluded(p,t)]
        corpus[handle.lower()] = rows
        for p,t in rows:
            background.update(grams(p['text'], info.get('lang', 'en')))
            bg_posts += 1
    cards = {}
    for name, cluster in sorted(roster['persona_clusters'].items()):
        lang = cluster['lang']
        rows = []
        daily = []; hours = Counter(); dated_mass = 0
        donors = {}
        for d in cluster['donors']:
            own = corpus.get(d['handle'].lower(), [])
            if not own:
                continue
            donors[d['handle']] = d['weight']
            weight = d['weight']/len(own)
            dates = []
            for p,t in sorted(own, key=lambda row: str(row[0].get('id'))):
                rows.append((d['handle'],p,t,weight))
                dt = timestamp(p)
                if dt:
                    dates.append(dt.date()); hours[dt.hour] += weight; dated_mass += weight
            if dates:
                # Includes inactive days inside the observed interval; truncated scrape, not a publishing target.
                span = (max(dates)-min(dates)).days+1
                counts = Counter(dates)
                daily.extend((counts.get(min(dates).fromordinal(min(dates).toordinal()+i),0),d['weight']/span) for i in range(span))
        mass = sum(w for _,_,_,w in rows)
        hooks = {h:{'share':0, 'first_lines':[]} for h in HOOKS}
        sentences=[]; mix=Counter(); signatures=Counter(); rawfreq=Counter(); norms=Counter()
        evidence=[]
        for handle,p,t,w in rows:
            text=p['text'].strip(); first=text.split('\n')[0].strip(); h=hook(first)
            hooks[h]['share'] += w
            e={'handle':handle,'id':str(p['id']),'text':text[:140]}
            evidence.append(e)
            if len(hooks[h]['first_lines'])<3:
                hooks[h]['first_lines'].append({'handle':handle,'id':str(p['id']),'text':first})
            parts=[s.strip() for s in re.split(r'[。！？!?\n]+|(?<=[a-z])\.\s+',text) if s.strip()]
            for s in parts:
                size=len(re.sub(r'\s','',s)) if lang=='zh' else len(re.findall(r"\b[\w']+\b",s))
                sentences.append((size,w/len(parts)))
            mix[t.get('post_type','unknown')] += w
            norms['emoji'] += w*bool(EMOJI.search(text))
            norms['thread'] += w*bool((t.get('structure') or {}).get('thread_marker') or p.get('thread') or p.get('self_thread') or re.search(r'(?:^|\n)\d+/\d*',text))
            norms['media'] += w*bool(p.get('media') or p.get('photos') or p.get('video') or p.get('videos'))
            norms['data'] += w*bool(t.get('numbers') or t.get('post_type') in ('data_take','earnings_take'))
            gs=grams(text,lang); rawfreq.update(gs)
            for g in gs: signatures[g] += w
        for value in hooks.values(): value['share']=round(value['share']/mass,9) if mass else 0
        signature=[{'phrase':g,'cluster_share':round(freq/mass,6),
                    'lift':round((freq/mass)/(background[g]/bg_posts),4),'do_not_copy':True}
                   for g,freq in signatures.items() if mass and rawfreq[g]>=2 and background[g] and bg_posts]
        signature.sort(key=lambda x:(-x['lift'],-x['cluster_share'],x['phrase']))
        short=evidence[:4]
        cards[name]={'version':1,'cluster':name,'lang':lang,'use':'Style evidence only; never copy phrases, facts, numbers or identity.',
                     'sample':{'posts':len(rows),'donors':donors},
                     'method':'Roster weights normalized over available eligible donors; equal mass per donor post; sentence mass equal within post. UTC cadence over observed scrape interval. Signature lift is weighted cluster document frequency divided by unweighted eligible all-donor document frequency (3-word EN / 4-character ZH n-grams, present in at least 2 cluster posts).',
                     'cadence':{'posts_per_day_median':quantile(daily,.5),'active_hours_utc':{str(h):round(v/dated_mass,6) for h,v in sorted(hours.items())}},
                     'hooks':hooks,'sentence_length':{'unit':'chars' if lang=='zh' else 'words','median':quantile(sentences,.5),'p25':quantile(sentences,.25),'p75':quantile(sentences,.75)},
                     'signature_phrasing':signature[:12],
                     **{key+'_rate':round(norms[key]/mass,6) if mass else None for key in ('emoji','thread','media')},
                     'data_opinion':{'data_share':round(norms['data']/mass,9) if mass else None,'opinion_share':round(1-norms['data']/mass,9) if mass else None,'data_to_opinion':round(norms['data']/(mass-norms['data']),9) if mass-norms['data']>1e-12 else None,'definition':'Data: numeric tags or data_take/earnings_take; opinion: remaining posts (proxy, not semantic verdict).'},
                     'post_type_mix':{k:round(v/mass,6) for k,v in sorted(mix.items())},
                     'do':[{'rule':'Lead with a clear judgment; use data to support it.','evidence':short},
                           {'rule':f'Prefer {max(hooks, key=lambda h: hooks[h]["share"])} openings and the observed sentence band as flexible guidance.','evidence':short}],
                     'dont':[{'rule':'Do not copy donor wording, personal experience, facts or numbers.','evidence':short},
                             {'rule':'Do not convert observed confidence into an unsupported trade call.','evidence':short}]}
    return cards


def compact_summary(card):
    if not card:
        return {}
    return {'hooks':{h:v['share'] for h,v in card['hooks'].items()},
            'sentence_length':card['sentence_length'],
            'emoji_rate':card['emoji_rate'],'thread_rate':card['thread_rate'],
            'data_opinion':{k:card['data_opinion'][k] for k in ('data_share','opinion_share','data_to_opinion')},
            'do':[r['rule'] for r in card['do']], 'dont':[r['rule'] for r in card['dont']]}


def write_cards(cards, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        '# Donor voice cards', '',
        'Style evidence only. Signature phrases are do_not_copy markers. '
        'Cadence reflects the observed scrape, not a posting target. '
        'Missing hook examples remain empty; no examples are invented. '
        'Do/don’t snippets illustrate style, not recommended content.', '',
    ]
    for name, card in sorted(cards.items()):
        (out / (name + '.json')).write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
        lines.extend([
            f'## {name}', '',
            f"{card['sample']['posts']} eligible posts; {len(card['sample']['donors'])} weighted donors. "
            f"Language: {card['lang']}.", '',
            card['method'], '',
            '### Compact prompt summary', '', '```json',
            json.dumps(compact_summary(card), ensure_ascii=False, indent=2), '```', '',
            '### Cadence and media', '',
            f"Median posts/day: {card['cadence']['posts_per_day_median']}. "
            f"Media share: {card['media_rate']}.", '',
            'Active hours (UTC, weighted share): ' + json.dumps(card['cadence']['active_hours_utc']), '',
            '### Post type mix', '',
            '```json', json.dumps(card['post_type_mix'], indent=2), '```', '',
            '### First lines by hook', '',
        ])
        for kind, details in card['hooks'].items():
            lines.extend([f"**{kind}** — share {details['share']}", ''])
            if not details['first_lines']:
                lines.extend(['No observed examples.', ''])
            for example in details['first_lines']:
                text = example['text'].replace('\n', ' ')
                lines.append(f"- @{example['handle']} / {example['id']}: {text}")
            lines.append('')
        lines.extend([
            '### Signatures — do_not_copy', '',
            'Contrastive style markers only. Never use these as required phrases in prompts.', '',
        ])
        for marker in card['signature_phrasing']:
            lines.append(f"- {marker['phrase']} (share {marker['cluster_share']}; lift {marker['lift']}; do_not_copy)")
        lines.extend(['', '### Do / don’t with style evidence', ''])
        for kind in ('do', 'dont'):
            for rule in card[kind]:
                lines.append(f"- {kind}: {rule['rule']}")
                for example in rule['evidence']:
                    text = example['text'].replace('\n', ' ')
                    lines.append(f"  - @{example['handle']} / {example['id']}: {text}")
            lines.append('')
    (out / 'README.md').write_text('\n'.join(lines))
