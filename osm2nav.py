#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""osm2nav.py — единый запуск: имя города → карта → готовая база.

Linux:
    python3 osm2nav.py "Новороссийск"
    python3 osm2nav.py "Санкт-Петербург" 5          # +5 км вокруг адм. границы
    python3 osm2nav.py minlon minlat maxlon maxlat  # вручную, через ТОЧКУ

Windows: этот же файл собирается в один osm2nav.exe (см. build_windows.sh) и
запускается через osm2nav.cmd — ввёл город, дальше всё само, результат в консоли.

Делает сам:
  1. геокодинг названия (Nominatim), опциональное расширение бокса на N км;
  2. закачку карты через Overpass (зеркала, дробление, merge) → In/data.osm;
  3. конвертацию → Out/loadstone.txt (LoadStone) + route.xml, route.dat,
     затем типизацию route.dat точками ENRICH v2 (residence/path/
     intersection/transport + view).

Выход — те же три файла, что и раньше. Замены выражений берутся из
ReplaceListWord.txt рядом со скриптом/exe.
"""
import os
import sys

HERE = (os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, 'frozen', False)
        else os.path.dirname(os.path.abspath(__file__)))
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, HERE)

import get_osm   # noqa: E402  (та же папка)
import convert   # noqa: E402
import enrich    # noqa: E402

IN_DIR = os.path.join(HERE, "In")
OUT_DIR = os.path.join(HERE, "Out")


def _resolve_box(argv):
    """(box, radius). 4 числа → вручную; иначе имя [+ радиус км]."""
    if len(argv) == 4:
        try:
            minlon, minlat, maxlon, maxlat = (float(argv[0]), float(argv[1]),
                                              float(argv[2]), float(argv[3]))
            return (minlat, maxlat, minlon, maxlon), 0.0
        except ValueError:
            return None, None
    name = argv[0] if len(argv) >= 1 else ""
    radius = 0.0
    if len(argv) >= 2:
        try:
            radius = float(argv[1])
        except ValueError:
            radius = 0.0
    if not name.strip():
        name = input("Название населённого пункта: ").strip()
    if not name:
        print("Пустое название.")
        return None, None
    box = get_osm.geocode_city(name)
    if box is None:
        return None, None
    return get_osm.expand_box(box, radius), radius


def main(argv=None):
    # Русский текст в консоль Windows: обычно cp866 — переключаем на UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    argv = list(sys.argv[1:] if argv is None else argv)
    box, radius = _resolve_box(argv)
    if box is None:
        print("Не смог определить координаты. Можно вручную:")
        print("osm2nav minlon minlat maxlon maxlat")
        print("пример: osm2nav 38.43 55.84 38.47 55.86")
        return 2
    if radius:
        print("Радиус вокруг города: %g км." % radius)

    print("Бокс: lat %.4f..%.4f  lon %.4f..%.4f"
          % (box[0], box[1], box[2], box[3]), flush=True)

    # 1) качаем карту
    os.makedirs(IN_DIR, exist_ok=True)
    osm_path = os.path.join(IN_DIR, "data.osm")
    if os.path.exists(osm_path):
        os.remove(osm_path)
    print("== Шаг 1 из 3: закачка карты ==", flush=True)
    if not get_osm.download_box(box, osm_path):
        print("Закачка не удалась. Проверь интернет и запусти ещё раз.")
        return 1
    mb = os.path.getsize(osm_path) / (1024 * 1024)
    print("Карта готова: %s (%.1f МБ)" % (osm_path, mb), flush=True)

    # 2) конвертируем (тот же convert.py, но вызовом модуля, а не отдельным
    #    процессом — так работает и внутри собранного exe)
    print("== Шаг 2 из 3: конвертация ==", flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    rc = convert.main([osm_path, "-o", OUT_DIR])
    if rc not in (0, None):
        print("Конвертация завершилась с ошибкой (код %s)." % rc)
        return 1

    # 3) типизация route.dat (ENRICH v2 — порт enrich_route_dat.ps1)
    print("== Шаг 3 из 3: типизация route.dat (ENRICH v2) ==", flush=True)
    enrich.enrich_route(osm_path, os.path.join(OUT_DIR, "route.dat"))

    print("")
    print("Готово. Файлы для программ навигации:")
    print("  " + os.path.join(OUT_DIR, "loadstone.txt") + "  — LoadStone")
    print("  " + os.path.join(OUT_DIR, "route.xml"))
    print("  " + os.path.join(OUT_DIR, "route.dat")
          + "  — DotWalker (типизированные точки ENRICH)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
