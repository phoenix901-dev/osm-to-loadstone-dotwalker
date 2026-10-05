# get_osm.ps1 - замена шага закачки OSM для конвертера LoadStone/DotWalker.
# Без Python: использует только встроенный в Windows PowerShell.
# Кладёт свежий .osm в .\In\data.osm, дальше запускай convert.cmd.
# Качает через Overpass API (он специально для выкачки целых областей, а не
# через обычный OSM API, который режет частые запросы на больших городах).
# Если кусок тяжёл для сервера - сам дробит на четверти, пока не влезет.
# Серверов несколько: занят или не отвечает один - пробует следующий.

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$ua = "get_osm_cmd/1.0 (OSM-Loadstone-Converter)"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$inDir = Join-Path $scriptDir "In"

# Overpass-зеркала. Первый - основной и самый шустрый, остальные запасные.
# kumi убран: он зависает на 90 секунд (не отвечает вообще), это тормозило весь обход.
$script:mirrors = @(
    'https://overpass-api.de/api/interpreter',
    'https://overpass.openstreetmap.fr/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
    'https://overpass.osm.ch/api/interpreter',
    'https://overpass.nchc.org.tw/api/interpreter'
)
# Когда последний раз стучались в каждый сервер - для вежливой паузы
# (Overpass просит не слать больше одного запроса в ~5 секунд на сервер).
$script:lastReq = @{}

# Число с ТОЧКОЙ, а не запятой - иначе русская локаль ломает ссылку на скачивание.
function Num([double]$x) {
    return $x.ToString("0.########", $inv)
}

function Save-Overpass {
    param([string]$base, [string]$query, [string]$outPath, [int]$timeoutSec = 90)
    # Возвращает 'ok' — скачано и есть данные; 'too_big' — запрос тяжеловат (дробить);
    # 'transient' — сервер занят/не отвечает/отдал пустоту (повторить на другом сервере).
    $url = "$base`?data=" + [uri]::EscapeDataString($query)
    try {
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.UserAgent = $ua
        $req.Timeout = $timeoutSec * 1000
        $req.ReadWriteTimeout = $timeoutSec * 1000
        $resp = $req.GetResponse()
        $stream = $resp.GetResponseStream()
        $fs = [System.IO.File]::Create($outPath)
        $stream.CopyTo($fs)
        $fs.Close()
        $stream.Close()
        $resp.Close()
    } catch {
        # GetResponse бросает MethodInvocationException с WebException внутри — берём по GetBaseException().
        $status = $null
        $resp2 = $null
        try {
            $we = $_.Exception.GetBaseException()
            if ($we -is [System.Net.WebException]) { $resp2 = $we.Response }
        } catch {
            $resp2 = $null
        }
        if ($null -ne $resp2) {
            $status = [int]$resp2.StatusCode
            try {
                $rs = $resp2.GetResponseStream()
                if ($null -ne $rs) {
                    $sr = New-Object System.IO.StreamReader($rs)
                    [void]$sr.ReadToEnd()
                    $sr.Close()
                }
            } catch {
                # тело ответа не прочиталось — статус уже известен, это неважно
            }
            $resp2.Close()
        }
        if ($status -eq 400) { return 'too_big' }
        # 429 лимит запросов, 5xx, таймауты, сеть — транзиентное, повторим на другом сервере.
        return 'transient'
    }

    # Overpass отдаёт HTTP 200 даже когда внутри ошибка или пустота — проверяем первые байты файла.
    $head = ''
    try {
        $fs2 = [System.IO.File]::OpenRead($outPath)
        $buf = New-Object byte[] 16384
        $n = $fs2.Read($buf, 0, 16384)
        $fs2.Close()
        if ($n -gt 0) { $head = [System.Text.Encoding]::UTF8.GetString($buf, 0, $n) }
    } catch {
        $head = ''
    }
    if ($head -match '<strong|runtime error|Error') {
        # Сервер занят/перегружен — повторим, а не дробить.
        if ($head -match 'too busy|open64|Dispatcher_Client') { return 'transient' }
        # Сам запрос не успел по времени — кусок тяжеловат, надо дробить.
        if ($head -match 'Query timed out') { return 'too_big' }
        return 'transient'
    }
    # Нет ни одного элемента — мёртвое или устаревшее зеркало отдало пустоту. Идём к следующему.
    if ($head -match '<node |<way |<relation ') { return 'ok' }
    return 'transient'
}

