@echo off
setlocal
set "TARGET=%LOCALAPPDATA%\Programs\VRGallery"
echo.
echo  This removes the VR Gallery app from: %TARGET%
echo  (Your photos and the VRGallery library in %%LOCALAPPDATA%%\VRGallery are kept.)
echo.
choice /C YN /M " Uninstall VR Gallery"
if errorlevel 2 exit /b 0
powershell -NoProfile -Command "foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){ Remove-Item ($d+'\VR Gallery.lnk') -ErrorAction SilentlyContinue }"
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v VRGallery /f >nul 2>&1
rmdir /S /Q "%TARGET%"
echo  Uninstalled.
pause
