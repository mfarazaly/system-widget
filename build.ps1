# Builds:
#   dist\SystemWidget.exe              (one-file standalone executable)
#   dist\SystemWidget-1.2.10-win64.zip    (portable: exe + README)
#   dist\SystemWidget-1.2.10-win64.msi    (installer, built when WiX is present)
#
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Native tools (PyInstaller, WiX) write progress to stderr.  Under Windows
# PowerShell 5.1 that becomes a terminating NativeCommandError when
# $ErrorActionPreference is Stop, so relax it around external programs and
# check $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"

py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name SystemWidget `
    --icon "$root\assets\icon.ico" `
    --version-file "$root\assets\version.txt" `
    --distpath "$root\dist" `
    --workpath "$root\build\work" `
    --specpath "$root\build" `
    "$root\SystemWidget.pyw"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Copy-Item "$root\packaging\README.txt" "$root\dist\README.txt" -Force

$zip = "$root\dist\SystemWidget-1.2.10-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$root\dist\SystemWidget.exe", "$root\dist\README.txt" `
    -DestinationPath $zip -CompressionLevel Optimal

Write-Host ""
Write-Host "Built:" -ForegroundColor Green
Write-Host "  $root\dist\SystemWidget.exe"
Write-Host "  $zip"

# ------------------------------------------------------------------ MSI ---- #
# WiX is optional: install it once with
#     dotnet tool install --global wix --version 5.0.2
#     wix extension add -g WixToolset.UI.wixext/5.0.2
$wix = Join-Path $env:USERPROFILE ".dotnet\tools\wix.exe"
if (Test-Path $wix) {
    $msi = "$root\dist\SystemWidget-1.2.10-win64.msi"
    if (Test-Path $msi) { Remove-Item $msi -Force }
    & $wix build "$root\installer\SystemWidget.wxs" `
        -ext WixToolset.UI.wixext `
        -pdb "$root\build\SystemWidget.wixpdb" `
        -o $msi
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  $msi"
    } else {
        Write-Warning "MSI build failed (exe and zip are fine)"
    }
} else {
    Write-Host "  (MSI skipped - WiX not installed, see README)" -ForegroundColor DarkGray
}

exit 0
