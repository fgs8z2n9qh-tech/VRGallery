# Package dist\VRGallery into a shareable VRGallery-Setup.zip (run build.ps1 first).
$root = $PSScriptRoot
$name = "VRGallery"
$dist = Join-Path $root "dist\$name"
if (-not (Test-Path (Join-Path $dist "$name.exe"))) {
    Write-Error "dist\$name\$name.exe not found - run build.ps1 first."
    exit 1
}
$stage = Join-Path $root "dist\_setup_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null

Copy-Item $dist (Join-Path $stage $name) -Recurse
Copy-Item (Join-Path $root "installer\Install VR Gallery.cmd") $stage
Copy-Item (Join-Path $root "installer\README.txt") $stage
# uninstaller travels inside the app folder so it lands in the install target too
Copy-Item (Join-Path $root "installer\Uninstall VR Gallery.cmd") (Join-Path $stage $name)

$zip = Join-Path $root "dist\$name-Setup.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "OK: $zip ($mb MB)"
