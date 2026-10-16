@echo off
rem Run from an installed Visual Studio x64 developer prompt. No downloads.
setlocal
where cl.exe >nul 2>nul || (echo Open a Visual Studio x64 developer prompt first. & exit /b 2)
if not exist "..\test-tmp" mkdir "..\test-tmp"
cl.exe /nologo /std:c++17 /EHsc /O2 /Brepro /Fo:"..\test-tmp\windows_ocr_stdin.obj" "tools\windows_ocr_stdin.cpp" /Fe:"..\test-tmp\windows_ocr_stdin.exe"
exit /b %errorlevel%
