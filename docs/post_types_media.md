# Post types beyond the plain post: quotes, reposts, replies, images (design only)

Status: 2026-10-07 implemented: quote/reply post_mode (`live/post_mode.py`), fetched-data charts (`live/charts.py`, dark candles + FRED/DefiLlama lines), `live/draft_media.py` + `scripts/apply_media.py`, public-heat re-rank (`live/heat.py`, FD_HEAT=1, $0.20/day cap). Screenshots and replies (phase 2) not yet. Scope: the 20 fd20 main accounts. Publishing stays manual: FD
produces drafts and assets for the review inbox; a human posts by hand. Nothing here adds a publish call,
a scheduler that posts, or X API write access.

## 1. What exists today

- `live/posting_habits.py` already samples a `post_format` per draft from each account's donor cluster
  (`post_type_mix`: one_liner, quick_take, news_flash, chart_caption, list_dump, long_take, thread,
  quote_comment, question). `chart_caption` fills `image_needed` (a text description) and `quote_comment`
  fills `quoted` (the short quoted line). Neither carries a real target URL or an image file.
- Ingest keeps last-24h X originals; reposts, replies and thread parts are dropped; quotes only when long.
- The review inbox row (`live/compose_inbox.py`) carries `source.url`, `text`, `post_format`, review status.
  The dashboard (`backend/compose_inbox.py`, 8684 `/compose-inbox`, static `fd20_review_<day>.html`) shows
  text, findings and review buttons.

## 2. Draft schema additions

