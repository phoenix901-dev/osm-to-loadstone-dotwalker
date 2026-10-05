#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enrich.py — Linux-порт enrich_route_dat.ps1 (ENRICH v2).

Читает In/data.osm (свежую загрузку get_osm.py) и текущий Out/route.dat
(плоские pt;-строки из convert.py), дописывает типированные точки DotWalker:
pt.residence / pt.path / pt.intersection / pt.transport и view-линии (азимуты
отрезков улиц). Повторный запуск идемпотентен: берёт из route.dat только плоские
pt;, типированные и view пересоздаёт заново.

Дома без addr:street получают улицу по ближайшей улице с названием (~90 м).
"""
import os
import sys
import math
import xml.etree.ElementTree as ET

CELL_DEG = 0.0015   # размер ячейки сетки (~100-150 м) для быстрого поиска улицы
MAX_DIST = 90.0     # ближайшая улица в пределах ~90 м


def fmt(v):
    """0.######: до 6 знаков, без хвостовых нулей, точка."""
    if isinstance(v, int):
        return str(v)
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def get_bearing(lat1, lon1, lat2, lon2):
    r = math.pi / 180.0
    lat1r, lat2r = lat1 * r, lat2 * r
    dlon = (lon2 - lon1) * r
    y = math.sin(dlon) * math.cos(lat2r)
    x = (math.cos(lat1r) * math.sin(lat2r)
         - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    deg = math.degrees(math.atan2(y, x))
    return int((deg + 360.0) % 360.0)


def _node_tags(el):
    tags = {}
    for tg in el.findall("tag"):
        tags[tg.get("k")] = tg.get("v")
    return tags


def enrich_route(osm_path, route_path):
    """Типизирует route.dat по In/data.osm. Возвращает dict со счётчиками."""
    # --- проход 1: узлы (id -> lat/lon/tags) ---
    # ВАЖНО: el.clear() зовём ТОЛЬКО на node/way/relation (после обработки их
    # конца). Чистить на каждом элементе нельзя: у <tag>/<nd> end-событие
    # срабатывает раньше родительского, и их очистка отцепляет теги до того,
    # как node/way дойдёт до findall("tag") — теги окажутся пустыми.
    nodes = {}
    for ev, el in ET.iterparse(osm_path, events=("end",)):
        if el.tag == "osm":
            break
        if el.tag == "node":
            nid = el.get("id")
            lat_s, lon_s = el.get("lat"), el.get("lon")
            if nid is None or lat_s is None or lon_s is None:
                continue
            nodes[nid] = (float(lat_s), float(lon_s), _node_tags(el))
            el.clear()
        elif el.tag in ("way", "relation"):
            el.clear()
    print(f"Узлов: {len(nodes)}")

    street_grid = {}   # "cai_coi" -> список отрезков (name, la1, lo1, la2, lo2)
    node_streets = {}  # id узла -> множество названий улиц (way highway+name)
    node_pois = {}     # id узла -> множество названий POI (way name без highway)

    def add_street_seg(name, la1, lo1, la2, lo2):
        if la1 == la2 and lo1 == lo2:
            return
        cai0 = int(math.floor(min(la1, la2) / CELL_DEG))
        cai1 = int(math.floor(max(la1, la2) / CELL_DEG))
        coi0 = int(math.floor(min(lo1, lo2) / CELL_DEG))
        coi1 = int(math.floor(max(lo1, lo2) / CELL_DEG))
        for a in range(cai0, cai1 + 1):
            for o in range(coi0, coi1 + 1):
                key = f"{a}_{o}"
                street_grid.setdefault(key, []).append((name, la1, lo1, la2, lo2))

    def get_nearest_street(lat, lon):
        # Название ближайшей улицы в пределах 90 м, иначе None.
        cai = int(math.floor(lat / CELL_DEG))
        coi = int(math.floor(lon / CELL_DEG))
        best = None
        best_d = MAX_DIST
        mlat = math.cos(lat * math.pi / 180.0)
        for da in (-1, 0, 1):
            for do in (-1, 0, 1):
                segs = street_grid.get(f"{cai + da}_{coi + do}")
                if not segs:
                    continue
                for (nm, la1, lo1, la2, lo2) in segs:
                    dx, dy = la2 - la1, lo2 - lo1
                    l2 = dx * dx + dy * dy
                    if l2 == 0:
                        continue
                    t = ((lat - la1) * dx + (lon - lo1) * dy) / l2
                    t = max(0.0, min(1.0, t))
                    plat, plon = la1 + t * dx, lo1 + t * dy
                    dlat = (lat - plat) * 111320.0
                    dlon = (lon - plon) * 111320.0 * mlat
                    d = math.sqrt(dlat * dlat + dlon * dlon)
                    if d < best_d:
                        best_d = d
                        best = nm
        return best

    # --- проход 2: пути ---
    view_ways = []   # (name, [(lat, lon), ...]) для view-азимутов
    res_way_pool = []  # (tags, refs) для домов-полигонов (way с addr:housenumber)
    for ev, el in ET.iterparse(osm_path, events=("end",)):
        if el.tag == "osm":
            break
        if el.tag == "way":
            tags = _node_tags(el)
            refs = [nd.get("ref") for nd in el.findall("nd")
                    if nd.get("ref") is not None]
            if refs:
                nm = tags.get("name")
                if nm:
                    is_highway = "highway" in tags
                    if is_highway:
                        # Отрезки улиц в сетку: по ним выводим улицу для домов.
                        prev = None
                        for r in refs:
                            if r in nodes:
                                if prev is not None:
                                    (la1, lo1, _) = nodes[prev]
                                    (la2, lo2, _) = nodes[r]
                                    add_street_seg(nm, la1, lo1, la2, lo2)
                                prev = r
                    for r in refs:
                        if r not in nodes:
                            continue
                        if is_highway:
                            node_streets.setdefault(r, set()).add(nm)
                        else:
                            node_pois.setdefault(r, set()).add(nm)
                if nm and "highway" in tags:
                    coords = [nodes[r][:2] for r in refs if r in nodes]
                    view_ways.append((nm, coords))
                if "addr:housenumber" in tags:
                    res_way_pool.append((tags, refs))
            el.clear()
        elif el.tag in ("node", "relation"):
            el.clear()

    def get_res_name(tags, num, lat, lon):
        st = tags.get("addr:street")
        pl = tags.get("addr:place")
        nm = tags.get("name")
        if nm and st:
            return f"{nm}, {st} {num}"
        if st:
            return f"{st} {num}"
        if nm:
            return nm
        if pl:
            return f"{pl} {num}"
        st2 = get_nearest_street(lat, lon)
        if st2:
            return f"{st2} {num}"
        return None

    # --- residence: дома и POI с адресами ---
    res = []
    res_dedup = set()

    def add_res(name, lat, lon):
        key = f"{name}|{int(lat * 1000000)}|{int(lon * 1000000)}"
        if key in res_dedup:
            return
        res_dedup.add(key)
        res.append((name, lat, lon))

    for (lat, lon, tags) in nodes.values():
        num = tags.get("addr:housenumber")
        if not num:
            continue
        name = get_res_name(tags, num, lat, lon)
        if name:
            add_res(name, lat, lon)

    for (tags, refs) in res_way_pool:
        if "addr:housenumber" not in tags or not refs:
            continue
        sum_lat = sum_lon = cnt = 0.0
        for r in refs:
            if r in nodes:
                sum_lat += nodes[r][0]
                sum_lon += nodes[r][1]
                cnt += 1
        if cnt == 0:
            continue
        clat, clon = sum_lat / cnt, sum_lon / cnt
        name = get_res_name(tags, tags["addr:housenumber"], clat, clon)
        if name:
            add_res(name, clat, clon)

    # --- path (переходы/светофоры) и transport (остановки) ---
    path = []
    transport = []
    for (lat, lon, tags) in nodes.values():
        h = tags.get("highway")
        if h == "crossing":
            c = tags.get("crossing")
            if c == "traffic_signals":
                name = "регулируемый переход"
            elif c in ("uncontrolled", "unmarked"):
                name = "нерегулируемый переход"
            else:
                name = "переход"
            path.append((name, lat, lon))
        elif h == "traffic_signals":
            path.append(("сигнал светофора", lat, lon))
        is_bus = (h == "bus_stop") or (tags.get("public_transport")
                                       in ("bus_stop", "stop_position"))
        rw = tags.get("railway")
        is_rail = rw in ("station", "halt", "tram_stop", "stop")
        if is_bus or is_rail:
            nm = tags.get("name")
            if nm:
                name = nm
            elif is_rail:
                name = "ж/д остановка"
            else:
                name = "автобусная остановка"
            transport.append((name, lat, lon))

    # --- intersection: узлы, где сходятся >=2 улицы с названиями ---
    intersection = []
    for nid, streets in node_streets.items():
        if len(streets) < 2 or nid not in nodes:
            continue
        names = sorted(streets, key=lambda s: s.casefold())
        items = names[:2]
        pois = node_pois.get(nid)
        if pois:
            items.append(next(iter(pois)))
        name = ", ".join(items)
        (lat, lon, _) = nodes[nid]
        intersection.append((name, lat, lon))

    # --- view: азимуты отрезков улиц с названиями ---
    view = []
    for (nm, coords) in view_ways:
        for i in range(len(coords) - 1):
            (la1, lo1), (la2, lo2) = coords[i], coords[i + 1]
            if la1 == la2 and lo1 == lo2:
                continue
            view.append((nm, get_bearing(la1, lo1, la2, lo2)))

    # --- сборка: плоские pt; (нормализуем) + новые типированные + view ---
    flat = []
    with open(route_path, "r", encoding="utf-8", newline="", errors="replace") as f:
        for line in f.read().split("\r\n"):
            if line.startswith("pt;"):
                t = line.rstrip(";")
                if t:
                    flat.append(t + ";;;;")

    def typed_line(prefix, name, lat, lon):
        return f"{prefix};{name};{fmt(lat)};{fmt(lon)};;;;"

    parts = []
    parts.extend(flat)
    parts.extend(typed_line("pt.residence", n, la, lo) for (n, la, lo) in res)
    parts.extend(typed_line("pt.path", n, la, lo) for (n, la, lo) in path)
    parts.extend(typed_line("pt.intersection", n, la, lo)
                 for (n, la, lo) in intersection)
    parts.extend(typed_line("pt.transport", n, la, lo)
                 for (n, la, lo) in transport)
    parts.extend(f"view;{nm};{b};" for (nm, b) in view)

    data = "\r\n".join(parts) + ("\r\n" if parts else "")
    tmp = route_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    os.replace(tmp, route_path)

    counts = dict(flat=len(flat), residence=len(res), path=len(path),
                  intersection=len(intersection), transport=len(transport),
                  view=len(view), total=len(parts))
    print("Готово: route.dat = %d строк (плоских %d, residence %d, path %d, "
          "intersection %d, transport %d, view %d)"
          % (counts["total"], counts["flat"], counts["residence"],
             counts["path"], counts["intersection"], counts["transport"],
             counts["view"]))
    return counts


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    here = os.path.dirname(os.path.abspath(__file__))
    osm_path = os.path.join(here, "In", "data.osm")
    route_path = os.path.join(here, "Out", "route.dat")
    if len(argv) >= 1:
        osm_path = argv[0]
    if len(argv) >= 2:
        route_path = argv[1]
    if not os.path.exists(osm_path):
        print("Нет In/data.osm — сначала запусти get_osm.py.")
        return 1
    if not os.path.exists(route_path):
        print("Нет route.dat — сначала запусти convert.py.")
        return 1
    print("=== ENRICH v2 ===")
    print("Дома без addr:street получают улицу по ближайшей улице.")
    enrich_route(osm_path, route_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
