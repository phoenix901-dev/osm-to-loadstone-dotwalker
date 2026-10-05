# enrich_route_dat.ps1 - обогащение out\route.dat типированными точками для DotWalker.
# Читает In\data.osm (свежую загрузку get_osm.ps1) и текущий out\route.dat (из convert.cmd),
# добавляет к плоским точкам pt.residence / pt.path / pt.intersection / pt.transport и view-линии
# (направления улиц). Запускается автоматически из convert.cmd.
# Без Python: только встроенный в Windows PowerShell.
$ErrorActionPreference = 'Stop'
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$osmPath = Join-Path $scriptDir 'In\data.osm'
$routePath = Join-Path $scriptDir 'out\route.dat'

if (-not (Test-Path $osmPath)) {
    Write-Host 'Нет In\data.osm - сначала запусти get_osm.cmd.'
    exit 1
}
if (-not (Test-Path $routePath)) {
    Write-Host 'Нет out\route.dat - сначала запусти convert.cmd.'
    exit 1
}

function Fmt([double]$v) { return $v.ToString('0.######', $inv) }

function Get-Bearing([double]$lat1, [double]$lon1, [double]$lat2, [double]$lon2) {
    $r = [Math]::PI / 180.0
    $lat1r = $lat1 * $r; $lat2r = $lat2 * $r
    $dlon = ($lon2 - $lon1) * $r
    $y = [Math]::Sin($dlon) * [Math]::Cos($lat2r)
    $x = [Math]::Cos($lat1r) * [Math]::Sin($lat2r) - [Math]::Sin($lat1r) * [Math]::Cos($lat2r) * [Math]::Cos($dlon)
    $deg = [Math]::Atan2($y, $x) * 180.0 / [Math]::PI
    return [int](($deg + 360.0) % 360.0)
}

# --- вывод улицы для домов без тега addr:street ---
# В OSM многие дома имеют только номер (addr:housenumber) без addr:street. Такую улицу
# определяем по положению: ближайшая улица с названием в пределах ~90 м.
$cellDeg = 0.0015   # размер ячейки сетки (~100-150 м) - для быстрого поиска
$streetGrid = @{}   # "cai_coi" -> список отрезков @{ n; la1; lo1; la2; lo2 }

function Add-StreetSeg($name, [double]$la1, [double]$lo1, [double]$la2, [double]$lo2) {
    if ($la1 -eq $la2 -and $lo1 -eq $lo2) { return }
    $minLa = [Math]::Min($la1, $la2); $maxLa = [Math]::Max($la1, $la2)
    $minLo = [Math]::Min($lo1, $lo2); $maxLo = [Math]::Max($lo1, $lo2)
    $cai0 = [int][Math]::Floor($minLa / $cellDeg); $cai1 = [int][Math]::Floor($maxLa / $cellDeg)
    $coi0 = [int][Math]::Floor($minLo / $cellDeg); $coi1 = [int][Math]::Floor($maxLo / $cellDeg)
    for ($a = $cai0; $a -le $cai1; $a++) {
        for ($o = $coi0; $o -le $coi1; $o++) {
            $key = "$a`_$o"
            if (-not $streetGrid.ContainsKey($key)) { $streetGrid[$key] = New-Object System.Collections.ArrayList }
            [void]$streetGrid[$key].Add(@{ n = $name; la1 = $la1; lo1 = $lo1; la2 = $la2; lo2 = $lo2 })
        }
    }
}

function Get-NearestStreet([double]$lat, [double]$lon) {
    # Название ближайшей улицы в пределах 90 м, иначе $null.
    $cai = [int][Math]::Floor($lat / $cellDeg); $coi = [int][Math]::Floor($lon / $cellDeg)
    $best = $null; $bestD = 90.0
    $mLat = [Math]::Cos($lat * [Math]::PI / 180.0)
    for ($da = -1; $da -le 1; $da++) {
        for ($do = -1; $do -le 1; $do++) {
            $key = "$($cai + $da)`_$($coi + $do)"
            if (-not $streetGrid.ContainsKey($key)) { continue }
            foreach ($s in $streetGrid[$key]) {
                $dx = $s.la2 - $s.la1; $dy = $s.lo2 - $s.lo1
                $l2 = $dx * $dx + $dy * $dy
                if ($l2 -eq 0) { continue }
                $t = (($lat - $s.la1) * $dx + ($lon - $s.lo1) * $dy) / $l2
                if ($t -lt 0) { $t = 0 } elseif ($t -gt 1) { $t = 1 }
                $plat = $s.la1 + $t * $dx; $plon = $s.lo1 + $t * $dy
                $dlat = ($lat - $plat) * 111320.0
                $dlon = ($lon - $plon) * 111320.0 * $mLat
                $d = [Math]::Sqrt($dlat * $dlat + $dlon * $dlon)
                if ($d -lt $bestD) { $bestD = $d; $best = $s.n }
            }
        }
    }
    return $best
}

