@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Откат кассы на предыдущую версию ===
echo.
echo Используйте, если после обновления касса работает неправильно.
echo Перед откатом закройте кассу.
echo.
choice /c YN /m "Откатить на предыдущую версию? Y - да, N - нет"
if errorlevel 2 exit /b 0
echo.
py updater.py --rollback
echo.
pause
