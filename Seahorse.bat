@echo off
rem Windows: double-click to open Seahorse.
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw seahorse_app.py %*) || (python seahorse_app.py %*)
