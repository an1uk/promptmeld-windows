$ErrorActionPreference = "Stop"
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDirectory
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "The virtual environment is missing. Follow the setup steps in README.md."
}

$projectMetadata = Get-Content -Raw (
    Join-Path $projectRoot "pyproject.toml"
)
$versionMatch = [regex]::Match(
    $projectMetadata,
    '(?m)^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"'
)
if (-not $versionMatch.Success) {
    throw "The project version must use the numeric major.minor.patch format."
}

$buildDirectory = Join-Path $projectRoot "build"
$buildNumberFile = Join-Path $buildDirectory "build-number.txt"
New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null
$buildNumber = 0
if (Test-Path -LiteralPath $buildNumberFile) {
    $savedBuildNumber = Get-Content -Raw -LiteralPath $buildNumberFile
    if (-not [int]::TryParse($savedBuildNumber.Trim(), [ref]$buildNumber)) {
        throw "The saved build number is invalid: $buildNumberFile"
    }
}
$buildNumber++
Set-Content -LiteralPath $buildNumberFile -Value $buildNumber -Encoding ASCII

$major = [int]$versionMatch.Groups[1].Value
$minor = [int]$versionMatch.Groups[2].Value
$patch = [int]$versionMatch.Groups[3].Value
$baseVersion = "$major.$minor.$patch"
$buildVersion = "$baseVersion.$buildNumber"
$versionInfoPath = Join-Path $buildDirectory "windows-version-info.txt"
$versionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($major, $minor, $patch, $buildNumber),
    prodvers=($major, $minor, $patch, $buildNumber),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'PromptMeld contributors'),
          StringStruct('FileDescription', 'PromptMeld'),
          StringStruct('FileVersion', '$buildVersion'),
          StringStruct('InternalName', 'PromptMeld'),
          StringStruct('LegalCopyright', 'Copyright (c) PromptMeld contributors'),
          StringStruct('OriginalFilename', 'PromptMeld.exe'),
          StringStruct('ProductName', 'PromptMeld'),
          StringStruct('ProductVersion', '$buildVersion')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -LiteralPath $versionInfoPath -Value $versionInfo -Encoding UTF8

Push-Location $projectRoot
try {
    & $python "tools\check_licenses.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency licence audit failed. The release was not built."
    }

    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name "PromptMeld" `
        --version-file $versionInfoPath `
        --icon "src\promptmeld\resources\branding\promptmeld.ico" `
        --add-data "src\promptmeld\resources;promptmeld\resources" `
        "tools\entrypoints\promptmeld_launcher.py"
    if ($LASTEXITCODE -ne 0) {
        throw "The PromptMeld application package build failed."
    }

    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --console `
        --onedir `
        --contents-directory "." `
        --name "PromptMeldAutomation" `
        --version-file $versionInfoPath `
        --manifest "assets\windows\promptmeld-automation.manifest" `
        --icon "src\promptmeld\resources\branding\promptmeld.ico" `
        --collect-all pywinauto `
        "tools\entrypoints\promptmeld_automation.py"
    if ($LASTEXITCODE -ne 0) {
        throw "The PromptMeld automation helper build failed."
    }

    $mainOutput = Join-Path $projectRoot "dist\PromptMeld"
    $mainInternal = Join-Path $mainOutput "_internal"
    $helperOutput = Join-Path $projectRoot "dist\PromptMeldAutomation"

    $helperSmokeTest = Start-Process `
        -FilePath (Join-Path $helperOutput "PromptMeldAutomation.exe") `
        -ArgumentList "--self-test" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($helperSmokeTest.ExitCode -ne 0) {
        throw "The packaged automation helper failed its startup smoke test."
    }

    Set-Content `
        -LiteralPath (Join-Path $mainOutput "VERSION") `
        -Value $buildVersion `
        -Encoding ASCII

    $smokeTest = Start-Process `
        -FilePath (Join-Path $mainOutput "PromptMeld.exe") `
        -ArgumentList "--smoke-test" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($smokeTest.ExitCode -ne 0) {
        throw "The packaged PromptMeld executable failed its startup smoke test."
    }

    # PyInstaller collects all Qt platform input plugins. PromptMeld does not
    # use Qt PDF, QML, Quick, or Virtual Keyboard. In particular, Virtual
    # Keyboard is GPL-only in the open-source Qt distribution, so prevent
    # unused copyleft-only binaries from entering the MIT release.
    $unusedQtFiles = @(
        "PySide6\Qt6Pdf.dll",
        "PySide6\Qt6Qml.dll",
        "PySide6\Qt6QmlMeta.dll",
        "PySide6\Qt6QmlModels.dll",
        "PySide6\Qt6QmlWorkerScript.dll",
        "PySide6\Qt6Quick.dll",
        "PySide6\Qt6VirtualKeyboard.dll",
        "PySide6\plugins\imageformats\qpdf.dll",
        "PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll"
    )
    $resolvedMainInternal = [System.IO.Path]::GetFullPath(
        $mainInternal
    ).TrimEnd("\") + "\"
    foreach ($relativePath in $unusedQtFiles) {
        $target = [System.IO.Path]::GetFullPath(
            (Join-Path $mainInternal $relativePath)
        )
        if (-not $target.StartsWith(
            $resolvedMainInternal,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove an unexpected Qt output path."
        }
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }

    Copy-Item `
        -LiteralPath (Join-Path $helperOutput "PromptMeldAutomation.exe") `
        -Destination $mainInternal `
        -Force
    Get-ChildItem -LiteralPath $helperOutput |
        Where-Object Name -ne "PromptMeldAutomation.exe" |
        ForEach-Object {
            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $mainInternal `
                -Recurse `
                -Force
        }

    # The helper belongs inside the main package. Do not leave a second
    # user-facing application folder beside PromptMeld.
    $distRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $projectRoot "dist")
    )
    $resolvedHelperOutput = [System.IO.Path]::GetFullPath($helperOutput)
    $expectedHelperOutput = Join-Path $distRoot "PromptMeldAutomation"
    if ($resolvedHelperOutput -ne $expectedHelperOutput) {
        throw "Refusing to remove an unexpected helper output path."
    }
    Remove-Item -LiteralPath $resolvedHelperOutput -Recurse -Force

    & $python "tools\check_licenses.py" `
        --collect-licenses (Join-Path $mainOutput "LICENSES") `
        --check-bundle $mainOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged dependency licence audit failed."
    }

    Write-Host "PromptMeld build created: $buildVersion"
} finally {
    Pop-Location
}
