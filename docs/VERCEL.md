# Deploying the upload UI on Vercel

The **upload page** and a **proxy API route** can be deployed to Vercel. The actual PDF extraction (Tesseract, Tika, diagrams) runs on a **backend** you host elsewhere; Vercel only serves the UI and forwards requests.

## Why two parts?

- **Vercel** has short serverless timeouts (e.g. 60s) and no Tesseract/Poppler/Java. It cannot run the full extraction.
- **Backend** (this repo’s FastAPI app) runs OCR and returns JSON. Deploy it using the repo **Dockerfile** to [Railway](https://railway.app), [Render](https://render.com), or [Fly.io](https://fly.io).

## Step-by-step

**→ Prefer simple steps? See [DEPLOY_SIMPLE.md](DEPLOY_SIMPLE.md)** (Railway + Vercel, no jargon).  
**→ More options (Render, Fly.io):** [DEPLOY_STEPS.md](DEPLOY_STEPS.md).

1. **Deploy the backend** (Railway / Render / Fly.io) using the included `Dockerfile`. Note the public backend URL.
2. **Deploy to Vercel** from the project root: `vercel` or connect the repo in the [Vercel dashboard](https://vercel.com).
3. **Add env var:** Vercel project → **Settings** → **Environment Variables** → `EXTRACT_API_URL` = your backend URL (no trailing slash).
4. **Redeploy** so the variable is applied.

## 3. Behaviour

- **`/`** – Serves `public/index.html` (upload form).
- **`POST /api/extract`** – Serverless function that forwards the upload and query params to `EXTRACT_API_URL/extract` and returns the backend response.

If `EXTRACT_API_URL` is not set, `POST /api/extract` returns **503** with instructions to set it.

## 4. Timeouts

- Vercel Pro: function timeout is typically 60s; for long extractions the proxy can still time out.
- For large PDFs, prefer calling the backend URL directly (e.g. from a script or another service) or increase the backend timeout and use a queue.

## 5. Local dev with same UI

Run the FastAPI app locally; it serves the same upload page and handles both `/extract` and `/api/extract`:

```bash
uvicorn app.api:app --reload
# Open http://127.0.0.1:8000 — form posts to /api/extract
```
