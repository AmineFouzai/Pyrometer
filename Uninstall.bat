@echo off
taskkill /f /im PyrometerLite.exe >nul 2>nul
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Pyrometer Lite.lnk" 2>nul
rmdir /s /q "%LOCALAPPDATA%\PyrometerLite" 2>nul
echo Pyrometer Lite removed.
pause
