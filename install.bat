@echo off
echo === Установка зависимостей для Склад ===
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python 3.10+ с https://python.org
    pause
    exit /b 1
)

echo [1/3] Обновление pip...
py -m pip install --upgrade pip --quiet

echo [2/3] Установка зависимостей...
py -m pip install PyQt6 pyodbc SQLAlchemy --quiet

echo [3/3] Проверка ODBC Driver...
py -c "import pyodbc; drivers = pyodbc.drivers(); print('Найдены драйверы:', drivers)" 2>nul

echo.
echo === Готово! Запустите: python main.py ===
pause
