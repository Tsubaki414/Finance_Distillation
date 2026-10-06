# ZH register (研报腔) root cause and fix — Oct 6 v5

Measured with `/workspace/x/zh_register/metrics.py` (drafts v2–v4b vs ZH donor corpus in
`live/donors/posts`, quoted speech / links stripped):

| persona | corpus | sentence len mean/median (CJK) | clauses/sentence | formal /1k | colloquial /1k |
|---|---|---|---|---|---|
| zh_macro | donors | 27.5 / 22 | 2.44 | 1.7 | 5.4 |
| zh_macro | drafts | 26.4 / 25 | 2.06 | 28.4 | 4.7 |
| zh_industry | donors | 23.5 / 18 | 2.29 | 1.5 | 6.1 |
| zh_industry | drafts | 27.5 / 26 | 1.92 | 19.7 | 3.0 |

Sentence length is not the problem; the lexicon is (formal connectives 13–17× donors).

Where the formality came from:
1. **thesis_lock**: the stance `account_view` (English STANCE prompt, research units) averaged
   39–45 CJK chars per sentence, 19–33 formal hits / 1k, 0 colloquial markers; COMPOSE line 1
   restates it (v4b zh_macro 「货币政策仍以流动性和结构性工具为主」 appears in both).
2. **English-only COMPOSE** plus research-prose units that were paraphrased sentence by sentence.
3. **Synthetic style anchors**: on judgment posts the only ZH style exemplars were curated
   "restraint" shapes (handle `overnight_clean`), clean written prose, not donor lines.

Fix (all soft):
- `live/zh_register.py`: Chinese system addendum `SYSTEM_ZH` (restate in own spoken words, do not
  paraphrase thesis_lock/units sentences; EN sources = translate + light edit; short sentences; no
  research connectives; no crowd-feeling attribution; no AI templates) and a payload block with 4
  real donor lines (`register_anchors`, rotated by source hash, filtered: 8–36 CJK chars, no digits /
  quotes / links / promo / abuse / 不是 / crowd attribution / research connectives) plus the donors'
  own connectors from `language_habits`.
- Stance: ZH personas get `account_view_register` (one spoken sentence ≤35 chars, no research words).
- Synthetic `overnight_clean` restraint shapes are no longer sent when the ZH register is on.
- Soft checks `zh_register` (≥2 research connectives or an AI template phrase; ~2% of donor posts
  of draft length trip it) and `market_feeling` (很多人认为 / 市场普遍认为 / 大家都觉得 …) join the
  one structure regeneration. Anchors are added to the copy check.
- Switches: `zh_register=False` / `FD_ZH_REGISTER=0`; default on only for ZH personas with a
  signature or voice card.
