"""Risk rules for every draft (Oct 8, 36 accounts; Fiona: prepare meme / airdrop accounts).

Deterministic HARD checks (live/qa_levels.HARD), on top of the existing HOLD rules (no fabrication, no wrong numbers,
no unreadable jargon, no trade calls):
  contract_address   a token contract address in the body (EVM 0x..40 hex, Solana / Tron base58, or a 'CA:' label)
  guaranteed_return  稳赚 / 保本 / 必涨 / 百倍币 / guaranteed returns / risk-free yield / next 100x ... unless negated
                     ('没有保本的理财', 'there is no risk-free yield' are fine)
  scam_promotion     a call to act (冲 / 上车 / 抓紧 / ape in / claim now ...) next to presale / whitelist / wallet-approval /
                     'send funds' wording in the same sentence: the draft is pushing readers into a scam-shaped flow
  referral_link      invite / referral / rebate codes and links (邀请码 / 返佣 / use my code)
They apply to all accounts (a contract address or 'guaranteed' never belongs in any of them); the meme / airdrop /
prediction / yield accounts also carry them as stance rejects so the writer avoids them up front.
"""
from __future__ import annotations

import re

VERSION = 'risk-rules-v1'
HARD_CODES = ('contract_address', 'guaranteed_return', 'scam_promotion', 'referral_link')

URL = re.compile(r'https?://\S+')
EVM_ADDRESS = re.compile(r'(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9A-Za-z])')
# base58 (no 0 O I l), 32-44 chars, with both a digit and a letter: Solana mints (often ...pump), Tron (T...)
B58_ADDRESS = re.compile(r'(?<![0-9A-Za-z])(?=[1-9A-HJ-NP-Za-km-z]*\d)(?=[1-9A-HJ-NP-Za-km-z]*[A-Za-z])'
                         r'[1-9A-HJ-NP-Za-km-z]{32,44}(?![0-9A-Za-z])')
CA_LABEL = re.compile(r'(?:\bCA\b|合约地址|代币地址|contract address)\s*[:：]\s*\S{6,}', re.I)

ZH_GUARANTEE = re.compile(r'稳赚(?:不赔)?|稳赢|包赚|保本|保收益|无风险(?:收益|套利|理财)?|零风险|必涨|必中|必有空投|百倍币|千倍币|十倍币|'
                          r'闭眼(?:冲|买|入)|躺赚|稳拿|稳吃|白送的钱|白捡的钱|只涨不跌')
EN_GUARANTEE = re.compile(r"\bguaranteed\s+(?:returns?|profits?|gains?|yields?|airdrops?|allocations?|wins?|money|income)\b|"
                          r"\brisk[- ]free\s+(?:yields?|returns?|profits?|money|trades?|income|apy)\b|\bcan'?t lose\b|"
                          r"\bfree money\b|\bnext\s+\d{2,4}x\b|\b\d{3,4}x\s+gems?\b|\b100x (?:coin|token|play)s?\b|\bsure thing\b|\beasy money\b|"
                          r"\bprinting money\b|\bzero risk\b", re.I)
ZH_NEGATION = re.compile(r'(?:不|没有|没|并非|别信|不是|谈不上|不存在|哪有|哪来的|从来没有|无所谓|所谓的?|号称|宣称|声称|打着)\S{0,3}$')
EN_NEGATION = re.compile(r"(?:\bno\b|\bnot\b|\bnever\b|isn'?t|aren'?t|\bnothing\b|there'?s no|without|so-called|"
                         r"\bpromis\w*|\bclaim\w*|\bmarketed as|\bsold as|\bpitch\w*)\W+(?:\w+\W+){0,3}$", re.I)

ZH_ACT = re.compile(r'冲(?!量|击|突|淡|高回落)|上车|赶紧|快去|速度|抓紧|进场|梭哈|别错过|错过就没|马上|立刻')
EN_ACT = re.compile(r"\bape(?:\s+in)?\b|\bget in\b|\bdon'?t miss\b|\bhurry\b|\bclaim (?:now|here|yours)\b|\bjoin now\b|"
                    r"\bbuy (?:now|before)\b|\bact fast\b|\bbefore it'?s too late\b|\bsend\b", re.I)
SCAM_MARK = re.compile(r'预售|私募|白名单|授权钱包|连接钱包|转账到|打款到|领取链接|presale|pre-sale|private sale|whitelist|'
                       r'connect (?:your )?wallet|approve (?:the )?(?:contract|spend)|send (?:eth|sol|usdt|usdc|bnb|funds)|'
                       r'claim link|airdrop checker link', re.I)
REFERRAL = re.compile(r'邀请码|返佣|推荐码|注册链接|返现链接|ref(?:erral)?\s*(?:code|link)|use (?:my )?code|invite code|'
                      r'promo code|sign up with my', re.I)


def _sentences(text):
    return [s for s in re.split(r'(?<=[。！？!?\n;；])|(?<=\.)\s', text) if s.strip()]


def _negated(text, start, zh):
    before = text[max(0, start - 30):start]
    return bool((ZH_NEGATION if zh else EN_NEGATION).search(before))


def findings(body, lang=None):
    """HARD risk findings for a draft body ([{'code', 'detail'}])."""
    text = str(body or '')
    if not text.strip():
        return []
    out = []
    plain = URL.sub(' ', text)
    addrs = [m.group(0) for m in EVM_ADDRESS.finditer(plain)] + [m.group(0) for m in B58_ADDRESS.finditer(plain)]
    addrs += [m.group(0) for m in CA_LABEL.finditer(plain)]
    if addrs:
        out.append({'code': 'contract_address', 'detail': ', '.join(dict.fromkeys(a[:16] + '…' for a in addrs))})
    hits = [m.group(0) for m in ZH_GUARANTEE.finditer(text) if not _negated(text, m.start(), True)]
    hits += [m.group(0) for m in EN_GUARANTEE.finditer(text) if not _negated(text, m.start(), False)]
    if hits:
        out.append({'code': 'guaranteed_return', 'detail': '、'.join(dict.fromkeys(hits))})
    scam = []
    for s in _sentences(text):
        mark = SCAM_MARK.search(s)
        act = ZH_ACT.search(s) or EN_ACT.search(s)
        if mark and act and not _negated(s, act.start(), lang == 'zh'):
            scam.append(s.strip()[:60])
    if scam:
        out.append({'code': 'scam_promotion', 'detail': ' | '.join(scam)})
    refs = [m.group(0) for m in REFERRAL.finditer(text)]
    if refs:
        out.append({'code': 'referral_link', 'detail': '、'.join(dict.fromkeys(refs))})
    return out


FIXES = {
    'contract_address': ('Delete the contract address / CA line. Name the token by its ticker or project name only; '
                         'never give readers an address to buy (不写合约地址，只写项目名或代币符号).'),
    'guaranteed_return': ('Remove the guarantee wording (稳赚 / 保本 / 必涨 / 百倍 / guaranteed / risk-free / next 100x). '
                          'Say what the return depends on and what can go wrong instead (写清楚收益靠什么、风险在哪).'),
    'scam_promotion': ('Do not push readers into a presale / whitelist / wallet-approval / send-funds flow. If the project '
                       'is worth mentioning, describe it and its red flags in the third person, with no call to act '
                       '(写成观察和风险提示，不号召参与).'),
    'referral_link': 'Delete the invite / referral / rebate code or link; drafts never carry one (不带邀请码、返佣链接).',
}
