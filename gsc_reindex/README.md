# Автоматический запрос переобхода URL в Google

Вы кладёте URL в `urls.xlsx` (1-я колонка) или `urls.txt`, скрипт отправляет их на переобход. Готовые URL запоминаются в `state.json` — при повторном запуске пропускаются, лимит дня считается сам.

```bash
pip install -r requirements.txt && playwright install chromium
cp urls.example.txt urls.txt   # впишите свои URL
```

## Режим ui (по умолчанию) — кнопка «Запросить индексирование»
Делает то же, что вы руками в Search Console, но сам. Лимит Google ~10–12 URL/сутки на ресурс.
```bash
python gsc_reindex.py urls.txt --property sc-domain:site.ru            # первый раз: войти в Google в окне
python gsc_reindex.py urls.txt --property sc-domain:site.ru --headless # дальше без окна
```
Сессия хранится в `.browser_profile/`. Если вход блокируется — `--channel chrome`.
Селекторы кнопок заданы для русского и английского интерфейса; если Google поменяет вёрстку, правятся константы `BTN_REQUEST`/`TXT_*`.

## Режим api — Google Indexing API (до 200 URL/сутки)
1. Google Cloud → создать проект → включить «Web Search Indexing API».
2. Создать сервисный аккаунт, скачать JSON-ключ как `service_account.json`.
3. В Search Console → Настройки → Пользователи и разрешения добавить e-mail сервисного аккаунта как **Владельца**.
```bash
python gsc_reindex.py urls.txt --mode api
```
Важно: Google официально поддерживает этот API только для страниц с разметкой JobPosting/BroadcastEvent. Для обычных страниц запросы принимаются, но эффект не гарантирован.

Режим ui для обычных страниц надёжнее; api — для вакансий/трансляций или как эксперимент.

## Полностью автоматический режим (`--loop`)
```bash
python gsc_reindex.py urls.xlsx --property sc-domain:boca.su --loop --wait 4
```
Скрипт работает, пока Google не ответит «квота исчерпана», затем ждёт 4 часа и пробует снова. Если за попытку ничего не отправилось (квота ещё не сброшена, ошибка), снова ждёт 4 часа. Когда все URL пройдены — завершается сам.
Запуск в один клик: `run_windows.bat` / `run_mac_linux.sh`. Первый раз без `--headless` войдите в Google; компьютер не должен засыпать. Для работы без вашего компьютера запустите на сервере/VPS (после первого входа перенесите папку `.browser_profile`).
