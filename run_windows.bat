@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install requests -q
:retry
python yadisk_download.py "https://disk.360.yandex.ru/d/EVyFa73e56Y6dQ" -o mebel_2024
if errorlevel 1 (
  echo.
  echo Была ошибка. Автоповтор через 30 секунд... ^(закройте окно, чтобы остановить^)
  timeout /t 30 >nul
  goto retry
)
echo.
echo Готово. Файлы в папке mebel_2024.
pause
