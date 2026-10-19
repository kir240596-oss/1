@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt -q
python -m playwright install chromium
:: ресурс GSC: sc-domain:boca.su (доменный) или https://boca.su/ (префикс URL)
python gsc_reindex.py urls.xlsx --property sc-domain:boca.su --loop --wait 4 --real-chrome
pause
