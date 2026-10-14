@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install requests
python yadisk_download.py "https://disk.360.yandex.ru/d/EVyFa73e56Y6dQ" -o mebel_2024
echo.
echo Готово. Файлы в папке mebel_2024. Если были ошибки - просто запустите этот файл ещё раз.
pause
