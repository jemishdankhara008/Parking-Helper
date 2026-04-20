# Admin: Left sidebar navigation — streams on first two views; full controls on the third.
# Run from project root: streamlit run admin/admin_app.py --server.port 8502 --server.address 127.0.0.1

# Main admin dashboard for detector control, ROI tooling, live previews, and analytics.
import io
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import streamlit as st
from page_analytics import page_analytics

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PARKING_LOTS_CSV = DATA_DIR / "parking_lots.csv"
DETECTOR_SCRIPT = PROJECT_ROOT / "main" / "main.py"
ROI_SCRIPT = PROJECT_ROOT / "main" / "roi" / "roi_selector_lot11.py"

API_URL_KEY = "admin_api_url"


def _api_url() -> str:
    return (st.session_state.get(API_URL_KEY) or os.environ.get("API_URL") or "http://127.0.0.1:8000").rstrip(
        "/"
    )


def _live_headers():
    secret = (os.environ.get("LIVE_ADMIN_SECRET") or "").strip()
    if not secret:
        return {}
    return {"X-Admin-Token": secret}


def _admin_password():
    p = (os.environ.get("ADMIN_PANEL_PASSWORD") or "").strip()
    if p:
        return p
    try:
        return str(st.secrets["admin_panel_password"])
    except Exception:
        return ""


def _show_live_endpoint(path: str, empty_hint: str):
    base = _api_url()
    try:
        r = requests.get(f"{base}{path}", headers=_live_headers(), timeout=8)
        if r.status_code == 200:
            st.image(io.BytesIO(r.content), use_container_width=True)
        elif r.status_code == 401:
            st.warning(
                "API returned 401. Set **LIVE_ADMIN_SECRET** the same on uvicorn and this app."
            )
        elif r.status_code == 404:
            st.info(empty_hint)
        else:
            st.warning(r.text or f"HTTP {r.status_code}")
    except Exception as e:
        st.error(str(e))


LOG_FILE = DATA_DIR / "detector.log"
PID_FILE = DATA_DIR / "detector.pid"


def _proc_alive(proc: Optional[subprocess.Popen]) -> bool:
    if proc is not None and proc.poll() is None:
        return True
    
    # Also check PID file if proc is None (e.g. after refresh)
    if PID_FILE.is_file():
        try:
            import psutil
            pid = int(PID_FILE.read_text().strip())
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                # Ensure it is actually our detector
                if "python" in p.name().lower():
                    return True
        except Exception:
            pass
    return False


