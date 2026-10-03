"""Private source annotations and review flags. Never rewrites or redacts a body.

Patterns nominate spans for editorial judgment; they do not establish ownership or
semantic dispensability. Offsets are Unicode [start,end) in the immutable source.
"""
from datetime import datetime, timezone
import re
from live.distillation_source import digest
from live.numeric_fidelity import verified_time_anchors

VERSION = 'source-hygiene-v2-research-history-context'
ACTIONS = {'retain', 'remove', 'attribute', 'needs_context', 'out_of_scope'}
ADDRESS = r'(?<![\w])(?:0x[a-fA-F0-9]{40}|bc1[a-zA-HJ-NP-Z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|[1-9A-HJ-NP-Za-km-z]{32,44})(?![\w])'
PERSONAL = r'\b(?:I|my|mine|we|our)\b|我(?:们|的)?|本人|笔者'
OWNERSHIP = r'(?:\b(?:my|our)\s+(?:positions?|holdings?|portfolio|book|fund|wallet|returns?|clients?|career)\b|\b(?:I|we)\s+(?:hold|own|bought|sold|manage|earned|made|worked|work|charge|built|have\s+(?:a\s+)?(?:position|portfolio))\b|(?:我(?:们)?|本人|笔者).{0,16}(?:持仓|仓位|买入|卖出|赚了|收益|回报|管理基金|任职|工作|收取|钱包))'
RESEARCH_HISTORY = (r'\b(?:my|our)\s+(?:(?:earlier|previous|recent|prior)\s+)?(?:research|reports?|studies|study|analysis|data|models?|estimates?)\b|'
    r'\b(?:I|we)\s+(?:(?:have|had)\s+(?:been\s+)?|previously\s+|earlier\s+)?(?:covering|reported|published|documented|measured|collected|tested|estimated|studied|study|constructed|developed)\b|'
    r'我(?:们)?(?:的)?(?:(?:此前|之前|先前|最近)的?)?(?:研究|报告|报道|数据|模型|实证|测算|调查)|'
    r'我(?:们)?(?:(?:一直|长期|此前|曾经|曾|已经|已)在?)?(?:报道|跟踪|发表|撰写|构建|搜集|收集|研究|测量|测算)|'
    r'我(?:们)?通过[^。！？!?;；\n]{0,55}来研究|我(?:们)?将[^。！？!?;；\n]{0,55}衡量为')
