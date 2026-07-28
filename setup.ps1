$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    $python = $null
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12)"
        if ($LASTEXITCODE -eq 0) {
            & py -3.12 -m venv (Join-Path $projectRoot ".venv")
        }
    }

    if (-not (Test-Path $venvPython)) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw "Python 3.12 was not found. Install it from https://www.python.org/downloads/ and rerun setup.ps1."
        }
        & python -c "import sys; assert sys.version_info[:2] == (3, 12)"
        if ($LASTEXITCODE -ne 0) {
            throw "The 'python' command is not Python 3.12."
        }
        & python -m venv (Join-Path $projectRoot ".venv")
    }
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e ".[dev]"
& $venvPython (Join-Path $projectRoot "tools\check_licenses.py")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency licence audit failed."
}

Write-Host "PromptMeld is ready. Write well and prosper."
Write-Host "Run it with: .\run.ps1"
