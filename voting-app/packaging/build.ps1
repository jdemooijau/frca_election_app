# Build the Windows installer: tests, release gate, PyInstaller, smoke test,
# Inno Setup. Run from anywhere:  powershell -File voting-app\packaging\build.ps1
# -SkipChangelogCheck allows a dev build without a CHANGELOG heading.
param([switch]$SkipChangelogCheck)

$ErrorActionPreference = "Stop"
$Packaging = $PSScriptRoot
$AppDir = Split-Path $Packaging -Parent
$RepoDir = Split-Path $AppDir -Parent
Set-Location $AppDir

function Step($name, [scriptblock]$block) {
    Write-Host "==> $name"
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

$Version = (Select-String -Path "$AppDir\version.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "FRCA Election $Version"

if (-not $SkipChangelogCheck) {
    $heading = "## [$Version]"
    if (-not (Select-String -Path "$RepoDir\CHANGELOG.md" -SimpleMatch $heading -Quiet)) {
        throw "CHANGELOG.md has no '$heading' heading. Add the release entry first, or pass -SkipChangelogCheck for a dev build."
    }
}

Step "Tests" { python -m pytest -q }
Step "Display fit release gate" { python scripts/check_display_fit.py }

$Venv = "$Packaging\.venv-build"
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    Step "Create build venv" { python -m venv $Venv }
}
$Py = "$Venv\Scripts\python.exe"
Step "Install build requirements" { & $Py -m pip install --quiet --disable-pip-version-check -r "$Packaging\requirements-build.txt" }

Step "PyInstaller" {
    & $Py -m PyInstaller "$Packaging\frca_election.spec" --distpath "$Packaging\dist" --workpath "$Packaging\build" --noconfirm --log-level WARN
}

$Exe = "$Packaging\dist\FRCA-Election\FRCA-Election.exe"
Step "Smoke test" { & $Py "$Packaging\smoke_test.py" $Exe }

$Iss = "$Packaging\installer.iss"
if (-not (Test-Path $Iss)) {
    Write-Host "No installer.iss yet; stopping after the smoke test."
    exit 0
}
$Iscc = foreach ($ver in "7", "6") {
    "$env:ProgramFiles\Inno Setup $ver\ISCC.exe"
    "${env:ProgramFiles(x86)}\Inno Setup $ver\ISCC.exe"
    "$env:LOCALAPPDATA\Programs\Inno Setup $ver\ISCC.exe"
}
$Iscc = $Iscc | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6.3+ or 7 (ISCC.exe) not found. Install it from https://jrsoftware.org/isinfo.php" }
Step "Inno Setup" { & $Iscc /Q "/DAppVersion=$Version" $Iss }
Write-Host "Built $Packaging\dist\FRCA-Election-Setup-$Version.exe"
