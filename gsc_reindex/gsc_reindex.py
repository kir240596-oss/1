#!/usr/bin/env python3
"""Массовый запрос переобхода URL в Google (Search Console).

Два режима:
  api — Google Indexing API (сервисный аккаунт, до 200 URL/сутки, быстро).
        Официально работает только для JobPosting/BroadcastEvent; для
        остальных страниц Google ответ принимает, но индексацию не гарантирует.
  ui  — автоматизация кнопки «Запросить индексирование» в Search Console
        через Playwright (как делает человек, лимит ~10-12 URL/сутки на ресурс).

Состояние пишется в state.json: уже отправленные URL пропускаются при повторном запуске.
"""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "state.json"


def ensure(module, package=None):
    """Ставит библиотеку, если её нет (на случай сорвавшейся установки)."""
    import importlib
    import subprocess
    try:
        importlib.import_module(module)
    except ImportError:
        print(f"Устанавливаю {package or module}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package or module])


def load_urls(path):
    if Path(path).suffix.lower() in (".xlsx", ".xlsm"):
        ensure("openpyxl")
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).active
        lines = [str(r[0]) for r in ws.iter_rows(values_only=True) if r and r[0]]
    else:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    urls = []
    for line in lines:
        line = line.strip()
        if line.startswith("http"):
            urls.append(line)
    return list(dict.fromkeys(urls))  # без дублей, порядок сохраняем


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"done": {}, "failed": {}}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def sent_today(st, mode):
    today = date.today().isoformat()
    return sum(1 for v in st["done"].values() if v["mode"] == mode and v["date"] == today)


# ---------- режим api ----------
def run_api(urls, st, args):
    ensure("google.auth", "google-auth")
    ensure("requests")
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    creds = service_account.Credentials.from_service_account_file(
        args.credentials, scopes=["https://www.googleapis.com/auth/indexing"]
    )
    session = AuthorizedSession(creds)
    endpoint = "https://indexing.googleapis.com/v3/urlNotifications:publish"
    for url in urls:
        if sent_today(st, "api") >= args.limit:
            print(f"Достигнут дневной лимит {args.limit}, остановка.")
            break
        r = session.post(endpoint, json={"url": url, "type": "URL_UPDATED"}, timeout=30)
        if r.status_code == 200:
            print(f"OK    {url}")
            st["done"][url] = {"mode": "api", "date": date.today().isoformat()}
            st["failed"].pop(url, None)
        else:
            msg = f"{r.status_code} {r.text[:200]}"
            print(f"FAIL  {url} — {msg}")
            st["failed"][url] = msg
            if r.status_code == 429:
                print("Квота исчерпана, остановка.")
                save_state(st)
                break
        save_state(st)
        time.sleep(args.delay)


# ---------- режим ui ----------
BTN_REQUEST = re.compile(r"Запросить индексирование|Request indexing", re.I)
TXT_DONE = re.compile(r"Индексирование запрошено|Indexing requested", re.I)
TXT_QUOTA = re.compile(r"Превышена квота|Quota exceeded", re.I)
TXT_ALREADY = re.compile(r"уже в очереди|already.*(requested|queue)", re.I)


def chrome_exe():
    import os
    import shutil
    cands = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome") or "", shutil.which("chromium") or "",
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit("Chrome не найден. Установите Google Chrome.")


def connect_real_chrome(p, port=9222):
    """Запускает обычный Chrome (без флагов автоматизации — Google пускает войти) и подключается к нему."""
    import subprocess
    url = f"http://localhost:{port}"
    try:
        return p.chromium.connect_over_cdp(url)
    except Exception:  # noqa: BLE001
        pass
    subprocess.Popen([
        chrome_exe(), f"--remote-debugging-port={port}",
        f"--user-data-dir={HERE / 'chrome_profile'}", "--no-first-run",
        "https://search.google.com/search-console",
    ])
    for _ in range(30):
        time.sleep(1)
        try:
            return p.chromium.connect_over_cdp(url)
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("Не удалось подключиться к Chrome")


