@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在运行自检...
python selftest.py
echo.
pause
