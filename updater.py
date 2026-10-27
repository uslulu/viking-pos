"""
Автообновление кассы. Запускается из launch.vbs вместо main.py:

    py updater.py

1. Сверяет локальный VERSION с version.json на сервере (таймаут 5 сек).
2. Если на сервере версия новее — спрашивает кассира «Обновить сейчас /
   Позже» (без ответа за ASK_TIMEOUT сек — «Позже», касса запускается как
   обычно). При согласии скачивает zip, проверяет sha256 и содержимое,
   копирует текущие файлы в backup/<текущая версия>, распаковывает архив
   поверх и обновляет VERSION.
3. Запускает main.py. Сразу после обновления следит за ним: если main.py
   завершился с ошибкой до показа главного окна — откатывает файлы из backup,
   помечает версию как плохую (повторно не ставится) и запускает старую.

На любой ошибке (нет сети, битый архив, нет места) файлы не меняются,
причина пишется в update.log, запускается текущая версия.

Только стандартная библиотека: обновлятор не должен зависеть от того,
что он обновляет. config.ini, backup/ и логи никогда не перезаписываются.

Ручной откат на предыдущую версию (rollback.bat):

    py updater.py --rollback

Дополнительные ключи config.ini, секция [update]:
    ask = false — ставить обновления без вопроса
    ca_file = путь к PEM, если сервер с самоподписанным сертификатом
    allow_http = true — только для отладки
"""
import configparser
import ctypes
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(APP_DIR, "VERSION")
CONFIG_FILE = os.path.join(APP_DIR, "config.ini")
CONFIG_EXAMPLE = os.path.join(APP_DIR, "config.example.ini")
STATE_FILE = os.path.join(APP_DIR, "update_state.json")
LOG_FILE = os.path.join(APP_DIR, "update.log")
MAIN_LOG = os.path.join(APP_DIR, "main.log")
STARTED_FLAG = os.path.join(APP_DIR, "update_started.flag")
BACKUP_DIR = os.path.join(APP_DIR, "backup")
TMP_DIR = os.path.join(APP_DIR, "update_tmp")

DEFAULT_URL = "https://github.com/uslulu/viking-pos/releases/latest/download/version.json"
# Старый адрес из config.ini первых установок — переводим на GitHub
LEGACY_URLS = {"https://food.sheolon.ru/pos-updates/version.json"}
CHECK_TIMEOUT = 5            # сек, на version.json
DOWNLOAD_TIMEOUT = 5         # сек, на каждую операцию сокета при скачивании
DOWNLOAD_DEADLINE = 300      # сек, на весь архив
MAX_ZIP_SIZE = 200 * 1024 * 1024
KEEP_BACKUPS = 3
SHOW_WINDOW_DELAY = 700      # мс: при быстрой проверке окно не мелькает
ASK_TIMEOUT = 60             # сек: без ответа на вопрос об обновлении — «Позже»

# Верхний уровень папки, который обновление и откат не трогают
PRESERVE = {
    "config.ini", "backup", "update_tmp", "update.log", "update_state.json",
    "main.log", "update_started.flag", ".git", "dist", "build",
}
SKIP_DIRS = {"__pycache__"}

UPDATER_MUTEX = r"Local\VikingPOS_updater"
MAIN_MUTEX = r"Local\VikingPOS_main"      # создаётся в main.py

log = logging.getLogger("updater")
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.OpenMutexW.restype = ctypes.c_void_p
_k32.CloseHandle.argtypes = [ctypes.c_void_p]


class UpdateError(Exception):
    pass


# ── Вспомогательное ─────────────────────────────────────────────────────────

def setup_logging():
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def parse_version(s: str) -> tuple:
    parts = s.strip().split(".")
    if not 1 <= len(parts) <= 4 or not all(p.isdigit() for p in parts):
        raise UpdateError(f"Некорректная версия: {s!r}")
    return tuple(int(p) for p in parts)


def read_local_version() -> str:
    try:
        with open(VERSION_FILE, encoding="utf-8-sig") as f:
            v = f.read().strip()
        parse_version(v)
        return v
    except (OSError, UpdateError):
        return "0.0.0"


def write_atomic(path: str, text: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {}


def save_state(state: dict):
    write_atomic(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))


