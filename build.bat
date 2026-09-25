@echo off
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --clean PyrometerLite.spec
if errorlevel 1 pause & exit /b 1

rem Keep a loose copy of the .NET assemblies beside the exe so the CLR can
rem probe the application folder as well as the bundled extraction folder.
for %%F in (
  LibreHardwareMonitorLib.dll HidSharp.dll
  System.Memory.dll System.Buffers.dll System.Numerics.Vectors.dll
  System.Runtime.CompilerServices.Unsafe.dll System.Threading.Tasks.Extensions.dll
  Microsoft.Bcl.HashCode.dll Microsoft.Bcl.AsyncInterfaces.dll
  System.Collections.Immutable.dll System.Reflection.Metadata.dll
  System.Resources.Extensions.dll System.Security.AccessControl.dll
  System.Security.Principal.Windows.dll System.Threading.AccessControl.dll
  System.IO.Pipelines.dll System.Text.Json.dll System.Text.Encodings.Web.dll
  System.CodeDom.dll System.Formats.Nrbf.dll Microsoft.Win32.TaskScheduler.dll
) do if exist "..\%%F" copy /y "..\%%F" "dist\%%F" >nul

echo Built: %~dp0dist\PyrometerLite.exe
pause