Write-Host 'Читаю In\data.osm...'
[xml]$osm = Get-Content -Raw -Encoding UTF8 $osmPath
$root = $osm.osm

# --- проход 1: узлы (id -> lat/lon/tags) ---
$nodes = @{}
foreach ($n in @($root.node)) {
    if ($null -eq $n) { continue }
    $tags = @{}
    foreach ($tg in @($n.tag)) {
        if ($null -ne $tg) { $tags[[string]$tg.k] = [string]$tg.v }
    }
    $nodes[[string]$n.id] = @{ lat = [double]$n.lat; lon = [double]$n.lon; tags = $tags }
}
Write-Host ("Узлов: {0}" -f $nodes.Count)

# --- проход 2: пути. Собираем street/poi по узлам и список путей ---
$nodeStreets = @{}   # id узла -> набор названий улиц (way с highway+name)
$nodePois = @{}      # id узла -> набор названий POI (way с name без highway)
$wayList = New-Object System.Collections.ArrayList
foreach ($w in @($root.way)) {
    if ($null -eq $w) { continue }
    $tags = @{}
    foreach ($tg in @($w.tag)) {
        if ($null -ne $tg) { $tags[[string]$tg.k] = [string]$tg.v }
    }
    $refs = New-Object System.Collections.ArrayList
    foreach ($nd in @($w.nd)) {
        if ($null -ne $nd) { [void]$refs.Add([string]$nd.ref) }
    }
    [void]$wayList.Add(@{ tags = $tags; refs = $refs })
    $nm = $tags['name']
    if ($nm) {
        $isHighway = $tags.ContainsKey('highway')
        if ($isHighway) {
            # Отрезки улиц в сетку: по ним выводим улицу для домов без addr:street.
            $prev = $null
            foreach ($r in $refs) {
                if ($nodes.ContainsKey($r)) {
                    if ($null -ne $prev) {
                        Add-StreetSeg $nm $nodes[$prev].lat $nodes[$prev].lon $nodes[$r].lat $nodes[$r].lon
                    }
                    $prev = $r
                }
            }
        }
        foreach ($r in $refs) {
            if ($isHighway) {
                if (-not $nodeStreets.ContainsKey($r)) { $nodeStreets[$r] = @{} }
                $nodeStreets[$r][$nm] = $true
            } else {
                if (-not $nodePois.ContainsKey($r)) { $nodePois[$r] = @{} }
                $nodePois[$r][$nm] = $true
            }
        }
    }
}

function Get-ResName($tags, $num, [double]$lat, [double]$lon) {
    $st = $tags['addr:street']; $pl = $tags['addr:place']; $nm = $tags['name']
    if ($nm -and $st) { return "$nm, $st $num" }
    if ($st) { return "$st $num" }
    if ($nm) { return $nm }
    if ($pl) { return "$pl $num" }
    # Номер есть, а улицы на доме нет - определяем по ближайшей улице с названием.
    $st2 = Get-NearestStreet $lat $lon
    if ($st2) { return "$st2 $num" }
    return $null
}

# --- residence: дома и POI с адресами ---
$resList = New-Object System.Collections.ArrayList
$resDedup = @{}
function Add-Res($name, $lat, $lon) {
    $key = $name + '|' + ([long]($lat * 1000000)).ToString($inv) + '|' + ([long]($lon * 1000000)).ToString($inv)
    if ($resDedup.ContainsKey($key)) { return }
    $resDedup[$key] = $true
    [void]$resList.Add(@{ name = $name; lat = $lat; lon = $lon })
}
foreach ($v in $nodes.Values) {
    $num = $v.tags['addr:housenumber']
    if (-not $num) { continue }
    $name = Get-ResName $v.tags $num $v.lat $v.lon
    if ($name) { Add-Res $name $v.lat $v.lon }
}
foreach ($w in $wayList) {
    $num = $w.tags['addr:housenumber']
    if (-not $num -or $w.refs.Count -eq 0) { continue }
    $sumLat = 0.0; $sumLon = 0.0; $cnt = 0
    foreach ($r in $w.refs) {
        if ($nodes.ContainsKey($r)) { $sumLat += $nodes[$r].lat; $sumLon += $nodes[$r].lon; $cnt++ }
    }
    if ($cnt -eq 0) { continue }
    $clat = $sumLat / $cnt; $clon = $sumLon / $cnt
    $name = Get-ResName $w.tags $num $clat $clon
    if ($name) { Add-Res $name $clat $clon }
}

