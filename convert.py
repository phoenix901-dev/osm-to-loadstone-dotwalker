#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM -> LoadStone + DotWalker (linux-порт конвейера).
Повторяет 1:1 работу связки Windows-конвертера:
  osm.exe (Sqlite3UsingConverter) -> ReplaceListWord.txt -> route.xml/route.dat
  -> точка в конец имени -> reprocessor (-p3 -n3 -sname) -> loadstone.txt

Запуск:
  python3 convert.py [in/data.osm] [-o out] [-m email]
  (по умолчанию: in/data.osm, выводит в out/, email osm2nav@phoenix901.ru,
   файл замен ReplaceListWord.txt ищется рядом со скриптом)

На выходе в out/: loadstone.txt (LoadStone), route.xml + route.dat (DotWalker).
"""
import sys, os, time, hashlib, argparse

# ---- карта аменити: ключ OSM -> русская подпись (из loadstone.mo) ----
AMENITY_RU = {

    'aerodrome': 'аэродром',
    'arts_centre': 'художественный центр',
    'atm': 'банкомат',
    'attraction': 'достопримечательность',
    'bakery': 'булочная',
    'bank': 'банк',
    'basketball': 'баскетбол',
    'bench': 'скамейка',
    'beverages': 'напитки',
    'bicycle_rental': 'прокат велосипедов',
    'books': 'книги',
    'bureau_de_change': 'обменник',
    'bus_station': 'автовокзал',
    'bus_stop': 'автобусная остановка',
    'cafe': 'кафе',
    'car': 'продажа автомобилей',
    'car_repair': 'автосервис',
    'cemetery': 'кладбище',
    'cinema': 'кино',
    'circus': 'цирк',
    'city': 'город',
    'cityhall': 'городская администрация',
    'clothes': 'одежда',
    'college': 'колледж',
    'computer': 'компьютер',
    'convenience': 'магазин',
    'courthouse': 'суд',
    'crematorium': 'крематорий',
    'crossing': 'перекресток',
    'dentist': 'зубная',
    'doctors': 'поликлиника',
    'doityourself': 'сделай сам',
    'electronics': 'электроника',
    'embassy': 'посольство',
    'fast_food': 'быстрое питание',
    'fire_station': 'пожарная',
    'florist': 'цветы',
    'football': 'футбол',
    'forest': 'лес',
    'fountain': 'фонтан',
    'fuel': 'заправка',
    'furniture': 'мебель',
    'garden': 'сквер',
    'hairdresser': 'парикмахерская',
    'halt': 'платформа',
    'hamlet': 'деревня',
    'hockey': 'хоккей',
    'hospital': 'больница',
    'hotel': 'гостиница',
    'ice_rink': 'каток',
    'industrial': 'промзона',
    'island': 'остров',
    'kindergarten': 'детсад',
    'kiosk': 'киоск',
    'laundry': 'прачечная',
    'level_crossing': 'железнодорожный переезд',
    'library': 'библиотека',
    'mall': 'пешеходная зона',
    'memorial': 'памятник',
    'monument': 'монумент',
    'motel': 'модель',
    'motor': 'авто',
    'museum': 'музей',
    'nightclub': 'ночной клуб',
    'optician': 'оптика',
    'outdoor': 'свежий воздух',
    'park': 'парк',
    'parking': 'стоянка',
    'pharmacy': 'аптека',
    'pier': 'дамба',
    'place_of_worship': 'церковь',
    'playground': 'спортплощадка',
    'police': 'полиция',
    'post_office': 'почта',
    'prison': 'тюрьма',
    'pub': 'бар',
    'public_building': 'издательство',
    'restaurant': 'ресторан',
    'school': 'школа',
    'shoes': 'обувь',
    'shopping_center': 'торговый центр',
    'skating': 'коньки',
    'skiing': 'лыжи',
    'soccer': 'футбол',
    'sports_centre': 'спортивный центр',
    'stadium': 'стадион',
    'station': 'станция',
    'stationery': 'канцелярские товары',
    'studio': 'студия',
    'suburb': 'пригород',
    'subway_entrance': 'вход в метро',
    'supermarket': 'супермаркет',
    'swimming': 'плаванье',
    'telephone': 'телефон',
    'telescope': 'телескоп',
    'tennis': 'тенис',
    'theatre': 'театр',
    'toilets': 'туалет',
    'tower': 'башня',
    'town': 'город',
    'townhall': 'городская администрация',
    'tram_stop': 'трамвайная остановка',
    'university': 'университет',
    'vending_machine': 'автомат по продаже',
    'veterinary': 'Ветеринарная клиника',
    'village': 'поселок',
    'waste_disposal': 'помойка',
    'water_tower': 'водонапорная башня',
    'zoo': 'зоопарк',
}

GUIDELINE = 'Подсказка: %s'          # перевод 'guideline: %s' из каталога

AMENITY_LIST = ('amenity', 'shop', 'railway', 'tourism', 'historic', 'place',
                'aeroway', 'man_made', 'sport', 'leisure')
NAME_LIST = ['name', 'description', 'operator']
SKIP_NAMES = ('FIXME', '(type road name)')
NO_PREFIX = ('common', 'pitch', 'park')


def translate_amenity(a):
    return AMENITY_RU.get(a, a)


def crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xffff
            else:
                crc = (crc << 1) & 0xffff
    return crc


# ---------- геометрия (geocalc.py дословно) ----------
from math import pi, sin, cos, acos, asin, sqrt, atan2, floor, fabs
FLATTENING = 1.0 / 298.257223563
ERAD = 6378.135
EPS = 5e-12
DE2RA = 0.01745329252


def EllipsoidDistance(lat1, lon1, lat2, lon2):
    distance = 0.0
    faz = 0.0
    baz = 0.0
    r = 1.0 - FLATTENING
    if lon1 == lon2 and lat1 == lat2:
        return distance
    lat1 *= DE2RA
    lat2 *= DE2RA
    lon1 *= DE2RA
    lon2 *= DE2RA
    cosy1 = cos(lat1)
    cosy2 = cos(lat2)
    if cosy1 == 0.0:
        cosy1 = 1e-10
    if cosy2 == 0.0:
        cosy2 = 1e-10
    c = 0.0; d = 0.0; e = 0.0; cz = 0.0; c2a = 0.0; sa = 0.0
    sx = 0.0; cx = 0.0; y = 0.0; sy = 0.0; cy = 0.0
    tu1 = r * sin(lat1) / cosy1
    tu2 = r * sin(lat2) / cosy2
    cu1 = 1.0 / sqrt(tu1 * tu1 + 1.0)
    su1 = cu1 * tu1
    cu2 = 1.0 / sqrt(tu2 * tu2 + 1.0)
    x = lon2 - lon1
    distance = cu1 * cu2
    baz = distance * tu2
    faz = baz * tu1
    while fabs(d - x) > EPS:
        sx = sin(x)
        cx = cos(x)
        tu1 = cu2 * sx
        tu2 = baz - su1 * cu2 * cx
        sy = sqrt(tu1 * tu1 + tu2 * tu2)
        cy = distance * cx + faz
        y = atan2(sy, cy)
        sa = distance * sx / sy
        c2a = -sa * sa + 1.0
        cz = faz + faz
        if c2a > 0.0:
            cz = -cz / c2a + cy
        e = cz * cz * 2.0 - 1.0
        c = ((-3.0 * c2a + 4.0) * FLATTENING + 4.0) * c2a * FLATTENING / 16.0
        d = x
        x = ((e * cy * c + cz) * sy * c + y) * sa
        x = (1.0 - c) * x * FLATTENING + lon2 - lon1
    x = sqrt((1.0 / r / r - 1.0) * c2a + 1.0) + 1.0
    x = (x - 2.0) / x
    c = 1.0 - x
    c = (x * x / 4.0 + 1.0) / c
    d = (0.375 * x * x - 1.0) * x
    x = e * cy
    distance = 1.0 - e - e
    distance = ((((sy * sy * 4.0 - 3.0) * distance * cz * d / 6.0 - x) * d / 4.0
                 + cz) * sy * d + y) * c * ERAD * r
    return distance


# ---------- порядок итерации тегов как в Python 2.6 (Windows) ----------
# Референтный движок строил dict {k: v} из <tag> детей, затем итерировал
# tags.iteritems() в порядке хэш-слотов CPython 2.6 (32-битный long). От этого
# зависит, какой из amenity-тегов «победит». Воспроизводим тот же порядок.


def _py2_str_hash32(b):
    # CPython 2 string_hash, обрезанный до 32 бит (Windows long).
    if not b:
        return 0
    x = (b[0] << 7) & 0xFFFFFFFF
    for c in b:
        x = ((1000003 * x) ^ c) & 0xFFFFFFFF
    x = (x ^ len(b)) & 0xFFFFFFFF
    if x == 0xFFFFFFFF:
        x = 0xFFFFFFFE
    return x


def _py2_dict_order(keys):
    """Порядок итерации dict, построенного вставкой keys (в этом порядке),
    в CPython 2.6: lookdict_string probe, рост при fill >= 2/3 таблицы ×4
    (8→32→128…), реинсерт в порядке слотов старой таблицы. Удалений нет."""
    keys = list(dict.fromkeys(keys))

    def place_in(slots, size, k):
        h = _py2_str_hash32(k.encode('ascii'))
        i = h & (size - 1)
        perturb = h
        while slots[i] is not None:
            i = (i * 5 + perturb + 1) & (size - 1)
            perturb >>= 5
        slots[i] = k

    size = 8
    slots = [None] * size
    used = 0
    for k in keys:
        place_in(slots, size, k)
        used += 1
        if used * 3 >= size * 2:  # fill (== used) crossed 2/3
            target = used * 4
            newsize = 8
            while newsize < target:
                newsize *= 2
            old = slots
            size = newsize
            slots = [None] * size
            for kk in old:
                if kk is not None:
                    place_in(slots, size, kk)
    return [s for s in slots if s is not None]


# ---------- конструктор имени (osmconverter.constructName) ----------
def construct_name(tags):
    """tags: итерируемая (k, v) в порядке появления в XML; теги обходятся
    в порядке dict Python 2.6, как в референтном движке."""
    tags = list(tags)
    vals = {}
    for k, v in tags:
        if k is not None and v is not None:
            vals[k] = v
    name = amenity = highway = building = street = address = None
    names = {}
    for k in _py2_dict_order(vals.keys()):
        v = vals[k]
        if k in NAME_LIST:
            names[k] = v
        elif k == 'highway' and v == 'bus_stop':
            amenity = v
        elif k in AMENITY_LIST:
            amenity = v
        elif k == 'tactile_paving' and v == 'yes':
            name = GUIDELINE % name
        elif k == 'highway':
            highway = v
        elif k == 'building':
            building = v
        elif k in ('addr:street', 'street:name'):
            street = v
        elif k in ('addr:housenumber', 'addr:housename', 'street:nr'):
            address = v
    if amenity == 'yes':
        amenity = None
    for s in NAME_LIST:
        if s in names:
            name = names[s]
            break
    if building and (address or street):
        street = '' if street is None else street + ' '
        if address is None:
            address = ''
        name = street + address
    if name:
        name = name.replace('"', "'").replace('\n', ' ').replace('\r', ' ')
        if amenity:
            name = '%s: %s' % (translate_amenity(amenity), name)
    elif amenity and amenity not in NO_PREFIX:
        name = translate_amenity(amenity)
    return name, amenity, building, highway


# ---------- движок: обход XML + перекрёстки ----------
class Converter(object):
    def __init__(self, email, stable_ids=True):
        self.user_id = crc16(email.encode('utf-8'))
        base_env = os.environ.get('CONVERT_BASE_ID')
        self.base_id = int(base_env) if base_env else int(time.time()) - 315360000
        self.cur_id = self.base_id
        self.stable_ids = stable_ids
        self.pois = []          # (name, lat_int, lon_int) в порядке эмиссии
        self.nodes = {}         # osm id -> (lat, lon)
        self.ways_rows = []     # (name, lat, lon) именованных шоссейных way

    def add_poi(self, name, lat, lon):
        self.pois.append((name, int(lat * 10000000.0), int(lon * 10000000.0)))
        self.cur_id += 1

    def poi_id(self, name, lat, lon, index):
        """id точки. Улучшенный режим — стабильный: зависит только от самой
        точки (имя+координаты), а не от времени прогона. Поэтому при обновлении
        базы города одна и та же точка сохраняет id, и LoadStone не плодит
        дубликаты при слиянии. 63-битный хэш: коллизий практически нет.
        Режим --faithful — как в Windows: base_id(время)+порядковый."""
        if not self.stable_ids:
            return self.base_id + index
        raw = ('%d|%d|%s' % (lat, lon, name)).encode('utf-8')
        h = int.from_bytes(hashlib.sha1(raw).digest()[:8], 'big')
        return h & 0x7FFFFFFFFFFFFFFF

    def run(self, source):
        import xml.etree.ElementTree as ET
        context = ET.iterparse(source, events=('start', 'end'))
        context = iter(context)
        event, root = next(context)
        for event, elem in context:
            if event == 'start':
                continue
            if elem.tag == 'node':
                lat = float(elem.get('lat'))
                lon = float(elem.get('lon'))
                name, amenity, building, highway = construct_name(
                    (c.get('k'), c.get('v')) for c in elem)
                if name:
                    self.add_poi(name, lat, lon)
                self.nodes[int(elem.get('id'))] = (lat, lon)
            elif elem.tag == 'way':
                refs = [int(c.get('ref')) for c in elem if c.tag == 'nd']
                name, amenity, building, highway = construct_name(
                    (c.get('k'), c.get('v')) for c in elem if c.tag == 'tag')
                if not name or name in SKIP_NAMES:
                    pass
                elif (building or amenity):
                    ref = refs.pop()
                    if len(refs) > 0 and refs[0] == ref:
                        lat = lon = 0.0
                        for rid in refs:
                            n = self.nodes[rid]
                            lat += n[0]
                            lon += n[1]
                        lat /= len(refs)
                        lon /= len(refs)
                    else:
                        n = self.nodes[ref]
                        lat, lon = n[0], n[1]
                    self.add_poi(name, lat, lon)
                elif highway:
                    for rid in refs:
                        n = self.nodes.get(rid)
                        if n:
                            self.ways_rows.append((name, n[0], n[1]))
            if elem.tag not in ('nd', 'tag'):
                root.clear()
        source.close()
        self.calculate_intersections()

    def calculate_intersections(self):
        self.ways_rows.sort(key=lambda k: (k[1], k[2]))
        prevName = None
        prevLat = prevLon = 0.0
        map1 = []
        for way in self.ways_rows:
            distance = EllipsoidDistance(way[1], way[2], prevLat, prevLon)
            if distance > 0.001:
                map1.append((way[0], way[1], way[2], False))
            elif not way[0] == prevName:
                map1.append((way[0] + ' X ' + prevName, way[1], way[2], True))
            (prevName, prevLat, prevLon) = way
        del self.ways_rows
        map1.sort(key=lambda k: (k[1], k[2], 0 if k[3] else 1))
        map2 = []
        prevLat = prevLon = 0.0
        for r in map1:
            distance = EllipsoidDistance(r[1], r[2], prevLat, prevLon)
            if distance <= 0.001:
                continue
            map2.append(r)
            prevLat, prevLon = r[1], r[2]
        del map1
        map2.sort(key=lambda k: (k[0], k[1], k[2]))
        prevName = None
        prevLat = prevLon = 0.0
        for r in map2:
            distance = EllipsoidDistance(r[1], r[2], prevLat, prevLon)
            if distance <= 0.025 and r[0] == prevName:
                continue
            if r[3]:
                self.add_poi(r[0], r[1], r[2])
        return len(map2)

    def data_text(self):
        """Текст файла osm.exe-вывода: lsdb-шапка + строки 'NAME',… + пустая."""
        header = ['#!lsdb', 'table,point',
                  'name,latitude,longitude,accuracy,satellites,priority,userid,id']
        parts = [h + '\n' for h in header]
        uid = str(self.user_id)
        for i, (name, lat, lon) in enumerate(self.pois):
            parts.append('"%s",%d,%d,1,10,0,%s,%d\n'
                         % (name, lat, lon, uid, self.poi_id(name, lat, lon, i)))
        parts.append('\n')
        return ''.join(parts)


# ---------- reduceClosePoints (dbtools.py дословно) ----------
def reduce_close_points(points, approx_dist, name_must_match):
    if name_must_match:
        points.sort(key=lambda k: (k['lat'], k['lon'], k['name']))
    else:
        points.sort(key=lambda k: (k['lat'], k['lon']))
    count = 0
    result = points
    prev = None
    i = 0
    while i < len(result):
        p = result[i]
        if not prev or (name_must_match and prev['name'].lower() != p['name'].lower()):
            prev = p
            i += 1
            continue
        d = EllipsoidDistance(p['lat'] / 10000000.0, p['lon'] / 10000000.0,
                              prev['lat'] / 10000000.0, prev['lon'] / 10000000.0)
        if round(d, 4) > approx_dist / 1000:
            prev = p
            i += 1
        else:
            del result[i]
            count += 1
    return count


def loadstone_records(dot_lines, n_emit, truncate_long=True):
    """Прочитать dot-inserted lsdb-строки как reprocessor: TextParser.loadTable
    с PointRecord. Возвращает (rows, dropped): строки 3..3+n_emit-1, валидные
    по checkLabel/checkLat/... в порядке строк. Числовые поля идут сразу после
    закрывающей кавычки через запятую.
    Имя >75 символов: в режиме Windows-1:1 запись роняется; улучшенный режим
    (truncate_long=True, по умолчанию) — имя обрезается до 75, точка не теряется."""
    rows = []
    dropped = 0
    for i in range(3, 3 + n_emit):
        line = dot_lines[i]
        q2 = line.find('"', 1)
        name = line[1:q2]
        if len(name) > 75:
            if not truncate_long:
                dropped += 1
                continue
            name = name[:75]
        parts = line[q2 + 1:].split(',')
        # parts[0] == '' (закрывающая кавычка перед первой запятой)
        if len(parts) != 8:
            dropped += 1
            continue
        lat_s, lon_s, acc_s, sat_s, prio_s, uid_s, id_s = parts[1:]
        if not (lat_s.isdigit() and lon_s.isdigit() and acc_s.isdigit()
                and sat_s.isdigit() and prio_s.isdigit() and uid_s.isdigit()
                and id_s.isdigit()):
            dropped += 1
            continue
        lat = int(lat_s)
        lon = int(lon_s)
        prio = int(prio_s)
        if abs(lat / 10000000.0) >= 90 or abs(lon / 10000000.0) >= 180:
            dropped += 1
            continue
        if int(acc_s) > 100 or int(sat_s) > 12 or prio > 7 or not (10 <= int(uid_s) <= 99999):
            dropped += 1
            continue
        rows.append({'name': name, 'lat': lat, 'lon': lon,
                     'accuracy': int(acc_s), 'satellites': int(sat_s),
                     'priority': prio, 'userid': int(uid_s), 'id': int(id_s)})
    return rows, dropped


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('source', nargs='?', default='in/data.osm')
    ap.add_argument('-o', '--out', default='out')
    ap.add_argument('-m', '--email', default='osm2nav@phoenix901.ru')
    ap.add_argument('--replace', default=None,
                    help='файл замен (по умолчанию ReplaceListWord.txt рядом со скриптом)')
    ap.add_argument('--faithful', action='store_true',
                    help='режим Windows 1:1: ронять точки с запятой в имени, '
                         'ронять имена >75 символов, id от времени прогона')
    args = ap.parse_args()
    faithful = args.faithful

    script_dir = os.path.dirname(os.path.abspath(__file__))
    replace_file = args.replace or os.path.join(script_dir, 'ReplaceListWord.txt')
    replace_pairs = []
    if os.path.exists(replace_file):
        with open(replace_file, 'rb') as f:
            raw = f.read().decode('utf-8')
        for line in raw.replace('\r\n', '\n').split('\n'):
            if '=' in line:
                parts = line.split('=')
                replace_pairs.append((parts[0], parts[1]))
    else:
        print('Предупреждение: не найден %s — замена выражений пропущена.' % replace_file)

    print('Читаю %s …' % args.source)
    print('Режим: %s' % ('Windows 1:1 (--faithful)' if faithful else 'улучшенный'))
    conv = Converter(args.email, stable_ids=not faithful)
    inter = conv.run(open(args.source, 'rb'))
    n_emit = len(conv.pois)
    print('POI эмитировано: %d' % n_emit)

    # 1) текст osm.exe-вывода
    data = conv.data_text()
    # 2) ReplaceListWord (как 1.vbs)
    for a, b in replace_pairs:
        data = data.replace(a, b)
    out_lines = data.split('\n')

    # 3) route.xml / route.dat (1.vbs перебор строк 3..UBound-2)
    xml_lines = []
    dat_lines = []
    n_skip = 0
    for i in range(3, len(out_lines) - 2):
        txt2 = out_lines[i]
        if txt2.startswith('"'):
            stn = txt2[1:]
            if '"' in stn:
                ar = txt2.split('",')
                if len(ar) == 2:
                    title = ar[0][1:]
                    rest = ar[1].split(',')
                    lat_s = rest[0]
                    lon_s = rest[1]
                    if len(lat_s) < 7 or len(lon_s) < 7:
                        n_skip += 1
                        continue
                    title_dot = title + '.'
                    lat_f = lat_s[:-7] + '.' + lat_s[-7:]
                    lon_f = lon_s[:-7] + '.' + lon_s[-7:]
                    pxml = ('<Point><Title>' + title_dot + '</Title><Lat>' + lat_f
                            + '</Lat><Lng>' + lon_f
                            + '</Lng><Description></Description></Point>')
                    pdat = ('pt;' + title_dot.replace(';', ' ') + ';' + lat_f
                            + ';' + lon_f + ';;')
                    pxml = pxml.replace('&', ' and ')
                    pdat = pdat.replace('&', ' and ')
                    # Windows-1:1 ронял строку с запятой в названии (76 точек на
                    # Новороссийск); улучшенный режим такую точку сохраняет.
                    if faithful and ',' in pxml:
                        n_skip += 1
                        continue
                    dat_lines.append(pdat)
                    xml_lines.append(pxml)
                # split !=2 -> строка молча теряется (как в 1.vbs)
            else:
                n_skip += 1
        else:
            n_skip += 1

    # 4) точка в конец имени (dot-insert) -> вход reprocessor
    dot = data.replace('",', '.",')
    dot_lines = dot.split('\n')

    # 5) reprocessor: читаем строки (как lsdb point-таблица), дедуп, сортировка
    recs, n_bad = loadstone_records(dot_lines, n_emit, truncate_long=not faithful)
    r1 = reduce_close_points(recs, 3, False)
    r2 = reduce_close_points(recs, 3, True)
    recs.sort(key=lambda k: k['name'])

    os.makedirs(args.out, exist_ok=True)
    # loadstone.txt (writeToBuffer: имя в кавычках, поля в lsdb-порядке)
    with open(os.path.join(args.out, 'loadstone.txt'), 'w', encoding='utf-8',
              newline='') as f:
        f.write('#!lsdb\n')
        f.write('table,point\n')
        f.write('name,latitude,longitude,accuracy,satellites,priority,userid,id\n')
        for r in recs:
            f.write('"%s",%d,%d,%d,%d,%d,%d,%d\n' % (
                r['name'], r['lat'], r['lon'], r['accuracy'], r['satellites'],
                r['priority'], r['userid'], r['id']))
        f.write('\n')
    # route.xml / route.dat (CRLF как в 1.vbs)
    with open(os.path.join(args.out, 'route.xml'), 'w', encoding='utf-8',
              newline='') as f:
        f.write("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><Route>\r\n")
        for x in xml_lines:
            f.write(x + '\r\n')
        f.write('</Route>\r\n')
    with open(os.path.join(args.out, 'route.dat'), 'w', encoding='utf-8',
              newline='') as f:
        for x in dat_lines:
            f.write(x + '\r\n')

    print('route.xml точек: %d' % len(xml_lines))
    print('route.dat строк: %d' % len(dat_lines))
    print('loadstone записей: %d (убрано p:%d n:%d, невалидных строк: %d)'
          % (len(recs), r1, r2, n_bad))
    print('пропущено при сборке route: %d' % n_skip)


if __name__ == '__main__':
    main()
