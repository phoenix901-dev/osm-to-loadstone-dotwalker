#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""get_osm.py — Linux-порт get_osm.ps1: закачка свежего .osm через Overpass API.

Кладёт готовый файл в In/data.osm (каталог рядом со скриптом), дальше запускай
convert.py. Если кусок тяжеловат для сервера — сам дробит на четверти, пока не
влезет. Серверов несколько: занят или не отвечает один — пробует следующий.

Поведение пофайлово повторяет get_osm.ps1 (зеркала, классификация ответа,
вежливые паузы, преддробление ~0.5° долготы, BFS-четвертование до глубины 14,
merge с дедупом по type:id и синтезом <bounds>).

CLI:
    python3 get_osm.py "Название города" [радиус_км]
    python3 get_osm.py minlon minlat maxlon maxlat     # через ТОЧКУ
"""
import os
import re
import sys
import time
import math
import json
import tempfile
import urllib.parse
import urllib.request
import urllib.error

UA = "get_osm_cmd/1.0 (OSM-Loadstone-Converter)"

# Overpass-зеркала. Первый — основной, остальные запасные.
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IN_DIR = os.path.join(SCRIPT_DIR, "In")

# Скольким русским сообщениям тут соответствует одна строка в get_osm.ps1.
# last_req[mirror] = монотонное время последнего запроса к этому серверу.
last_req = {}


def num(x):
    """Число с ТОЧКОЙ, до 8 знаков без хвостовых нулей (аналог '0.########')."""
    if isinstance(x, int):
        return str(x)
    s = f"{x:.8f}".rstrip("0").rstrip(".")
    if s in ("", "-"):
        s = "0"
    return s


def _http_get(url, timeout_sec=90):
    """Скачивает URL в память, возвращает (status, body_bytes)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body
    except urllib.error.URLError:
        return 0, b""
    except Exception:
        return 0, b""


def _head_text(body):
    """Первые 16 КБ ответа как UTF-8 (аналог чтения первых байт в ps1)."""
    if not body:
        return ""
    head = body[:16384]
    return head.decode("utf-8", errors="replace")


def save_overpass(base, query, out_path, timeout_sec=90):
    """Один запрос к одному зеркалу. Возвращает 'ok'/'too_big'/'transient'."""
    url = base + "?data=" + urllib.parse.quote(query, safe="")
    status, body = _http_get(url, timeout_sec)
    if status == 0:
        return "transient"  # сеть/таймаут — повторим на другом сервере
    if status == 400:
        return "too_big"
    if status != 200:
        # 429 лимит запросов, 5xx — транзиентное.
        return "transient"
    # Overpass отдаёт HTTP 200 даже при внутренней ошибке — смотрим на первые байты.
    head = _head_text(body)
    if re.search(r"<strong|runtime error|Error", head):
        # Сервер занят/перегружен — повторим, а не дробить.
        if re.search(r"too busy|open64|Dispatcher_Client", head):
            return "transient"
        # Сам запрос не успел по времени — кусок тяжеловат, надо дробить.
        if re.search(r"Query timed out", head):
            return "too_big"
        return "transient"
    # Нет ни одного элемента — мёртвое зеркало отдало пустоту. К следующему.
    if re.search(r"<node |<way |<relation ", head):
        with open(out_path, "wb") as f:
            f.write(body)
        return "ok"
    return "transient"


def _announce_downloading():
    print("Качаю фрагмент карты. Сервер отвечает обычно 10-60 секунд, иногда до "
          "двух минут — если на экране тихо, всё идёт, жди.", flush=True)


def get_tile(tile, out_path):
    """Качает один кусок, обходя серверы по кругу.
    Возвращает 'ok'/'too_big' (надо дробить)/'failed' (сдались после повторов)."""
    parts = tile.split(";")
    s, n, w, e = (float(parts[0]), float(parts[1]),
                  float(parts[2]), float(parts[3]))
    # Overpass хочет bbox в порядке south,west,north,east.
    query = ("[out:xml][timeout:60];"
             "(node(%s,%s,%s,%s);way(%s,%s,%s,%s););(._;>;);out body;"
             % (num(s), num(w), num(n), num(e),
                num(s), num(w), num(n), num(e)))
    announced = False
    for pass_no in range(3):
        split = False
        for m in MIRRORS:
            # Вежливая пауза: к одному серверу не чаще раза в 5 секунд.
            el = time.monotonic() - last_req.get(m, 0.0)
            need = 5.0 - el
            if need > 0:
                time.sleep(need)
            if not announced:
                announced = True
                _announce_downloading()
            r = save_overpass(m, query, out_path)
            last_req[m] = time.monotonic()
            if r == "ok":
                return "ok"
            if r == "too_big":
                if not split:
                    split = True
                    print("Фрагмент великоват для сервера — разбиваю его на "
                          "четыре части.", flush=True)
            else:
                if not split:
                    print("Сервер занят или не ответил — пробую следующий "
                          "сервер.", flush=True)
        if split:
            return "too_big"
        # Все серверы транзиентно отказали — ждём подольше и пробуем ещё круг:
        # 5с, потом 15с.
        if pass_no < 2:
            wait = 5 + pass_no * 10
            print(f"Все серверы сейчас заняты — это штатно, они сами "
                  f"перезагружаются. Жду {wait}с и повторяю фрагмент.",
                  flush=True)
            time.sleep(wait)
    return "failed"


