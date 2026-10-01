@echo off
cd /d "%~dp0"
echo === Сборка exe ===
py -m pip install pyinstaller --quiet
py -m PyInstaller --onefile --windowed --icon=resources\icon.ico ^
    --name="Система учёта" ^
    --add-data="resources;resources" ^
    main.py
echo === Готово: dist\Система учёта.exe ===
pause
