@echo off
REM Quick launcher for the local admin dashboard with basic env validation.
cd /d "%~dp0"
REM Admin-only Streamlit (localhost).
REM Set ADMIN_PANEL_PASSWORD before running, or add admin_panel_password to .streamlit/secrets.toml.
REM Must match LIVE_ADMIN_SECRET on the API if you set it there.
if "%API_URL%"=="" set API_URL=http://127.0.0.1:8000
if "%ADMIN_PANEL_PASSWORD%"=="" (
  echo ADMIN_PANEL_PASSWORD is not set.
  echo Set it in this terminal first, for example:
  echo   set ADMIN_PANEL_PASSWORD=your-strong-password
  echo Or add admin_panel_password to .streamlit\secrets.toml
  pause
  exit /b 1
)
echo Starting admin panel on http://127.0.0.1:8502 ...
streamlit run admin/admin_app.py --server.port 8502 --server.address 127.0.0.1
pause
