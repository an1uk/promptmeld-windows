$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "The virtual environment is missing. Follow the setup steps in README.md."
}

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
        --icon "src\writing_launcher\resources\branding\promptmeld.ico" `
        --add-data "src\writing_launcher\resources;writing_launcher\resources" `
        "launcher.py"

    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --console `
        --onedir `
        --contents-directory "." `
        --name "PromptMeldAutomation" `
        --icon "src\writing_launcher\resources\branding\promptmeld.ico" `
        --collect-all pywinauto `
        "automation_launcher.py"

    $mainOutput = Join-Path $projectRoot "dist\PromptMeld"
    $mainInternal = Join-Path $mainOutput "_internal"
    $helperOutput = Join-Path $projectRoot "dist\PromptMeldAutomation"

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
} finally {
    Pop-Location
}
