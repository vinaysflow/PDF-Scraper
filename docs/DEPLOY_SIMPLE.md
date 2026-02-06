# Deploy in 2 parts (simple steps)

You need **two** things on the internet:

1. **Backend** – the thing that actually reads the PDF (OCR). We’ll put it on **Railway**.
2. **Website** – the upload page people see. We’ll put it on **Vercel**.

---

# Part 1: Put the backend on Railway

This is the server that runs when someone uploads a PDF.

1. Go to **https://railway.app** and sign in (e.g. with GitHub).

2. Click **“New Project”**.

3. Choose **“Deploy from GitHub repo”**.  
   Pick the repo that has this code.  
   If your repo has more than just `pdf-ocr-mvp`, in the service settings set **Root Directory** to `pdf-ocr-mvp`.

4. Railway will try to build. It should see the **Dockerfile** in the repo and use it.  
   If it asks for a start command, you don’t need to change anything (the Dockerfile already has it).

5. Open your new service → **Settings** → **Networking** → **Generate Domain**.  
   You’ll get a link like:  
   `https://something.up.railway.app`

6. **Copy that link** and keep it.  
   Don’t add a slash at the end.  
   Example: `https://pdf-ocr-backend.up.railway.app`  
   This is your **backend URL**.

7. Wait until the deploy is **finished** (green / “Success”).  
   You can open that link in the browser; you might see the upload page or an API page. That’s fine.

---

# Part 2: Put the upload page on Vercel

This is the page where users pick a PDF and click “Extract”.

1. Go to **https://vercel.com** and sign in (e.g. with GitHub).

2. Click **“Add New…”** → **“Project”**.

3. **Import** your GitHub repo (the same one you used for Railway).  
   If the repo has more than `pdf-ocr-mvp`, set **Root Directory** to `pdf-ocr-mvp`.  
   Then click **Deploy**.  
   Wait until it’s done.

4. You’ll get a link like:  
   `https://your-project.vercel.app`  
   That’s your **upload website**. If you open it now and try to extract a PDF, it will say the backend isn’t set. So next we connect it to the backend.

5. In Vercel, open your project. Go to **Settings** (top menu).

6. In the left sidebar click **Environment Variables**.

7. Click **“Add New”** (or similar).  
   - **Name:** type exactly: `EXTRACT_API_URL`  
   - **Value:** paste the **backend URL** from Part 1 (the Railway link, no slash at the end).  
   - Save.

8. Go to **Deployments** (top menu).  
   Open the **three dots** on the latest deployment → **Redeploy**.  
   Confirm.  
   This makes Vercel use the new variable.

9. When the redeploy is done, open your Vercel link again.  
   Upload a small PDF and click **Extract**.  
   It should now talk to the Railway backend and show a result (or an error if something’s wrong).

---

# Cheat sheet

| What        | Where to do it | What you get                    |
|------------|----------------|----------------------------------|
| Backend    | railway.app    | A URL like `https://xxx.up.railway.app` |
| Upload page| vercel.com     | A URL like `https://yyy.vercel.app`     |
| Connect them | Vercel → Settings → Environment Variables | Add `EXTRACT_API_URL` = backend URL, then Redeploy |

**Backend URL** = the Railway link (no `/` at the end).  
**EXTRACT_API_URL** = that same link, typed in Vercel’s env vars.

If the upload page says “EXTRACT_API_URL is not set”, you didn’t add the variable or didn’t redeploy after adding it.
