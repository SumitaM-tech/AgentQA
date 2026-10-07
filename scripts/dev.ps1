# Starts backend (8000) and frontend (5173) in two windows. Add -Demo to also start the demo shop (8080).
param([switch]$Demo)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\backend'; .\venv\Scripts\Activate.ps1; python run.py"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\frontend'; npm run dev"
if ($Demo) {
  # The demo shop is a local app, so local targets must be allowed for the backend (see README, Security).
  Write-Host "Demo shop: http://127.0.0.1:8080  (set BROWSER_ALLOW_PRIVATE_NETWORKS=true in .env to let the agent test it)" -ForegroundColor Yellow
  Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\demo-app'; python server.py 8080"
}
Write-Host "Frontend: http://localhost:5173   API docs: http://localhost:8000/docs" -ForegroundColor Green