All new fields live on the inbox row and the run draft JSON. Absent field = plain post (today's behaviour).

```json
{
  "post_kind": "post | quote | repost_note | reply",
  "quote_target_url": "https://x.com/<handle>/status/<id>",
  "quote_target": {"handle": "...", "post_id": "...", "excerpt": "<=120 chars", "fetched_at": "..."},
  "reply_to_url": "https://x.com/<handle>/status/<id>",
  "media": [{"kind": "chart | screenshot | source_image", "path": "assets/<day>/<draft_id>/1.png",
             "alt": "...", "licence": {...}, "data_sources": [...], "sha256": "..."}],
  "media_plan": {"wanted": "chart_caption", "description": "...", "status": "made | pending | not_allowed"}
}
```

`post_kind` is separate from `post_format.type`: `quote_comment` (a writing shape) becomes `post_kind=quote`
only when a real target URL exists; otherwise it falls back to a plain post with the same text shape.

## 3. Quote-tweets

- Target choice: only from the draft's own source packet. If a unit came from an X post
  (`source.platform == 'x'` and a status URL), that post is the candidate target. News or RSS sources never
  become quote targets (a link is not a quote).
- Pick rule: the X post whose unit the stance / thesis actually rests on (the primary unit), not the most
  popular one. Skip if the post is a reply, a repost, deleted, from a protected account, or older than the
  account's freshness window (quoting a stale post looks odd).
- Text rule: the draft reacts to the quoted post and must not restate it (the existing `quote_comment`
  guidance). Same-language quote = no attribution frame needed, the quote card is the credit.
- QA: `quote_target_url` must equal a URL stored in the source packet (deterministic, hard fail otherwise);
  the excerpt must be a span of the stored post text.
- Dashboard: show the target as a link (opens X) plus a "copy link" button and a "copy text" button. The
  reviewer opens the target, presses Quote on X, pastes the text.

## 4. Reposts / RT-with-note

- Plain repost (no text) is not a draft; it is a suggestion row: `post_kind=repost_note`, `text` empty,
  `note_for_reviewer` saying why this source post fits the account. Counts toward nothing (not a ready
  draft, not the per-account quota).
- RT-with-note on X is a quote-tweet; it uses section 3.
- Only donor-like accounts get repost suggestions: if the account's donors repost rarely, none.

## 5. Replies

- Replies are higher risk (they enter someone else's thread, tone can read as spam). Phase 1: off for all
  accounts. Phase 2 (opt-in per account): `post_kind=reply`, `reply_to_url` from the source packet, max 1
  reply draft a day per account, text 1-2 lines, no links, no tickers the parent did not mention, no
  self-promotion. Same review flow; the reviewer replies by hand.
- Never reply to the accounts FD itself runs (no self-interaction) and never to a post that mentions us.

## 6. Posts with images

Three image sources, tried in this order for a `chart_caption` draft:

1. **Self-made chart from licensed data.**
   - Data: FRED (public domain US government series; FRED terms ask for a source credit), DefiLlama
     (open API, free use with credit), CoinGecko (free API; attribution "Data by CoinGecko" required on the
     free plan). Each fetch is cached under `live/store/chart_data/<provider>/<series>/<date>.json` with the
     request URL and fetch time.
   - Render: matplotlib, one series or two at most, a donor-like casual look rather than a research-house
     look: plain white or light background, one accent colour, short title in the account's language,
     no gridline clutter, small source credit bottom-left ("Data: FRED"), account handle watermark optional.
     Size 1600x900 (X 16:9). A small style preset per account cluster (font size, colours) taken from
     the donors' chart posts, so a meme account and a macro account do not share one house style.
   - Numbers: every number in the caption must appear in the plotted data (same check as section B grounding,
     with the chart data as a source span). The chart may not show a value outside the fetched series.
   - Spec saved next to the PNG (`chart_spec.json`: provider, series, window, transforms) so it can be
     re-rendered and audited.
2. **Screenshot of the source post.** For X sources: a screenshot of the original post (headless browser,
   logged out, public post only), cropped to the card. Use it only when the draft names / reacts to that
   post and quoting is not chosen. No screenshots of paywalled articles or private groups.
3. **Reuse of the source's own image.** Only when the licence allows: the unit's `licence_tier` / usage
   permits reproduction and `no_reproduction` is false (see `live/licence_rules.py`), or the image is an
   official public-domain release (e.g. US government chart). Otherwise `media_plan.status=not_allowed` and
   the reviewer sees the description only.

If none applies, the draft stays text-only and `media_plan.description` tells the reviewer what image the
donor would have used; the reviewer can attach one by hand.

## 7. Dashboard

- Per draft: the text, a "copy text" button, the quote / reply target link with "copy link", image
  thumbnails with a **download button** per image (and "download all" as a zip for the day/account), the
  alt text and the data credit.
- A visible kind badge: Post / Quote / Repost suggestion / Reply / +Image.
- Review buttons unchanged (approve / minor_edit / major_edit / reject). Approval is a label; there is no
  Post button.

## 8. Per-account post-type mix from donors

- Use the existing `post_type_mix` plus two new donor stats from the same donor post samples:
  `quote_share`, `image_share` (already partly computed: `recent_quote_share`, `has_image`), and later
  `reply_share`, `repost_share` when ingest keeps those (today ingest drops them, so these need a separate
  donor-only crawl).
- Shrink toward the cluster mean (same as `QUOTE_PRIOR_N`), cap quotes at 0.30 and images at 0.50 until we
  have more than 1-2 days of quote metadata per donor.
- Sampling: per draft, sample `post_kind` and image need from the mix; if the sampled kind is impossible
  for this packet (no X source to quote, no chart data), fall back to a plain post rather than switching
  the packet.

## 9. Manual posting only

- No X API write scopes, no posting bot, no scheduled post. The suggested post time stays a hint.
- After a human posts, they may paste the live URL back into the inbox row (`published_url`) so we can
  later read engagement. That is a record, not an action.

## 10. Rollout

1. Schema fields + dashboard copy / link / download buttons (no model change).
2. Quote targets from X sources with the URL check.
3. FRED / DefiLlama / CoinGecko charts for `market_data_charts` and the macro / on-chain accounts.
4. Source screenshots; licence-gated source images.
5. Replies, opt-in per account, after a week of quote drafts reviewed.

Open questions: which accounts may quote rivals; whether watermark the handle on charts; how long cached
chart data is kept.
