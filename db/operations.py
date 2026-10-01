from db.connection import fetch_all, fetch_one, execute, _get_conn
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


class OrderError(Exception):
    """Ошибка, текст которой можно показать кассиру."""


def discounted_price(price: float, pct: float) -> float:
    """Цена за единицу со скидкой pct %, округлённая до копеек."""
    if not pct:
        return float(price)
    d = Decimal(str(float(price))) * (100 - Decimal(str(pct))) / 100
    return float(d.quantize(Decimal("0.01"), ROUND_HALF_UP))


def order_total(items, pct: float = 0.0) -> float:
    """Сумма заказа со скидкой — ровно та, что запишется в Operations."""
    total = sum(Decimal(str(float(i.get("Qtty") or 0)))
                * Decimal(str(discounted_price(float(i.get("PriceOut") or 0), pct)))
                for i in items)
    return float(Decimal(total).quantize(Decimal("0.01"), ROUND_HALF_UP))


def get_open_tables():
    """Незакрытые заказы — те у которых нет оплаты"""
    sql = """
        SELECT
            o.Acct,
            o.ObjectID,
            ob.Name  AS ObjectName,
            p.Company AS PartnerName,
            u.Name   AS UserName,
            MAX(o.Date) AS LastDate,
            SUM(o.Qtty * o.PriceOut) AS Total,
            MAX(o.Note) AS Note
        FROM Operations o
        LEFT JOIN Objects  ob ON o.ObjectID  = ob.ID
        LEFT JOIN Partners p  ON o.PartnerID = p.ID
        LEFT JOIN Users    u  ON o.OperatorID= u.ID
        WHERE o.OperType = 2
          AND NOT EXISTS (
              SELECT 1 FROM Payments p WHERE p.OperType = 2 AND p.Acct = o.Acct
          )
        GROUP BY o.Acct, o.ObjectID, ob.Name, p.Company, u.Name
        ORDER BY MAX(o.Date) DESC
    """
    rows = fetch_all(sql)
    # Извлекаем номер стола из Note
    for row in rows:
        note = row.get('Note') or ''
        if note.startswith('TABLE:'):
            try:
                row['TableNum'] = int(note.split(':')[1])
            except:
                row['TableNum'] = 0
        else:
            row['TableNum'] = 0
    return rows


def get_table_items(acct: int) -> list:
    sql = """
        SELECT
            o.ID,
            o.GoodID,
            g.Name  AS GoodName,
            o.Qtty,
            o.PriceOut,
            o.Discount,
            (o.Qtty * o.PriceOut) AS LineTotal,
            g.Measure1
        FROM Operations o
        JOIN Goods g ON o.GoodID = g.ID
        WHERE o.OperType = 2 AND o.Acct = ?
        ORDER BY o.ID
    """
    return fetch_all(sql, [acct])


def add_item(acct: Optional[int], good_id: int, qty: float, price_out: float,
             price_in: float, partner_id: int, object_id: int,
             operator_id: int, user_id: int, table_num: int = 0) -> Optional[int]:
    """Добавляет строку заказа и возвращает номер заказа (None — ошибка).
    acct=None — новый заказ: номер выдаётся в той же транзакции под
    блокировкой, чтобы два устройства не получили один и тот же номер."""
    conn = _get_conn(); cur = conn.cursor()
    try:
        if acct is None:
            cur.execute("SELECT ISNULL(MAX(Acct), 0) + 1 FROM Operations WITH (UPDLOCK, HOLDLOCK)")
            acct = int(cur.fetchone()[0])
        note = f"TABLE:{table_num}" if table_num else ""
        now = datetime.now()
        cur.execute("""
            INSERT INTO Operations
                (OperType, Acct, GoodID, PartnerID, ObjectID, OperatorID,
                 Qtty, Sign, PriceIn, PriceOut, VATIn, VATOut,
                 Discount, CurrencyID, CurrencyRate, Date, UserID, UserRealTime, Note)
            VALUES (2,?,?,?,?,?,?,-1,?,?,0,0,0,1,1,?,?,?,?)
        """, [acct, good_id, partner_id or 1, object_id or 1, operator_id,
              qty, price_in, price_out, now, user_id, now, note])
        conn.commit()
        return acct
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        print(f"add_item error: {e}")
        return None
    finally:
        cur.close()


def change_qty(operation_id: int, delta: float) -> bool:
    """Меняет количество в строке заказа на месте (строка, стол и
    себестоимость сохраняются). Количество не может стать <= 0."""
    try:
        n = execute("""
            UPDATE Operations SET Qtty = Qtty + ?
            WHERE ID = ? AND OperType = 2 AND Qtty + ? > 0
        """, [delta, operation_id, delta])
        return n == 1
    except Exception as e:
        print(f"change_qty error: {e}")
        return False


