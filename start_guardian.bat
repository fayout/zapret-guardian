@echo off
chcp 65001 > nul
title Zapret Guardian 2.0
color 0A

:: Check for Administrator Privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

start "" pythonw.exe ZapretGuardian.pyw
exit
