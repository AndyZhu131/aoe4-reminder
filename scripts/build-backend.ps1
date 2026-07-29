[CmdletBinding()]
param(
    [string]$Python = $env:AOE4_PYTHON,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repositoryRoot ".venv-build"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$distributionRoot = Join-Path $repositoryRoot "dist\backend"
$tesseractRoot = if ($env:AOE4_TESSERACT_ROOT) {
    $env:AOE4_TESSERACT_ROOT
} else {
    Join-Path ${env:ProgramFiles} "Tesseract-OCR"
}

if (-not $Python) {
    $Python = if (Test-Path "C:\Python313\python.exe") {
        "C:\Python313\python.exe"
    } else {
        "python.exe"
    }
}

if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venvRoot
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $repositoryRoot "requirements-build.txt")

if (-not (Test-Path (Join-Path $tesseractRoot "tesseract.exe"))) {
    throw "Tesseract OCR was not found at '$tesseractRoot'. Install it there or set AOE4_TESSERACT_ROOT before building."
}

if ($Clean -and (Test-Path $distributionRoot)) {
    Remove-Item -LiteralPath $distributionRoot -Recurse -Force
}

& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name "aoe4-assistant" `
    --distpath $distributionRoot `
    --workpath (Join-Path $repositoryRoot "build\pyinstaller") `
    --specpath (Join-Path $repositoryRoot "build") `
    --paths (Join-Path $repositoryRoot "scripts") `
    --hidden-import "mss.windows" `
    --collect-all "cv2" `
    --add-data "$(Join-Path $repositoryRoot 'data');data" `
    --add-data "$(Join-Path $repositoryRoot 'templates');templates" `
    --add-data "$(Join-Path $repositoryRoot 'config');config" `
    --add-data "$(Join-Path $repositoryRoot 'runtime');runtime" `
    --add-data "$tesseractRoot;tesseract" `
    (Join-Path $repositoryRoot "scripts\aoe4_assistant.py")

Write-Host "Backend bundle created at $distributionRoot\aoe4-assistant"
