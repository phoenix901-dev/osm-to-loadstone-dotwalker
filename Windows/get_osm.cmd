@echo off
rem get_osm.cmd - download OSM data without Python (uses built-in PowerShell).
rem Put get_osm.cmd and get_osm.ps1 in the converter folder, run get_osm.cmd.
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0get_osm.ps1" %*
echo.
pause
