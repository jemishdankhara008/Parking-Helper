# ============================================
# SECTION: Live — latest annotated frame JPEG
# Set LIVE_ADMIN_SECRET so only clients sending X-Admin-Token can read frames.
# If LIVE_ADMIN_SECRET is unset, endpoints stay open (local dev only).
# ============================================

# Live file-serving routes used by the admin and user dashboards for frames, logs, and detector status.
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]
FRAME_PATH = ROOT / "data" / "latest_frame.jpg"
FRAME_PATH_ROI = ROOT / "data" / "latest_frame_roi.jpg"
LOG_PATH = ROOT / "data" / "detector.log"
PID_PATH = ROOT / "data" / "detector.pid"
STATUS_PATH = ROOT / "data" / "parking_status.json"

router = APIRouter(prefix="/live", tags=["live"])


def verify_live_token(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    secret = (os.environ.get("LIVE_ADMIN_SECRET") or "").strip()
    if not secret:
        return
    # A shared header token is enough here because these routes expose machine output, not end-user account data.
    if not x_admin_token or x_admin_token.strip() != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


@router.get("/latest")
def latest_frame(_: None = Depends(verify_live_token)):
    if not FRAME_PATH.is_file():
        raise HTTPException(404, "No frame yet — start detection engine")
    return FileResponse(FRAME_PATH, media_type="image/jpeg", filename="latest_frame.jpg")


@router.get("/latest/path")
def latest_path_info(_: None = Depends(verify_live_token)):
    return {"path": str(FRAME_PATH), "exists": FRAME_PATH.is_file()}


@router.get("/roi/latest")
def latest_frame_roi(_: None = Depends(verify_live_token)):
    if not FRAME_PATH_ROI.is_file():
        raise HTTPException(
            404,
            "No ROI mapper frame yet — run python main/roi/roi_selector_lot11.py (Phase 1 or 2)",
        )
    return FileResponse(
        FRAME_PATH_ROI, media_type="image/jpeg", filename="latest_frame_roi.jpg"
    )


@router.get("/logs")
def get_logs(_: None = Depends(verify_live_token)):
    if not LOG_PATH.is_file():
        return {"logs": "No logs yet."}
    try:
        # Read last 100 lines
        with open(LOG_PATH, "r") as f:
            lines = f.readlines()
            return {"logs": "".join(lines[-100:])}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}


@router.get("/status")
def get_status(_: None = Depends(verify_live_token)):
    # 1. Check PID file
    pid = None
    process_running = False
    if PID_PATH.is_file():
        try:
            import psutil
            pid = int(PID_PATH.read_text().strip())
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                if "python" in p.name().lower():
                    process_running = True
        except Exception:
            pass

    # 2. Check data freshness (parking_status.json)
    file_exists = STATUS_PATH.is_file()
    last_update = os.path.getmtime(STATUS_PATH) if file_exists else None
    
    import time
    # Running if process exists OR file updated in last 30s
    is_fresh = (time.time() - last_update) < 30 if last_update else False
    
    # 3. Read latest metrics if possible
    metrics = {"total": 0, "empty": 0, "occupied": 0}
    if file_exists:
        try:
            import json
            with open(STATUS_PATH, "r") as f:
                data = json.load(f)
                for lot in data.values():
                    metrics["total"] += lot.get("total_spots", 0)
                    metrics["empty"] += lot.get("empty_spots", 0)
                    metrics["occupied"] += lot.get("occupied_spots", 0)
        except Exception:
            pass

    return {
        "running": process_running,
        "stale": not is_fresh if file_exists else True,
        "pid": pid,
        "last_update": last_update,
        "file_exists": file_exists,
        "metrics": metrics
    }
