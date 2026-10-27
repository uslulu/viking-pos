"""
Отчёт о подключённой базе — только чтение (одни SELECT).

    py -m db.report

Запускать в папке кассы. Печатает отчёт и сохраняет его в db_report.txt:
версия SQL Server, таблицы и колонки, которые нужны кассе, количества,
открытые заказы, выручка, расхождения оплат. Паролей и имён в отчёте нет.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_config import BASE_DIR, DB_NAME, DB_SERVER  # noqa: E402
import db.connection as db  # noqa: E402

# Колонки, к которым обращается касса (см. docs/DATABASE.md)
REQUIRED = {
    "Operations": ["ID", "OperType", "Acct", "GoodID", "PartnerID", "ObjectID", "OperatorID",
                   "Qtty", "Sign", "PriceIn", "PriceOut", "VATIn", "VATOut", "Discount",
                   "CurrencyID", "CurrencyRate", "Date", "UserID", "UserRealTime", "Note"],
    "Payments": ["Acct", "OperType", "PartnerID", "Qtty", "Mode", "Sign", "Date", "UserID",
                 "ObjectID", "UserRealTime", "Type"],
    "Goods": ["ID", "Code", "BarCode1", "Name", "Measure1", "PriceIn", "PriceOut1", "PriceOut2",
              "MinQtty", "TaxGroup", "GroupID", "IsRecipe", "Deleted"],
    "GoodsGroups": ["ID", "Name", "Deleted"],
    "Users": ["ID", "Code", "Name", "Password", "UserLevel", "GroupID", "Deleted"],
    "Objects": ["ID", "Name", "Deleted"],
    "Partners": ["ID", "Company", "Deleted", "IsVeryUsed"],
}
OTHER = ["UsersGroups", "OperationType", "Store"]

PAID = "EXISTS (SELECT 1 FROM Payments p WHERE p.OperType = 2 AND p.Acct = o.Acct)"


class Report:
    def __init__(self):
        self.lines = []

    def __call__(self, text=""):
        print(text)
        self.lines.append(text)

    def section(self, title):
        self()
        self(f"── {title} " + "─" * max(3, 60 - len(title)))

    def safe(self, title, fn):
        """Ошибка одного раздела не прерывает весь отчёт."""
        try:
            fn()
        except Exception as e:
            self(f"  ! {title}: {e}")


def one(sql, params=None):
    return db.fetch_one(sql, params)


def when(v):
    return v.strftime("%d.%m.%Y %H:%M") if isinstance(v, datetime) else (v or "—")


def money(v):
    return f"{float(v or 0):,.2f}".replace(",", " ")


def main():
    r = Report()
    r(f"Отчёт о базе кассы — {datetime.now():%d.%m.%Y %H:%M}")
    r(f"Сервер: {DB_SERVER}   База: {DB_NAME}")
    if not db.connect(DB_SERVER, DB_NAME):
        r("Не удалось подключиться к базе. Проверьте [database] в config.ini и доступ "
          "пользователя Windows к SQL Server.")
        return save(r)

    r.section("SQL Server")

    def server():
        v = one("SELECT CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(50)) AS ver, "
                "CAST(SERVERPROPERTY('Edition') AS NVARCHAR(200)) AS ed, "
                "SUSER_SNAME() AS login, DB_NAME() AS dbname")
        r(f"  Версия: {v['ver']}  ({v['ed']})")
        r(f"  Касса входит как: {v['login']}")
        s = one("SELECT SUM(CAST(size AS BIGINT)) * 8 / 1024 AS mb FROM sys.database_files")
        r(f"  Размер файлов базы: {s['mb']} МБ")
        b = one("SELECT MAX(backup_finish_date) AS last FROM msdb.dbo.backupset "
                "WHERE database_name = DB_NAME() AND type = 'D'")
        r(f"  Последняя полная резервная копия: {when(b['last']) if b['last'] else 'не найдена'}")
    r.safe("сервер", server)

    r.section("Таблицы и колонки, нужные кассе")
    missing_any = False
    for table, cols in REQUIRED.items():
        rows = db.fetch_all("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_NAME = ?", [table])
        have = {x["COLUMN_NAME"].lower() for x in rows}
        if not have:
            r(f"  ✗ {table}: таблицы нет"); missing_any = True
            continue
        miss = [c for c in cols if c.lower() not in have]
        cnt = one(f"SELECT COUNT(*) AS n FROM [{table}]")["n"]
        extra = len(have) - (len(cols) - len(miss))
        if miss:
            missing_any = True
            r(f"  ✗ {table}: строк {cnt}; нет колонок: {', '.join(miss)}")
        else:
            r(f"  ✓ {table}: строк {cnt}; нужные кассе колонки есть ({len(cols)}), "
              f"прочих колонок: {extra}")
    for table in OTHER:
        rows = db.fetch_all("SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES "
                            "WHERE TABLE_NAME = ?", [table])
        exists = rows and rows[0]["n"]
        r(f"  · {table}: {'есть, касса её не изменяет' if exists else 'таблицы нет'}")
    r("  Итог: " + ("каких-то колонок не хватает — часть функций кассы будет падать"
                    if missing_any else "структура подходит кассе"))

    r.section("Справочники")

    def refs():
        u = db.fetch_all("SELECT UserLevel, COUNT(*) AS n FROM Users WHERE Deleted = 0 "
                         "GROUP BY UserLevel ORDER BY UserLevel")
        names = {0: "кассиры", 1: "менеджеры", 2: "администраторы"}
        r("  Сотрудники: " + ", ".join(f"{names.get(x['UserLevel'], 'уровень ' + str(x['UserLevel']))} — {x['n']}"
                                        for x in u))
        e = one("SELECT COUNT(*) AS n FROM Users WHERE Deleted = 0 "
                "AND (Password IS NULL OR LTRIM(RTRIM(Password)) = '')")
        if e["n"]:
            r(f"  ⚠ Сотрудников с пустым паролем: {e['n']} — вход без пароля")
        g = one("SELECT COUNT(*) AS n, SUM(CASE WHEN ISNULL(PriceOut1, 0) = 0 THEN 1 ELSE 0 END) AS noprice, "
                "SUM(CASE WHEN GroupID IS NULL THEN 1 ELSE 0 END) AS nogroup FROM Goods WHERE Deleted = 0")
        gg = one("SELECT COUNT(*) AS n FROM GoodsGroups")
        r(f"  Товары: {g['n']} (без цены — {g['noprice'] or 0}, без группы — {g['nogroup'] or 0}), "
          f"групп — {gg['n']}")
        ob = db.fetch_all("SELECT TOP 5 ID, Name FROM Objects WHERE Deleted = 0 ORDER BY Name")
        r("  Объекты (касса берёт первый): " + ", ".join(f"{x['Name']} (ID {x['ID']})" for x in ob))
    r.safe("справочники", refs)

    r.section("Продажи")

    def sales():
        s = one("SELECT COUNT(DISTINCT Acct) AS n, MIN(Date) AS first, MAX(Date) AS last "
                "FROM Operations WHERE OperType = 2")
        r(f"  Всего заказов-продаж: {s['n']}, с {when(s['first'])} по {when(s['last'])}")
        m = one("SELECT ISNULL(MAX(Acct), 0) AS mx FROM Operations")
        r(f"  Следующий номер заказа будет: {int(m['mx']) + 1}")
        o = db.fetch_all(f"""
            SELECT o.Acct, MAX(o.Note) AS Note, COUNT(*) AS lines,
                   SUM(o.Qtty * o.PriceOut) AS total, MIN(o.Date) AS opened
            FROM Operations o WHERE o.OperType = 2 AND NOT {PAID}
            GROUP BY o.Acct ORDER BY MIN(o.Date)""")
        r(f"  Открытых заказов сейчас: {len(o)}")
        for x in o[:15]:
            r(f"    №{x['Acct']}  {x['Note'] or 'без стола'}  позиций {x['lines']}  "
              f"сумма {money(x['total'])}  открыт {when(x['opened'])}")
        tables = {}
        for x in o:
            if x["Note"]:
                tables.setdefault(x["Note"], []).append(x["Acct"])
        dup = {k: v for k, v in tables.items() if len(v) > 1}
        if dup:
            r("  ⚠ Несколько открытых заказов на одном столе: "
              + "; ".join(f"{k}: {v}" for k, v in dup.items()))
        old = [x for x in o if (datetime.now() - x["opened"]).days >= 1]
        if old:
            r(f"  ⚠ Открыты дольше суток: {len(old)} — возможно, забытые заказы")
    r.safe("продажи", sales)

    def revenue():
        p = db.fetch_all("SELECT Mode, COUNT(DISTINCT Acct) AS n, SUM(Qtty) AS s FROM Payments "
                         "WHERE OperType = 2 AND Date >= DATEADD(day, -30, GETDATE()) GROUP BY Mode")
        names = {0: "наличные", 1: "карта", 2: "перевод"}
        total = sum(float(x["s"] or 0) for x in p)
        r(f"  Выручка за 30 дней: {money(total)}  ("
          + ", ".join(f"{names.get(x['Mode'], 'Mode ' + str(x['Mode']))} {money(x['s'])}" for x in p) + ")")
        d = one(f"""
            SELECT COUNT(*) AS n FROM (
                SELECT o.Acct FROM Operations o WHERE o.OperType = 2 AND {PAID}
                GROUP BY o.Acct
                HAVING ABS(SUM(o.Qtty * o.PriceOut) - (SELECT SUM(p.Qtty) FROM Payments p
                           WHERE p.OperType = 2 AND p.Acct = o.Acct)) > 0.01) t""")
        r(f"  Оплаченных заказов, где оплата ≠ сумме позиций: {d['n']}"
          + ("  (см. запрос в docs/DATABASE.md)" if d["n"] else ""))
        sd = one("SELECT COUNT(DISTINCT Acct) AS n FROM Operations WHERE OperType = 2 AND Discount > 0")
        r(f"  Заказов со скидкой: {sd['n']}")
    r.safe("выручка", revenue)

    def other_types():
        t = db.fetch_all("SELECT o.OperType, MAX(ot.RU) AS name, COUNT(*) AS n, MAX(o.Date) AS last "
                         "FROM Operations o LEFT JOIN OperationType ot ON ot.ID = o.OperType "
                         "GROUP BY o.OperType ORDER BY o.OperType")
        r()
        r("  Типы операций в базе (2 — продажи кассы, остальные — Microinvest):")
        for x in t:
            r(f"    {x['OperType']:>3}  {x['name'] or '?':<28} строк {x['n']:<8} последняя {when(x['last'])}")
    r.safe("типы операций", other_types)

    save(r)


def save(r):
    path = os.path.join(BASE_DIR, "db_report.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(r.lines) + "\n")
        print(f"\nОтчёт сохранён: {path}")
    except OSError as e:
        print(f"\nНе удалось сохранить отчёт: {e}")


if __name__ == "__main__":
    main()
