# VRGallery onedir build (PyInstaller) + Desktop shortcut.
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$name = "VRGallery"          # exe + folder
$display = "VR Gallery"      # what the shortcut is called

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name $name `
    --icon (Join-Path $root "assets\$name.ico") `
    --add-data "$root\assets;assets" `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $root "build") `
    --specpath $root `
    (Join-Path $root "run.py")

$exe = Join-Path $root "dist\$name\$name.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build failed."
    exit 1
}

# Desktop shortcut (and clean up the ones earlier names left behind)
$ws = New-Object -ComObject WScript.Shell
foreach ($s in @("Aperture.lnk", "VRChronicle.lnk", "VRGallery.lnk")) {
    $p = [IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), $s)
    if (Test-Path $p) { Remove-Item $p -Force }
}
$lnk = $ws.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "$display.lnk"))
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = (Join-Path $root "dist\$name")
$lnk.IconLocation = (Join-Path $root "assets\$name.ico")
$lnk.Description = "VRChat photo album"
$lnk.Save()
Write-Host "OK: dist\$name\$name.exe + Desktop\$display.lnk"
