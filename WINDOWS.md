# Running AgentQA Cloud on Windows (Core i3 friendly)

No Docker, Kubernetes, Ollama or Neo4j needed. Requirements: **Python 3.11+**, **Node 20+**, and a Gemini API key
(https://aistudio.google.com/apikey). Database: SQLite works out of the box; PostgreSQL is optional.

## Quick start (PowerShell)

```powershell
git clone <your repo> ; cd agentqa-cloud
.\scripts\setup.ps1          # venv, pip install, playwright install chromium, npm install, creates .env
notepad .env                 # set GEMINI_API_KEY=...
.\scripts\dev.ps1            # opens backend :8000 and frontend :5173
```
Open http://localhost:5173. If PowerShell blocks scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Manual equivalent
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
python run.py                 # NOT plain `uvicorn --reload` on Windows (see Troubleshooting)
# second window
cd frontend
npm install
npm run dev
```

## Try the demo shop (has intentional bugs)
```powershell
# in .env:  BROWSER_ALLOW_PRIVATE_NETWORKS=true      (local targets are blocked by default)
.\scripts\dev.ps1 -Demo      # demo shop on http://127.0.0.1:8080
```
In the UI: Projects -> New project (`http://127.0.0.1:8080`) -> **Run QA test** -> goal
“Thoroughly test the checkout flow.” Turn `BROWSER_ALLOW_PRIVATE_NETWORKS` back to `false` afterwards.

## Docker (optional)
```powershell
Copy-Item .env.example .env   # set POSTGRES_PASSWORD and GEMINI_API_KEY
docker compose up --build     # UI http://localhost:8080, API http://localhost:8000/docs
```
Docker Desktop with the WSL2 backend is recommended; give it at least 4 GB RAM.

## Tips for a low-end laptop
- Keep `MAX_CONCURRENT_BROWSERS=1` (default). Extra runs wait in "queued".
- Use `MAX_STEPS=25–40` while experimenting; each step is one Gemini call plus one browser action.
- Close other Chrome windows during a run; Chromium is the main memory consumer (~300–500 MB).

## Troubleshooting
| Symptom | Fix |
|---|---|
| Run fails with `NotImplementedError` | You started the server with `uvicorn --reload`, which breaks Playwright on Windows. Start it with `python run.py` (or add `--loop none`) |
| `playwright` says browser not found | `.\venv\Scripts\python.exe -m playwright install chromium` |
| Run fails with “Target rejected … private” | Local targets are blocked by design; see the demo section |
| UI shows “Disconnected” | Backend not running on port 8000, or `VITE_API_URL` is wrong (restart `npm run dev` after editing) |
| “GEMINI_API_KEY missing” warning | The run still works with a built-in explorer, without AI decisions |
| `Address already in use` | Another process uses 8000/5173: `netstat -ano | findstr :8000` |
