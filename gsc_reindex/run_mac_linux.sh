#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt -q
python3 -m playwright install chromium
# ресурс GSC: sc-domain:boca.su (доменный) или https://boca.su/ (префикс URL)
python3 gsc_reindex.py urls.xlsx --property sc-domain:boca.su --loop --wait 4 --real-chrome
