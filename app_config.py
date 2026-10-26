"""
Настройки конкретной точки из config.ini рядом с main.py.
Если файла или ключа нет — используются значения по умолчанию.
"""
import configparser
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

_DEFAULTS = {
    "database": {
        "server": r"localhost\SQLEXPRESS",
        "database": "cafel",
    },
    "cafe": {
        "name": "Викинг",
    },
    "update": {
        "enabled": "true",
        "url": "https://github.com/uslulu/viking-pos/releases/latest/download/version.json",
    },
}


def load() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_dict(_DEFAULTS)
    try:
        # utf-8-sig: Блокнот может сохранить файл с BOM
        cfg.read(CONFIG_PATH, encoding="utf-8-sig")
    except (configparser.Error, UnicodeDecodeError) as e:
        print(f"config.ini error: {e}")
    return cfg


_cfg = load()

DB_SERVER = _cfg.get("database", "server")
DB_NAME = _cfg.get("database", "database")
CAFE_NAME = _cfg.get("cafe", "name")
