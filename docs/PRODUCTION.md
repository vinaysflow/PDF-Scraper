# Production deployment (Railway / containers)

## Required environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SKIP_NATIVE` | **Yes** (Railway) | `""` (off) | Set to `1` to disable native extraction (Java). Prevents JVM from starting and avoids OOM in small containers. |
| `PORT` | Auto-set by Railway | — | When present the app runs in **safe mode** (lower DPI, page batching). |

## Recommended environment variables

Set these in Railway → service → **Variables** and **Redeploy**:

| Variable | Recommended value | Description |
|----------|-------------------|-------------|
| `SKIP_NATIVE` | `1` | Prevents JVM OOM. |
| `JOB_STORE_DIR` | `/tmp/job_store` | Persists async job state to disk so jobs survive restarts. Without this, a restart causes "Job not found" 404 on active jobs. |
| `SAFE_BATCH_PAGES` | `2` | Pages rendered + OCR'd at a time in safe mode. Lower = less peak memory. Default is `3`; use `2` on free/starter tier. |

## Optional tuning variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_MAX_PAGES` | `5` | Max pages for sync extraction. Requests over this limit should use the async endpoint. |
| `ASYNC_MAX_PAGES` | `100` | Max pages for async extraction jobs. |
| `SAFE_DPI` | `300` | DPI cap when running in safe mode (Railway). |
| `SAFE_BATCH_PAGES` | `3` | Number of pages rendered + OCR'd at a time in safe mode to bound memory. |
| `MAX_FILE_SIZE_BYTES` | `20971520` (20 MB) | Max upload size. Requests larger than this return 413. |

## Startup log

On startup the app prints one line:

```
PDF OCR config: SKIP_NATIVE=True SAFE_MODE=True SYNC_MAX_PAGES=5 ...
```

Verify that `SKIP_NATIVE=True` and `SAFE_MODE=True` when running on Railway. If `SKIP_NATIVE=False`, the variable is not set — add it in Railway → service → Variables and redeploy.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Upload page (HTML) |
| `GET` | `/health` | Health check (returns `{"status": "ok"}`) |
| `GET` | `/api/config` | Runtime limits (`sync_max_pages`, `async_max_pages`) |
| `POST` | `/api/extract` | Sync extraction (small docs, up to `SYNC_MAX_PAGES`) |
| `POST` | `/api/extract/async` | Async extraction — returns 202 + job_id |
| `GET` | `/api/extract/async/{job_id}` | Poll async job status and result |

## 502 checklist

1. **Is `SKIP_NATIVE=1` set?** If not, the first request starts a JVM and can OOM.
2. **Check startup log** — is `SAFE_MODE=True`? If not, `PORT` may not be set.
3. **Is `SAFE_BATCH_PAGES` low enough?** Default is `3`; try `2` on free/starter tier. In safe mode, OCR always uses batched processing (even with `force_ocr`), so this controls peak memory.
4. **Check page count** — are you extracting many pages via the sync endpoint? Use the async endpoint or set `max_pages` ≤ `SYNC_MAX_PAGES`.
5. **Check file size** — is the PDF very large? The limit is `MAX_FILE_SIZE_BYTES`.
6. **Check Railway logs** — open Deployments → latest → Logs for tracebacks or OOM messages.