function Get-Tile {
    param([string]$tile, [string]$outPath)
    # Качает один кусок, обходя серверы по кругу.
    # Возвращает 'ok' / 'too_big' (надо дробить) / 'failed' (сдались после повторов).
    $parts = $tile.Split(';')
    $s = [double]$parts[0]
    $n = [double]$parts[1]
    $w = [double]$parts[2]
    $e = [double]$parts[3]
    # Overpass хочет bbox в порядке south,west,north,east.
    $query = "[out:xml][timeout:60];(node($(Num $s),$(Num $w),$(Num $n),$(Num $e));way($(Num $s),$(Num $w),$(Num $n),$(Num $e)););(._;>;);out body;"
    $announced = $false
    for ($pass = 0; $pass -lt 3; $pass++) {
        $split = $false
        foreach ($m in $script:mirrors) {
            # Вежливая пауза: к одному серверу не чаще раза в 5 секунд.
            $key = $m
            if ($script:lastReq.ContainsKey($key)) {
                $el = (Get-Date) - $script:lastReq[$key]
                $need = 5.0 - $el.TotalSeconds
                if ($need -gt 0) { Start-Sleep -Milliseconds ([int]($need * 1000)) }
            }
            if (-not $announced) {
                $announced = $true
                Write-Host "Качаю фрагмент карты. Сервер отвечает обычно 10-60 секунд, иногда до двух минут — если на экране тихо, всё идёт, жди."
            }
            $r = Save-Overpass $m $query $outPath
            $script:lastReq[$key] = Get-Date
            if ($r -eq 'ok') { return 'ok' }
            if ($r -eq 'too_big') {
                if (-not $split) { $split = $true; Write-Host "Фрагмент великоват для сервера — разбиваю его на четыре части." }
            } else {
                if (-not $split) { Write-Host "Сервер занят или не ответил — пробую следующий сервер." }
            }
        }
        if ($split) { return 'too_big' }
        # Все серверы транзиентно отказали (лимит запросов, перегрузка) — ждём подольше
        # и пробуем ещё круг: 5с, потом 15с. Короткие 3с не дают серверу остыть.
        if ($pass -lt 2) {
            $wait = 5 + $pass * 10
            Write-Host ("Все серверы сейчас заняты — это штатно, они сами перезагружаются. Жду {0}с и повторяю фрагмент." -f $wait)
            Start-Sleep -Seconds $wait
        }
    }
    return 'failed'
}

function Get-BoundingBox {
    param([string]$name)
    $q = [uri]::EscapeDataString($name)
    $url = "https://nominatim.openstreetmap.org/search?q=$q&format=json&limit=1"
    try {
        $data = Invoke-RestMethod -Uri $url -UserAgent $ua -TimeoutSec 60
    } catch {
        Write-Host ("Геокодинг не ответил: " + $_.Exception.Message)
        return $null
    }
    if ($null -eq $data -or @($data).Count -eq 0) {
        Write-Host ("Не нашёл населённый пункт: " + $name)
        return $null
    }
    $bb = @($data)[0].boundingbox
    # boundingbox: [minlat, maxlat, minlon, maxlon]
    return @([double]$bb[0], [double]$bb[1], [double]$bb[2], [double]$bb[3])
}

