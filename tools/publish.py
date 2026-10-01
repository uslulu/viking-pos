"""
Выпуск новой версии кассы.

    py tools/publish.py                       # 1.0.0 -> 1.0.1
    py tools/publish.py minor -n "Скидки"     # 1.0.1 -> 1.1.0
    py tools/publish.py 2.0.0 -n "..."        # явная версия
    py tools/publish.py --upload-only         # повторно выложить текущую версию
    py tools/publish.py --dry-run             # только собрать архив в dist/

Что делает:
  1. проверяет, что в git нет незакоммиченных изменений;
  2. поднимает VERSION, коммитит, ставит тег vX.Y.Z;
  3. собирает dist/viking-pos-X.Y.Z.zip из файлов под git
     (без __pycache__, config.ini, tools/ и служебных файлов);
  4. считает sha256 и пишет dist/version.json;
  5. по scp выкладывает архив, затем version.json (атомарно, через mv).

Параметры сервера — в tools/publish.ini.
"""
import argparse
import configparser
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
VERSION_FILE = os.path.join(ROOT, "VERSION")
PUBLISH_INI = os.path.join(ROOT, "tools", "publish.ini")

# Не попадают в архив обновления
EXCLUDE_TOP = {"tools", "dist", "build", "backup", "update_tmp", ".gitignore",
               ".gitattributes", "config.ini", "update_state.json"}
EXCLUDE_PARTS = {"__pycache__", ".git"}


def die(msg):
    print(f"ОШИБКА: {msg}", file=sys.stderr)
    sys.exit(1)