def run_ui(urls, st, args):
    ensure("playwright")
    from playwright.sync_api import sync_playwright

    profile = HERE / ".browser_profile"
    with sync_playwright() as p:
        if args.real_chrome:
            browser = connect_real_chrome(p)
            ctx = browser.contexts[0]
            page = ctx.new_page()
        else:
            ctx = p.chromium.launch_persistent_context(
                str(profile), headless=args.headless, channel=args.channel or None,
                args=["--disable-blink-features=AutomationControlled"], viewport={"width": 1400, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://search.google.com/search-console?resource_id={args.property}")
        if "accounts.google" in page.url and args.headless:
            print("Сессия Google не авторизована. Один раз запустите без --headless и войдите в аккаунт.")
            page.close() if args.real_chrome else ctx.close()
            return
        if "accounts.google" in page.url:
            input("Войдите в аккаунт Google в открытом окне Chrome, затем нажмите Enter здесь... ")
            page.goto(f"https://search.google.com/search-console?resource_id={args.property}")
        fails = 0
        for url in urls:
            if args.limit and sent_today(st, "ui") >= args.limit:
                print(f"Достигнут локальный лимит {args.limit}, остановка.")
                break
            if fails >= 3:
                print("3 ошибки подряд — похоже, не работает вход/интерфейс, остановка до следующей попытки.")
                break
            try:
                box = page.get_by_role("combobox").first
                box.click()
                box.fill(url)
                box.press("Enter")
                btn = page.get_by_role("button", name=BTN_REQUEST).first
                btn.wait_for(timeout=120_000)  # проверка «живого» URL занимает до пары минут
                btn.click()
                page.get_by_text(TXT_DONE).or_(page.get_by_text(TXT_QUOTA)).first.wait_for(timeout=180_000)
                if page.get_by_text(TXT_QUOTA).count():
                    print("Квота ресурса исчерпана, остановка.")
                    break
                fails = 0
                print(f"OK    {url}")
                st["done"][url] = {"mode": "ui", "date": date.today().isoformat()}
                st["failed"].pop(url, None)
                for close in (r"Закрыть|Close", r"Понятно|Got it|OK"):
                    b = page.get_by_role("button", name=re.compile(close, re.I))
                    if b.count():
                        b.first.click()
                        break
            except Exception as e:  # noqa: BLE001
                print(f"FAIL  {url} — {type(e).__name__}: {str(e)[:150]}")
                st["failed"][url] = type(e).__name__
                fails += 1
                page.goto(f"https://search.google.com/search-console?resource_id={args.property}")
            save_state(st)
            time.sleep(args.delay)
        page.close() if args.real_chrome else ctx.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls_file", help="xlsx (URL в 1-й колонке) или txt: один URL на строку")
    ap.add_argument("--mode", choices=["api", "ui"], default="ui")
    ap.add_argument("--credentials", default=str(HERE / "service_account.json"), help="[api] JSON сервисного аккаунта")
    ap.add_argument("--property", help="[ui] ресурс GSC: sc-domain:site.ru или https://site.ru/ (префикс URL)")
    ap.add_argument("--headless", action="store_true", help="[ui] без окна (после первого входа)")
    ap.add_argument("--real-chrome", action="store_true", help="[ui] запустить обычный Chrome и подключиться к нему (Google пускает войти, профиль в chrome_profile/)")
    ap.add_argument("--channel", default="", help="[ui] 'chrome' — использовать установленный Chrome")
    ap.add_argument("--limit", type=int, help="макс. URL за сутки (api: 200, ui: 0 = без локального лимита)")
    ap.add_argument("--delay", type=float, help="пауза между URL, сек (api: 1, ui: 5)")
    ap.add_argument("--loop", action="store_true", help="работать, пока не пройдут все URL; при остановке (лимит/ошибка) ждать --wait часов и повторять")
    ap.add_argument("--wait", type=float, default=4, help="пауза между попытками в --loop, часов (по умолчанию 4)")
    ap.add_argument("--force", action="store_true", help="игнорировать state.json и слать всё заново")
    args = ap.parse_args()

    if args.limit is None:
        args.limit = 200 if args.mode == "api" else 0  # ui: лимит определяет сам Google (сообщение о квоте)
    args.delay = args.delay if args.delay is not None else (1 if args.mode == "api" else 5)
    if args.mode == "ui" and not args.property:
        sys.exit("Для --mode ui укажите --property")

    all_urls = load_urls(args.urls_file)
    while True:
        st = load_state()
        urls = all_urls if args.force else [u for u in all_urls if u not in st["done"]]
        args.force = False
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] К отправке: {len(urls)} URL, режим {args.mode}")
        try:
            (run_api if args.mode == "api" else run_ui)(urls, st, args)
        except Exception as e:  # noqa: BLE001
            print(f"Ошибка запуска: {type(e).__name__}: {e}")
        st = load_state()
        left = [u for u in all_urls if u not in st["done"]]
        print(f"Отправлено: {len(st['done'])}, осталось: {len(left)}, ошибок: {len(st['failed'])}")
        if not left:
            print("Все URL из списка обработаны.")
            break
        if not args.loop:
            print("Запустите скрипт снова (или используйте --loop) — продолжит с места остановки.")
            break
        nxt = datetime.fromtimestamp(time.time() + args.wait * 3600)
        print(f"Следующая попытка в {nxt:%Y-%m-%d %H:%M} (через {args.wait} ч). Не закрывайте окно.")
        time.sleep(args.wait * 3600)


if __name__ == "__main__":
    main()
