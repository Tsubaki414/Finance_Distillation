"""Remove reviewed promotional spans from working copies; never alter source files.

Decisions are editorial content exclusions, not allegations of undisclosed payment.
Terms such as subscriptions, registration, or benefits alone are not evidence of ads.
"""
import re

VERSION = 'clean-v3-reviewed-commercial-spans'
FOOTER = re.compile(r'(?im)^[ \t]*(?:(?:@|#)Gate\b[^\n]*一站[^\n]*|(?:本条|此内容)[^\n]*赞助[^\n]*)[ \t]*$')
WHOLE_POSTS = {
    '2093047700967313632': 'deposit-to-claim-reward campaign and platform pitch',
    '2076589362339528766': 'single-project promotional pitch with signup CTA; no separable independent analysis selected',
    '2077259839638806616': 'brand-anniversary campaign and giveaway',
    '2094299708487557508': 'account-linking and subscription-reward campaign',
    '2063967212365570478': 'channel/video teaser and subscription CTA; questions without standalone analysis',
    '2064939368096383119': 'recruitment and membership benefits; not financial research',
    '2065059281226043839': 'paywalled research subscription CTA only',
    '2085251441632186444': 'brokerage-account signup pitch only',
    '2089382795550572867': 'membership-channel CTA without disclosed analysis',
    '2090799498901791227': 'performance teaser directing readers to paid membership',
    '2095052335676633160': 'paid membership launch, pricing and conversion offer',
    '2091835773423403168': 'single-platform product launch and account feature pitch without independent analysis',
    '2088554410159059441': 'single-project product and token launchpad pitch; conservatively excluded from persona exemplars',
}
TAILS = {
    '2080191070990963086': ('对币市用户来说，现在也能方便用期权来做美股交易了。', 'brokerage product, account-opening and pricing promotion'),
    '2083423924495196486': ('这有何差别？都在最新的一篇长文里', 'paywalled longform and subscription promotion'),
    '2071500949953417587': ('获取完整的list和mapping内容逻辑请订阅', 'paid membership CTA and price'),
}
EXACT_SPANS = {
    '2094731852733145287': [('更新在订阅里（X终于给我开订阅了），', 'self-subscription promotion embedded in analysis')],
}
# High precision output gate. This is a lexical screening layer, not proof that
# every possible undisclosed promotion can be detected automatically.
PROMOTION_GATE = re.compile(
    r'(?:@|#)Gate\b[^\n]*一站|邀请码|返佣|开户链接|优惠码|推广链接|'
    r'(?:请|欢迎|建议|立即|马上).{0,8}订阅|订阅起来|会员.{0,15}(?:最低价|提价|送一个月)|'
    r'入金.{0,35}(?:奖励|领取)|注册.{0,20}(?:领取|奖励|返现)|'
    r'开户极简|先把账户搭好|领取.{0,15}空投|'
    r'\b(?:affiliate link|referral code|promo code|sign up.{0,20}bonus|paid partnership)\b', re.I)

def clean_promotions(text, post_id=None):
    spans = []
    decision = WHOLE_POSTS.get(str(post_id))
    if decision:
        spans.append({'start': 0, 'end': len(text), 'text': text,
                      'reason': 'reviewed_whole_post_commercial_exclusion', 'review_note': decision})
    else:
        spans.extend({'start': m.start(), 'end': m.end(), 'text': m.group(),
                      'reason': 'explicit_isolated_sponsor_footer'} for m in FOOTER.finditer(text))
        if str(post_id) in TAILS:
            anchor, note = TAILS[str(post_id)]
            if text.count(anchor) != 1:
                raise ValueError(f'Promotion review anchor changed: {post_id}')
            start = text.index(anchor)
            spans.append({'start': start, 'end': len(text), 'text': text[start:],
                          'reason': 'reviewed_commercial_tail', 'review_note': note})
        for exact, note in EXACT_SPANS.get(str(post_id), []):
            if text.count(exact) != 1:
                raise ValueError(f'Promotion review span changed: {post_id}')
            start = text.index(exact)
            spans.append({'start': start, 'end': start + len(exact), 'text': exact,
                          'reason': 'reviewed_embedded_commercial_span', 'review_note': note})
    spans.sort(key=lambda s: s['start'])
    # Overlap is not silently accepted, so the provenance remains replayable.
    assert all(a['end'] <= b['start'] for a, b in zip(spans, spans[1:]))
    cleaned = text
    for span in reversed(spans):
        assert text[span['start']:span['end']] == span['text']
        cleaned = cleaned[:span['start']] + cleaned[span['end']:]
    return cleaned.strip(), spans, decision

def output_gate(text):
    return [{'start': m.start(), 'end': m.end(), 'match': m.group()} for m in PROMOTION_GATE.finditer(text)]
