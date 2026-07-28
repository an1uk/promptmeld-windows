param(
    [switch]$SkipApplicationBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$applicationOutput = Join-Path $projectRoot "dist\PromptMeld"
$installerScript = Join-Path $projectRoot "installer\PromptMeld.iss"

if (-not $SkipApplicationBuild) {
    & (Join-Path $projectRoot "build.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The PromptMeld application build failed."
    }
}

if (-not (Test-Path -LiteralPath (
    Join-Path $applicationOutput "PromptMeld.exe"
))) {
    throw (
        "The packaged application is missing. Run .\build.ps1 first or " +
        "omit -SkipApplicationBuild."
    )
}

$compilerCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$compiler = $compilerCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1

if (-not $compiler) {
    $compilerCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($compilerCommand) {
        $compiler = $compilerCommand.Source
    }
}

if (-not $compiler) {
    throw (
        "Inno Setup 6 is required to build the installer. Install it with " +
        "'winget install --id JRSoftware.InnoSetup -e', then run this " +
        "script again."
    )
}

$projectMetadata = Get-Content -Raw (
    Join-Path $projectRoot "pyproject.toml"
)
$versionMatch = [regex]::Match(
    $projectMetadata,
    '(?m)^version\s*=\s*"([^"]+)"'
)
if (-not $versionMatch.Success) {
    throw "Could not read the application version from pyproject.toml."
}
$version = $versionMatch.Groups[1].Value

& $compiler "/DMyAppVersion=$version" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed to build the installer."
}

$installer = Join-Path (
    Join-Path $projectRoot "dist\installer"
) "PromptMeld-Setup-v$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "The installer compiler completed without producing $installer."
}

Write-Host "Installer created: $installer"
