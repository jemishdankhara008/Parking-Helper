@echo off
REM Convenience launcher that opens the API, user UI, admin UI, and detector in separate terminals.
echo ===================================================
echo Starting all Parking Helper components...
echo ===================================================

echo.
echo Please ensure your Python virtual environment is activated 
echo and dependencies are installed (pip install -r requirements.txt) 
echo before running this script if you have not done so already.
echo.
pause

:: 1. FastAPI Backend
echo [1/4] Starting FastAPI Backend...
start "FastAPI Backend" cmd /k "run_api.bat"

:: 2. Streamlit User UI
echo [2/4] Starting Streamlit User UI...
start "Streamlit User UI" cmd /k "streamlit run ui/app_ui.py"

:: 3. Streamlit Admin Panel
echo [3/4] Starting Streamlit Admin Panel...
start "Streamlit Admin Panel" cmd /k "run_admin.bat"

:: 4. Main Computer Vision Loop
echo [4/4] Starting Computer Vision Loop...
start "Computer Vision Loop" cmd /k "python main/main.py"

echo.
echo ===================================================
echo All components have been launched in separate windows!
echo Keep those windows open to keep the services running.
echo ===================================================
pause
