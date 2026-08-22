@echo off
setlocal
set "TARGET=%LOCALAPPDATA%\Programs\VRChronicle"
echo.
echo  Installing VRChronicle to: %TARGET%
echo.
robocopy "%~dp0VRChronicle" "%TARGET%" /MIR /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
    echo  Copy failed.
    pause
    exit /b 1
)
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){ $l=$ws.CreateShortcut($d+'\VRChronicle.lnk'); $l.TargetPath='%TARGET%\VRChronicle.exe'; $l.WorkingDirectory='%TARGET%'; $l.Description='VRChat photo album'; $l.Save() }"
echo  Done! Shortcuts were created on the Desktop and in the Start Menu.
echo.
choice /C YN /M " Launch VRChronicle now"
if errorlevel 2 exit /b 0
start "" "%TARGET%\VRChronicle.exe"
