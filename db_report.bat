@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Отчёт о базе кассы: только чтение, результат в db_report.txt
py -m db.report
echo.
pause
