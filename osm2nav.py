#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""osm2nav.py — единый запуск для Linux: имя города → карта → готовая база.

Всё по одной команде:
    python3 osm2nav.py "Новороссийск"
    python3 osm2nav.py "Санкт-Петербург" 5        # +5 км вокруг адм. границы
    python3 osm2nav.py minlon minlat maxlon maxlat  # вручную, через ТОЧКУ

Делает сам:
  1. геокодинг названия (Nominatim), опциональное расширение бокса на N км;
  2. закачку карты через Overpass (зеркала, дробление, merge) → In/data.osm;
  3. конвертацию convert.py → Out/loadstone.txt (LoadStone) + route.xml,
     route.dat, затем типизацию route.dat точками ENRICH v2 (residence/path/
     intersection/transport + view) — как в Windows-сборке.

Выход — те же три файла, что на Windows. Замены выражений берутся из
ReplaceListWord.txt рядом с этим скриптом (как в Windows-сборке).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import get_osm  # noqa: E402  (та же папка)

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
    argv = list(sys.argv[1:] if argv is None else argv)
    box, radius = _resolve_box(argv)
    if box is None:
        print("Не смог определить координаты. Можно вручную:")
        print("python3 osm2nav.py minlon minlat maxlon maxlat")
        print("пример: python3 osm2nav.py 38.43 55.84 38.47 55.86")
        return 2
    if radius:
        print(f"Радиус вокруг города: {radius:g} км.")

    print(f"Бокс: lat {box[0]:.4f}..{box[1]:.4f}  lon {box[2]:.4f}..{box[3]:.4f}",
          flush=True)

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
    print(f"Карта готова: {osm_path} ({mb:.1f} МБ)", flush=True)

    # 2) конвертируем
    print("== Шаг 2 из 3: конвертация ==", flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    convert_py = os.path.join(HERE, "convert.py")
    rc = os.system(f'"{sys.executable}" "{convert_py}" "{osm_path}" -o "{OUT_DIR}"')
    if rc != 0:
        print("Конвертация завершилась с ошибкой (код %s)." % rc)
        return 1

    # 3) типизация route.dat (ENRICH v2 — порт enrich_route_dat.ps1)
    print("== Шаг 3 из 3: типизация route.dat (ENRICH v2) ==", flush=True)
    import enrich
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
