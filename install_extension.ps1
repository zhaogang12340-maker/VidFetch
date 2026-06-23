# Register VidFetch Native Messaging host for Chrome + Edge (writes HKCU, no admin needed).
# Run via install_extension.bat.
$ErrorActionPreference = "Stop"

$HostName = "com.vidfetch.host"
$ExtId    = "iklkefonkeckmifmdkbniphnngimfdgm"
$Dir      = Split-Path -Parent $MyInvocation.MyCommand.Definition
$HostExe  = Join-Path $Dir "vidfetch_host.exe"
$Manifest = Join-Path $Dir "$HostName.json"

if (-not (Test-Path $HostExe)) {
    Write-Host "[ERROR] vidfetch_host.exe not found next to this script:" -ForegroundColor Red
    Write-Host "        $HostExe"
    Write-Host "        Put vidfetch_host.exe, VidFetch exe and this script in the SAME folder."
    exit 1
}

# 1) native host manifest (absolute path; allowed_origins locked to our extension id)
$obj = [ordered]@{
    name            = $HostName
    description     = "VidFetch native messaging host"
    path            = $HostExe
    type            = "stdio"
    allowed_origins = @("chrome-extension://$ExtId/")
}
($obj | ConvertTo-Json -Depth 4) | Out-File -FilePath $Manifest -Encoding ascii -Force
Write-Host "[OK] host manifest written: $Manifest"

# 2) registry (Chrome + Edge)
$targets = @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$HostName"
)
foreach ($key in $targets) {
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "(default)" -Value $Manifest
    Write-Host "[OK] registered: $key"
}

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  1) Chrome/Edge -> Extensions page -> enable Developer mode"
Write-Host "  2) Load unpacked -> select the 'browser_extension' folder"
Write-Host "  3) Extension ID should be: $ExtId"
Write-Host "  4) On a video page, right-click -> 'Download with VidFetch'"
Write-Host ""
Write-Host "If you move this folder, run install_extension.bat again."