PATTERNS = {
    'holdings': r'\b(?:my|our)\s+(?:positions?|holdings?|portfolio|book)\b|\b(?:I|we)\s+(?:hold|own|bought|sold|am long|am short)\b|(?:我(?:们)?|本人|笔者).{0,12}(?:持仓|仓位|买入|卖出|做多|做空)|(?:我的|本人)组合',
    'wallet_or_contract_address': ADDRESS,
    'contact_details': r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:微信|wechat|telegram|联系我|私信我|DM me|contact me)\s*[:：]?\s*[@\w+.-]*|(?<!\w)\+\d[\d ()-]{7,}\d',
    'referral_link': r'https?://[^\s<>"）)]+(?:[?&](?:ref|referral|affiliate|invite|inviteCode|aff|refcode)=)[^\s<>"）)]+|https?://(?:t\.me|discord\.gg)/[^\s<>"）)]+',
    'cta': r'\b(?:subscribe to|sign up|follow me|join (?:my|our|the) (?:group|channel|newsletter)|use (?:my |our )?(?:code|link)|click (?:the |this )?link|DM me|like and (?:share|repost))[^\n。.!?]*|(?:订阅我的|关注我|扫码|加入我的|加入我们|加群|邀请码|推荐码|点击链接|点赞转发|私信我)[^\n。！？]*',
    'employment_history': r'\b(?:I|we)\s+(?:work(?:ed)?|manage(?:d)?|founded|built|charge)\b|\b(?:my|our)\s+(?:career|employer|clients?|fund|fees?)\b|(?:我(?:们)?|本人).{0,15}(?:任职|工作|创办|管理基金|收取|收费|客户)',
    'personal_performance': r'\b(?:my|our)\s+(?:returns?|performance|P&L|profit)\b|\b(?:I|we)\s+(?:made|earned|returned|lost)\s+[$\d]|(?:我(?:们)?|本人).{0,12}(?:收益|回报|赚了|亏了|盈利)',
    'research_history': RESEARCH_HISTORY,
    'time_relative': r'\b(?:today|tonight|yesterday|tomorrow|now|currently|this (?:week|month|year|morning)|next (?:week|month|year)|last (?:week|month|year))\b|今天|今晚|昨天|明天|本周|这周|下周|上周|本月|这个月|今年|明年|去年|现在|目前|如今|眼下|刚刚',
    'media_reference': r'\b(?:as (?:shown|seen) (?:in|below)|see (?:the |this )?(?:chart|image|video|thread)|chart below|pictured|in the (?:chart|image|video)|thread below|(?:shown|illustrated|depicted) (?:below|above))\b|如图|下图|上图|图中|这张图|看图|视频里|视频中|接上文|下(?:一)?条(?!件|款)|见线程|如下图|如下所示|(?:可见|详见|参见|见)(?:于)?(?:下文|上文)',
    'content_continuation': r'\b(?:here we (?:explain|show)|we will (?:explain|show|discuss) (?:below|later))\b|(?:这里|下文|下面)(?:我(?:们)?)?(?:将|会|要)(?:解释|介绍|讨论|展示)',
    'platform_artifact': r'(?<!\w)@[A-Za-z0-9_]{1,15}|(?<!\w)\$[A-Z][A-Z0-9.]{0,9}\b|https?://t\.co/\S+|(?:^|\n)RT\s+|(?:^|\n)\d{1,2}/\d{1,2}\b',
}


def annotate(source):
    text=source['original_text'];rows=[]
    quotes=list(re.finditer(r'“[^”\n]+”|「[^」]+」|"[^"\n]+"',text))
    def add(kind,start,end,quote,metadata=None):
        left=max(text.rfind('\n',0,start),text.rfind('。',0,start))+1 if start is not None else None
        right=next((i for i in range(end,len(text)) if text[i] in '\n。!?！？'),len(text)) if end is not None else None
        rows.append({'id':digest([VERSION,source['source_hash'],kind,start,end,quote,metadata])[:20],
          'kind':kind,'start':start,'end':end,'quote':quote,
          'context':text[left:right+1] if left is not None else '',
          'speaker_hint':'quoted_speaker_unresolved' if start is not None and any(q.start()<=start<q.end() for q in quotes) else 'source_author_or_unspecified',
          'basis':'pattern_candidate' if start is not None else 'source_metadata',
          'semantic_necessity':'unreviewed','metadata':metadata})
    for kind,pattern in PATTERNS.items():
        for match in re.finditer(pattern,text,re.I):add(kind,match.start(),match.end(),match.group())
    for match in quotes:add('quoted_speech',match.start(),match.end(),match.group())
    for key in ('media_dependencies','reply_to','quoted_post','thread_id','thread_post_ids'):
        if source.get(key):add('context_dependency',None,None,'',{'field':key,'value':source[key]})
    return {'version':VERSION,'source_hash':source['source_hash'],'annotations':rows,
            'original_unchanged':True,'method':'pattern hints + source metadata; not semantic adjudication'}


def selected_annotations(report,selection):
    return [a for a in report['annotations'] if a['start'] is None or any(
        a['start']<p['end'] and a['end']>p['start'] for p in selection['passages'])]


