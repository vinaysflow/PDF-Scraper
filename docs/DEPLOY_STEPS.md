# Deploy steps: Backend + Vercel upload UI

Follow these steps to get the upload page on Vercel and the extraction API running on a backend.

---

## Part 1: Deploy the backend (FastAPI + OCR)

The backend needs **Tesseract**, **Poppler**, and **Java** (for native extraction). Easiest is to use the included **Dockerfile**.

### Option A: Railway

1. **Sign in:** [railway.app](https://railway.app) → Login (GitHub is fine).

2. **New project:**  
   **Dashboard** → **New Project** → **Deploy from GitHub repo**.  
   Select your repo (the one containing `pdf-ocr-mvp`).  
   If the repo is the whole repo (not just pdf-ocr-mvp), set **Root Directory** to `pdf-ocr-mvp` in the service settings.

3. **Use Docker:**  
   In the new service → **Settings** → **Build**:
   - **Builder:** Dockerfile  
   - **Dockerfile path:** `Dockerfile` (in repo root or `pdf-ocr-mvp` if root dir is set).

   Or leave “Nixpacks” and add a **Dockerfile** at the repo root (or in `pdf-ocr-mvp` if that’s the root). Railway will detect it.

4. **Port:**  
   **Settings** → **Networking** → **Port:** leave default or set to `8000`.  
   Railway sets `PORT`; the Dockerfile uses it.

5. **Generate domain:**  
   **Settings** → **Networking** → **Generate Domain**.  
   You’ll get a URL like `https://pdf-ocr-mvp-production-xxxx.up.railway.app`.

6. **Save the URL** — this is your **backend URL** (no trailing slash).  
   Example: `https://pdf-ocr-mvp-production-xxxx.up.railway.app`

7. **Deploy:** Push to GitHub or click **Deploy** in Railway. Wait until the deploy is live, then open the URL in the browser. You should see the upload page (or a “Not Found” for GET / if only the API is deployed; try `https://your-backend-url/docs` for Swagger).

---

### Option B: Render

1. **Sign in:** [render.com](https://render.com) → Login.

2. **New Web Service:**  
   **Dashboard** → **New** → **Web Service**.

3. **Connect repo:**  
   Connect your GitHub repo.  
   Set **Root Directory** to `pdf-ocr-mvp` if the repo is not just this app.

4. **Build & run:**
   - **Environment:** Docker  
   - **Dockerfile path:** `Dockerfile` (relative to root directory).

   Or without Docker:
   - **Build Command:** `pip install -e .`
   - **Start Command:** `uvicorn app.api:app --host 0.0.0.0 --port $PORT`
   - You must use a **Docker** or **Native** environment that has Tesseract, Poppler, and Java installed (Render’s default Python image does not; use Docker).

5. **Instance type:** Free or paid. Free has cold starts and request time limits.

6. **Create Web Service.** Render will assign a URL like `https://pdf-ocr-mvp.onrender.com`.

7. **Save that URL** as your **backend URL** (no trailing slash).

---

### Option C: Fly.io

1. **Install CLI:**  
   `curl -L https://fly.io/install.sh | sh` (or see [fly.io/docs](https://fly.io/docs/hands-on/install-flyctl/)).

2. **Login:**  
   `fly auth login`

3. **From project root** (directory that contains `Dockerfile` and `app/`):
   ```bash
   fly launch --no-deploy
   ```
   When prompted, choose app name and region; say no to PostgreSQL.

4. **Set port:**  
   In `fly.toml` (created by `fly launch`), ensure:
   ```toml
   [env]
     PORT = "8000"

   [[services]]
     internal_port = 8000
     protocol = "tcp"
     ...
   ```

5. **Deploy:**
   ```bash
   fly deploy
   ```

6. **URL:**  
   `fly status` or the dashboard will show the URL, e.g. `https://pdf-ocr-mvp.fly.dev`.  
   Use that as your **backend URL** (no trailing slash).

---

## Part 2: Deploy the upload UI to Vercel

1. **Install Vercel CLI (optional):**  
   ```bash
   npm i -g vercel
   ```

2. **Deploy from project root** (the `pdf-ocr-mvp` directory that contains `vercel.json`, `api/`, and `public/`):
   ```bash
   cd /path/to/pdf-ocr-mvp
   vercel
   ```
   - Log in or link your account if asked.  
   - **Set up and deploy?** Yes.  
   - **Which scope?** Your account (or team).  
   - **Link to existing project?** No (first time) or Yes if you already created one.  
   - **Project name:** e.g. `pdf-ocr-upload`.  
   - **Directory:** `./` (current directory).

   Or skip CLI and use the dashboard:

   - Go to [vercel.com](https://vercel.com) → **Add New** → **Project**.  
   - Import your GitHub repo.  
   - **Root Directory:** set to `pdf-ocr-mvp` if the repo is not just this app.  
   - **Framework Preset:** Other.  
   - **Build Command:** leave empty (static + serverless).  
   - **Deploy.**

3. **Add the backend URL:**  
   In the Vercel project:
   - **Settings** → **Environment Variables**  
   - **Add:**
     - **Key:** `EXTRACT_API_URL`  
     - **Value:** your backend URL from Part 1, e.g. `https://pdf-ocr-mvp-production-xxxx.up.railway.app`  
     - **Environments:** Production (and Preview if you want).  
   - **Save.**

4. **Redeploy:**  
   **Deployments** → open the three dots on the latest deployment → **Redeploy**.  
   Or push a new commit so Vercel redeploys.  
   This applies the new `EXTRACT_API_URL`.

5. **Test:**  
   Open your Vercel URL (e.g. `https://pdf-ocr-upload.vercel.app`).  
   Upload a small PDF and run Extract.  
   - If you see “EXTRACT_API_URL is not set”, the env var wasn’t applied — check spelling and redeploy.  
   - If the request times out, the backend might be cold or the PDF too large for the proxy timeout.

---

## Quick reference

| Step | What to do |
|------|------------|
| 1. Backend | Deploy this app with the Dockerfile to Railway / Render / Fly.io. Note the public URL. |
| 2. Vercel | From `pdf-ocr-mvp`: `vercel` or connect repo in Vercel and deploy. |
| 3. Env var | Vercel → Project → Settings → Environment Variables → `EXTRACT_API_URL` = backend URL (no trailing slash). |
| 4. Redeploy | Vercel → Redeploy so the env is used. |

If **EXTRACT_API_URL** is not set, **POST /api/extract** on Vercel returns **503** with a message to set it.  
More on timeouts and behaviour: [VERCEL.md](VERCEL.md).