def geocode_city(name):
    """Nominatim: имя города → (minlat, maxlat, minlon, maxlon) или None."""
    url = ("https://nominatim.openstreetmap.org/search?q="
           + urllib.parse.quote(name, safe="") + "&format=json&limit=1")
    status, body = _http_get(url, 60)
    if status != 200:
        print("Геокодинг не ответил (http %s)." % status)
        return None
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        print("Геокодинг вернул не-JSON.")
        return None
    if not data:
        print("Не нашёл населённый пункт:", name)
        return None
    bb = data[0]["boundingbox"]  # [minlat, maxlat, minlon, maxlon]
    return (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))


def expand_box(box, km):
    """box=[minlat,maxlat,minlon,maxlon]; km<=0 → без изменений."""
    if km <= 0:
        return box
    minlat, maxlat, minlon, maxlon = box
    lat = (minlat + maxlat) / 2.0
    dlat = km / 111.32
    dlon = km / (111.32 * max(0.2, math.cos(math.pi / 180.0 * lat)))
    return (max(-90.0, minlat - dlat), min(90.0, maxlat + dlat),
            max(-180.0, minlon - dlon), min(180.0, maxlon + dlon))


# Элементы OSM-вывода плоские (не вложены), поэтому нижняя граница элемента —
# это просто ближайший закрывающий тег того же типа. Дедуп по type:id.
_ELEM_OPEN = re.compile(r"<(?P<type>node|way|relation)\b(?=[^>]*\bid\s*=\s*\"(?P<id>\d+)\")[^>]*?/?>")


def _iter_elements(text):
    """Вербатильные spans элементов <node|way|relation id="NNN">…</тип> в порядке
    документа. Воспроизводит то, что вылавливал один .NET-регэксп в ps1."""
    pos = 0
    while True:
        m = _ELEM_OPEN.search(text, pos)
        if not m:
            return
        head = m.group(0)
        typ = m.group("type")
        start = m.start()
        if head.endswith("/>"):
            yield text[start:m.end()], typ
            pos = m.end()
        else:
            end = text.find("</" + typ + ">", m.end())
            if end == -1:
                return  # обрезанный/битый чанк — дальше разбирать нечего
            end += len(typ) + 3
            yield text[start:end], typ
            pos = end


def merge_chunks(paths, out_path, box):
    """Слияние: один раз по каждому чанку, уникализация по type:id, запись сразу."""
    print("Собираю базу: это тоже занимает немного времени.", flush=True)
    bounds_done = False
    seen = set()
    count = 0
    bounds_pat = re.compile(r"<bounds[^>]*/>")
    total = len(paths)
    with open(out_path, "wb") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'.encode())
        f.write('<osm version="0.6" generator="get_osm.py">\n'.encode())
        for ci, p in enumerate(paths, 1):
            print(f"  Фрагмент {ci} из {total}…", flush=True)
            with open(p, "rb") as fh:
                raw = fh.read()
            text = raw.decode("utf-8", errors="replace")
            if not bounds_done:
                bm = bounds_pat.search(text)
                if bm:
                    f.write(bm.group(0).encode() + b"\n")
                    bounds_done = True
            since_report = 0
            for elem, typ in _iter_elements(text):
                # id извлекается повторно (он же попал в match group, но span-итератор
                # отдаёт только строку) — берём из атрибута.
                im = re.search(r'\bid\s*=\s*"(\d+)"', elem[:elem.find(">") + 1])
                if not im:
                    continue
                key = typ + ":" + im.group(1)
                if key in seen:
                    continue
                seen.add(key)
                f.write(elem.encode("utf-8", errors="replace") + b"\n")
                count += 1
                since_report += 1
                if since_report >= 200000:
                    print(f"  Обработано элементов: {count}.", flush=True)
                    since_report = 0
        if not bounds_done and box is not None:
            f.write(("<bounds minlat=\"%s\" minlon=\"%s\" maxlat=\"%s\" "
                     "maxlon=\"%s\"/>\n" % (num(box[0]), num(box[2]),
                                            num(box[1]), num(box[3]))).encode())
        f.write("</osm>\n".encode())
    print(f"Уникальных элементов: {count}", flush=True)


