# Daily ingestion cron

Configure `RELAY_API_KEY` (or `ACCOUNT_RELAY_API_KEY` with its matching base URL) in the cron environment, **or** the existing `REVIEW_BASE_URL` / `REVIEW_API_KEY` pair in the repository `.env`. REVIEW fallback requires `https://api.erisedai.com/v1`. The wrapper leaves ACCOUNT_RELAY variables unset when no relay key is supplied. See the relay configuration note in [ACCOUNT_SOURCES.md](ACCOUNT_SOURCES.md). Never put credentials in logs or crontab command text.

From the repository, check prerequisites without network calls or model spending:

```sh
/workspace/fd_venv/bin/python scripts/daily_ingest_preflight.py
/workspace/fd_venv/bin/python scripts/daily_ingest.py --dry-run --no-dashboard
```

Dry-run exercises ingestion without paid extraction; source fetches may use the network. Preflight checks writable store/runs directories, the nonblocking ingestion lock, and relay resolution. It prints configuration source and host only. The flock file may persist after exit; an unlocked old file is safe because the kernel releases ownership on process exit. Preflight is advisory; ingestion acquires the same lock again to prevent concurrent runs.

The wrapper enables `FD_PACK_AUGMENT=1` to use existing non-fact units where available and skips dashboard rebuilding. It logs START, END and exit code to `/workspace/x/ingest_runs/YYYY-MM-DD.cron.log`. A failed preflight writes `YYYY-MM-DD.preflight_failed.json` there and prevents ingestion. Ingestion summaries are `YYYYMMDD.json` in the runs directory; the lock is `daily_ingest.lock`. Store defaults to `live/store/content_units`; `--store` and `--runs-dir` overrides are checked by preflight too.

Example for cron implementations supporting `CRON_TZ` (05:13 London, including DST):

```cron
CRON_TZ=Europe/London
13 5 * * * /workspace/fd_new/Finance_Distillation/scripts/cron/daily_ingest.sh
```

If the scheduler does not support `CRON_TZ`, configure its scheduling timezone as Europe/London.
