@echo off
REM BrainDock Windows Build Script (Batch wrapper)
REM
REM This script calls the PowerShell build script.
REM Set environment variables before running:
REM
REM   set GEMINI_API_KEY=your-key
REM   set STRIPE_SECRET_KEY=your-key
REM   set STRIPE_PUBLISHABLE_KEY=your-key
REM   set STRIPE_PRICE_ID=your-id
REM   build\build_windows.bat
REM

echo ================================================
echo         BrainDock Windows Build
echo ================================================
echo.

REM Check if GEMINI_API_KEY is set (use 'defined' for robust check)
if not defined GEMINI_API_KEY (
    echo Error: GEMINI_API_KEY environment variable is required.
    echo.
    echo Usage:
    echo   set GEMINI_API_KEY=your-key
    echo   set STRIPE_SECRET_KEY=your-key
    echo   set STRIPE_PUBLISHABLE_KEY=your-key
    echo   set STRIPE_PRICE_ID=your-id
    echo   build\build_windows.bat
    echo.
    pause
    exit /b 1
)

REM Run PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"

pause
