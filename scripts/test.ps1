# Runs every check: backend tests, frontend type-check/lint/build.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location "$root\backend";  & .\venv\Scripts\python.exe -m pytest -q
Set-Location "$root\frontend"; npm run lint; npm run build
Write-Host "All checks passed." -ForegroundColor Green