def mutex_exists(name: str) -> bool:
    SYNCHRONIZE = 0x00100000
    h = _k32.OpenMutexW(SYNCHRONIZE, False, name)
    if h:
        _k32.CloseHandle(h)
        return True
    return False


def acquire_mutex(name: str):
    """Хэндл мьютекса или None, если уже запущен другой экземпляр."""
    ERROR_ALREADY_EXISTS = 183
    h = _k32.CreateMutexW(None, False, name)
    if h and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _k32.CloseHandle(h)
        return None
    return h


def read_config() -> configparser.ConfigParser:
    if not os.path.exists(CONFIG_FILE) and os.path.exists(CONFIG_EXAMPLE):
        shutil.copyfile(CONFIG_EXAMPLE, CONFIG_FILE)
        log.info("config.ini не найден — создан из config.example.ini")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_dict({"update": {"enabled": "true", "url": DEFAULT_URL, "ask": "true",
                              "ca_file": "", "allow_http": "false"}})
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8-sig")
    except (configparser.Error, UnicodeDecodeError) as e:
        log.error("Ошибка в config.ini: %s", e)
    return cfg


def rmtree(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def clear_pycache():
    for root, dirs, _ in os.walk(APP_DIR):
        if root == APP_DIR:
            dirs[:] = [d for d in dirs if d not in PRESERVE]
        for d in list(dirs):
            if d == "__pycache__":
                rmtree(os.path.join(root, d))
                dirs.remove(d)


def app_files(root: str) -> list:
    """Относительные пути файлов приложения (без PRESERVE и __pycache__)."""
    result = []
    for cur, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(cur, root)
        if rel_dir == ".":
            dirs[:] = [d for d in dirs if d not in PRESERVE and d not in SKIP_DIRS]
            files = [f for f in files if f not in PRESERVE]
        else:
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".pyc", ".tmp")):
                continue
            result.append(os.path.normpath(os.path.join(rel_dir, f)))
    return result


def copy_files(names, src_root: str, dst_root: str):
    for rel in names:
        dst = os.path.join(dst_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(src_root, rel), dst)


# ── Сеть ────────────────────────────────────────────────────────────────────

def ssl_context(cfg) -> ssl.SSLContext:
    ca_file = cfg.get("update", "ca_file").strip()
    if ca_file:
        return ssl.create_default_context(cafile=os.path.join(APP_DIR, ca_file))
    return ssl.create_default_context()


def check_scheme(url: str, cfg):
    scheme = urllib.parse.urlparse(url).scheme
    if scheme == "https" or (scheme == "http" and cfg.getboolean("update", "allow_http")):
        return
    raise UpdateError(f"Разрешён только HTTPS: {url}")


