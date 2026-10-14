#!/usr/bin/env python3
"""Скачивание публичной папки Яндекс.Диска файл за файлом.

Использует публичный API Яндекс.Диска (токен не нужен, ссылка должна быть
публичной). Обходит папку рекурсивно, воссоздаёт структуру каталогов,
скачивает файлы по одному, пропускает уже скачанные (по размеру),
докачивает прерванные (Range) и повторяет попытки при ошибках/лимитах.

Примеры:
  python yadisk_download.py "https://disk.yandex.ru/d/XXXXXXXX" -o ./mebel_2024
  # если ссылка ведёт на корень, а нужна подпапка:
  python yadisk_download.py "https://disk.yandex.ru/d/XXXXXXXX" --path "/Мебель 2024"
  # только посмотреть список без скачивания:
  python yadisk_download.py "https://disk.yandex.ru/d/XXXXXXXX" --list
"""
import argparse
import json
import os
import sys
import time

import requests

API = "https://cloud-api.yandex.net/v1/disk/public/resources"
PAGE = 40
session = requests.Session()


def api_get(url, params, retries=40):
    """GET к API с повторами и ожиданием при 429/5xx."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=(15, 180))
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                wait = min(60, 5 * (attempt + 1))
                print(f"  API {r.status_code}, жду {wait}с...", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            wait = min(60, 5 * (attempt + 1))
            print(f"  Ошибка сети ({e}), жду {wait}с...", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Не удалось получить {url} {params}")


def walk(public_key, path):
    """Генератор (относительный_путь_в_папке, item) для всех файлов рекурсивно."""
    offset = 0
    print(f"  читаю папку {path} ...", flush=True)
    while True:
        data = api_get(API, {"public_key": public_key, "path": path,
                             "limit": PAGE, "offset": offset})
        emb = data.get("_embedded", {})
        items = emb.get("items", [])
        if offset:
            print(f"    {path}: прочитано {offset + len(items)}", flush=True)
        for it in items:
            if it["type"] == "dir":
                yield from walk(public_key, it["path"])
            else:
                yield it
        if len(items) < PAGE:
            break
        offset += PAGE


def safe(name):
    return "".join("_" if c in '<>:"|?*\0' else c for c in name).strip() or "_"


def download(public_key, item, dest, retries=8):
    """Скачивает один файл с докачкой. Возвращает True/False."""
    size = item.get("size")
    if size is not None and os.path.exists(dest) and os.path.getsize(dest) == size:
        print(f"  пропуск (уже есть): {dest}")
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"

    for attempt in range(retries):
        try:
            # ссылка на скачивание живёт недолго — запрашиваем перед каждой попыткой
            link = api_get(API + "/download",
                           {"public_key": public_key, "path": item["path"]})["href"]
            have = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            with session.get(link, headers=headers, stream=True, timeout=120) as r:
                if r.status_code == 416:  # уже докачано
                    have = size or have
                elif r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                else:
                    mode = "ab" if r.status_code == 206 else "wb"
                    with open(part, mode) as f:
                        for chunk in r.iter_content(1024 * 1024):
                            f.write(chunk)
            if size is not None and os.path.getsize(part) != size:
                raise RuntimeError(
                    f"размер {os.path.getsize(part)} != {size}")
            os.replace(part, dest)
            return True
        except Exception as e:  # noqa: BLE001
            wait = min(60, 5 * (attempt + 1))
            print(f"  попытка {attempt + 1}/{retries} не удалась: {e}; жду {wait}с",
                  file=sys.stderr)
            time.sleep(wait)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="публичная ссылка на папку Яндекс.Диска")
    ap.add_argument("-o", "--out", default="yadisk_download", help="куда сохранять")
    ap.add_argument("--path", default="/",
                    help="подпапка внутри публичной ссылки, напр. '/Мебель 2024'")
    ap.add_argument("--list", action="store_true", help="только показать список файлов")
    ap.add_argument("--pause", type=float, default=1.0,
                    help="пауза между файлами, сек (по умолчанию 1)")
    a = ap.parse_args()

    base = a.path if a.path.startswith("/") else "/" + a.path
    root = api_get(API, {"public_key": a.url, "path": base, "limit": 1})
    print(f"Папка: {root.get('name')}")

    os.makedirs(a.out, exist_ok=True)
    cache = os.path.join(a.out, "_list.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            files = json.load(fh)
        print(f"Список файлов взят из кэша {cache} (удалите его, чтобы перечитать)")
    else:
        files = list(walk(a.url, base))
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(files, fh, ensure_ascii=False)
    total = sum(f.get("size", 0) for f in files)
    print(f"Найдено файлов: {len(files)}, ~{total / 1024**3:.2f} ГБ")
    if a.list:
        for f in files:
            print(f"{f.get('size', 0):>12}  {f['path']}")
        return

    prefix = base.rstrip("/")
    failed = []
    for i, f in enumerate(files, 1):
        rel = f["path"][len(prefix):].lstrip("/") if f["path"].startswith(prefix) \
            else f["path"].lstrip("/")
        dest = os.path.join(a.out, *[safe(p) for p in rel.split("/")])
        print(f"[{i}/{len(files)}] {rel}")
        if not download(a.url, f, dest):
            failed.append(rel)
        time.sleep(a.pause)

    print(f"\nГотово. Успешно: {len(files) - len(failed)}, с ошибками: {len(failed)}")
    if failed:
        with open(os.path.join(a.out, "_failed.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(failed))
        print("Список неудачных: _failed.txt — просто запустите скрипт ещё раз, "
              "скачанное пропустится.")
        sys.exit(1)


if __name__ == "__main__":
    main()
