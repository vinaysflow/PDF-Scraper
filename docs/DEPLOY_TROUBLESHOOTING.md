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

## What to send so we can fix it

Copy and paste:

1. **Which one failed?** Railway or Vercel?
2. **The exact error message** (from the build log or runtime log).
3. **What you did right before** (e.g. “first deploy from GitHub”, “added env var and redeployed”).

With that we can give you a precise fix.
