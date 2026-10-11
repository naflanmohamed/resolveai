# Deploy ResolveAI using free tiers (GitHub + Neon + Render)

_Last verified against public provider documentation: October 9, 2026. Plans and limits can change. This guide uses a personal, synthetic-data demo. For commercial production use, upgrade resources and security._

## Stack

- **Code hosting:** GitHub public or private repository (free option)
- **Database:** [Neon](https://neon.com/) PostgreSQL Free, currently 1 GB storage per project. External DB avoids Render's ephemeral filesystem.
- **API:** [Render](https://render.com/) Web Service, **Free** plan, Docker runtime.
- **Frontend:** [Render](https://render.com/) Static Site, **Free** option.
- **AI:** Local classifier/RAG/draft generator; **no Gemini key required**.

Render's **Free web service sleeps after 15 minutes of inactivity**; initial requests can take around a minute to resume. Free web services have limited usage hours and are not recommended for production. Render's own free PostgreSQL database expires after 30 days, **so this guide uses Neon instead.**

## 1. Put the code on GitHub

Extract the ZIP and open a terminal at the `resolveai` root, then:

```bash
git init
git add .
git commit -m "Build ResolveAI portfolio application"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/resolveai.git
git push -u origin main
```

Create the empty GitHub repository **before** pushing. Do not commit any `.env` file, secrets, API keys, real customer information, database file or `node_modules` folder.

## 2. Create a free PostgreSQL database on Neon

1. Sign up at https://console.neon.tech/ and create a project (e.g. `resolveai-db`).
2. Select the Free plan. Copy its **PostgreSQL connection string** securely from the project dashboard. Example format (**placeholder**, not a working connection string):

   ```
   postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
   ```

3. Keep this as the Render backend's **`DATABASE_URL`**. Never paste it in frontend env settings, client-side code, commits, README issues or screenshots.
4. This application creates its SQLAlchemy tables on API startup. You don't need to run migrations for the provided v1 schema.

## 3. Deploy the FastAPI backend on Render

1. At https://dashboard.render.com/ select **New → Web Service** and connect your GitHub `resolveai` repository.
2. Configure:
   - **Name:** `resolveai-api` (or another available name)
   - **Root directory:** `backend`
   - **Runtime / Language:** `Docker`
   - **Instance type:** `Free`
   - **Dockerfile path:** `./Dockerfile` relative to the root directory
   - **Health check path:** `/api/health` (if the UI offers the field)
3. Set environment variables under **Environment** (the values below are example shapes):

   ```text
   DATABASE_URL=<the real Neon connection string>
   JWT_SECRET=<generate a new long random private string>
   CORS_ORIGINS=https://YOUR-FRONTEND.onrender.com
   DEMO_MODE=true
   ALLOW_REGISTRATION=false
   GEMINI_API_KEY=
   ```

4. Click **Deploy Web Service**. On first launch, the backend creates its database tables in Neon. Open your allocated URL followed by `/api/health`. You should see `{"status":"ok", ...}`.
5. **Important:** You won't know your static frontend URL yet. Put a planned URL in CORS for now, and update it to the **actual** frontend hostname in Step 5.

**Alternative:** The repo includes `render.yaml` for a backend-only Render Blueprint, but the dashboard process is easier for a first deployment.

## 4. Deploy the React frontend on Render

1. In Render select **New → Static Site** and connect the same repository.
2. Configure:
   - **Name:** `resolveai-web` (or an available name)
   - **Root directory:** `frontend`
   - **Build command:** `npm install && npm run build`
   - **Publish directory:** `dist`
3. Set the build-time environment variable:

   ```text
   VITE_API_URL=https://YOUR-ACTUAL-BACKEND.onrender.com
   ```

   Include `https://`, **no `/api` at the end** and no trailing slash.
4. Deploy. Open the static-site URL Render gives you.

Because the UI does not use URL-based client-side routing, **no catch-all rewrite is necessary** in this version.

## 5. Fix CORS and finish setup

1. Copy the **exact** frontend URL you received in Step 4 (e.g. `https://resolveai-web.onrender.com`).
2. In **backend Render service → Environment**, change `CORS_ORIGINS` to that URL (without a final slash). Save and redeploy/restart as required.
3. Visit the frontend and **register your admin account right away**. It is the first registered user on a new database.
4. Sign in and select **Load demo data** to seed **six fictional policies and seven fictional customer tickets**. This is available only when `DEMO_MODE=true`; if disabled, add documents and tickets manually.
5. Open a ticket, inspect cited evidence, approve the response, and see the dashboard update.

Your project should now have two public URLs:

- Frontend: `https://YOUR-FRONTEND.onrender.com`
- Backend Swagger docs: `https://YOUR-BACKEND.onrender.com/docs`

## Optional: enable Gemini drafting

No AI API key is required for the working baseline. If eligible to use Gemini API:

1. Get a provider-issued API key from https://aistudio.google.com/.
2. Store it **only** in the backend Render Environment as `GEMINI_API_KEY`.
3. Set `GEMINI_MODEL` to an available model under your free tier.
4. Deploy or restart backend, create a ticket after uploading relevant docs, and verify the draft shows `gemini` as its generator. If quotas are unavailable or calls fail, the app falls back to source-linked local drafting.

Gemini free-tier eligibility, models, usage quotas, geographic availability and data-use terms can vary. **Never enable paid billing merely to run this portfolio demo** without knowing the implications. Don't send sensitive customer information to external APIs.

## Test your public deployment

- Visit `https://YOUR-BACKEND.onrender.com/api/health` → JSON `status: ok`.
- Visit `https://YOUR-FRONTEND.onrender.com` → register/login UI.
- Register first admin → login successfully.
- Click `Load demo data` → documents appear; tickets are generated with drafts.
- Open any ticket → compare citations → edit draft → Approve → Copy response → Resolve.
- Reload page → data still exists because stored in Neon.
- Refresh `/docs` to inspect the API.

## Troubleshooting

| Symptom | Fix |
|---|---|
| API slow on first request | Normal Render Free cold start. Wait until the API service wakes; check Render logs. |
| "Failed to fetch" / CORS console error | Confirm `VITE_API_URL` targets the backend URL and backend `CORS_ORIGINS` exactly matches frontend origin. Redeploy **frontend** after changing `VITE_API_URL`; it is embedded at build time. |
| Database connection error | Verify Neon host/user/password/db name and `sslmode=require` in backend `DATABASE_URL`. Never put this URL in the frontend. |
| "Registration is closed" | The database already has an admin. Log in with the first account, or use the admin's Team page to add an agent. |
| Seeding rejected | Seed works only if demo mode is enabled and **both** documents/tickets tables are empty. |
| No policy matches | Upload support policies with the keywords needed; lexical TF-IDF retrieval is a baseline, not semantic embeddings. |
| PDF says no text | Use a text-based PDF or TXT/Markdown; OCR is not included. |
| Changes disappear | You accidentally deployed with SQLite on ephemeral storage. Change backend `DATABASE_URL` to the persistent Neon URL. |
| Gemini doesn't generate | Ensure API key/model/permissions/quota and review provider errors; without it local generation remains functional. |
| Build fails | Review Render build log for exact error. Ensure Node.js supports Vite 6 and Python 3.12 is used by Dockerfile. |

## Free-tier reminders

- **Render Free**: 750 instance-hours per workspace/month according to current documentation; service sleeps after 15 minutes idle. Limits on bandwidth/build usage apply.
- **Neon Free**: currently 1 GB storage per project; verify current compute quotas and retention behavior in the Neon dashboard.
- **Render free database**: not used here because the free database has a 30-day expiration.
- **Optional paid services**: check pricing and disable billing before exceeding quotas. No uptime or zero-cost guarantee is implied.

Official documentation: https://render.com/docs/free · https://render.com/docs/your-first-deploy · https://neon.com/pricing · https://ai.google.dev/gemini-api/docs/pricing
