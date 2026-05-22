# Builds the standalone Windows .exe distribution.
# Requires: Python 3.10+, MSVC Build Tools (only if libpff-python isn't already installed).
#
# Usage:
#   pwsh ./build_exe.ps1                # full clean build
#   pwsh ./build_exe.ps1 -SkipDeps      # skip pip install (faster iteration)

param([switch]$SkipDeps)

$ErrorActionPreference = 'Stop'

if (-not $SkipDeps) {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"
}

Write-Host "Cleaning previous build..." -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
pyinstaller --noconfirm pst_search.spec

if (Test-Path "dist/pst-search/pst-search.exe") {
    $size = [math]::Round((Get-ChildItem -Recurse "dist/pst-search" | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host "Build complete: dist/pst-search/pst-search.exe ($size MB total)" -ForegroundColor Green
    Write-Host "Test it with:   ./dist/pst-search/pst-search.exe index sample.pst" -ForegroundColor Yellow
} else {
    Write-Error "Build failed - pst-search.exe not produced"
    exit 1
}
