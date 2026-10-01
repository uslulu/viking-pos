from db.connection import fetch_all, fetch_one, execute


# ── Группы ───────────────────────────────────────────────────────────────────

def get_groups() -> list:
    return fetch_all("SELECT * FROM GoodsGroups ORDER BY Name")


def create_group(name: str) -> bool:
    try:
        execute("INSERT INTO GoodsGroups (Name, Deleted) VALUES (?, 0)", [name])
        return True
    except Exception as e:
        print(f"create_group: {e}"); return False


def update_group(gid: int, name: str) -> bool:
    try:
        execute("UPDATE GoodsGroups SET Name=? WHERE ID=?", [name, gid])
        return True
    except Exception as e:
        print(f"update_group: {e}"); return False


def delete_group(gid: int) -> bool:
    try:
        # Товары переносим в "без группы"
        execute("UPDATE Goods SET GroupID=NULL WHERE GroupID=?", [gid])
        execute("DELETE FROM GoodsGroups WHERE ID=?", [gid])
        return True
    except Exception as e:
        print(f"delete_group: {e}"); return False


# ── Товары ────────────────────────────────────────────────────────────────────

def get_all(search: str = "", group_id=None) -> list:
    sql = """
        SELECT g.*, gg.Name as GroupName
        FROM Goods g
        LEFT JOIN GoodsGroups gg ON g.GroupID = gg.ID
        WHERE g.Deleted = 0
    """
    params = []
    if search:
        sql += " AND (g.Name LIKE ? OR g.Code LIKE ? OR g.BarCode1 LIKE ?)"
        s = f"%{search}%"; params += [s, s, s]
    if group_id == -1:  # без группы
        sql += " AND g.GroupID IS NULL"
    elif group_id:
        sql += " AND g.GroupID = ?"; params.append(group_id)
    sql += " ORDER BY g.Name"
    return fetch_all(sql, params)


def get_by_id(good_id: int):
    return fetch_one("SELECT * FROM Goods WHERE ID=?", [good_id])


def create(data: dict) -> bool:
    try:
        execute("""
            INSERT INTO Goods (Code, BarCode1, Name, Measure1, PriceIn, PriceOut1,
                               PriceOut2, MinQtty, TaxGroup, GroupID, IsRecipe, Deleted)
            VALUES (?,?,?,?,?,?,?,?,?,?,0,0)
        """, [
            data.get("Code",""), data.get("BarCode1",""), data.get("Name",""),
            data.get("Measure1","шт"), float(data.get("PriceIn",0)),
            float(data.get("PriceOut1",0)), float(data.get("PriceOut2",0)),
            float(data.get("MinQtty",0)), int(data.get("TaxGroup",1)),
            data.get("GroupID"),
        ])
        return True
    except Exception as e:
        print(f"create: {e}"); return False


def update(good_id: int, data: dict) -> tuple:
    try:
        n = execute("""
            UPDATE Goods SET Code=?, BarCode1=?, Name=?, Measure1=?,
                PriceIn=?, PriceOut1=?, GroupID=?
            WHERE ID=?
        """, [
            data.get("Code",""), data.get("BarCode1",""), data.get("Name",""),
            data.get("Measure1","шт"), float(data.get("PriceIn",0)),
            float(data.get("PriceOut1",0)),
            data.get("GroupID"), good_id,
        ])
        if n == 0:
            return False, "Товар не найден в базе"
        return True, ""
    except Exception as e:
        print(f"update: {e}"); return False, str(e)


def delete(good_id: int) -> bool:
    try:
        execute("UPDATE Goods SET Deleted=1 WHERE ID=?", [good_id])
        return True
    except Exception as e:
        print(f"delete: {e}"); return False


def get_stock(good_id: int) -> float:
    try:
        r = fetch_one("SELECT ISNULL(SUM(Qtty),0) as t FROM Store WHERE GoodID=?", [good_id])
        return float(r["t"]) if r else 0.0
    except: return 0.0


def get_last_price(good_id: int) -> float:
    try:
        r = fetch_one(
            "SELECT TOP 1 PriceOut FROM Operations "
            "WHERE GoodID=? AND OperType=2 AND PriceOut>0 ORDER BY Date DESC",
            [good_id]
        )
        return float(r["PriceOut"]) if r else 0.0
    except: return 0.0