def git(*args) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode:
        die(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def parse_version(s):
    parts = s.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        die(f"версия должна быть вида X.Y.Z: {s!r}")
    return tuple(int(p) for p in parts)


def read_version() -> str:
    with open(VERSION_FILE, encoding="utf-8") as f:
        return f.read().strip()


def next_version(current: str, bump: str) -> str:
    major, minor, patch = parse_version(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if parse_version(bump) <= parse_version(current):
        die(f"новая версия {bump} должна быть больше текущей {current}")
    return bump


def release_files() -> list:
    # Под git + новые неигнорируемые (для --dry-run; при выпуске дерево чистое)
    files = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    result = []
    for f in files:
        if not f:
            continue
        parts = f.split("/")
        if parts[0] in EXCLUDE_TOP or EXCLUDE_PARTS & set(parts) or f.endswith(".pyc"):
            continue
        if not os.path.isfile(os.path.join(ROOT, f)):
            die(f"файл под git отсутствует на диске: {f}")
        result.append(f)
    if "main.py" not in result or "updater.py" not in result or "VERSION" not in result:
        die("в архив не попали main.py / updater.py / VERSION")
    return sorted(result)


def build_zip(version: str) -> str:
    os.makedirs(DIST, exist_ok=True)
    path = os.path.join(DIST, f"viking-pos-{version}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in release_files():
            if f == "VERSION":
                z.writestr("VERSION", version + "\n")
            else:
                z.write(os.path.join(ROOT, f), f)
    return path


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(version: str, zip_path: str, base_url: str, notes: str) -> str:
    manifest = {
        "version": version,
        "url": base_url.rstrip("/") + "/" + os.path.basename(zip_path),
        "sha256": sha256_of(zip_path),
        "notes": notes,
    }
    path = os.path.join(DIST, "version.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return path


def load_server():
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(PUBLISH_INI, encoding="utf-8-sig"):
        die(f"нет {PUBLISH_INI}")
    s = cfg["server"]
    return {
        "host": s["host"], "user": s["user"], "port": s.get("port", "22"),
        "key": os.path.expanduser(s.get("key", "")),
        "remote_dir": s["remote_dir"].rstrip("/"), "base_url": s["base_url"],
    }


def ssh_opts(srv) -> list:
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if srv["key"]:
        opts += ["-i", srv["key"], "-o", "IdentitiesOnly=yes"]
    return opts


def run(cmd):
    print("  $", " ".join(cmd))
    # cwd=dist и относительные пути: scp принимает «C:» в абсолютном пути за имя хоста
    if subprocess.run(cmd, cwd=DIST).returncode:
        die("команда завершилась с ошибкой")


def upload(srv, zip_path: str, manifest_path: str):
    target = f"{srv['user']}@{srv['host']}"
    d = srv["remote_dir"]
    opts = ssh_opts(srv)
    # Сначала архив, потом version.json — клиенты не увидят версию без архива
    zip_name = os.path.basename(zip_path)
    run(["scp", "-P", srv["port"], *opts, zip_name, f"{target}:{d}/"])
    run(["scp", "-P", srv["port"], *opts, os.path.basename(manifest_path),
         f"{target}:{d}/version.json.tmp"])
    run(["ssh", "-p", srv["port"], *opts, target,
         f"chmod 644 {d}/version.json.tmp {d}/{zip_name}"
         f" && mv -f {d}/version.json.tmp {d}/version.json"])


def check_published(srv, version: str):
    import urllib.request
    url = srv["base_url"].rstrip("/") + "/version.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        ok = data.get("version") == version
        print(f"{url}: version={data.get('version')}" + ("  ✓" if ok else "  ✗ ожидалась " + version))
    except Exception as e:
        print(f"Не удалось проверить {url}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Выпуск новой версии кассы")
    ap.add_argument("bump", nargs="?", default="patch",
                    help="patch | minor | major | X.Y.Z (по умолчанию patch)")
    ap.add_argument("-n", "--notes", default="", help="что нового")
    ap.add_argument("--upload-only", action="store_true",
                    help="без поднятия версии: собрать и выложить текущую (тег должен быть на HEAD)")
    ap.add_argument("--dry-run", action="store_true",
                    help="только собрать архив в dist/, без git и выкладки")
    args = ap.parse_args()

    current = read_version()
    parse_version(current)

    if args.dry_run:
        version = next_version(current, args.bump)
        zip_path = build_zip(version)
        write_manifest(version, zip_path, "https://example.invalid/", args.notes)
        print(f"Собрано: {zip_path}")
        return

    srv = load_server()
    if git("status", "--porcelain"):
        die("есть незакоммиченные изменения — сначала git commit")

    if args.upload_only:
        version = current
        tag = f"v{version}"
        if git("tag", "-l", tag) != tag or git("rev-list", "-n1", tag) != git("rev-parse", "HEAD"):
            die(f"тег {tag} не указывает на HEAD")
        notes = args.notes or git("tag", "-l", "--format=%(contents)", tag)
    else:
        version = next_version(current, args.bump)
        tag = f"v{version}"
        if git("tag", "-l", tag):
            die(f"тег {tag} уже существует")
        notes = args.notes or input(f"Что нового в {version}: ").strip()
        with open(VERSION_FILE, "w", encoding="utf-8", newline="\n") as f:
            f.write(version + "\n")
        git("add", "VERSION")
        git("commit", "-m", f"Версия {version}" + (f": {notes}" if notes else ""))
        git("tag", "-a", tag, "-m", notes or f"Версия {version}")
        print(f"Коммит и тег {tag} созданы")

    zip_path = build_zip(version)
    manifest_path = write_manifest(version, zip_path, srv["base_url"], notes)
    print(f"Выкладываю {os.path.basename(zip_path)} на {srv['host']}…")
    try:
        upload(srv, zip_path, manifest_path)
    except SystemExit:
        print(f"\nВыкладка не удалась. Коммит и тег {tag} уже созданы — после исправления "
              f"запустите:\n  py tools/publish.py --upload-only", file=sys.stderr)
        raise
    check_published(srv, version)
    print(f"Готово: версия {version} опубликована. Терминалы обновятся при следующем запуске.")


if __name__ == "__main__":
    main()