def _launch_detector():
    if _proc_alive(st.session_state.get("det_proc")):
        st.warning("Production detector is already running (check PID or process list).")
        return
    if not PARKING_LOTS_CSV.is_file():
        st.error(f"Missing `{PARKING_LOTS_CSV.name}`. Add it under `data/` or upload in **Configuration & controls**.")
        return
    
    # Open log file for appending
    log_file = open(LOG_FILE, "a")
    log_file.write(f"\n--- DETECTOR STARTED AT {pd.Timestamp.now()} ---\n")
    log_file.flush()
    
    # The detector runs in a separate process so the Streamlit admin app stays responsive.
    proc = subprocess.Popen(
        [sys.executable, str(DETECTOR_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        stdout=log_file,
        stderr=log_file,
    )
    st.session_state.det_proc = proc
    
    # Save PID
    PID_FILE.write_text(str(proc.pid))
    
    st.success(f"Started **main/main.py** (PID: {proc.pid}). Logs redirected to data/detector.log.")


def _stop_detector():
    # 1. Try session state
    p = st.session_state.get("det_proc")
    if p and p.poll() is None:
        p.terminate()
        st.session_state.det_proc = None
        if PID_FILE.is_file():
            PID_FILE.unlink()
        st.info("Stopped detector (terminated session process).")
        return

    # 2. Try PID file
    if PID_FILE.is_file():
        try:
            import psutil
            pid = int(PID_FILE.read_text().strip())
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                p.terminate()
                st.info(f"Stopped detector (terminated PID {pid}).")
            PID_FILE.unlink()
            st.session_state.det_proc = None
        except Exception as e:
            st.error(f"Failed to stop via PID file: {e}")
    else:
        st.warning("No detector process or PID file found.")


@st.fragment(run_every=5)
def _detector_status_fragment():
    base = _api_url()
    try:
        r = requests.get(f"{base}/live/status", headers=_live_headers(), timeout=5)
        if r.status_code == 200:
            data = r.json()
            is_running = data.get("running", False)
            is_stale = data.get("stale", True)
            pid = data.get("pid")
            metrics = data.get("metrics", {})

            # 1. Status Bar
            if is_running:
                if is_stale:
                    st.warning(f"🟠 Detector Active (PID {pid}) but DATA IS STALE")
                else:
                    st.success(f"🟢 Detector Active (PID {pid}) — Live data flowing")
            else:
                st.error("🔴 Detector is STOPPED")
            
            # 2. Metrics Row
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Spots", metrics.get("total", 0))
            c2.metric("Empty", metrics.get("empty", 0))
            c3.metric("Occupied", metrics.get("occupied", 0))

            if data.get("last_update"):
                ts = pd.to_datetime(data["last_update"], unit='s')
                st.caption(f"Last detection update: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.error(f"Could not fetch status: {r.status_code}")
    except Exception as e:
        st.caption(f"Status check failed: {e}")


@st.fragment(run_every=5)
def _detector_logs_fragment():
    base = _api_url()
    try:
        r = requests.get(f"{base}/live/logs", headers=_live_headers(), timeout=5)
        if r.status_code == 200:
            logs = r.json().get("logs", "")
            st.text_area("Live Detector Logs (Last 100 entries)", value=logs, height=350, help="Updates automatically every 5 seconds")
            if not logs or "No logs" in logs:
                st.info("Waiting for detector output...")
        else:
            st.error(f"Could not fetch logs: {r.status_code}")
    except Exception as e:
        st.caption(f"Log fetch failed: {e}")


ROI_PID_FILE = DATA_DIR / "roi.pid"


def _launch_roi(video_path: str, csv_name: str, speed: int, load_baseline: bool):
    if _proc_alive(st.session_state.get("roi_proc")):
        st.warning("ROI mapper is already running. Stop it first.")
        return
    
    final_video = video_path.strip()
    
    # Handle uploaded file
    up_vid = st.session_state.get("cfg_up_vid")
    if up_vid:
        temp_vid_path = DATA_DIR / up_vid.name
        with open(temp_vid_path, "wb") as f:
            f.write(up_vid.getbuffer())
        final_video = str(temp_vid_path)

    if not final_video:
        st.error("Enter a video path / URL / folder, or upload a video file.")
        return

    csv_clean = csv_name.strip()
    if not csv_clean.endswith(".csv"):
        csv_clean += ".csv"
    
    cmd = [
        sys.executable,
        str(ROI_SCRIPT),
        "--video",
        final_video,
        "--csv",
        csv_clean,
        "--speed",
        str(int(speed)),
    ]
    if load_baseline:
        cmd.append("--load-baseline")
    else:
        cmd.append("--no-load-baseline")
    
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
    st.session_state.roi_proc = proc
    ROI_PID_FILE.write_text(str(proc.pid))
    
    st.success(f"Started ROI mapper (PID: {proc.pid}). OpenCV window should appear on the server.")


def _stop_roi():
    # 1. Try session state
    p = st.session_state.get("roi_proc")
    if p and p.poll() is None:
        p.terminate()
        st.session_state.roi_proc = None
        if ROI_PID_FILE.is_file():
            ROI_PID_FILE.unlink()
        st.info("Stopped ROI mapper (terminated session process).")
        return

    # 2. Try PID file
    if ROI_PID_FILE.is_file():
        try:
            import psutil
            pid = int(ROI_PID_FILE.read_text().strip())
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                p.terminate()
                st.info(f"Stopped ROI mapper (terminated PID {pid}).")
            ROI_PID_FILE.unlink()
            st.session_state.roi_proc = None
        except Exception as e:
            st.error(f"Failed to stop ROI via PID file: {e}")
    else:
        st.warning("No ROI process or PID file found.")


st.set_page_config(page_title="Parking Helper — Admin", page_icon="🔒", layout="wide")

if "admin_ui_ok" not in st.session_state:
    st.session_state.admin_ui_ok = False
if "det_proc" not in st.session_state:
    st.session_state.det_proc = None
if "roi_proc" not in st.session_state:
    st.session_state.roi_proc = None
if API_URL_KEY not in st.session_state:
    st.session_state[API_URL_KEY] = os.environ.get("API_URL", "http://127.0.0.1:8000")

pw = _admin_password()
if not pw:
    st.error(
        "Set **ADMIN_PANEL_PASSWORD** in the environment, or **admin_panel_password** in `.streamlit/secrets.toml`. "
        "No default admin password is provided anymore."
    )
    st.stop()

if not st.session_state.admin_ui_ok:
    st.markdown("### Admin sign-in")
    entered = st.text_input("Password", type="password")
    if st.button("Sign in"):
        if entered == pw:
            st.session_state.admin_ui_ok = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

st.markdown(
    """
<style>
[data-testid="stSidebar"] { min-width: 19rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { white-space: normal; }
</style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.title("Admin")
    st.markdown("### Pages")
    view = st.radio(
        "Navigate",
        [
            "Live Operations",
            "Live Stream",
            "Analytics",
            "ROI Mapper",
            "Configuration & controls",
        ],
        key="admin_nav",
        label_visibility="collapsed",
    )

if view == "Live Operations":
    st.header("🛰️ Live Operations")
    
    # 1. Live Status Card
    _detector_status_fragment()
    
    st.divider()
    
    # 2. Quick Actions
    st.subheader("System Controls")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🚀 Start System", type="primary", use_container_width=True):
            _launch_detector()
    with c2:
        if st.button("🛑 Stop System", use_container_width=True):
            _stop_detector()
    with c3:
        if st.button("🔄 Restart", use_container_width=True):
            _stop_detector()
            import time
            time.sleep(1)
            _launch_detector()

    st.divider()
    
    # 3. Quick Logs
    st.subheader("Recent Activity")
    _detector_logs_fragment()

elif view == "Live Stream":
    st.subheader("Live stream")
    st.markdown(
        """
**Source:** `python main/main.py` (multiprocess parking monitor).  
**JPEG file:** `data/latest_frame.jpg` (updated ~1×/s while the detector runs).  
**API:** `GET /live/latest` — base URL is set under **Configuration & controls** in the sidebar.

Configure and launch the detector from **Configuration & controls** in the sidebar.
        """
    )
    st.caption(f"Detector process running: **{'yes' if _proc_alive(st.session_state.det_proc) else 'no'}**")

    if hasattr(st, "fragment"):

        @st.fragment(run_every=1)
        def _poll_det():
            _show_live_endpoint(
                "/live/latest",
                "No live frame yet — Ensure the detector is started in 'Live Operations'.",
            )

        _poll_det()
    else:
        _show_live_endpoint("/live/latest", "No frame yet.")
        st.button("Refresh", key="r_det")

elif view == "Analytics":
    page_analytics()

elif view == "ROI Mapper":
    st.subheader("Live stream")
    st.markdown(
        """
**Source:** `python main/roi/roi_selector_lot11.py` (Phase 1 scan or Phase 2 editor).  
**JPEG file:** `data/latest_frame_roi.jpg` (updated ~1×/s while the tool runs).  
**API:** `GET /live/roi/latest`

OpenCV windows appear on this PC. Launch options are under **Configuration & controls** in the sidebar.
        """
    )
    
    roi_active = _proc_alive(st.session_state.get("roi_proc"))
    if roi_active:
        st.success("🟢 ROI Mapper is ACTIVE (OpenCV window should be visible)")
    else:
        st.info("⚪ ROI Mapper is INACTIVE")

    if hasattr(st, "fragment"):

        @st.fragment(run_every=1)
        def _poll_roi():
            _show_live_endpoint(
                "/live/roi/latest",
                "No ROI frame yet — Launch mapper below to start auto-discovery preview.",
            )

        _poll_roi()
    else:
        _show_live_endpoint("/live/roi/latest", "No frame yet.")
        st.button("Refresh", key="r_roi")

else:
    st.header("Configuration & controls")

    st.session_state[API_URL_KEY] = st.text_input(
        "API base URL (for live streams above)",
        value=st.session_state[API_URL_KEY],
        help="FastAPI must expose /live/latest and /live/roi/latest",
    )
    st.caption("Example: `python -m uvicorn api.app:app --host 127.0.0.1 --port 8000`")

    st.divider()

    st.subheader("Production detector (`main/main.py`)")
    st.markdown(
        "No CLI arguments — configuration is **`data/parking_lots.csv`** "
        "(`ParkingLotID`, `URL`, `ROI`)."
    )
    st.code(str(PARKING_LOTS_CSV), language="text")

    if PARKING_LOTS_CSV.is_file():
        try:
            df_pl = pd.read_csv(PARKING_LOTS_CSV)
            st.dataframe(df_pl, use_container_width=True, hide_index=True)
        except Exception as e:
            st.warning(f"Could not preview CSV: {e}")
    else:
        st.warning("**parking_lots.csv** is missing — create it or upload below.")

    up_pl = st.file_uploader("Replace parking_lots.csv", type=["csv"], key="up_parking_lots")
    if up_pl is not None:
        if st.button("Save uploaded file to data/parking_lots.csv", key="save_pl"):
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(PARKING_LOTS_CSV, "wb") as f:
                f.write(up_pl.getbuffer())
            st.success("Saved. Switch view in the sidebar to refresh preview if needed.")
            st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Launch detector", type="primary", use_container_width=True, key="go_det"):
            _launch_detector()
    with c2:
        if st.button("Stop detector", use_container_width=True, key="stop_det"):
            _stop_detector()

    # Log display
    _detector_logs_fragment()
    if st.button("Clear logs", key="clear_logs"):
        if LOG_FILE.is_file():
            LOG_FILE.write_text(f"--- LOGS CLEARED AT {pd.Timestamp.now()} ---\n")
            st.rerun()

    st.divider()

    st.subheader("ROI mapper (`roi_selector_lot11.py`)")
    st.markdown("Same prompts as the interactive CLI, via headless flags.")

    st.markdown("**1 · Video source**")
    video_in = st.text_input(
        "File path, folder of videos, or YouTube URL",
        placeholder=r"e.g. C:\Videos\lot.mp4",
        help="CLI prompt 1",
        key="cfg_video_in",
    )
    up_vid = st.file_uploader(
        "Or upload a video",
        type=["mp4", "avi", "mov", "mkv", "webm"],
        key="cfg_up_vid",
    )

    st.markdown("**2 · Output CSV**")
    csv_out = st.text_input(
        "CSV filename (under main/data/)",
        value="PL11_Smart_Parking_loop.csv",
        key="cfg_csv_out",
    )

    st.markdown("**3 · Existing ROIs (baseline)**")
    csv_for_check = (csv_out.strip() or "out.csv") if csv_out.strip() else "out.csv"
    if not csv_for_check.endswith(".csv"):
        csv_for_check += ".csv"
    roi_data_main = PROJECT_ROOT / "main" / "data" / csv_for_check
    roi_data_root = DATA_DIR / csv_for_check
    exists_hint = roi_data_main.is_file() or roi_data_root.is_file()
    load_bl = st.checkbox(
        "Load existing ROIs as baseline before scanning",
        value=True,
        key="cfg_load_bl",
    )
    if exists_hint:
        st.success(f"Found **{csv_for_check}** — baseline can load if enabled.")
    else:
        st.info(f"No existing **{csv_for_check}** yet.")

    st.markdown("**4 · Scan speed**")
    speed = st.selectbox(
        "Playback speed multiplier",
        options=[1, 2, 3, 5, 10],
        index=1,
        key="cfg_speed",
    )

    r1, r2 = st.columns(2)
    with r1:
        if st.button("Launch ROI mapper", type="primary", use_container_width=True, key="go_roi"):
            _launch_roi(video_in, csv_out, speed, load_bl)
    with r2:
        if st.button("Stop ROI mapper", use_container_width=True, key="stop_roi"):
            _stop_roi()

    st.divider()
    if not (os.environ.get("LIVE_ADMIN_SECRET") or "").strip():
        st.info(
            "Optional: set **LIVE_ADMIN_SECRET** on the API and this machine so `/live/*` requires **X-Admin-Token**."
        )
