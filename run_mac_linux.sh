#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 -m pip install requests
python3 yadisk_download.py "https://disk.360.yandex.ru/d/EVyFa73e56Y6dQ" -o mebel_2024
