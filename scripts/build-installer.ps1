param(
    [switch]$SkipApplicationBuild,
    [switch]$AllowSameVersion
)

$ErrorActionPreference = "Stop"
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDirectory
$applicationOutput = Join-Path $projectRoot "dist\PromptMeld"
$installerScript = Join-Path $projectRoot "installer\PromptMeld.iss"

if (-not $SkipApplicationBuild) {
    & (Join-Path $scriptDirectory "build.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The PromptMeld application build failed."
    }
}

if (-not (Test-Path -LiteralPath (
    Join-Path $applicationOutput "PromptMeld.exe"
))) {
    throw (
        "The packaged application is missing. Run .\scripts\build.ps1 first or " +
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

$versionFile = Join-Path $applicationOutput "VERSION"
if (-not (Test-Path -LiteralPath $versionFile)) {
    throw "The packaged application does not contain its generated VERSION file."
}
$version = (Get-Content -Raw -LiteralPath $versionFile).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "The packaged application version is invalid: $version"
}

$installer = Join-Path (
    Join-Path $projectRoot "dist\installer"
) "PromptMeld-Setup-v$version.exe"
if (
    (Test-Path -LiteralPath $installer) -and
    -not $AllowSameVersion
) {
    throw (
        "An installer already exists for v$version. Increase the version in " +
        "pyproject.toml before producing a new distributable build. Use " +
        "-AllowSameVersion only when deliberately reproducing the same release."
    )
}

& $compiler "/DMyAppVersion=$version" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed to build the installer."
}

if (-not (Test-Path -LiteralPath $installer)) {
    throw "The installer compiler completed without producing $installer."
}

Write-Host "Installer created: $installer"
