# One-time setup on Windows (PowerShell 5.1+). Run from the repository root:  .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> Backend: virtualenv + dependencies" -ForegroundColor Cyan
Set-Location backend
if (-not (Test-Path venv)) { python -m venv venv }
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "==> Installing Chromium for Playwright (one-time, ~150 MB)" -ForegroundColor Cyan
& .\venv\Scripts\python.exe -m playwright install chromium
Set-Location ..

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host "Created .env  ->  open it and set GEMINI_API_KEY (and DATABASE_URL if you use PostgreSQL)." -ForegroundColor Yellow
}

Write-Host "==> Frontend: npm install" -ForegroundColor Cyan
Set-Location frontend
npm install --legacy-peer-deps
if (-not (Test-Path .env)) { "VITE_API_URL=http://localhost:8000" | Set-Content .env }
Set-Location ..
Write-Host "`nSetup complete. Start everything with:  .\scripts\dev.ps1" -ForegroundColor Green
