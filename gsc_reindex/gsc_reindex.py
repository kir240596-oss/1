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
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "state.json"


def load_urls(path):
    urls = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
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


def run_ui(urls, st, args):
    from playwright.sync_api import sync_playwright

    profile = HERE / ".browser_profile"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=args.headless, channel=args.channel or None,
            args=["--disable-blink-features=AutomationControlled"], viewport={"width": 1400, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://search.google.com/search-console?resource_id={args.property}")
        if "accounts.google" in page.url:
            input("Войдите в аккаунт Google в открытом окне, затем нажмите Enter здесь... ")
            page.goto(f"https://search.google.com/search-console?resource_id={args.property}")
        for url in urls:
            if sent_today(st, "ui") >= args.limit:
                print(f"Достигнут дневной лимит {args.limit}, остановка.")
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
                page.goto(f"https://search.google.com/search-console?resource_id={args.property}")
            save_state(st)
            time.sleep(args.delay)
        ctx.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls_file", help="txt-файл: один URL на строку (# — комментарий)")
    ap.add_argument("--mode", choices=["api", "ui"], default="ui")
    ap.add_argument("--credentials", default=str(HERE / "service_account.json"), help="[api] JSON сервисного аккаунта")
    ap.add_argument("--property", help="[ui] ресурс GSC: sc-domain:site.ru или https://site.ru/ (префикс URL)")
    ap.add_argument("--headless", action="store_true", help="[ui] без окна (после первого входа)")
    ap.add_argument("--channel", default="", help="[ui] 'chrome' — использовать установленный Chrome")
    ap.add_argument("--limit", type=int, help="макс. URL за сутки (api: 200, ui: 10)")
    ap.add_argument("--delay", type=float, help="пауза между URL, сек (api: 1, ui: 5)")
    ap.add_argument("--retry-failed", action="store_true", help="повторить URL из failed")
    ap.add_argument("--force", action="store_true", help="игнорировать state.json и слать всё заново")
    args = ap.parse_args()

    args.limit = args.limit or (200 if args.mode == "api" else 10)
    args.delay = args.delay if args.delay is not None else (1 if args.mode == "api" else 5)
    if args.mode == "ui" and not args.property:
        sys.exit("Для --mode ui укажите --property")

    st = load_state()
    urls = load_urls(args.urls_file)
    if not args.force:
        urls = [u for u in urls if u not in st["done"]]
    print(f"К отправке: {len(urls)} URL, режим {args.mode}, лимит/сутки {args.limit}")
    (run_api if args.mode == "api" else run_ui)(urls, st, args)
    left = [u for u in load_urls(args.urls_file) if u not in st["done"]]
    print(f"Итого отправлено: {len(st['done'])}, осталось: {len(left)}, ошибок: {len(st['failed'])}")
    if left:
        print("Запустите скрипт завтра — он продолжит с места остановки.")


if __name__ == "__main__":
    main()
