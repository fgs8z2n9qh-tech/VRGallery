@echo off
setlocal
set "TARGET=%LOCALAPPDATA%\Programs\VRChronicle"
echo.
echo  This removes the VRChronicle app from: %TARGET%
echo  (Your photos and the VRChronicle library in %%LOCALAPPDATA%%\VRChronicle are kept.)
echo.
choice /C YN /M " Uninstall VRChronicle"
if errorlevel 2 exit /b 0
powershell -NoProfile -Command "foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){ Remove-Item ($d+'\VRChronicle.lnk') -ErrorAction SilentlyContinue }"
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v VRChronicle /f >nul 2>&1
rmdir /S /Q "%TARGET%"
echo  Uninstalled.
pause
