@echo off
rem osm2nav.cmd — запуск конвертера в один шаг.
rem Двойной клик или из консоли: введи город — дальше всё само, результат ниже.
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "ARGS=%*"
if not "%ARGS%"=="" (
    "%~dp0osm2nav.exe" %ARGS%
) else (
    echo OSM -^> LoadStone + DotWalker
    echo.
    set /p "CITY=Название населённого пункта: "
    set /p "RAD=Радиус вокруг города в км (Enter — без расширения): "
    if defined RAD (
        "%~dp0osm2nav.exe" "!CITY!" !RAD!
    ) else (
        "%~dp0osm2nav.exe" "!CITY!"
    )
)
echo.
pause
