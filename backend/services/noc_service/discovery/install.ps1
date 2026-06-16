# ──────────────────────────────────────────────────────────────────────────────
# Network Discovery Tool — installer (Windows / PowerShell)
# Run from an elevated PowerShell:  powershell -ExecutionPolicy Bypass -File install.ps1
# ──────────────────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Here ".venv"

Write-Host "==> Network Discovery Tool installer" -ForegroundColor Cyan

# 1. nmap binary (Npcap is required for scapy ARP scans on Windows)
if (-not (Get-Command nmap -ErrorAction SilentlyContinue)) {
    Write-Host "==> nmap not found." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "==> Installing nmap via winget (includes Npcap)..."
        winget install -e --id Insecure.Nmap --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "!! Please install Nmap (with Npcap) from https://nmap.org/download.html" -ForegroundColor Red
    }
} else {
    Write-Host "==> nmap already installed."
}

# 2. Python venv + deps
Write-Host "==> Creating virtual environment at $Venv"
python -m venv $Venv
& (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $Venv "Scripts\pip.exe") install -r (Join-Path $Here "requirements-discovery.txt")

Write-Host ""
Write-Host "==> Done." -ForegroundColor Green
Write-Host "Run the dashboard (run PowerShell as Administrator for full ARP scans):"
Write-Host "    & '$Venv\Scripts\Activate.ps1'"
Write-Host "    python -m backend.services.noc_service.discovery.run serve"
Write-Host ""
Write-Host "Or a one-off CLI scan:"
Write-Host "    python -m backend.services.noc_service.discovery.run scan --export"
Write-Host ""
Write-Host "Dashboard:  http://localhost:8088/   (default login: admin / admin)"
Write-Host "Set `$env:DISCOVERY_ADMIN_PASSWORD before first run to change the password."
