# ExcelLence AI

**ExcelLence AI** is a production-grade, AI-powered Excel workbench for non-technical office workers. It lets you grant access to an Excel workbook and issue natural-language commands to (1) extract data into structured tables, (2) perform calculations and derive new columns via formulas, and (3) generate charts — all written directly into a real `.xlsx` file that opens natively in Microsoft Excel.

> All data stays local. Only your AI prompt (and a small data sample for context) is sent to the Groq API. Your workbooks never leave your machine.

![ExcelLence AI screenshot](docs/screenshot.png)

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Groq API key | Free at [console.groq.com](https://console.groq.com/keys) |

---

## Local Setup (5 minutes)

```bash
# 1. Clone the repo
git clone https://github.com/your-org/excellence-ai.git
cd excellence-ai

# 2. Create and activate a virtual environment
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Open .env and set:  GROQ_API_KEY=gsk_...

# 5. Run the app
python main.py
# or from the repo root:
#   bash run.sh        (macOS/Linux)
#   run.bat            (Windows)
```

Open **http://localhost:8000** in your browser.  
Log in with **any email + any password ≥ 4 characters** (mock auth, no real credentials needed).

---

## File Structure

```
excellence-ai/
├── README.md
├── run.sh / run.bat          # One-command launchers
├── Procfile                  # Railway / Render process declaration
├── railway.json              # Railway deployment config
├── render.yaml               # Render deployment config (fallback)
├── runtime.txt               # Python version pin (3.11.9)
├── .gitignore
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── main.py               # FastAPI entrypoint + startup seeding
│   └── app/
│       ├── config.py         # Settings from .env / env vars
│       ├── models.py         # Pydantic request/response schemas
│       ├── routes/
│       │   ├── auth.py       # Mock login/logout (HTTP-only cookie)
│       │   ├── workbooks.py  # List, create, upload, download .xlsx
│       │   ├── chat.py       # AI orchestration endpoint (Phase I/II/III)
│       │   └── pages.py      # Serves login.html + app.html via Jinja2
│       └── services/
│           ├── excel_engine.py   # All openpyxl operations (backup-before-write)
│           ├── groq_client.py    # Groq SDK wrapper + system prompts
│           ├── extractor.py      # URL scraping + optional OCR
│           ├── intent_router.py  # Keyword + LLM intent classification
│           └── audit.py          # Writes to hidden _Audit sheet
└── frontend/
    ├── templates/
    │   ├── login.html
    │   └── app.html
    └── static/
        ├── css/ (reset.css, login.css, app.css)
        ├── js/  (grid.js, chat.js, ribbon.js, app.js, login.js)
        └── img/ (logo.svg)
```

---

## How It Works

### Phase I — Extract
Type *"Extract this table from [URL]"* or paste raw data. The AI returns a structured JSON preview. Click **Confirm** and the data is written as a real Excel `ListObject` table with formatted headers and auto-width columns.

### Phase II — Calculate
Type *"Add a profit margin column"* or *"Sum all revenue by category"*. The AI returns Excel-native formulas (e.g. `=G2/E2`). Formulas are sandboxed (no `INDIRECT`, no external links) and validated with a numeric checksum before writing.

### Phase III — Chart
Type *"Create a bar chart of profit margin by product"*. The AI selects the right chart type, data range, and anchor cell. A live-linked chart is embedded in the workbook.

### Safety guarantees
- **Preview-before-write**: nothing touches the `.xlsx` until you click Confirm.
- **Backup-before-write**: every write snapshots the file to `.backups/` first.
- **Formula sandbox**: unsafe patterns (`INDIRECT`, `WEBSERVICE`, external links) are rejected.
- **Audit trail**: every applied action is appended to a hidden `_Audit` sheet.

---

## Deploy to Railway (Recommended — ~2 minutes)

Railway gives you a persistent volume so workbooks survive between redeploys.

1. Push this repo to GitHub.
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select this repo.
3. Railway auto-detects `railway.json` and starts building.
4. Click the new service → **Variables** tab → add:
   - `GROQ_API_KEY` = your key from [console.groq.com/keys](https://console.groq.com/keys)
   - `APP_SECRET_KEY` = any long random string (run `openssl rand -hex 32` to generate one)
5. **Settings → Volumes** → add a volume mounted at `/data` (1 GB is sufficient).
6. **Settings → Networking** → **Generate Domain**. Open the URL. Done.

> On first boot the app auto-creates `Q2_Financial_Analysis.xlsx` with the demo dataset.

---

## Deploy to Render (Fallback — ~3 minutes)

1. Push this repo to GitHub.
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint** → select this repo.
3. Render reads `render.yaml` and provisions the service + 1 GB disk automatically.
4. When prompted, paste your `GROQ_API_KEY`. `APP_SECRET_KEY` is auto-generated by Render.
5. Wait for the build to finish. Open the `.onrender.com` URL. Done.

---

## Why Railway / Render and not Vercel / Netlify?

This app writes real `.xlsx` files to disk (workbooks, backups, audit logs). Vercel and Netlify run serverless functions with read-only filesystems (except `/tmp`, which is wiped between invocations) — workbooks would not persist. Railway and Render both provide persistent volumes, long-running uvicorn processes, automatic HTTPS, and GitHub auto-deploy.

---

## Environment Variables

Only two variables **must** be set in the deployment dashboard:

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | **Yes** | From [console.groq.com/keys](https://console.groq.com/keys) |
| `APP_SECRET_KEY` | **Yes** | Any long random string (Render auto-generates) |

All other variables have sensible defaults in `config.py` and `render.yaml`:

| Variable | Default (local) | Production override |
|---|---|---|
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Same |
| `WORKBOOK_DIR` | `./data/workbooks` | `/data/workbooks` |
| `UPLOAD_DIR` | `./data/uploads` | `/data/uploads` |
| `AI_TEMPERATURE` | `0.2` | Same |
| `ENABLE_WEB_SCRAPING` | `true` | Same |
| `ENABLE_OCR` | `false` | Same |

---

## Troubleshooting

**Build fails on openpyxl / pandas wheels**  
→ Ensure `runtime.txt` pins Python `3.11.9`, not 3.12. Some wheels aren't available for 3.12 yet.

**Chat returns "AI is rate-limited"**  
→ `GROQ_API_KEY` is missing or invalid. Check the Variables tab in your Railway/Render dashboard.

**Workbooks disappear after redeploy**  
→ The persistent volume isn't mounted. On Railway: Settings → Volumes → mount at `/data`. On Render: confirm the `disk:` block is in `render.yaml` and the service was deployed as a Blueprint.

**Healthcheck failing / app won't start**  
→ Confirm `/health` returns 200 by visiting `https://your-app.railway.app/health`. If it errors, check the deploy logs for a Python import error.

**Port conflict locally**  
→ Change `PORT=8001` in `.env` and restart.

**"GROQ_API_KEY is not set" warning in logs**  
→ The app still boots so you can reach the login page. Add the key to `.env` (local) or the Variables tab (deployed) and restart.
