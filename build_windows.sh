#!/usr/bin/env bash
# Собирает Windows-версию: один самодостаточный osm2nav.exe (Python 3 вшит,
# внешние .exe и PowerShell не нужны). Требуется podman.
#
# Образ cdrx/pyinstaller-windows:python3 = wine + PyInstaller, собирает
# windows/.exe прямо на Linux. Результат: dist/windows/osm2nav.exe
# + osm2nav.cmd (лаунчер) + ReplaceListWord.txt (словарь замен, рядом с exe).
set -euo pipefail
cd "$(dirname "$0")"

podman run --rm -v "$PWD:/src:z" -w /src cdrx/pyinstaller-windows:python3 \
    "pyinstaller --onefile --console --name osm2nav --distpath dist/windows osm2nav.py"

cp Windows/osm2nav.cmd  dist/windows/
cp ReplaceListWord.txt  dist/windows/
echo "Готово: dist/windows/osm2nav.exe (+ osm2nav.cmd, ReplaceListWord.txt)"
