# Parking Helper

Real-time smart parking detection system for the Cambrian College AIE1014 capstone.

## Active System Flow

The project works in this order and this flow remains unchanged:

`main/main.py` detector  ->  writes JSON/CSV into `data/`  ->  FastAPI reads data  ->  Streamlit admin and user UIs display data

## Core Components

- `main/main.py`: source-of-truth detector that reads configured video sources, detects vehicles, and writes `data/parking_status.json`, `data/parking_status.csv`, and `data/reporting/*_history.csv`
- `main/roi/roi_selector_lot11.py`: ROI mapping tool for generating parking-spot polygons saved into `data/*.csv`
- `api/app.py`: FastAPI backend for health, image prediction, reservations, auth, QR, and live frame access
- `ui/app_ui.py`: Streamlit user UI for dashboard, analyse image, reservations, analytics, and chatbot
- `admin/admin_app.py`: Streamlit admin UI for detector control, live monitoring, logs, and ROI launcher

## Data Files

- `data/parking_lots.csv`: detector configuration with `ParkingLotID`, `Name`, `URL`, and `ROI`
- `data/parking_status.json`: latest per-lot snapshot used by the UI and reservation checks
- `data/parking_status.csv`: latest combined CSV snapshot
- `data/reporting/*_history.csv`: time-series history for analytics
- `data/reservations.db`: SQLite storage for users and reservations

## Requirements

- Python 3.11 recommended
- `pip install -r requirements.txt`
- YOLO weights available in the repo root as `yolov8n.pt` or `yolov8s.pt`

## Environment

Copy `.env.example` to `.env` and set the values you need.

Required for secure operation:

- `JWT_SECRET`
- `ADMIN_PANEL_PASSWORD`
- `LIVE_ADMIN_SECRET` if you want `/live/*` admin protection

Optional:

- `API_URL`
- `OPENAI_API_KEY`
- `CORS_ORIGINS`

## Run The System

### 1. Start the API

```bash
python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
```

Or run `run_api.bat`.

### 2. Start the user UI

```bash
streamlit run ui/app_ui.py
```

### 3. Start the admin UI

Set `ADMIN_PANEL_PASSWORD` first, then run:

```bash
streamlit run admin/admin_app.py --server.port 8502 --server.address 127.0.0.1
```

Or run `run_admin.bat` after setting the password in that terminal.

### 4. Start the detector

```bash
python main/main.py
```

This reads `data/parking_lots.csv` and updates the JSON/CSV files in `data/`.

### 5. Optional helper

`run_all.bat` starts the API, user UI, admin UI, and detector in separate windows.

## ROI Mapping

Run the ROI mapper manually:

```bash
python main/roi/roi_selector_lot11.py
```

Or start it from the admin UI under `Configuration & controls`.

The saved ROI CSV should live under `data/` and match the `ROI` filename in `data/parking_lots.csv`.

## Main API Routes

- `GET /health`
- `GET /info`
- `POST /predict`
- `POST /reserve`
- `GET /reservations`
- `GET /reservations/history`
- `DELETE /reserve/{reservation_id}`
- `GET /available/{lot_id}`
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `PATCH /auth/me`
- `POST /qr/reservation/{reservation_id}`
- `GET /qr/image/{token}`
- `GET /qr/data/{token}`
- `GET /live/latest`
- `GET /live/roi/latest`
- `GET /live/logs`
- `GET /live/status`

## Notes

- `main/main.py` is the detector source of truth.
- The API and Streamlit apps depend on the detector output files in `data/`.
- `data/parking_lots.csv` now uses portable relative paths; adjust the `URL` values to your own local videos or stream URLs as needed.
- The repository may still contain experimental or historical files, but the active runtime flow is the five core files listed above.