def validate_decisions(value,annotations):
    if not isinstance(value,list):raise ValueError('Missing source-hygiene editorial decisions')
    ids={a['id'] for a in annotations};seen=set()
    for row in value:
        if not isinstance(row,dict) or row.get('annotation_id') not in ids or row['annotation_id'] in seen:
            raise ValueError('Unknown or duplicate source-hygiene decision')
        if row.get('action') not in ACTIONS or not isinstance(row.get('reason'),str) or not row['reason'].strip():
            raise ValueError('Source-hygiene decision needs action and semantic reason')
        if row['action']=='attribute' and not str(row.get('attribution','')).strip():
            raise ValueError('Attribution decision needs the actual speaker')
        seen.add(row['annotation_id'])
    if seen!=ids:raise ValueError('Not every selected source artifact was considered')
    return value


def enabled(account):return (account.get('source_hygiene') or {}).get('enabled') is True


def editorial_prompt():
    return '''Private source hygiene / identity boundary: annotations are uncertain hints, NOT a deletion list.
Decide from the original meaning whether each selected artifact is necessary, removable, needs
local attribution, irrelevant to the chosen passage, or requires missing context. Preserve valuable
experience, examples, quotations, conditions and force. Ordinary opinions need no default author
byline. A holding, employment, return, fee or history belongs to its actual speaker, never the target
account. A quotation's speaker is not automatically the source author. Historic relative times must
remain anchored to the source date, not read as current advice. Wallet/address or CTA examples may
be essential evidence; distinguish those from an invitation to send funds, subscribe or contact.
Keep all annotations/decisions/QA private. Do not add audit explanations to public copy.
Return hygiene_decisions for every annotation overlapping the selected passages (metadata
dependencies also need a decision): [{annotation_id,action:"retain|remove|attribute|needs_context|out_of_scope",
reason:"specific semantic purpose or reason it is dispensable",attribution:"actual speaker if needed"}].
Do not mechanically remove every flagged span or delete meaningful reasoning to evade a check.'''


WRITER_BOUNDARY = '''Source-hygiene decisions are private editorial guidance, subordinate to source meaning.
Do not transfer personal holdings, wallets, work, history or returns to this account. Preserve necessary
experience using local attribution, not a default "author said" wrapper. Do not publish a source CTA
as our invitation. Keep relative dates historically anchored when necessary. Retain semantically
necessary quoted speech or technical address examples with clear context; never turn them into
naked addresses or a payment instruction. Do not narrate your hygiene/QA/editing process in the post.'''


def date_value(value):
    if not value:return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError,AttributeError):
        from email.utils import parsedate_to_datetime
        try:return parsedate_to_datetime(value).astimezone(timezone.utc)
        except (ValueError,TypeError):return None


