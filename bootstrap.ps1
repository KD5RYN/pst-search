# One-command source install for pst-search on Windows.
# Assumes Python 3.10+ and Node 18+ are already installed.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Require-Cmd($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Host "missing: $name" -ForegroundColor Red
        Write-Host "  install it with: $hint" -ForegroundColor Yellow
        exit 1
    }
}

Require-Cmd python "winget install Python.Python.3.12"
Require-Cmd node   "winget install OpenJS.NodeJS.LTS"
Require-Cmd npm    "(npm ships with Node)"

Write-Host '==> Installing Python package (editable)' -ForegroundColor Cyan
python -m pip install --user -e .

Write-Host '==> Installing Node dependencies' -ForegroundColor Cyan
Push-Location pst_search\node
try {
    npm install --no-audit --no-fund
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Done. Start the app with:' -ForegroundColor Green
Write-Host '  pstsearch serve'
Write-Host 'Or, if pip''s user-script dir isn''t on PATH:'
Write-Host '  python -m pst_search serve'
