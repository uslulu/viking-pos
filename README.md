# Склад — Система управления складом
Клон Microinvest Warehouse Pro Light на Python + PyQt6

## Структура проекта
```
warehouse/
├── main.py              # Точка входа
├── install.bat          # Установка зависимостей
├── run.bat              # Запуск
├── requirements.txt     # Зависимости
├── db/
│   ├── connection.py    # Подключение к MS SQL Server
│   └── users.py         # Работа с пользователями
├── ui/
│   ├── styles.py        # Глобальные стили
│   ├── login.py         # Окно авторизации
│   ├── main_window.py   # Главное окно с sidebar
│   └── dashboard.py     # Рабочий стол (статистика)
└── logic/               # Бизнес-логика (этапы 2-5)
```

## Установка на терминал
1. Python 3.12 из Microsoft Store (команда `py`).
2. Распакуйте архив `viking-pos-X.Y.Z.zip` в папку кассы.
3. Запустите `install.bat` — поставит зависимости и создаст `config.ini`.
4. Ярлык на рабочем столе — на `launch.vbs`.

## Настройки точки — config.ini
Лежит рядом с `main.py`, шаблон — `config.example.ini`. Не входит в архив
обновления и никогда не перезаписывается.
- `[database] server, database` — SQL Server (Windows-аутентификация)
- `[cafe] name` — название в чеке
- `[update] enabled, url` — автообновление

## Автообновление
`launch.vbs` → `py updater.py` → `py main.py`. Updater сверяет `VERSION`
с `version.json` последнего релиза на GitHub
(`releases/latest/download/version.json`), при новой версии скачивает архив, проверяет
sha256, кладёт бэкап в `backup/<версия>` и распаковывает поверх. Если новая
версия падает до показа главного окна — откат из бэкапа, версия больше не
ставится. Лог — `update.log`, вывод кассы — `main.log`.

## Выпуск новой версии
```
git commit -am "..."
py tools/publish.py -n "Что нового"          # patch: 1.0.0 -> 1.0.1
py tools/publish.py minor -n "Что нового"    # 1.0.1 -> 1.1.0
```
Скрипт создаёт тег и GitHub Release с архивом и `version.json`; репозиторий —
в `tools/publish.ini`. Нужен GitHub CLI: `winget install GitHub.cli`, затем один
раз `gh auth login`.

## Этапы разработки
- [x] Этап 1 — Каркас, авторизация, дашборд
- [ ] Этап 2 — Справочники (Товары, Контрагенты, Объекты)
- [ ] Этап 3 — Операции (Приход, Расход, Продажи, Возвраты)
- [ ] Этап 4 — Склад, остатки, партии
- [ ] Этап 5 — Отчёты, касса, печать
