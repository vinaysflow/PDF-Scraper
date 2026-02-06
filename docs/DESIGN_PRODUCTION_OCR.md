# Production PDF/OCR design: research-based

This doc summarizes how **best-in-class** document extraction services (Google Document AI, Amazon Textract) are designed, then maps our app to those patterns and proposes a concrete path to production-ready behavior.

---

## 1. How the leaders do it

### 1.1 Amazon Textract

- **Sync API**
  - **1 page only** for PDF/TIFF.
  - Use for single-page, near real-time responses.
- **Async API**
  - **Multi-page (up to 3,000 pages)** for PDF/TIFF.
  - **Start** operation (e.g. `StartDocumentTextDetection`) → returns **JobId** immediately.
  - Document must be in **S3** (not inline) for async; inline limit ~5 MB.
  - Completion: **SNS topic** (or SQS) notifies when done; client then calls **Get** with `JobId` to fetch results.
  - Results stored server-side (e.g. 7 days); paginated Get for large outputs.
- **Best practices**
  - Use **confidence scores** in downstream logic.
  - **S3 + event-driven** (e.g. Lambda on upload) for scale.
  - **Status tracking** per job for observability.
  - **Post-processing** and templates for structured extraction.

Sources: [Textract async API](https://docs.aws.amazon.com/textract/latest/dg/api-async.html), [Textract best practices](https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html), [large doc processing](https://docs.aws.amazon.com/textract/latest/dg/async.html).

### 1.2 Google Document AI

- **Sync (online)**
  - **15 pages** (standard); up to 30 with imageless mode.
  - **40 MB** max file size.
  - Returns a `Document` object with text, layout, OCR, quality info.
- **Async (batch)**
  - **Larger limits** (e.g. 200–500+ pages by processor type).
  - **1 GB** max per file; up to 5,000 files per batch.
  - **Poll** long-running operation for status; then retrieve result.
- **Design**
  - Clear split: sync for small/fast, async for multi-page/large.
  - Document content via **raw bytes** (e.g. base64) or **reference**; batch uses references.
  - Response: structured `Document` (text, layout, quality, language).

Sources: [Document AI limits](https://cloud.google.com/document-ai/limits), [send request](https://docs.cloud.google.com/document-ai/docs/send-request), [poll operation](https://cloud.google.com/document-ai/docs/samples/documentai-poll-operation).

### 1.3 Common production pattern (APIs)

- **Submit** → **202 Accepted** + **job ID**.
- **Poll** GET with job ID until status is `completed` / `failed` / `canceled`.
- **Retrieve** result by job ID when completed.
- **Exponential backoff** on poll to avoid hammering.
- **Input**: for large docs, **reference (e.g. S3/URL)** instead of inline body to avoid timeouts and memory spikes.

Sources: Zuva, Microsoft Computer Vision, Modal doc-OCR examples, Google Doc AI samples.

---

## 2. Principles derived

| Principle | Meaning |
|-----------|--------|
| **Sync for small, async for large** | Sync only for single/few pages and small payloads; multi-page or heavy work is async (job + poll). |
| **No long-running HTTP for heavy work** | Request returns quickly (202 + job ID); processing runs in background so gateways and clients don’t time out. |
| **Reference over inline for large input** | Large files go to storage (S3, GCS, etc.); API receives a reference. Avoids loading full body into app memory and keeps request under size/time limits. |
| **Explicit limits and quotas** | Documented page/size limits per sync vs async; quotas (TPS, concurrent jobs) so clients and ops know what to expect. |
| **Confidence and structure in output** | Return confidence scores and structured layout (blocks, pages) so downstream can tune and validate. |
| **Observability** | Job status, timestamps, and clear errors so support and debugging are straightforward. |

---

## 3. Where our app sits today

| Aspect | Our app | Best-in-class pattern |
|--------|--------|------------------------|
| **API shape** | Single POST that runs full extraction in-request | Sync for 1–few pages; async (202 + job ID, poll, get result) for multi-page |
| **Input** | Whole PDF in request body (`await file.read()`) | For large: upload to storage, pass reference; or strict size limit for sync |
| **Processing** | All pages rendered then OCR’d in one go (high peak memory) | Batch pages or stream processing to bound memory |
| **Tika (Java)** | Optional but can start JVM in-process → OOM risk in containers | Doc AI/Textract are managed services; we run our own stack so must avoid heavy in-process JVM in constrained envs |
| **Limits** | Ad-hoc caps (DPI, pages) added reactively | Documented sync vs async limits and safe defaults |
| **Observability** | Minimal (one startup line) | Job status, duration, error reason per job |

So: we behave like a **single long-running sync API** for any size, with **inline upload** and **all-pages-in-memory** processing. That clashes with gateway timeouts, container memory, and how Google/AWS design their doc APIs.

---

## 4. Target design (aligned with research)

### 4.1 API surface

- **Sync endpoint** (e.g. `POST /api/extract`)
  - **Strict limits**: e.g. 1–5 pages, &lt; 5 MB file, or similar.
  - Use when “Max pages” ≤ sync limit and file small.
  - Returns **200** with full result or **413** / **400** if over limit.
- **Async endpoint** (e.g. `POST /api/extract/async`)
  - Accepts file (or, later, a reference) and options.
  - Returns **202 Accepted** + `{ "job_id": "...", "status": "accepted" }`.
  - Processing runs in background (worker/thread/task queue).
- **Status/result** (e.g. `GET /api/extract/async/{job_id}`)
  - Returns `{ "status": "pending" | "processing" | "completed" | "failed", "result": {...}?, "error": "..."? }`.
  - Client polls until `completed` or `failed`, then uses `result` or `error`.

Optional: webhook or SSE to push completion instead of polling (Phase 2).

### 4.2 Input handling

- **Sync**: keep body upload but enforce strict size limit (e.g. 5 MB) and stream to temp file (no full PDF in RAM).
- **Async**: same for MVP (stream to temp file, then enqueue job); later support “upload to storage first, pass URL/ref” to avoid holding large bodies in the API process.

### 4.3 Processing (memory and robustness)

- **No Tika in constrained envs**: when `SKIP_TIKA=1` (or “production” mode), Tika is never imported or called; OCR-only path only.
- **Page batching**: process N pages at a time (e.g. 2–3): render → OCR → discard images → next batch. Merge results. Caps peak memory regardless of page count.
- **Single source of “safe” limits**: one config (env or config file) for sync max pages, async max pages, max file size, DPI; logged at startup.
- **Worker concurrency**: limit parallel OCR/Tika workers (e.g. env) so we don’t multiply memory and CPU in a small container.

### 4.4 Observability and operations

- **Startup**: log sync/async limits, whether Tika is enabled, and “safe” defaults (e.g. `SKIP_TIKA`, `SAFE_MAX_PAGES`, `SAFE_DPI`).
- **Per job**: status, created_at, updated_at, optional duration; on failure, store and return a short error message/code.
- **Health**: e.g. `GET /health` that returns 200 when the app (and optionally dependencies) are ready; no heavy work.

---

## 5. Phased implementation plan

### Phase 1 – Stability (no new API shape)

- **Guarantee Tika-off path**: when `SKIP_TIKA=1`, never import or call Tika; single code path, no JVM.
- **Stream upload to temp file**: do not load full PDF into RAM; stream request body to disk.
- **Page batching in extract pipeline**: in “safe” mode (e.g. when `PORT` or `SKIP_TIKA`), render + OCR in small batches (e.g. 2–3 pages), merge; cap peak memory.
- **Centralized limits**: one module or config for `SYNC_MAX_PAGES`, `ASYNC_MAX_PAGES` (for later), `MAX_FILE_SIZE`, `SAFE_DPI`; read from env with sane defaults; log at startup.
- **Docs**: single “Production / Railway” section: env vars, limits, 502 checklist, and “use async when available” note.

Goal: current single POST works reliably on Railway (no 502) for documents within the new limits.

### Phase 2 – Async API (job + poll)

- Add **POST /api/extract/async** (202 + job_id).
- Add **GET /api/extract/async/{job_id}** (status + result or error).
- In-memory job store (or Redis/SQLite later): store pending/completed/failed state and result.
- Background worker (thread pool or process) that runs existing `extract_pdf` and updates job state.
- Frontend: for “Max pages” &gt; sync limit or “All”, use async; show “Processing…” and poll until done; then display result.

Goal: multi-page and large PDFs go through async path; no long HTTP request; aligns with Textract/Doc AI pattern.

### Phase 3 – Hardening and scale

- **File size limit** on both sync and async (e.g. reject &gt; 20 MB with 413).
- **Optional**: upload to object storage (S3/GCS) first; async endpoint accepts `file_url` or `file_ref` instead of body.
- **Optional**: webhook or SSE for completion instead of polling.
- **Retries and idempotency**: optional idempotency key for async submit; retry policy for transient failures in worker.

---

## 6. References

- [Amazon Textract – Asynchronous operations](https://docs.aws.amazon.com/textract/latest/dg/api-async.html)
- [Amazon Textract – Best practices](https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html)
- [Amazon Textract – Sync vs async (limits)](https://docs.aws.amazon.com/textract/latest/dg/limits.html)
- [Google Document AI – Limits](https://cloud.google.com/document-ai/limits)
- [Google Document AI – Poll long-running operation](https://cloud.google.com/document-ai/docs/samples/documentai-poll-operation)
- [Modal – Doc OCR job queue](https://modal.com/docs/examples/doc_ocr_jobs)
- [Zuva – OCR workflow (202 + poll)](https://zuva.ai/documentation/workflows/ocr-workflow)

---

## 7. Summary

- **Best-in-class** (Google, Amazon, others) use **sync for small/single-page** and **async (202 + job ID + poll) for multi-page/large**; they avoid long-running request handlers and put large input in storage + reference.
- **Our app** today is a single long-running sync path with inline upload and all-pages-in-memory, which leads to 502s and OOM in constrained deployments.
- **Target**: Phase 1 = same API but stable (Tika-off, stream upload, page batching, clear limits). Phase 2 = add async API and polling so we match industry pattern. Phase 3 = limits, optional storage ref, and robustness.

This gives a research-grounded, non-reactive roadmap instead of more one-off caps.
