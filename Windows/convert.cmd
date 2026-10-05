@echo off
cd /d "%~dp0"
if not exist .\out mkdir .\out
del .\out\*.* /q
if exist .\tmp rd /S /Q .\tmp
md .\tmp
.\conv\1.vbs
.\conv\reprocessor.exe ".\tmp\data.txt" -o ".\out\loadstone.txt" -p3 -n3 -sname > ".\tmp\reprocess.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enrich_route_dat.ps1"
exit
