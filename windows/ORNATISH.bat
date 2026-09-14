@echo off
chcp 65001 >nul
title RubaiSTT - o'rnatish
echo.
echo   RubaiSTT Dictation — o'zbekcha ovozli yozuv (Windows)
echo   Hamma narsani o'zi yuklab o'rnatadi (~850 MB). Oynani yopmang.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ornatish.ps1"
if errorlevel 1 (
  echo.
  echo   XATO chiqdi. Internetni tekshirib ORNATISH.bat ni QAYTADAN bosing — yuklangan qismi saqlanadi.
)
echo.
pause