def open_url(url: str, ctx, timeout: float):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"VikingPOS-updater/{read_local_version()}",
        "Cache-Control": "no-cache",
    })
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def fetch_manifest(url: str, ctx, cfg) -> dict:
    with open_url(url, ctx, CHECK_TIMEOUT) as resp:
        data = json.loads(resp.read(64 * 1024).decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise UpdateError("version.json: ожидался объект")
    for key in ("version", "url", "sha256"):
        if not isinstance(data.get(key), str):
            raise UpdateError(f"version.json: нет поля {key}")
    parse_version(data["version"])
    sha = data["sha256"].lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise UpdateError("version.json: некорректный sha256")
    data["sha256"] = sha
    data["url"] = urllib.parse.urljoin(url, data["url"])
    check_scheme(data["url"], cfg)
    return data


def fetch_manifest_deadline(url: str, ctx, cfg) -> dict:
    """fetch_manifest с жёстким лимитом: таймаут сокета не ограничивает DNS."""
    result = []

    def target():
        try:
            result.append(fetch_manifest(url, ctx, cfg))
        except Exception as e:
            result.append(e)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(CHECK_TIMEOUT + 0.5)
    if not result:
        raise UpdateError(f"Сервер обновлений не ответил за {CHECK_TIMEOUT} сек")
    if isinstance(result[0], Exception):
        raise result[0]
    return result[0]


def download(url: str, dest: str, expected_sha: str, ctx, on_progress):
    deadline = time.monotonic() + DOWNLOAD_DEADLINE
    h = hashlib.sha256()
    size = 0
    with open_url(url, ctx, DOWNLOAD_TIMEOUT) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ZIP_SIZE:
                raise UpdateError("Архив слишком большой")
            if time.monotonic() > deadline:
                raise UpdateError("Скачивание заняло слишком много времени")
            h.update(chunk)
            out.write(chunk)
            if total:
                on_progress(size * 100 // total)
    if total and size != total:
        raise UpdateError(f"Архив скачан не полностью: {size} из {total} байт")
    actual = h.hexdigest()
    if actual != expected_sha:
        raise UpdateError(f"sha256 не совпадает: ожидался {expected_sha}, получен {actual}")
    log.info("Скачано %d байт, sha256 совпадает", size)


# ── Архив, бэкап, откат ─────────────────────────────────────────────────────

def extract_checked(zip_path: str, version: str, dest: str) -> list:
    """Проверяет архив и распаковывает в dest. Возвращает список файлов."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad:
                raise UpdateError(f"Битый файл в архиве: {bad}")
            names = []
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                parts = name.split("/")
                if name.startswith("/") or ":" in name or ".." in parts:
                    raise UpdateError(f"Недопустимый путь в архиве: {name}")
                if parts[0] in PRESERVE or SKIP_DIRS & set(parts):
                    log.warning("Пропускаю %s из архива", name)
                    continue
                target = os.path.join(dest, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                names.append(os.path.normpath(name))
    except zipfile.BadZipFile as e:
        raise UpdateError(f"Битый архив: {e}")
    if "main.py" not in names or "updater.py" not in names:
        raise UpdateError("В архиве нет main.py или updater.py")
    try:
        with open(os.path.join(dest, "VERSION"), encoding="utf-8-sig") as f:
            zip_version = f.read().strip()
    except OSError:
        raise UpdateError("В архиве нет VERSION")
    if zip_version != version:
        raise UpdateError(f"VERSION в архиве {zip_version}, а в version.json {version}")
    return names


def make_backup(version: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, version)
    tmp = dest + ".tmp"
    rmtree(tmp)
    copy_files(app_files(APP_DIR), APP_DIR, tmp)
    rmtree(dest)
    os.replace(tmp, dest)
    log.info("Бэкап текущей версии: %s", dest)
    prune_backups(keep=dest)
    return dest


def prune_backups(keep: str):
    dirs = [os.path.join(BACKUP_DIR, d) for d in os.listdir(BACKUP_DIR)]
    dirs = [d for d in dirs if os.path.isdir(d) and d != keep]
    dirs.sort(key=os.path.getmtime, reverse=True)
    for d in dirs[KEEP_BACKUPS - 1:]:
        rmtree(d)
        log.info("Удалён старый бэкап %s", d)


def restore_backup(backup: str, new_names):
    """Возвращает файлы из backup. Файлы, добавленные новой версией, удаляет."""
    old_names = set(app_files(backup))
    if "main.py" not in old_names:
        raise UpdateError(f"Бэкап {backup} не найден или неполный — откат невозможен")
    for rel in new_names:
        if rel not in old_names:
            try:
                os.remove(os.path.join(APP_DIR, rel))
            except OSError:
                pass
    copy_files(old_names, backup, APP_DIR)
    clear_pycache()
    log.info("Файлы восстановлены из %s", backup)


def rollback(state: dict, reason: str):
    pending = state["pending"]
    log.error("Откат %s -> %s: %s", pending["version"], pending["previous"], reason)
    restore_backup(os.path.join(APP_DIR, pending["backup"]), pending["files"])
    bad = state.setdefault("bad_versions", [])
    if pending["version"] not in bad:
        bad.append(pending["version"])
    state.pop("pending", None)
    save_state(state)


# ── Обновление ──────────────────────────────────────────────────────────────

def recover_interrupted(state: dict):
    """Если прошлая установка оборвалась (выключили питание) — откат."""
    pending = state.get("pending")
    if pending and pending.get("stage") == "installing":
        rollback(state, "установка была прервана")


def check_update(cfg, state: dict):
    """version.json новой версии, которую можно ставить, или None."""
    if not cfg.getboolean("update", "enabled"):
        log.info("Автообновление выключено в config.ini")
        return None
    url = cfg.get("update", "url").strip()
    if url in LEGACY_URLS:
        log.info("Адрес обновлений %s заменён на %s", url, DEFAULT_URL)
        url = DEFAULT_URL
    check_scheme(url, cfg)
    local = read_local_version()

    manifest = fetch_manifest_deadline(url, ssl_context(cfg), cfg)
    remote = manifest["version"]
    if parse_version(remote) <= parse_version(local):
        log.info("Версия %s актуальна (на сервере %s)", local, remote)
        return None
    if remote in state.get("bad_versions", []):
        log.info("Версия %s пропущена: ранее была откачена", remote)
        return None
    log.info("Найдена новая версия %s (текущая %s)", remote, local)
    return manifest


def confirm_update(cfg, manifest: dict) -> bool:
    if not cfg.getboolean("update", "ask"):
        return True
    try:
        agreed = ask_update(read_local_version(), manifest["version"],
                            str(manifest.get("notes") or ""))
    except Exception as e:  # нет tkinter / дисплея — без согласия не ставим
        log.warning("Не удалось спросить об обновлении: %s", e)
        return False
    log.info("Обновление до %s: %s", manifest["version"],
             "кассир согласился" if agreed else "отложено")
    return agreed


def install_update(cfg, state: dict, manifest: dict, ui):
    remote = manifest["version"]
    local = read_local_version()
    ctx = ssl_context(cfg)
    ui.set(f"Обновление до версии {remote}…\nНе выключайте терминал", 0)
    rmtree(TMP_DIR)
    os.makedirs(TMP_DIR)
    try:
        zip_path = os.path.join(TMP_DIR, "update.zip")
        download(manifest["url"], zip_path, manifest["sha256"], ctx,
                 lambda p: ui.set(None, p))
        ui.set("Установка обновления…\nНе выключайте терминал", None)
        staging = os.path.join(TMP_DIR, "new")
        names = extract_checked(zip_path, remote, staging)

        backup = make_backup(local)
        state["pending"] = {
            "stage": "installing", "version": remote, "previous": local,
            "backup": os.path.relpath(backup, APP_DIR), "files": names,
        }
        save_state(state)
        try:
            copy_files(names, staging, APP_DIR)
            write_atomic(VERSION_FILE, remote + "\n")
            clear_pycache()
        except Exception as e:
            rollback(state, f"ошибка копирования: {e}")
            raise
        state["pending"]["stage"] = "installed"
        save_state(state)
        log.info("Установлена версия %s, ждём успешного запуска", remote)
    finally:
        rmtree(TMP_DIR)


# ── Запуск main.py ──────────────────────────────────────────────────────────

def start_main(watch: bool) -> subprocess.Popen:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if watch:
        try:
            os.remove(STARTED_FLAG)
        except OSError:
            pass
        env["POS_STARTED_FLAG"] = STARTED_FLAG
    else:
        env.pop("POS_STARTED_FLAG", None)
    try:
        mode = "w" if os.path.getsize(MAIN_LOG) > 1024 * 1024 else "a"
    except OSError:
        mode = "a"
    out = open(MAIN_LOG, mode, encoding="utf-8")
    out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} запуск версии {read_local_version()}\n")
    out.flush()
    python = sys.executable or "py"
    try:
        return subprocess.Popen([python, "main.py"], cwd=APP_DIR, env=env,
                                stdout=out, stderr=subprocess.STDOUT)
    except OSError:
        return subprocess.Popen(["py", "main.py"], cwd=APP_DIR, env=env,
                                stdout=out, stderr=subprocess.STDOUT)
    finally:
        out.close()


def main_log_tail(lines: int = 25) -> str:
    try:
        with open(MAIN_LOG, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def watch_new_version(state: dict, ui_factory):
    """Ждёт сигнала от main.py о старте. При падении до него — откат."""
    version = state["pending"]["version"]
    proc = start_main(watch=True)
    while True:
        if os.path.exists(STARTED_FLAG):
            os.remove(STARTED_FLAG)
            state.pop("pending", None)
            save_state(state)
            log.info("Версия %s успешно запущена", version)
            return
        code = proc.poll()
        if code is not None:
            if code == 0:
                # Закрыли окно входа — не ошибка; проверим при следующем запуске
                log.info("main.py закрыт до входа, проверка версии %s отложена", version)
                return
            log.error("main.py версии %s упал при старте (код %s):\n%s",
                      version, code, main_log_tail())
            ui_factory().run(lambda ui: rollback(state, f"код выхода {code}"),
                             "Ошибка обновления.\nВозврат прежней версии…")
            start_main(watch=False)
            return
        time.sleep(0.5)


# ── Окно «Обновление…» ──────────────────────────────────────────────────────

class UpdateWindow:
    """Маленькое окно поверх всех. Работа идёт в потоке; если работа
    закончилась быстрее SHOW_WINDOW_DELAY, окно так и не появляется."""

    def __init__(self):
        self.text = None
        self.percent = None
        self._dirty = False

    def set(self, text, percent):
        if text is not None:
            self.text = text
        self.percent = percent
        self._dirty = True

    def run(self, work, text):
        self.set(text, None)
        error = []

        def target():
            try:
                work(self)
            except Exception as e:
                error.append(e)

        t = threading.Thread(target=target, daemon=True)
        try:
            import tkinter as tk
            from tkinter import ttk
            self._run_tk(tk, ttk, t)
        except Exception as e:  # нет tkinter, нет дисплея — работаем без окна
            log.warning("Окно обновления недоступно: %s", e)
            if t.ident is None:
                t.start()
            t.join()
        if error:
            raise error[0]

    def _run_tk(self, tk, ttk, thread):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#2B579A")
        frame = tk.Frame(root, bg="#FFFFFF", padx=24, pady=18)
        frame.pack(padx=2, pady=2, fill="both", expand=True)
        label = tk.Label(frame, text=self.text, bg="#FFFFFF", fg="#222222",
                         font=("Segoe UI", 14), justify="center")
        label.pack()
        bar = ttk.Progressbar(frame, length=360, mode="indeterminate")
        bar.pack(pady=(14, 0))
        bar.start(12)

        def show():
            if thread.is_alive():
                root.update_idletasks()
                w, h = root.winfo_reqwidth(), root.winfo_reqheight()
                x = (root.winfo_screenwidth() - w) // 2
                y = (root.winfo_screenheight() - h) // 2
                root.geometry(f"+{x}+{y}")
                root.deiconify()

        def poll():
            if not thread.is_alive():
                bar.stop()
                root.after_cancel(show_id)
                root.quit()
                return
            if self._dirty:
                self._dirty = False
                label.config(text=self.text)
                if self.percent is None:
                    if str(bar["mode"]) != "indeterminate":
                        bar.config(mode="indeterminate")
                        bar.start(12)
                else:
                    if str(bar["mode"]) != "determinate":
                        bar.stop()
                        bar.config(mode="determinate", maximum=100)
                    bar["value"] = self.percent
            root.after(100, poll)

        thread.start()
        show_id = root.after(SHOW_WINDOW_DELAY, show)
        root.after(100, poll)
        root.mainloop()
        root.destroy()


def ask_update(local: str, remote: str, notes: str) -> bool:
    """Окно «Доступна новая версия»: True — обновить сейчас. Без ответа
    за ASK_TIMEOUT сек — False («Позже»), чтобы касса не стояла."""
    import tkinter as tk
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    answer = [False]
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#2B579A")
    frame = tk.Frame(root, bg="#FFFFFF", padx=28, pady=22)
    frame.pack(padx=2, pady=2, fill="both", expand=True)
    tk.Label(frame, text=f"Доступна новая версия {remote}", bg="#FFFFFF",
             fg="#1E3F7A", font=("Segoe UI", 16, "bold")).pack()
    tk.Label(frame, text=f"Сейчас установлена {local}", bg="#FFFFFF",
             fg="#666666", font=("Segoe UI", 11)).pack(pady=(2, 0))
    if notes:
        if len(notes) > 300:
            notes = notes[:300] + "…"
        tk.Label(frame, text=notes, bg="#FFFFFF", fg="#222222", wraplength=460,
                 justify="left", font=("Segoe UI", 11)).pack(pady=(12, 0))
    tk.Label(frame, text="Обновление займёт меньше минуты.\n"
                         "Если удобнее позже — касса запустится как обычно,\n"
                         "а предложение повторится при следующем запуске.",
             bg="#FFFFFF", fg="#444444", font=("Segoe UI", 11),
             justify="center").pack(pady=(12, 0))
    buttons = tk.Frame(frame, bg="#FFFFFF")
    buttons.pack(pady=(18, 0))

    def choose(value):
        answer[0] = value
        root.quit()

    tk.Button(buttons, text="Обновить сейчас", command=lambda: choose(True),
              bg="#217346", fg="#FFFFFF", activebackground="#1A5C35",
              activeforeground="#FFFFFF", font=("Segoe UI", 14, "bold"),
              relief="flat", padx=22, pady=12).pack(side="left", padx=8)
    later = tk.Button(buttons, text="Позже", command=lambda: choose(False),
                      bg="#E0E0E0", fg="#333333", activebackground="#CCCCCC",
                      font=("Segoe UI", 14), relief="flat", padx=22, pady=12)
    later.pack(side="left", padx=8)
    countdown = tk.Label(frame, bg="#FFFFFF", fg="#888888", font=("Segoe UI", 10))
    countdown.pack(pady=(12, 0))
    left = [ASK_TIMEOUT]

    def tick():
        if left[0] <= 0:
            choose(False)
            return
        countdown.config(text=f"Без ответа через {left[0]} с — «Позже»")
        left[0] -= 1
        root.after(1000, tick)

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 2}")
    root.deiconify()
    root.focus_force()
    tick()
    root.mainloop()
    root.destroy()
    return answer[0]


def manual_rollback() -> int:
    """Возвращает предыдущую версию из backup/ (rollback.bat). Текущая версия
    помечается плохой и больше не предлагается."""
    if mutex_exists(MAIN_MUTEX):
        print("Сначала закройте кассу, затем повторите откат.")
        return 1
    local = read_local_version()
    try:
        names = [d for d in os.listdir(BACKUP_DIR)
                 if not d.endswith(".tmp") and d != local
                 and os.path.isdir(os.path.join(BACKUP_DIR, d))]
    except OSError:
        names = []
    if not names:
        print("Нет сохранённых предыдущих версий в папке backup — откатывать не на что.")
        return 1
    names.sort(key=lambda d: os.path.getmtime(os.path.join(BACKUP_DIR, d)), reverse=True)
    target = names[0]
    log.warning("Ручной откат %s -> %s", local, target)
    restore_backup(os.path.join(BACKUP_DIR, target), app_files(APP_DIR))
    state = load_state()
    bad = state.setdefault("bad_versions", [])
    if local not in bad:
        bad.append(local)
    state.pop("pending", None)
    save_state(state)
    print(f"Готово: версия {local} заменена на {read_local_version()}.")
    print(f"Версия {local} больше не будет предлагаться к установке.")
    return 0


# ── Точка входа ─────────────────────────────────────────────────────────────

def main():
    setup_logging()
    mutex = acquire_mutex(UPDATER_MUTEX)
    if mutex is None:
        # Кассир нажал ярлык повторно, пока идёт обновление
        if "--rollback" in sys.argv[1:]:
            print("Сейчас идёт проверка или установка обновления — повторите откат позже.")
        return

    if "--rollback" in sys.argv[1:]:
        try:
            sys.exit(manual_rollback())
        except UpdateError as e:
            print(f"Откат не выполнен: {e}")
            sys.exit(1)

    state = {}
    main_running = False
    try:
        state = load_state()
        recover_interrupted(state)
        main_running = mutex_exists(MAIN_MUTEX)
        if main_running:
            log.info("Касса уже запущена — обновление пропущено")
        else:
            cfg = read_config()
            if not state.get("pending"):
                found = []
                UpdateWindow().run(lambda ui: found.append(check_update(cfg, state)),
                                   "Проверка обновлений…")
                manifest = found[0] if found else None
                if manifest and confirm_update(cfg, manifest):
                    UpdateWindow().run(
                        lambda ui: install_update(cfg, state, manifest, ui),
                        f"Обновление до версии {manifest['version']}…\nНе выключайте терминал")
    except Exception as e:
        log.error("Обновление не выполнено: %s", e, exc_info=not isinstance(e, (UpdateError, OSError)))

    try:
        if not main_running and state.get("pending", {}).get("stage") == "installed":
            watch_new_version(state, UpdateWindow)
        else:
            start_main(watch=False)
    except Exception:
        log.exception("Ошибка запуска main.py")
        subprocess.Popen(["py", "main.py"], cwd=APP_DIR)


if __name__ == "__main__":
    main()
