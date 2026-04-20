@echo off
REM Quick launcher for local FastAPI development from the project root.
cd /d "%~dp0"
echo Starting Parking Helper API...
python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
pause
