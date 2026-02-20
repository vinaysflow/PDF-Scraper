# Deployment failed – what to do

**Paste the exact error message** (from Railway or Vercel logs) so we can fix the right thing. Below are common fixes.

---

## Railway (backend) failed

**1. “Dockerfile not found” or it used Nixpacks instead**

- In your Railway service → **Settings** → **Build**.
- Set **Builder** to **Dockerfile** (or **Dockerfile Path** to `Dockerfile`).
- Redeploy.

**2. Build fails during `pip install` (e.g. opencv or numpy)**

- The Dockerfile was updated to add system libs for OpenCV (`libgl1-mesa-glx`, etc.). Pull the latest code and push again:
  ```bash
  cd "/Users/vinaytripathi/Documents/PDF scraper/pdf-ocr-mvp"
  git pull origin main   # if you already pushed the fix
  git add . && git commit -m "Fix Dockerfile for Railway" && git push
  ```
- If you’re on the latest and it still fails, copy the **full build log** from Railway (the red error lines) and we can fix the exact step.

**3. “Application failed to respond” or crash after deploy**

- Railway sets `PORT`. The Dockerfile uses `ENV PORT=8000` and `uvicorn ... --port ${PORT}`. That should be correct.
- In **Settings** → **Networking**, ensure a **Public networking** domain is generated.
- Check **Deploy** → **View logs** for Python tracebacks (e.g. missing Tesseract). If you see “Tesseract not found”, the image isn’t using the Dockerfile; switch the builder to Dockerfile and redeploy.

**4. “No space left” or disk errors**

- Free tier has limits. Try removing unused services or use a paid plan.

**5. 502 Bad Gateway when uploading a PDF (e.g. after a few seconds)**

- The app uses native extraction (Java), which starts a JVM on first use and can exhaust memory → process killed → 502. PDF rendering at high DPI can also OOM.
- **Fix (required):** In Railway → your service → **Variables**, add:
  - **Name:** `SKIP_NATIVE`  
  - **Value:** `1`
- Save, then **Redeploy** (Variables don’t apply until the service is redeployed).
- After deploy, open **Deployments** → latest → **Logs**. On startup you should see a line like:  
  `PDF OCR: SKIP_NATIVE='1' PORT='8000' -> safe_limits=on`  
  If you see `SKIP_NATIVE=''`, the variable isn’t set or the deploy didn’t pick it up.
- With `SKIP_NATIVE=1`, extraction is OCR-only (no native extraction). DPI and page count are also capped on Railway to reduce memory.

---

## Vercel (upload page) failed

**1. “Build failed” or “No output”**

- We don’t need a build: the site is static (`public/`) + one serverless function (`api/extract.js`).
- In Vercel → **Settings** → **General**:
  - **Framework Preset:** Other.
  - **Build Command:** leave **empty** (or override and leave blank).
  - **Output Directory:** leave **empty** or `.`
- Save and **Redeploy**.

**2. “Root Directory” or “Cannot find module”**

- If your repo has more than `pdf-ocr-mvp`, set **Root Directory** to `pdf-ocr-mvp` so Vercel sees `public/` and `api/`.
- If the error is in `api/extract.js`, make sure the repo has an `api` folder with `extract.js` in it (and that Root Directory isn’t hiding it).

**3. 503 or “EXTRACT_API_URL is not set” after deploy**

- The app deployed, but the backend isn’t connected.
- **Settings** → **Environment Variables** → add `EXTRACT_API_URL` = your Railway URL (no trailing slash).
- **Redeploy** after saving the variable.

**4. “Function exceeded time limit” when uploading a PDF**

- The Vercel function is only a proxy; the real work runs on Railway. Vercel has a ~60s (or 300s) limit for the proxy request.
- If the backend takes longer than that to respond, the proxy will time out. Use a smaller PDF to test, or call the Railway URL directly for large jobs.

---

## Async extraction: "Job not found" (404)

When using async extraction (e.g. uploading with "Max pages" left empty or set to a large number), the UI submits a job and then polls for the result. If you see **"Job not found"** during polling, the job was created but can no longer be found. Common causes and fixes:

**1. Backend restarted while the job was running**

- The job store is in-memory by default. If the backend process restarts (e.g. Railway redeploy, crash, or OOM), all in-progress jobs are lost.
- **Fix:** Set the environment variable **`JOB_STORE_DIR`** to a writable path (e.g. `/tmp/job_store`) in Railway → your service → **Variables**, then **Redeploy**. With this set, every job state change is persisted to disk and the store is repopulated on startup.

**2. Multiple backend instances**

- If more than one instance of the backend is running, the instance that created the job may not be the one that receives the poll request.
- **Fix:** Run a **single instance** of the backend service (in Railway → service → **Settings** → Replicas → 1).

**3. UI is on Vercel but async proxy is missing**

- The Vercel proxy must handle both `POST /api/extract/async` and `GET /api/extract/async/:job_id`. If only `api/extract.js` is deployed (which handles sync `/api/extract` only), the async requests 404 on Vercel without ever reaching the backend.
- **Fix:** Ensure `api/extract/async.js` and `api/extract/async/[jobId].js` are present in the repo and deployed to Vercel. Pull the latest code and redeploy Vercel.

**4. Quick workaround: use sync extraction**

- Set **Max pages** to a number (e.g. 10 or 20) in the upload form. This uses the synchronous endpoint, which does not require the job store or polling. The result is returned in a single request.

---

## What to send so we can fix it

Copy and paste:

1. **Which one failed?** Railway or Vercel?
2. **The exact error message** (from the build log or runtime log).
3. **What you did right before** (e.g. “first deploy from GitHub”, “added env var and redeployed”).

With that we can give you a precise fix.
