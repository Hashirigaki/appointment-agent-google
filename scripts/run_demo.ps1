$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python is not on PATH."
}

Write-Host "=== Appointment Agent recorded demo ==="
Write-Host "Backend: deterministic local JSON"
Write-Host "Flow: request -> retry -> proposal -> human approval -> confirmation"

python "$PSScriptRoot\run_mock.py"
if ($LASTEXITCODE -ne 0) {
    throw "Appointment workflow demo failed with exit code $LASTEXITCODE."
}
