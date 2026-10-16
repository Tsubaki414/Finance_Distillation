# AI-slop score (FD_SLOP_SCORE)

`live/slop_score.py` gives each final draft one soft score. Every AI-prose tell adds points; one tell stays below the
threshold, stacked or dense tells reach it (threshold 3.0, `FD_SLOP_THRESHOLD`).

| weight | tells |
|---|---|
| 2.0 | "isn't just X. It's Y" / "— it's Y", "don't just X, they Y", "not only X but", "No X, no Y, just Z", 没有…没有…只有…, 不只是/不仅是…更是, 不再是…而是, "Think of it as/like", 想象一下, 3+ distinct AI words |
| 1.0 | "the real question is" / 真正的问题在于, promo words (transformative, game-changing, 重塑, 前所未有 …), 2 AI words, 2 EN em-dashes, 这不是X。是Y |
| 0.5 | one zh 「——」, three-list with a filler last item (流动性、估值和情绪 / "momentum"), "robust, powerful and undeniably X" |

Exempt: text inside quotation marks; sentences with digits are exempt from the weak lexical tells (lists, promo, AI vocabulary).

Flow (daily_compose final loop, after humanize / fluency / opener fix): score ≥ threshold → ONE retry (deterministic:
`humanize.drop_moral_line`, `nat_tex.compress_dashes`; then the humanize LLM rewrite listing the template sentences,
checked by `_fidelity_ok`, `_entities_ok`, length and `rc_guard.guard_step`) → still ≥ threshold → HARD post_check
`ai_slop_score`, `needs_review` (held, not published). Row carries `slop_score` {score, tells, retried, held}.

Also: nat_tex A10 now compresses zh 「——」 to ≤ 1 per post; `drop_moral_line` also handles 2-sentence / 2-line posts
(first part must stay ≥ 8 zh / 25 en chars).

Rollback: `FD_SLOP_SCORE=0` turns off the score, the zh dash compression and the short-post moral cut.
Tests: `tests/test_slop_score_oct16.py`.