function Expand-Box {
    param([object]$box, [double]$km)
    $minlat = [double]$box[0]
    $maxlat = [double]$box[1]
    $minlon = [double]$box[2]
    $maxlon = [double]$box[3]
    if ($km -le 0) { return $box }
    $lat = ($minlat + $maxlat) / 2.0
    $dlat = $km / 111.32
    $dlon = $km / (111.32 * [Math]::Max(0.2, [Math]::Cos([Math]::PI / 180.0 * $lat)))
    return @(
        [Math]::Max(-90.0, $minlat - $dlat),
        [Math]::Min(90.0, $maxlat + $dlat),
        [Math]::Max(-180.0, $minlon - $dlon),
        [Math]::Min(180.0, $maxlon + $dlon)
    )
}

function Merge-Chunks {
    param([string[]]$paths, [string]$outPath, [object]$box)
    # Быстрое слияние: один .NET-регэксп на весь чанк (работает нативно, не через PowerShell),
    # уникализация по id через HashSet, запись сразу в файл — память ограничена одним чанком.
    # Построчный вариант на Windows PowerShell был в разы медленнее (миллионы вызовов функций).
    $pat = '(?is)<(?<type>node|way|relation)\b(?=[^>]*\bid\s*=\s*"(?<id>\d+)")[^>]*?(?:(?<self>/>)|>(?:(?!</\k<type>>).)*</\k<type>>)'
    $regex = New-Object System.Text.RegularExpressions.Regex($pat)
    $boundsPat = '<bounds[^>]*/>'
    $dedup = New-Object System.Collections.Generic.HashSet[string]
    $sw = New-Object System.IO.StreamWriter($outPath, $false, (New-Object System.Text.UTF8Encoding($false)))
    [void]$sw.Write('<?xml version="1.0" encoding="UTF-8"?>'); [void]$sw.Write("`n")
    [void]$sw.Write('<osm version="0.6" generator="get_osm.ps1">'); [void]$sw.Write("`n")
    $boundsDone = $false
    $count = 0
    $ci = 0
    $totalChunks = $paths.Count

    foreach ($p in $paths) {
        $ci++
        Write-Host ("Собираю базу: обрабатываю фрагмент {0} из {1}. Это тоже занимает немного времени." -f $ci, $totalChunks)
        $text = [System.IO.File]::ReadAllText($p)
        if (-not $boundsDone) {
            $bm = [regex]::Match($text, $boundsPat)
            if ($bm.Success) {
                [void]$sw.Write($bm.Value); [void]$sw.Write("`n")
                $boundsDone = $true
            }
        }
        # Match + NextMatch вместо Matches(): не копим все совпадения в памяти
        # (на больших чанках Matches() съедает сотни МБ на кэше Match-объектов).
        $m = $regex.Match($text)
        $sinceReport = 0
        while ($m.Success) {
            $key = "$($m.Groups['type'].Value):$($m.Groups['id'].Value)"
            if ($dedup.Add($key)) {
                [void]$sw.Write($m.Value); [void]$sw.Write("`n")
                $count++
                $sinceReport++
                if ($sinceReport -ge 200000) {
                    Write-Host ("  Обработано элементов: {0}." -f $count)
                    $sinceReport = 0
                }
            }
            $m = $m.NextMatch()
        }
    }
    # Overpass не отдаёт тег <bounds>, а конвертеру он может быть нужен — ставим общий бокс.
    if (-not $boundsDone -and $null -ne $box) {
        [void]$sw.Write("<bounds minlat=`"$(Num $box[0])`" minlon=`"$(Num $box[2])`" maxlat=`"$(Num $box[1])`" maxlon=`"$(Num $box[3])`"/>"); [void]$sw.Write("`n")
    }
    [void]$sw.Write('</osm>'); [void]$sw.Write("`n")
    $sw.Close()
    Write-Host ("Уникальных элементов: {0}" -f $count)
}

function Download-Box {
    param([object]$box, [string]$outPath)
    $minlat = [double]$box[0]
    $maxlat = [double]$box[1]
    $minlon = [double]$box[2]
    $maxlon = [double]$box[3]

    # Преддробление: очень широкий бокс не просим целиком (он всё равно тяжёл),
    # а сразу режем на куски примерно по полградуса долготы.
    $lonSpan = $maxlon - $minlon
    $initDepth = [Math]::Max(0, [Math]::Ceiling([Math]::Log([Math]::Max(0.001, $lonSpan / 0.5)) / [Math]::Log(2)))

    if ($initDepth -gt 0) {
        $cells = [int][Math]::Pow(4, $initDepth)
        Write-Host ("Область большая — поделю её примерно на {0} фрагментов и скачаю по очереди. Это займёт время, каждый готовый фрагмент буду подтверждать." -f $cells)
    }
    Write-Host "Если сервер занят — программа сама ждёт и пробует снова, ничего нажимать не нужно."

    $tmpDir = [System.IO.Path]::GetTempPath()
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue(@{ tile = "$(Num $minlat);$(Num $maxlat);$(Num $minlon);$(Num $maxlon)"; depth = 0 })
    $chunks = New-Object System.Collections.ArrayList
    $failed = New-Object System.Collections.ArrayList
    $maxDepth = 14
    $attempt = 0

    while ($queue.Count -gt 0) {
        $item = $queue.Dequeue()
        $parts = $item.tile.Split(';')
        $tminlat = [double]$parts[0]
        $tmaxlat = [double]$parts[1]
        $tminlon = [double]$parts[2]
        $tmaxlon = [double]$parts[3]

        if ($item.depth -lt $initDepth) {
            # Преддробление без запроса — просто разрезаем бокс до стартового размера.
            $midlat = ($tminlat + $tmaxlat) / 2.0
            $midlon = ($tminlon + $tmaxlon) / 2.0
            $nd = $item.depth + 1
            $queue.Enqueue(@{ tile = "$(Num $tminlat);$(Num $midlat);$(Num $tminlon);$(Num $midlon)"; depth = $nd })
            $queue.Enqueue(@{ tile = "$(Num $tminlat);$(Num $midlat);$(Num $midlon);$(Num $tmaxlon)"; depth = $nd })
            $queue.Enqueue(@{ tile = "$(Num $midlat);$(Num $tmaxlat);$(Num $tminlon);$(Num $midlon)"; depth = $nd })
            $queue.Enqueue(@{ tile = "$(Num $midlat);$(Num $tmaxlat);$(Num $midlon);$(Num $tmaxlon)"; depth = $nd })
            continue
        }

        $tmp = Join-Path $tmpDir ("tile_{0}.osm" -f $attempt)
        $attempt++
        if (Test-Path $tmp) { Remove-Item $tmp -Force }

        $result = Get-Tile $item.tile $tmp

        if ($result -eq 'ok') {
            [void]$chunks.Add($tmp)
            Write-Host ("Фрагмент скачан. Готовых фрагментов: {0}." -f $chunks.Count)
        } elseif ($result -eq 'too_big') {
            # Куски ещё велики для сервера - делим на 4 четверти и пробуем снова.
            if ($item.depth -ge $maxDepth) {
                [void]$failed.Add($item.tile)
                Write-Host ("Ошибка: кусок {0} не влез в сервер даже после дробления." -f $item.tile)
            } else {
                $midlat = ($tminlat + $tmaxlat) / 2.0
                $midlon = ($tminlon + $tmaxlon) / 2.0
                $nd = $item.depth + 1
                $queue.Enqueue(@{ tile = "$(Num $tminlat);$(Num $midlat);$(Num $tminlon);$(Num $midlon)"; depth = $nd })
                $queue.Enqueue(@{ tile = "$(Num $tminlat);$(Num $midlat);$(Num $midlon);$(Num $tmaxlon)"; depth = $nd })
                $queue.Enqueue(@{ tile = "$(Num $midlat);$(Num $tmaxlat);$(Num $tminlon);$(Num $midlon)"; depth = $nd })
                $queue.Enqueue(@{ tile = "$(Num $midlat);$(Num $tmaxlat);$(Num $midlon);$(Num $tmaxlon)"; depth = $nd })
            }
        } else {
            # Не скачалось даже после кругов по всем серверам — помечаем и идём дальше.
            [void]$failed.Add($item.tile)
            Write-Host ("Ошибка: кусок {0} не скачался даже после повторов." -f $item.tile)
        }
    }

    if ($chunks.Count -eq 0) {
        Write-Host "Скачать не удалось. Проверь интернет и попробуй ещё раз."
        return $false
    }

    Write-Host ("Скачано кусков: {0}" -f $chunks.Count)
    Merge-Chunks -paths $chunks.ToArray() -out $outPath -box $box
    foreach ($c in $chunks) { Remove-Item $c -Force -ErrorAction SilentlyContinue }
    for ($k = 0; $k -lt $attempt; $k++) {
        $p = Join-Path $tmpDir ("tile_{0}.osm" -f $k)
        if (Test-Path $p) { Remove-Item $p -Force -ErrorAction SilentlyContinue }
    }

    if ($failed.Count -gt 0) {
        Write-Host ""
        Write-Host ("ВНИМАНИЕ: {0} кусков не скачались — в этих местах карта будет неполной." -f $failed.Count)
        Write-Host "Координаты первых кусков:"
        for ($i = 0; $i -lt [Math]::Min(5, $failed.Count); $i++) {
            Write-Host ("  " + $failed[$i])
        }
        Write-Host "Просто запусти get_osm.cmd ещё раз — повтор добрает пропущенные куски."
    }
    return $true
}

function Main {
    $argsList = @($args)
    $box = $null
    $radius = 0.0

    if ($argsList.Count -eq 4) {
        # вручную: minlon minlat maxlon maxlat (через ТОЧКУ)
        try {
            $box = @([double]$argsList[1], [double]$argsList[3], [double]$argsList[0], [double]$argsList[2])
        } catch {
            Write-Host "Ожидал 4 числа: minlon minlat maxlon maxlat"
            Write-Host "пример: get_osm.cmd 38.43 55.84 38.47 55.86"
            return
        }
    } else {
        $name = ""
        if ($argsList.Count -ge 1) { $name = [string]$argsList[0] }
        if ($argsList.Count -ge 2) {
            try { $radius = [double]$argsList[1] } catch { $radius = 0.0 }
        }
        if ([string]::IsNullOrWhiteSpace($name)) {
            $name = Read-Host "Название населённого пункта"
        }
        $box = Get-BoundingBox $name
        if ($null -eq $box) {
            Write-Host "Не смог определить координаты. Можно вручную:"
            Write-Host "get_osm.cmd minlon minlat maxlon maxlat"
            Write-Host "пример: get_osm.cmd 38.43 55.84 38.47 55.86"
            return
        }
        $box = Expand-Box $box $radius
    }

    Write-Host ("Бокс: lat {0:F4}..{1:F4}  lon {2:F4}..{3:F4}" -f $box[0], $box[1], $box[2], $box[3])
    Write-Host "Качаю карту из открытой базы OpenStreetMap. Небольшой город — пара минут; область — заметно дольше. О ходе буду сообщать, в конце дам звуковой сигнал."

    [System.IO.Directory]::CreateDirectory($inDir) | Out-Null
    $out = Join-Path $inDir "data.osm"
    if (Test-Path $out) { Remove-Item $out -Force }

    if (-not (Download-Box -box $box -out $out)) {
        try { [console]::Beep(300, 600) } catch {}
        return
    }

    $mb = (Get-Item $out).Length / 1MB
    Write-Host ("Готово: {0} ({1:N1} МБ)" -f $out, $mb)
    Write-Host "Теперь запусти convert.cmd"
    try { [console]::Beep(700, 200); [console]::Beep(900, 250) } catch {}
}

Main @args