def download_box(box, out_path):
    """Качает весь бокс с преддроблением и BFS-четвертованием. True при успехе."""
    minlat, maxlat, minlon, maxlon = box
    lon_span = maxlon - minlon
    if lon_span <= 0:
        print("Некорректный бокс: долгота не растёт.")
        return False
    init_depth = max(0, math.ceil(math.log(max(0.001, lon_span / 0.5)) / math.log(2)))
    if init_depth > 0:
        cells = int(math.pow(4, init_depth))
        print(f"Область большая — поделю её примерно на {cells} фрагментов и "
              f"скачаю по очереди. Это займёт время, каждый готовый фрагмент "
              f"буду подтверждать.", flush=True)
    print("Если сервер занят — программа сама ждёт и пробует снова, ничего "
          "нажимать не нужно.", flush=True)

    tmp_dir = tempfile.mkdtemp(prefix="get_osm_tiles_")
    queue = [(f"{num(minlat)};{num(maxlat)};{num(minlon)};{num(maxlon)}", 0)]
    chunks = []
    failed = []
    max_depth = 14
    attempt = 0

    def quarter(tile, depth):
        p = tile.split(";")
        tminlat, tmaxlat, tminlon, tmaxlon = map(float, p)
        midlat = (tminlat + tmaxlat) / 2.0
        midlon = (tminlon + tmaxlon) / 2.0
        nd = depth + 1
        return [(f"{num(tminlat)};{num(midlat)};{num(tminlon)};{num(midlon)}", nd),
                (f"{num(tminlat)};{num(midlat)};{num(midlon)};{num(tmaxlon)}", nd),
                (f"{num(midlat)};{num(tmaxlat)};{num(tminlon)};{num(midlon)}", nd),
                (f"{num(midlat)};{num(tmaxlat)};{num(midlon)};{num(tmaxlon)}", nd)]

    try:
        while queue:
            tile, depth = queue.pop(0)
            if depth < init_depth:
                # Преддробление без запроса — просто разрезаем бокс.
                queue = quarter(tile, depth) + queue
                continue
            tmp = os.path.join(tmp_dir, f"tile_{attempt}.osm")
            attempt += 1
            result = get_tile(tile, tmp)
            if result == "ok":
                chunks.append(tmp)
                print(f"Фрагмент скачан. Готовых фрагментов: {len(chunks)}.",
                      flush=True)
            elif result == "too_big":
                if depth >= max_depth:
                    failed.append(tile)
                    print(f"Ошибка: кусок {tile} не влез в сервер даже после "
                          f"дробления.", flush=True)
                else:
                    queue = quarter(tile, depth) + queue
            else:
                failed.append(tile)
                print(f"Ошибка: кусок {tile} не скачался даже после повторов.",
                      flush=True)
        if not chunks:
            print("Скачать не удалось. Проверь интернет и попробуй ещё раз.")
            return False
        print(f"Скачано кусков: {len(chunks)}", flush=True)
        merge_chunks(chunks, out_path, box)
        if failed:
            print("")
            print(f"ВНИМАНИЕ: {len(failed)} кусков не скачались — в этих местах "
                  f"карта будет неполной.")
            print("Координаты первых кусков:")
            for t in failed[:5]:
                print("  " + t)
            print("Просто запусти get_osm.py ещё раз — повтор добрает "
                  "пропущенные куски.")
        return True
    finally:
        for f_ in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, f_))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    box = None
    radius = 0.0

    def _manual_hint():
        print("Можно вручную:")
        print("python3 get_osm.py minlon minlat maxlon maxlat")
        print("пример: python3 get_osm.py 38.43 55.84 38.47 55.86")

    if len(argv) == 4:
        try:
            # вручную: minlon minlat maxlon maxlat (через ТОЧКУ)
            minlon = float(argv[0])
            minlat = float(argv[1])
            maxlon = float(argv[2])
            maxlat = float(argv[3])
            box = (minlat, maxlat, minlon, maxlon)
        except ValueError:
            print("Ожидал 4 числа: minlon minlat maxlon maxlat")
            _manual_hint()
            return 2
    else:
        name = argv[0] if len(argv) >= 1 else ""
        if len(argv) >= 2:
            try:
                radius = float(argv[1])
            except ValueError:
                radius = 0.0
        if not name.strip():
            name = input("Название населённого пункта: ").strip()
        if not name:
            print("Пустое название.")
            return 2
        box = geocode_city(name)
        if box is None:
            _manual_hint()
            return 2
        box = expand_box(box, radius)

    print(f"Бокс: lat {box[0]:.4f}..{box[1]:.4f}  lon {box[2]:.4f}..{box[3]:.4f}",
          flush=True)
    print("Качаю карту из открытой базы OpenStreetMap. Небольшой город — пара "
          "минут; область — заметно дольше. О ходе буду сообщать.", flush=True)

    os.makedirs(IN_DIR, exist_ok=True)
    out = os.path.join(IN_DIR, "data.osm")
    if os.path.exists(out):
        os.remove(out)
    if not download_box(box, out):
        return 1
    mb = os.path.getsize(out) / (1024 * 1024)
    print(f"Готово: {out} ({mb:.1f} МБ)", flush=True)
    print("Теперь запусти convert.py", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
