# FD_VIDEO_SRC - daily video-transcript idea source (Oct 15, Fiona-approved pilot)

Material source for two lifestyle / newbie ZH accounts only: `zh_longterm_investing` (慢慢小鹿) and `crypto_newbie_zh` (小鱼说币).
Code: `live/video_src.py`; tests: `tests/test_video_src_oct15.py`. Switch `FD_VIDEO_SRC` (default 1; 0 = no fetch, no route, no
licence entry, stored units offered to nobody). `FD_VIDEO_ACCOUNTS` overrides the account list. `--no-video` skips it for one ingest run.

Flow (23:13 ingest, `live/daily_ingest.run`):
1. `video_start` (right after backup): detached child `python -m live.video_src collect` - X `/user-tweets` pages
   (<= 3 calls, >= 2.1 s apart, i.e. under the 30/min limit), own-video originals of the last 48 h, <= 15 min, >= 20 likes,
   top-liked first, <= 6 per day, yt-dlp (360p) -> mp3, faster-whisper `small` int8 in a grandchild process (ffmpeg decode;
   `FD_VIDEO_PYTHON` / `/usr/bin/python3` when the ingest venv has no faster-whisper). Own wall-clock budget
   `FD_VIDEO_BUDGET_S` (600 s): a video whose estimate (0.25 x duration + 45 s) no longer fits is skipped and retried next run.
2. `video_src` (after x_extract): waits at most `FD_VIDEO_WAIT_S` (120 s) for the child, kills it at that point (finished
   transcripts stay), then one flash EXTRACT call per transcript (own ring fence `FD_VIDEO_BUDGET_USD`, 0.20) -> idea units
   (fact / mechanism / view; units with a speaker word, return / yield claim, politics are dropped) tagged with the route beats.
   Transcripts + meta: `/workspace/x/video_src/<yyyymmdd>/<status id>.{txt,json}` (outside the repo).
3. Compose (`scripts/daily_compose.candidates`): the source is routed (`source_routes`) to the two accounts; <= 1 packet per account per
   call (accounts start at different packets), first in line (also ahead of hot packets), crypto beat gate skipped, 48 h from the post
   time (no look-back), and **max 1 draft per account per 7 days** (`video_src.weekly_blocked`, reads the compose inbox).
4. Own voice: the attribution frame is empty (`attribution_frame.render` -> `video_src.frame()`), the speaker is hidden from the
   model (existing never_name payload path), and `video_src.findings` is HARD: video / speaker / @ mention, >= 12 consecutive characters
   copied from the transcript, 不是X而是Y, ngl, return / yield claims, politics. The existing author-identity checks cover invented biography.

Rollback: `FD_VIDEO_SRC=0` (no code change). Stored units can be suppressed via `live/store/content_units/suppressed.jsonl`.
