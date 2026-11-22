$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Push-Location $RepoRoot
try {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv (exit code $LASTEXITCODE)." }
    }

    & $VenvPython -m pip install -r requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple/
    if ($LASTEXITCODE -ne 0) { throw "Failed to install requirements (exit code $LASTEXITCODE)." }

    Write-Host "Environment ready: $VenvPython"
} finally {
    Pop-Location
}
