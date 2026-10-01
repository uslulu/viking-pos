@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Установка кассы ===
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Команда py не найдена. Установите Python 3.12 из Microsoft Store.
    pause
    exit /b 1
)

echo [1/3] Обновление pip...
py -m pip install --upgrade pip --quiet

echo [2/3] Установка зависимостей...
py -m pip install PyQt6 pyodbc SQLAlchemy --quiet

echo [3/3] Проверка ODBC Driver...
py -c "import pyodbc; print('Найдены драйверы:', pyodbc.drivers())"

echo.
if not exist config.ini (
    copy /y config.example.ini config.ini >nul
    echo Создан config.ini - проверьте сервер БД и название кафе.
    notepad config.ini
) else (
    echo config.ini уже есть - не трогаю.
)

echo.
echo === Готово. Запуск: launch.vbs (ярлык на рабочем столе должен указывать на него) ===
pause
