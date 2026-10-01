@echo off
setlocal
call "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++20 /EHsc /W4 /MD "%~dp0smoke.cpp" /Fe:"%~dp0..\src-tauri\target\explorer-smoke.exe" /Fo:"%~dp0..\src-tauri\target\explorer-smoke.obj"
if errorlevel 1 exit /b %errorlevel%
"%~dp0..\src-tauri\target\explorer-smoke.exe" "%~dp0..\src-tauri\target\lenny-explorer.dll"
exit /b %errorlevel%
