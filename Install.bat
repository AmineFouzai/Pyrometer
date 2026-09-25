@echo off
set "APP=%LOCALAPPDATA%\PyrometerLite"
if not exist "dist\PyrometerLite.exe" (
  echo Build dist\PyrometerLite.exe first ^(run build.bat^).
  pause
  exit /b 1
)
mkdir "%APP%" 2>nul
copy /y "dist\PyrometerLite.exe" "%APP%\PyrometerLite.exe" >nul
copy /y "dist\*.dll" "%APP%\" >nul 2>nul
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Programs')+'\Pyrometer Lite.lnk');$s.TargetPath='%APP%\PyrometerLite.exe';$s.WorkingDirectory='%APP%';$s.Save()"
echo Installed to %APP%
echo Open "Pyrometer Lite" from the Start menu.
pause