def postcheck(source,text,guidance='',decisions=(),as_of=None):
    """Uncertain risks require human disposition; findings never edit `text`."""
    rows=[];as_of=date_value(as_of) or datetime.now(timezone.utc)
    def flag(code,quote,detail,location='draft',level='review'):
        rows.append({'id':digest([VERSION,code,quote,location])[:20],'code':code,'quote':quote,
                     'detail':detail,'location':location,'level':level,'status':'open','method':'heuristic; human review required'})
    author=source.get('author_name') or source.get('author_handle') or ''
    def local_context(start,end):
        boundaries=list(re.finditer(r'(?<=[.!?])\s+|[。！？]\s*|\n',text))
        left=max([0]+[m.end() for m in boundaries if m.end()<=start])
        right=min([len(text)]+[m.start() for m in boundaries if m.start()>=end])
        return text[max(left,start-180):min(right,end+180)]
    def attributed(context):
        named=author and author.casefold() in context.casefold() and re.search(r'\b(?:said|says|wrote|noted|explained|disclosed|recalled|according to)\b|提到|说|自述|写道',context,re.I)
        return bool(named or re.search(
          r'原作者|作者(?:提到|说|自述|的)|他(?:的|说)|她(?:的|说)|\b(?:the author|he said|she said|his positions|her positions)\b',context,re.I))
    for match in re.finditer(OWNERSHIP+'|'+RESEARCH_HISTORY,text,re.I):
        if not attributed(local_context(match.start(),match.end())):
            flag('possible_identity_transfer',match.group(),'Personal ownership/history has no clear local speaker attribution.')
    if re.search(PATTERNS['holdings']+'|'+PATTERNS['employment_history']+'|'+PATTERNS['personal_performance']+'|'+RESEARCH_HISTORY,source['original_text'],re.I):
        if re.search(r'(?:keep|retain|preserve|stay).{0,50}(?:first.person|\bI\b|\bmy\b)|(?:第一人称.{0,12}保留|保留.{0,12}第一人称|用第一人称)|(?:own book|my positions).{0,50}(?:stance|opinion)',guidance,re.I):
            flag('guidance_identity_boundary',guidance,'Editorial advice may preserve personal first person without preserving its owner. Check guidance independently.','editorial_guidance')
    for match in re.finditer(ADDRESS,text):
        context=local_context(match.start(),match.end())
        if not re.search(r'example|sample|contract|address of|wallet of|示例|合约|地址属于|钱包属于',context,re.I):
            flag('naked_address',match.group(),'Wallet/contract-like token appears without explanatory ownership or technical context.')
        else:flag('address_context_review',match.group(),'Check whether publishing this exact technical example is necessary.','draft','note')
    published=date_value(source.get('published_at'));stale=not published or (as_of-published).total_seconds()>48*3600
    _, verified_anchors=verified_time_anchors(source['original_text'],text,source)
    if stale:
        for match in re.finditer(PATTERNS['time_relative'],text,re.I):
            context=local_context(match.start(),match.end())
            adjacent_anchor=any(text[match.start():].startswith(note['quote']) for note in verified_anchors)
            # A spaced Chinese year/month is still an explicit date. A bare
            # year only licenses the exact adjacent source-supported year above.
            date_anchor=adjacent_anchor or re.search(r'\b20\d{2}\s*[-/年]\s*\d{1,2}|\b(?:on|in)\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\b|截至.{0,18}\d',context,re.I)
            if not date_anchor:flag('stale_time_reference',match.group(),'Relative time is not locally anchored to the historical source date.' if published else 'Source date is unknown; relative time needs review.')
    for match in re.finditer(PATTERNS['media_reference'],text,re.I):
        flag('media_or_thread_reference',match.group(),'Verify the referenced visual/thread will accompany this draft; backend media presence alone is not delivery.')
    for match in re.finditer(PATTERNS['content_continuation'],text,re.I):
        flag('content_continuation_reference',match.group(),'Check that the promised explanation is actually included in this standalone post; do not remove it mechanically.')
    for kind,code in [('cta','source_cta'),('referral_link','referral_link_publication'),('contact_details','contact_publication')]:
        for match in re.finditer(PATTERNS[kind],text,re.I):
            context=local_context(match.start(),match.end())
            if attributed(context) and re.search(r'[“"「]',context):
                flag(code,match.group(),'Quoted source artifact: review its semantic purpose and ownership.','draft','note')
            else:flag(code,match.group(),'Source-specific invitation/contact may read as belonging to the target account.')
    for row in decisions:
        if row.get('action')=='needs_context':flag('unresolved_source_context','',row.get('reason','Missing context'),'source')
    return {'version':VERSION,'checked_at':as_of.isoformat(),'draft_hash':digest(text),'findings':rows,
            'requires_review':any(r['level']=='review' for r in rows),'original_unchanged':True}


def eligible(account,source):
    allowed=(account.get('source_preferences') or {}).get('only_handles') or []
    if not allowed:return True
    from urllib.parse import urlparse
    path=urlparse(source.get('url') or '').path.strip('/').split('/')
    handles={str(source.get(k) or '').lstrip('@').lower() for k in ('author_handle','author_name')}
    if len(path)>2 and path[1]=='status':handles.add(path[0].lower())
    if str(source.get('source_id') or '').startswith('x_'):handles.add(source['source_id'][2:].lower())
    return bool(handles & {str(h).lstrip('@').lower() for h in allowed})
