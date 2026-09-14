@echo off
chcp 65001 >nul
title RubaiSTT - o'chirish
taskkill /f /im pythonw.exe >nul 2>&1
taskkill /f /im whisper-server.exe >nul 2>&1
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RubaiSTT.lnk" 2>nul
del /q "%USERPROFILE%\Desktop\RubaiSTT.lnk" 2>nul
rmdir /s /q "%LOCALAPPDATA%\RubaiSTT"
echo   RubaiSTT o'chirildi.
pause
