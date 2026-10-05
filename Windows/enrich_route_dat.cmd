@echo off
rem enrich_route_dat.cmd - добавление типированных точек (pt.residence, pt.path, pt.intersection, pt.transport) и направлений улиц (view) в out\route.dat из In\data.osm.
rem Запускается автоматически из convert.cmd. Можно запустить и отдельно, если уже есть In\data.osm и out\route.dat.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enrich_route_dat.ps1"
echo.
pause