# --- path (переходы/светофоры) и transport (остановки) ---
$pathList = New-Object System.Collections.ArrayList
$transportList = New-Object System.Collections.ArrayList
foreach ($v in $nodes.Values) {
    $h = $v.tags['highway']
    if ($h -eq 'crossing') {
        $c = $v.tags['crossing']
        if ($c -eq 'traffic_signals') { $name = 'регулируемый переход' }
        elseif ($c -eq 'uncontrolled' -or $c -eq 'unmarked') { $name = 'нерегулируемый переход' }
        else { $name = 'переход' }
        [void]$pathList.Add(@{ name = $name; lat = $v.lat; lon = $v.lon })
    } elseif ($h -eq 'traffic_signals') {
        [void]$pathList.Add(@{ name = 'сигнал светофора'; lat = $v.lat; lon = $v.lon })
    }
    $isBus = ($h -eq 'bus_stop') -or ($v.tags['public_transport'] -in @('bus_stop', 'stop_position'))
    $rw = $v.tags['railway']
    $isRail = $rw -in @('station', 'halt', 'tram_stop', 'stop')
    if ($isBus -or $isRail) {
        $nm = $v.tags['name']
        if ($nm) { $name = $nm }
        elseif ($isRail) { $name = 'ж/д остановка' }
        else { $name = 'автобусная остановка' }
        [void]$transportList.Add(@{ name = $name; lat = $v.lat; lon = $v.lon })
    }
}

# --- intersection: узлы, где сходятся >=2 улицы с названиями ---
$intersectionList = New-Object System.Collections.ArrayList
foreach ($key in $nodeStreets.Keys) {
    $streets = $nodeStreets[$key]
    if ($streets.Count -lt 2) { continue }
    if (-not $nodes.ContainsKey($key)) { continue }
    $names = @($streets.Keys | Sort-Object)
    $items = New-Object System.Collections.ArrayList
    foreach ($n in ($names | Select-Object -First 2)) { [void]$items.Add($n) }
    if ($nodePois.ContainsKey($key)) {
        foreach ($p in ($nodePois[$key].Keys | Select-Object -First 1)) { [void]$items.Add($p) }
    }
    $name = $items -join ', '
    $v = $nodes[$key]
    [void]$intersectionList.Add(@{ name = $name; lat = $v.lat; lon = $v.lon })
}

# --- view: направления каждого отрезка улиц с названиями ---
$viewList = New-Object System.Collections.ArrayList
foreach ($w in $wayList) {
    $nm = $w.tags['name']
    if (-not $nm -or -not $w.tags.ContainsKey('highway')) { continue }
    $coords = New-Object System.Collections.ArrayList
    foreach ($r in $w.refs) {
        if ($nodes.ContainsKey($r)) { [void]$coords.Add($nodes[$r]) }
    }
    for ($i = 0; $i -lt $coords.Count - 1; $i++) {
        $c1 = $coords[$i]; $c2 = $coords[$i + 1]
        if ($c1.lat -eq $c2.lat -and $c1.lon -eq $c2.lon) { continue }
        $b = Get-Bearing $c1.lat $c1.lon $c2.lat $c2.lon
        [void]$viewList.Add(@{ name = $nm; bearing = $b })
    }
}

# --- сборка: старые плоские pt (нормализуем до 4 точек с запятой) + новые типированные + view ---
$outLines = New-Object System.Collections.ArrayList
foreach ($line in [System.IO.File]::ReadAllLines($routePath)) {
    # берём только плоские pt; - типированные и view на повторном запуске не дублируем
    if ($line -match '^pt;') {
        $t = $line.TrimEnd(';')
        if ($t) { [void]$outLines.Add($t + ';;;;') }
    }
}

$sb = New-Object System.Text.StringBuilder
$nl = "`r`n"
foreach ($line in $outLines) { [void]$sb.Append($line).Append($nl) }
foreach ($p in $resList) { [void]$sb.Append("pt.residence;$($p.name);$(Fmt $p.lat);$(Fmt $p.lon);;;;$nl") }
foreach ($p in $pathList) { [void]$sb.Append("pt.path;$($p.name);$(Fmt $p.lat);$(Fmt $p.lon);;;;$nl") }
foreach ($p in $intersectionList) { [void]$sb.Append("pt.intersection;$($p.name);$(Fmt $p.lat);$(Fmt $p.lon);;;;$nl") }
foreach ($p in $transportList) { [void]$sb.Append("pt.transport;$($p.name);$(Fmt $p.lat);$(Fmt $p.lon);;;;$nl") }
foreach ($v in $viewList) { [void]$sb.Append("view;$($v.name);$($v.bearing);$nl") }

$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($routePath, $sb.ToString(), $enc)

$total = $outLines.Count + $resList.Count + $pathList.Count + $intersectionList.Count + $transportList.Count + $viewList.Count
Write-Host ("Готово: route.dat = {0} строк (плоских {1}, residence {2}, path {3}, intersection {4}, transport {5}, view {6})" -f `
    $total, $outLines.Count, $resList.Count, $pathList.Count, $intersectionList.Count, $transportList.Count, $viewList.Count)