def remove_item(operation_id: int) -> bool:
    try:
        execute("DELETE FROM Operations WHERE ID=? AND OperType=2", [operation_id])
        return True
    except Exception as e:
        print(f"remove_item error: {e}")
        return False


def close_table(acct: int, payments: dict, partner_id: int,
                object_id: int, user_id: int,
                discount_pct: float, expected_total: float) -> tuple:
    """payments: {Mode: сумма}. Mode 0=наличные, 1=карта, 2=перевод.
    Одной транзакцией: проверка, что заказ не оплачен и не изменился,
    запись скидки в строки (PriceOut — цена со скидкой, Discount — %),
    строки оплаты. Возвращает (ok, текст ошибки)."""
    conn = _get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM Payments WITH (UPDLOCK, HOLDLOCK) "
                    "WHERE OperType=2 AND Acct=?", [acct])
        if cur.fetchone():
            raise OrderError("Заказ уже оплачен")
        cur.execute("SELECT ID, Qtty, PriceOut FROM Operations WITH (UPDLOCK, HOLDLOCK) "
                    "WHERE OperType=2 AND Acct=?", [acct])
        rows = cur.fetchall()
        if not rows:
            raise OrderError("Заказ пуст или удалён")
        total = order_total([{"Qtty": r.Qtty, "PriceOut": r.PriceOut} for r in rows],
                            discount_pct)
        if abs(total - expected_total) > 0.005:
            raise OrderError(f"Заказ изменился (сейчас {total:.2f}). "
                             "Вернитесь к столам и откройте заказ заново")
        paid = round(sum(float(v) for v in payments.values()), 2)
        if abs(paid - total) > 0.005:
            raise OrderError(f"Оплата {paid:.2f} не равна сумме заказа {total:.2f}")
        if discount_pct:
            for r in rows:
                cur.execute("UPDATE Operations SET PriceOut=?, Discount=? WHERE ID=?",
                            [discounted_price(r.PriceOut, discount_pct),
                             float(discount_pct), r.ID])
        now = datetime.now()
        for mode, amount in payments.items():
            cur.execute("""
                INSERT INTO Payments
                    (Acct, OperType, PartnerID, Qtty, Mode, Sign,
                     Date, UserID, ObjectID, UserRealTime, Type)
                VALUES (?,2,?,?,?,-1,?,?,?,?,1)
            """, [acct, partner_id or 1, float(amount), int(mode),
                  now, user_id, object_id or 1, now])
        conn.commit()
        return True, ""
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        print(f"close_table error: {e}")
        return False, str(e) if isinstance(e, OrderError) else f"Ошибка базы данных: {e}"
    finally:
        cur.close()


def cancel_table(acct: int) -> bool:
    try:
        execute("DELETE FROM Operations WHERE Acct=? AND OperType=2", [acct])
        return True
    except Exception as e:
        print(f"cancel_table error: {e}")
        return False


def get_objects() -> list:
    return fetch_all("SELECT * FROM Objects WHERE Deleted=0 ORDER BY Name")


def get_default_partner():
    return fetch_one(
        "SELECT TOP 1 * FROM Partners WHERE Deleted=0 ORDER BY IsVeryUsed DESC, ID"
    )


def get_documents(oper_type=None, date_from=None, date_to=None, limit=300):
    sql = f"""
        SELECT TOP ({limit})
            o.Acct,
            o.OperType,
            ot.RU       AS OperName,
            MAX(o.Date) AS Date,
            p.Company   AS PartnerName,
            ob.Name     AS ObjectName,
            u.Name      AS UserName,
            SUM(o.Qtty * o.PriceOut) AS Total,
            COUNT(*)    AS Lines
        FROM Operations o
        LEFT JOIN OperationType ot ON o.OperType = ot.ID
        LEFT JOIN Partners      p  ON o.PartnerID = p.ID
        LEFT JOIN Objects       ob ON o.ObjectID  = ob.ID
        LEFT JOIN Users         u  ON o.OperatorID= u.ID
        WHERE 1=1
    """
    params = []
    if oper_type:
        sql += " AND o.OperType=?"; params.append(oper_type)
    if date_from:
        sql += " AND o.Date>=?"; params.append(date_from)
    if date_to:
        sql += " AND o.Date<=?"; params.append(date_to)
    sql += """
        GROUP BY o.Acct, o.OperType, ot.RU, p.Company, ob.Name, u.Name
        ORDER BY MAX(o.Date) DESC, o.Acct DESC
    """
    return fetch_all(sql, params)


def get_operation_types() -> list:
    return fetch_all("SELECT * FROM OperationType ORDER BY ID")
