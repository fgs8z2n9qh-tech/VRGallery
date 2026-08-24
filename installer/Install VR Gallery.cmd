@echo off
setlocal
set "TARGET=%LOCALAPPDATA%\Programs\VRGallery"
echo.
echo  Installing VR Gallery to: %TARGET%
echo.
robocopy "%~dp0VRGallery" "%TARGET%" /MIR /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
    echo  Copy failed.
    pause
    exit /b 1
)
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){ $l=$ws.CreateShortcut($d+'\VR Gallery.lnk'); $l.TargetPath='%TARGET%\VRGallery.exe'; $l.WorkingDirectory='%TARGET%'; $l.Description='VRChat photo album'; $l.Save() }"
echo  Done! Shortcuts were created on the Desktop and in the Start Menu.
echo.
choice /C YN /M " Launch VR Gallery now"
if errorlevel 2 exit /b 0
start "" "%TARGET%\VRGallery.exe"
