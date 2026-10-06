"""Public 华尔街见闻 US stock articles; facts with attribution, no quotations."""
import json
from datetime import datetime, timezone
from live.adapters import common

LIST = 'https://api-one-wscn.awtmt.com/apiv1/content/information-flow?channel={channel}&accept=article&limit=10'
# v10 (Fiona approved 10/6): global-channel = macro/global desk, channels.json ch142_wscn_global.
CHANNELS = {'us-stock-channel': ('wallstreetcn', 'zh_us_stock_commentary'),
            'global-channel': ('ch142_wscn_global', 'macro_zh')}
ARTICLE = 'https://api-one-wscn.awtmt.com/apiv1/content/articles/{}?extract=0'


def is_paid(item):
    return any(item.get(k) for k in ('is_paid', 'is_priced', 'vip', 'is_vip'))


def fetch(*, limit=1, transport=None, channel='us-stock-channel'):
    source_id, persona = CHANNELS[channel]
    st, body = common.http_get(LIST.format(channel=channel), transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'sources': [], 'requests': 1}
    sources, requests = [], 1
    for item in json.loads(body).get('data', {}).get('items', []):
        resource = item.get('resource', item)
        if item.get('resource_type', 'article') != 'article':
            continue
        if is_paid(item) or is_paid(resource):
            continue
        if len(sources) >= max(0, limit):
            break
        st, article = common.http_get(ARTICLE.format(resource['id']), transport=transport)
        requests += 1
        if st != 200:
            continue
        data = json.loads(article).get('data', {})
        if is_paid(data):
            continue
        text = common.html_text(data.get('content', ''))
        if not text:
            continue
        timestamp = data.get('display_time') or resource.get('display_time')
        published = datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else ''
        sources.append(common.make_source(id=f'wscn-{resource["id"]}', source_id=source_id,
                      text=text, publisher='华尔街见闻', title=data.get('title') or resource.get('title', ''),
                      url=resource.get('uri') or f'https://wallstreetcn.com/articles/{resource["id"]}',
                      published_at=published, adapter=source_id, lang='zh',
                      extra={'no_reproduction': True, 'persona_hint': persona}))
    return {'status': 'ok' if sources else 'no_public_articles', 'sources': sources, 'requests': requests}
