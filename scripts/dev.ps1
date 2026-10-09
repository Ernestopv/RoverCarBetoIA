# Development helper: create the virtualenv and install dev dependencies.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv..."
    python -m venv .venv
}

Write-Host "Installing dependencies..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt

Write-Host ""
Write-Host "Ready. Activate with:  .venv\Scripts\Activate.ps1"
Write-Host "Run the API with:      .venv\Scripts\python.exe -m uvicorn app.main:app --reload"
