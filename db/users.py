import hashlib
import hmac
from db.connection import fetch_all, fetch_one, execute


def authenticate(code: str, password: str):
    user = fetch_one(
        "SELECT * FROM Users WHERE Code=? AND Deleted=0", [code])
    if not user:
        return None
    stored = (user.get("Password") or "").strip()
    if _is_md5(stored):
        md5 = hashlib.md5(password.encode()).hexdigest().upper()
        ok = hmac.compare_digest(stored.upper(), md5)
    else:
        # Старые записи с паролем открытым текстом (или пустым).
        # Хэш как пароль не принимаем: иначе вход по украденному хэшу
        ok = hmac.compare_digest(stored.encode(), password.encode())
    return user if ok else None


def _is_md5(s: str) -> bool:
    return len(s) == 32 and all(c in "0123456789abcdefABCDEF" for c in s)


def get_all_users() -> list:
    return fetch_all(
        "SELECT * FROM Users WHERE Deleted=0 ORDER BY Name")


def get_user_by_id(user_id: int):
    return fetch_one("SELECT * FROM Users WHERE ID=?", [user_id])


def get_groups() -> list:
    return fetch_all("SELECT * FROM UsersGroups ORDER BY Name")


def create_user(data: dict) -> bool:
    try:
        pwd = data.get("Password", "")
        if pwd:
            pwd = hashlib.md5(pwd.encode()).hexdigest().upper()
        execute("""
            INSERT INTO Users (Code, Name, Password, UserLevel, GroupID, Deleted)
            VALUES (?, ?, ?, ?, ?, 0)
        """, [
            data.get("Code", ""),
            data.get("Name", ""),
            pwd,
            int(data.get("UserLevel", 0)),
            data.get("GroupID"),
        ])
        return True
    except Exception as e:
        print(f"create_user: {e}")
        return False


def update_user(user_id: int, data: dict) -> bool:
    try:
        execute("""
            UPDATE Users SET Code=?, Name=?, UserLevel=?, GroupID=?
            WHERE ID=?
        """, [
            data.get("Code", ""),
            data.get("Name", ""),
            int(data.get("UserLevel", 0)),
            data.get("GroupID"),
            user_id,
        ])
        return True
    except Exception as e:
        print(f"update_user: {e}")
        return False


def change_password(user_id: int, new_password: str) -> bool:
    try:
        pwd = hashlib.md5(new_password.encode()).hexdigest().upper()
        execute("UPDATE Users SET Password=? WHERE ID=?", [pwd, user_id])
        return True
    except Exception as e:
        print(f"change_password: {e}")
        return False


def delete_user(user_id: int) -> bool:
    try:
        execute("UPDATE Users SET Deleted=1 WHERE ID=?", [user_id])
        return True
    except Exception as e:
        print(f"delete_user: {e}")
        return False
