from db.connection import fetch_all, fetch_one, execute
from datetime import datetime


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
          AND o.Acct NOT IN (
              SELECT DISTINCT Acct FROM Payments WHERE OperType = 2
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


def get_next_acct() -> int:
    r = fetch_one("SELECT ISNULL(MAX(Acct), 0) + 1 AS next FROM Operations")
    return int(r["next"]) if r else 1


def add_item(acct: int, good_id: int, qty: float, price_out: float,
             price_in: float, partner_id: int, object_id: int,
             operator_id: int, user_id: int, table_num: int = 0) -> bool:
    try:
        note = f"TABLE:{table_num}" if table_num else ""
        execute("""
            INSERT INTO Operations
                (OperType, Acct, GoodID, PartnerID, ObjectID, OperatorID,
                 Qtty, Sign, PriceIn, PriceOut, VATIn, VATOut,
                 Discount, CurrencyID, CurrencyRate, Date, UserID, UserRealTime, Note)
            VALUES (2,?,?,?,?,?,?,-1,?,?,0,0,0,1,1,?,?,?,?)
        """, [acct, good_id, partner_id or 1, object_id or 1, operator_id,
              qty, price_in, price_out,
              datetime.now(), user_id, datetime.now(), note])
        return True
    except Exception as e:
        print(f"add_item error: {e}")
        return False


def remove_item(operation_id: int) -> bool:
    try:
        execute("DELETE FROM Operations WHERE ID=? AND OperType=2", [operation_id])
        return True
    except Exception as e:
        print(f"remove_item error: {e}")
        return False


def close_table(acct: int, payments: dict, partner_id: int,
                object_id: int, user_id: int) -> bool:
    """payments: {Mode: сумма}. Mode 0=наличные, 1=карта, 2=перевод.
    Все строки оплаты пишутся одной транзакцией."""
    from db.connection import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    try:
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
        return True
    except Exception as e:
        conn.rollback()
        print(f"close_table error: {e}")
        return False
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
