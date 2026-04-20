# Main user-facing Streamlit app for dashboard, image analysis, reservations, chatbot, and project info.
import os  # API_URL from env (local) or Streamlit Cloud secrets
import streamlit as st  # Web UI framework for dashboard
import requests  # HTTP client for FastAPI calls
import json  # Parse parking status JSON files
import time  # Measure API round trip latency
import io  # Bytes buffer for PIL images
from pathlib import Path  # Locate data directory on disk
from datetime import datetime  # Format dates on dashboard
from PIL import Image, ImageDraw, ImageFont  # Draw bounding boxes on images
import pandas as pd  # Load history CSV for analytics
import altair as alt  # Build charts for analytics page
import numpy as np

from page_auth import clear_auth_state, page_login, page_profile, page_signup, request_nav, sync_auth_user
from page_reserve import page_reserve


def _resolve_api_url():  # Streamlit Cloud: set API_URL in app secrets → your Render API
    try:
        v = st.secrets.get("API_URL")
        if v:
            return str(v).rstrip("/")
    except Exception:
        pass
    return os.environ.get("API_URL", "http://localhost:8000").rstrip("/")


API_URL = _resolve_api_url()  # e.g. https://parking-helper-api.onrender.com
DATA_DIR = Path(__file__).resolve().parent.parent / "data"  # Project data folder path
REPORTING_DIR = DATA_DIR / "reporting"  # Subfolder for per lot history CSVs
REQUEST_TIMEOUT = 30  # Seconds before POST predict fails

VEHICLE_COLORS = {  # Hex colors and labels per COCO vehicle id
    2: ("#FF3B3B", "Car"),  # Car class styling
    3: ("#FFB300", "Motorcycle"),  # Motorcycle class styling
    5: ("#448AFF", "Bus"),  # Bus class styling
    7: ("#B7EE85", "Truck"),  # Truck class styling
}


# ============================================
# SECTION: Page Config & CSS
# Dark theme injection for Streamlit
# ============================================
# • Defines inject_css to push custom HTML into the Streamlit page
# • Styles the app background, sidebar, metrics, buttons, and upload area
# • Hides default Streamlit chrome like header, footer, and main menu
# • Tweaks scrollbars, alerts, and expanders to match the dark theme
# ============================================

def inject_css():  # Push custom CSS into Streamlit page
    # Multiline CSS in st.markdown below; Python forbids # inside raw string lines.
    st.markdown("""
    <style>
    .stApp { background-color: #11131A; color: #F0F0F5; }
    section[data-testid="stSidebar"] {
        background-color: #11131A;
        border-right: 1px solid #2A2D3A;
    }
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown li { color: #8B8FA3; }
    [data-testid="stMetric"] {
        background: #1A1D27;
        border: 1px solid #2A2D3A;
        border-radius: 14px;
        padding: 20px 24px;
        transition: all 0.3s ease;
    }
    [data-testid="stMetric"]:hover {
        border-color: #FF3B3B44;
        box-shadow: 0 0 20px rgba(255, 59, 59, 0.08);
    }
    [data-testid="stMetric"] label {
        color: #8B8FA3 !important;
        font-size: 12px !important;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #F0F0F5 !important;
        font-size: 28px !important;
        font-weight: 800 !important;
    }
    [data-testid="stFileUploader"] {
        background: #1A1D27;
        border: 2px dashed #2A2D3A;
        border-radius: 14px;
        padding: 24px;
    }
    [data-testid="stFileUploader"]:hover { border-color: #FF3B3B66; }
    .stButton > button {
        background: linear-gradient(135deg, #FF3B3B, #CC2F2F) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 12px 24px !important;
        font-weight: 700 !important;
        font-size: 14px !important;
        letter-spacing: 0.5px;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 14px rgba(255, 59, 59, 0.3) !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #FF5252, #FF3B3B) !important;
        box-shadow: 0 6px 24px rgba(255, 59, 59, 0.45) !important;
        transform: translateY(-1px);
    }
    .stRadio > div { gap: 2px !important; }
    .stRadio > div > label {
        background: transparent !important;
        border-radius: 10px !important;
        padding: 10px 16px !important;
        color: #8B8FA3 !important;
        transition: all 0.2s ease;
    }
    .stRadio > div > label[data-checked="true"],
    .stRadio > div > label:hover {
        background: rgba(255, 59, 59, 0.08) !important;
        color: #FF3B3B !important;
    }
    .streamlit-expanderHeader {
        background: #1A1D27 !important;
        border: 1px solid #2A2D3A !important;
        border-radius: 10px !important;
        color: #F0F0F5 !important;
    }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #11131A; }
    ::-webkit-scrollbar-thumb { background: #2A2D3A; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #FF3B3B44; }
    .stAlert { border-radius: 10px !important; border: 1px solid #2A2D3A !important; }
    [data-testid="stDataFrame"] { border: 1px solid #2A2D3A; border-radius: 10px; }
    .landing-shell {
        position: relative;
        overflow: hidden;
        border: 1px solid #2A2D3A;
        border-radius: 22px;
        background:
            radial-gradient(circle at 78% 18%, rgba(110, 117, 255, 0.28), transparent 24%),
            radial-gradient(circle at 18% 0%, rgba(255, 59, 59, 0.18), transparent 20%),
            linear-gradient(180deg, #12131A 0%, #11131A 100%);
        padding: 26px 26px 32px 26px;
        margin-bottom: 24px;
    }
    .landing-topbar {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:16px;
        padding: 10px 6px 22px 6px;
        border-bottom: 1px solid rgba(255,255,255,0.04);
        margin-bottom: 30px;
    }
    .landing-brand {
        font-size: 20px;
        font-weight: 800;
        letter-spacing: -0.4px;
        color: #F0F0F5;
    }
    .landing-links {
        display:flex;
        gap:18px;
        flex-wrap:wrap;
        justify-content:center;
        font-size:12px;
        color:#8B8FA3;
    }
    .landing-pill {
        background: #F5F6FA;
        color: #11131A;
        padding: 10px 16px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 700;
        box-shadow: 0 10px 30px rgba(0,0,0,0.24);
    }
    .landing-grid {
        display:grid;
        grid-template-columns: 1.25fr 0.8fr 1.05fr;
        gap: 14px;
        align-items: stretch;
    }
    .landing-hero-copy {
        padding: 14px 12px 14px 6px;
    }
    .landing-kicker {
        display:inline-block;
        font-size:11px;
        font-weight:700;
        letter-spacing:1px;
        text-transform:uppercase;
        color:#FF8DA1;
        margin-bottom:16px;
    }
    .landing-title {
        font-size: 42px;
        line-height: 1.08;
        letter-spacing: -1.2px;
        color: #F0F0F5;
        font-weight: 800;
        margin-bottom: 16px;
        max-width: 420px;
    }
    .landing-copy {
        max-width: 420px;
        color: #8B8FA3;
        font-size: 14px;
        line-height: 1.7;
        margin-bottom: 22px;
    }
    .landing-card {
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 16px;
        background: rgba(17, 19, 26, 0.82);
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.25);
    }
    .landing-metric-card {
        padding: 18px;
        background:
            radial-gradient(circle at top left, rgba(122, 93, 255, 0.36), transparent 35%),
            linear-gradient(180deg, rgba(59,73,255,0.92), rgba(56,68,180,0.82));
        min-height: 186px;
    }
    .landing-metric-label {
        color: rgba(255,255,255,0.82);
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 10px;
    }
    .landing-metric-value {
        color: white;
        font-size: 62px;
        line-height: 1;
        font-weight: 800;
        margin-bottom: 8px;
        letter-spacing: -1px;
    }
    .landing-metric-sub {
        color: rgba(255,255,255,0.82);
        font-size: 12px;
        line-height: 1.6;
        margin-bottom: 18px;
        max-width: 180px;
    }
    .landing-chart-card {
        padding: 16px 18px 14px 18px;
        min-height: 186px;
    }
    .landing-chart-title {
        color:#F0F0F5;
        font-size:15px;
        font-weight:700;
        margin-bottom:4px;
    }
    .landing-chart-copy {
        color:#8B8FA3;
        font-size:12px;
        margin-bottom:16px;
    }
    .landing-chart-box {
        height: 112px;
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 12px;
        background:
            linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)),
            radial-gradient(circle at 35% 35%, rgba(255, 95, 152, 0.20), transparent 32%);
        position: relative;
        overflow: hidden;
    }
    .landing-chart-box::before {
        content:"";
        position:absolute;
        inset:0;
        background:
            linear-gradient(to top, transparent 23%, rgba(255,255,255,0.08) 24%, transparent 25%, transparent 48%, rgba(255,255,255,0.08) 49%, transparent 50%, transparent 73%, rgba(255,255,255,0.08) 74%, transparent 75%);
    }
    .landing-chart-box::after {
        content:"";
        position:absolute;
        left:10px;
        right:10px;
        bottom:12px;
        height:72px;
        border-radius: 999px 999px 10px 10px;
        background: linear-gradient(90deg, rgba(71,122,255,0.92), rgba(255,84,140,0.88));
        clip-path: polygon(0 18%, 14% 8%, 28% 65%, 46% 46%, 60% 64%, 78% 70%, 100% 92%, 100% 100%, 0 100%);
        opacity:0.95;
    }
    .landing-chart-dot {
        position:absolute;
        width:10px;
        height:10px;
        border-radius:50%;
        background:#FF67A8;
        top:22px;
        left:58%;
        box-shadow: 0 0 0 5px rgba(255, 103, 168, 0.12);
    }
    .landing-feature-row {
        display:grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
        margin-top: 18px;
    }
    .landing-feature-card {
        background: rgba(13, 15, 22, 0.88);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 14px;
        padding: 18px;
        min-height: 132px;
    }
    .landing-feature-title {
        color:#F0F0F5;
        font-size:16px;
        font-weight:700;
        margin-bottom:10px;
    }
    .landing-feature-copy {
        color:#8B8FA3;
        font-size:13px;
        line-height:1.65;
    }
    .landing-footer {
        margin-top: 22px;
        padding: 26px 28px;
        border-radius: 18px;
        background:
            radial-gradient(circle at 12% 10%, rgba(126, 198, 255, 0.28), transparent 24%),
            linear-gradient(135deg, #F2F5F9, #F8FAFD);
        color:#11131A;
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:18px;
        flex-wrap:wrap;
    }
    .landing-footer-title {
        font-size: 16px;
        font-weight: 800;
        margin-bottom: 8px;
        color:#141722;
    }
    .landing-footer-copy {
        font-size: 14px;
        max-width: 360px;
        line-height: 1.6;
        color:#4B5162;
    }
    @media (max-width: 980px) {
        .landing-grid, .landing-feature-row {
            grid-template-columns: 1fr;
        }
        .landing-title {
            font-size: 34px;
        }
        .landing-topbar {
            align-items:flex-start;
            flex-direction:column;
        }
    }
    </style>
    """, unsafe_allow_html=True)  # Render first style block as HTML
    # Second small style block for progress bar font
    st.markdown("""
    <style>
    font-face { font-family: 'Segoe UI', system-ui, sans-serif; }
    .stProgress > div > div > div {
        background: linear-gradient(90deg, #FF3B3B, #FF5252) !important;
    }
    </style>
    """, unsafe_allow_html=True)  # Render progress bar gradient CSS


# ============================================
# SECTION: Helpers (API, status, predict, draw)
# Shared by Analyse Image and Dashboard
# ============================================
# • check_api_health pings /health so the sidebar can show online or offline
# • load_parking_status reads parking_status.json from the detector
# • get_history_lots lists lots that have CSV history for analytics
# • predict posts an uploaded image to /predict and returns JSON or errors
# • draw_detections draws boxes and labels on the image for the Analyse page
# ============================================

@st.cache_data(ttl=30)  # Cache health probe for thirty seconds
def check_api_health():  # Return True if API responds OK
    try:  # Network errors become False
        r = requests.get(f"{API_URL}/health", timeout=5)  # probe backend health
        return r.status_code == 200  # Success if HTTP two hundred
    except Exception:  # Any failure means offline
        return False  # Treat errors as down


@st.cache_data(ttl=10)
def check_detector_status():  # Return running bool and last_update from API
    try:
        r = requests.get(f"{API_URL}/live/status", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"running": False, "last_update": None}


@st.fragment(run_every=10)
def _detector_status_sidebar_fragment():
    status = check_detector_status()
    is_running = status.get("running", False)
    is_stale = status.get("stale", True)
    last_ts = status.get("last_update")

    if is_running:
        if not is_stale:
            st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#1A1D27;border-radius:8px;border:1px solid #2A2D3A;"><div style="width:8px;height:8px;border-radius:50%;background:#B7EE85;box-shadow:0 0 6px #B7EE85;"></div><span style="font-size:12px;color:#8B8FA3;">Detector Live</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#1A1D27;border-radius:8px;border:1px solid #2A2D3A;"><div style="width:8px;height:8px;border-radius:50%;background:#FFB300;box-shadow:0 0 6px #FFB300;"></div><span style="font-size:12px;color:#8B8FA3;">Detector Stale</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#1A1D27;border-radius:8px;border:1px solid #2A2D3A;"><div style="width:8px;height:8px;border-radius:50%;background:#FF3B3B;box-shadow:0 0 6px #FF3B3B;"></div><span style="font-size:12px;color:#8B8FA3;">Detector Off</span></div>', unsafe_allow_html=True)

    if last_ts:
        ts = pd.to_datetime(last_ts, unit='s')
        st.caption(f"Update: {ts.strftime('%H:%M:%S')}")


def load_parking_status():  # Read aggregate JSON from detector
    path = DATA_DIR / "parking_status.json"  # written by detection engine
    try:  # File may be missing or invalid
        with open(path, "r") as f:  # Text read JSON file
            return json.load(f)  # Parse to dict
    except (FileNotFoundError, json.JSONDecodeError, IOError):  # Common read failures
        return None  # Signal no data to UI


def get_history_lots():  # List lot ids that have history files
    if not REPORTING_DIR.exists():  # No reporting folder yet
        return []  # Empty analytics choices
    return sorted(f.stem.replace("_history", "") for f in REPORTING_DIR.glob("*_history.csv"))  # Sorted lot names


def predict(uploaded_file):  # POST file to predict endpoint
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type or "image/jpeg")}  # Multipart tuple
    t0 = time.perf_counter()  # measure round-trip time
    try:  # Catch HTTP and network errors
        r = requests.post(f"{API_URL}/predict", files=files, timeout=REQUEST_TIMEOUT)  # Inference request
        elapsed = (time.perf_counter() - t0) * 1000  # Milliseconds elapsed
        if r.status_code == 200:  # OK response
            return r.json(), elapsed, None  # Data and timing without error
        detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text  # Error body
        return None, elapsed, str(detail)  # Propagate API error string
    except requests.exceptions.ConnectionError:  # Server not listening
        return None, (time.perf_counter() - t0) * 1000, "Connection refused"  # Refused message
    except requests.exceptions.Timeout:  # Request too slow
        return None, (time.perf_counter() - t0) * 1000, f"Timed out after {REQUEST_TIMEOUT}s"  # Timeout message
    except Exception as e:  # Any other client error
        return None, (time.perf_counter() - t0) * 1000, str(e)[:200]  # Truncated exception text


def draw_detections(image_bytes, predictions):  # Render boxes on image bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")  # Load PIL image RGB
    draw = ImageDraw.Draw(img)  # Drawing context
    font = ImageFont.load_default()  # Fallback bitmap font
    for path in ["C:\\Windows\\Fonts\\arialbd.ttf", "C:\\Windows\\Fonts\\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:  # Try nicer fonts
        try:  # Font file may be missing
            font = ImageFont.truetype(path, 18)  # Load TTF at size
            break  # Stop on first success
        except (OSError, IOError):  # Missing font path
            pass  # Try next candidate path

    for det in predictions:  # Each API detection dict
        cls_id = det.get("class_id", 2)  # Default to car id
        bbox = det.get("bbox", [0, 0, 0, 0])  # Pixel corners list
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]  # Integer box coords
        color, label = VEHICLE_COLORS.get(cls_id, ("#FF3B3B", "Vehicle"))  # Color and name
        rgb = tuple(int(color.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))  # Hex to RGB tuple

        for i in range(3):  # Thick outline loop
            draw.rectangle([x1-i, y1-i, x2+i, y2+i], outline=rgb)  # Nested rectangles

        label_text = f"{label} ✓"  # Text above box
        try:  # Pillow version may lack textbbox
            text_bbox = draw.textbbox((0, 0), label_text, font=font)  # Measure text box
            tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]  # Width height
        except AttributeError:  # Older Pillow fallback
            tw, th = len(label_text) * 10, 18  # Rough text size

        ly = max(0, y1 - th - 8)  # Label top Y clamped
        draw.rectangle([x1, ly, x1 + tw + 12, y1], fill=rgb)  # Label background bar
        draw.text((x1 + 6, ly + 2), label_text, fill=(255, 255, 255), font=font)  # White text

    buf = io.BytesIO()  # Output byte buffer
    img.save(buf, format="PNG")  # Encode PNG bytes
    return buf.getvalue()  # Raw bytes for st.image


# ============================================
# SECTION: Page — Analyse Image
# Upload, predict, draw boxes, show results
# ============================================
# • Lets the user upload a parking photo and run the API once
# • Caches prediction, image bytes, and timing in session state
# • Shows annotated or raw images with a two-column layout
# • Displays per-vehicle cards with confidence and bbox details
# ============================================

def page_analyse():  # Image upload and inference page
    st.markdown('<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Analyse Image</div>', unsafe_allow_html=True)  # Page title HTML
    st.markdown('<div style="font-size:14px;color:#8B8FA3;margin-bottom:24px;">Upload a parking lot image to detect vehicles</div>', unsafe_allow_html=True)  # Subtitle HTML

    col_left, col_right = st.columns([3, 2])  # Wide left narrow right layout

    with col_left:  # Left column content
        st.markdown('<div style="font-size:16px;font-weight:700;color:#F0F0F5;margin-bottom:12px;">Upload Parking Lot Image</div>', unsafe_allow_html=True)  # Section heading HTML
        uploaded = st.file_uploader("Upload", type=["jpg", "jpeg", "png"], label_visibility="collapsed", key="analyse_upload")  # File widget

        last_fn = st.session_state.get("last_filename", "")  # Previous upload name
        if uploaded and last_fn and uploaded.name != last_fn:  # New file selected
            for k in ["last_prediction", "last_image", "last_filename", "last_elapsed_ms"]:  # Keys to reset
                st.session_state.pop(k, None)  # Clear stale results
        has_results = "last_prediction" in st.session_state  # Boolean cache flag
        pred_list = st.session_state.get("last_prediction", {}).get("prediction") if has_results else []  # Detections list
        last_img = st.session_state.get("last_image")  # Raw bytes last upload

        if has_results and isinstance(pred_list, list) and pred_list and last_img:  # Show annotated
            annotated = draw_detections(last_img, pred_list)  # Draw boxes PNG bytes
            st.image(annotated, use_container_width=True)  # Show result image
        elif uploaded:  # No results yet show raw
            st.image(uploaded, use_container_width=True)  # Show original upload

        analyse_clicked = st.button("🔍 Analyse Parking Lot", use_container_width=True, key="analyse_btn")  # triggers POST /predict

    if analyse_clicked:  # User pressed analyse
        if not uploaded:  # Guard empty upload
            st.warning("Please upload an image first.")  # Prompt user
        else:  # Run inference path
            with st.spinner("Analysing parking lot..."):  # Show busy overlay
                data, elapsed_ms, err = predict(uploaded)  # Call API
                if err:  # Error string returned
                    if "Connection" in err or "refused" in err.lower():  # Cannot reach server
                        st.error("Cannot connect to API.")  # User visible error
                        st.code("python -m uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload", language="bash")  # Help text
                    elif "Timed out" in err or "timeout" in err.lower():  # Slow server
                        st.error("Request timed out.")  # Timeout message
                    else:  # Other API errors
                        st.error(f"API Error: {err}")  # Show detail string
                elif data:  # Successful JSON body
                    st.session_state["last_prediction"] = data  # Cache response dict
                    st.session_state["last_image"] = uploaded.getvalue()  # Cache image bytes
                    st.session_state["last_filename"] = uploaded.name  # Cache filename
                    st.session_state["last_elapsed_ms"] = elapsed_ms  # Cache timing
                    try:  # Toast may fail in some hosts
                        st.toast("Analysis complete!")  # Brief success popup
                    except Exception:  # Ignore toast failures
                        pass  # Non fatal
                    st.rerun()  # Refresh to show right column

    if "last_prediction" in st.session_state:  # Results available to show
        data = st.session_state["last_prediction"]  # Response dict
        elapsed_ms = st.session_state.get("last_elapsed_ms", 0)  # Latency ms
        predictions = data.get("prediction", [])  # List of detections
        total = data.get("total_vehicles", 0)  # Vehicle count

        with col_right:  # Results panel
            verdict_color = "#FF3B3B" if total > 0 else "#B7EE85"  # Red or green theme
            verdict_text = f"OCCUPIED — {total} vehicle{'s' if total != 1 else ''} detected" if total > 0 else "AVAILABLE — No vehicles detected"  # Banner text
            verdict_icon = "Red" if total > 0 else "Green"  # Unused label for semantics

            # Verdict banner HTML block follows
            st.markdown(f"""
            <div style="background:{verdict_color}11;border:1px solid {verdict_color}33;border-radius:12px;padding:20px;text-align:center;margin-bottom:16px;">
                <div style="font-size:16px;font-weight:700;color:{verdict_color};letter-spacing:0.5px;">{verdict_text}</div>
            </div>
            """, unsafe_allow_html=True)  # Render verdict strip

            st.metric("Total Vehicles Detected", total)  # Big number summary

            for det in predictions:  # One card per detection
                cls_id = det.get("class_id", 2)  # Class id with default car
                color, label = VEHICLE_COLORS.get(cls_id, ("#FF3B3B", "Vehicle"))  # Theme for row
                bbox = det.get("bbox", [0, 0, 0, 0])  # Corner list for display

                # Per-detection card HTML block follows
                st.markdown(f"""
                <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:10px;padding:14px;margin-bottom:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <div style="width:10px;height:10px;border-radius:50%;background:{color};"></div>
                            <span style="font-size:14px;font-weight:600;color:#F0F0F5;">{label}</span>
                        </div>
                        <span style="font-size:12px;font-weight:700;color:#B7EE85;">✅ Detected</span>
                    </div>
                    <div style="font-size:10px;color:#5A5E72;margin-top:6px;">bbox: [{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]</div>
                </div>
                """, unsafe_allow_html=True)  # Render one detection card

            st.caption(f"Response: {elapsed_ms:.0f}ms")  # Latency caption
            with st.expander("View Raw API Response"):  # Collapsible JSON
                st.json(data)  # Pretty print response dict


# ============================================
# SECTION: Page — Dashboard
# Read JSON, show lot cards
# ============================================
# • Loads live parking_status.json from the running detector
# • Shows empty-state help when no JSON file exists yet
# • Sums totals across lots and shows per-lot cards with spot chips
# • Renders occupancy bars and percent full for each lot
# ============================================

def page_dashboard():  # Live status JSON driven view
    st.markdown('<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Dashboard</div>', unsafe_allow_html=True)  # Title
    
    # Live Status Banner
    status_info = check_detector_status()
    if status_info.get("running") and not status_info.get("stale"):
        st.success("🛰️ System is LIVE — results are updated in real-time.")
    elif status_info.get("running") and status_info.get("stale"):
        st.warning("🟠 System is ACTIVE but data is STALE. Check engine stream.")
    else:
        st.error("🔴 Detection Engine is OFFLINE. Showing last known state.")

    st.markdown('<div style="font-size:14px;color:#8B8FA3;margin-bottom:24px;">Real-time parking lot monitoring</div>', unsafe_allow_html=True)  # Subtitle

    now = datetime.now().strftime("%Y-%m-%d")  # Today date string
    st.markdown(f'<div style="float:right;background:#1A1D27;border:1px solid #2A2D3A;border-radius:10px;padding:8px 16px;font-size:13px;color:#8B8FA3;">{now}</div>', unsafe_allow_html=True)  # Date badge
    st.markdown("<div style='clear:both;'></div>", unsafe_allow_html=True)  # Clear float layout

    status = load_parking_status()  # Read JSON dict or None
    if not status:  # Empty state
        # Multiline empty state HTML in next st.markdown
        st.markdown("""
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:14px;padding:48px;text-align:center;">
            <div style="font-size:48px;margin-bottom:16px;">🅿️</div>
            <div style="font-size:18px;font-weight:600;color:#F0F0F5;margin-bottom:8px;">No Live Data Available</div>
            <div style="font-size:14px;color:#8B8FA3;">Start the detection engine to see real-time parking status.<br>Or switch to <b style="color:#FF3B3B;">Analyse Image</b> to test with a single photo.</div>
        </div>
        """, unsafe_allow_html=True)  # Render empty state card
        return  # Stop dashboard layout

    m1, m2, m3, m4 = st.columns(4)  # Four summary metrics
    lots = list(status.keys())  # Lot id strings
    total_spots = sum(s["total_spots"] for s in status.values())  # Sum capacities
    available = sum(s["empty_spots"] for s in status.values())  # Sum empty
    occupied = sum(s["occupied_spots"] for s in status.values())  # Sum occupied

    m1.metric("Total Lots", len(lots))  # Count of lots
    m2.metric("Total Spots", total_spots)  # Global capacity
    m3.metric("Available Now", available, delta="open", delta_color="normal")  # Open spots metric
    m4.metric("Occupied Now", occupied, delta_color="inverse")  # Occupied metric

    for lot_id, lot_data in status.items():  # Card per lot
        occ_pct = lot_data["occupied_spots"] / max(lot_data["total_spots"], 1) * 100  # Percent full
        badges = ""  # Accumulate HTML badge string
        for spot_id, sp_status in sorted(lot_data.get("spots", {}).items(), key=lambda x: (len(x[0]), x[0])):  # Sorted spots
            color = "#FFFFFF" if sp_status == "empty" else "#8B5CF6"  # Badge colors
            icon = "✓" if sp_status == "empty" else "✗"  # Status icon
            badges += f'<span style="background:{color}22;color:{color};padding:3px 10px;border-radius:8px;margin:2px;display:inline-block;font-size:11px;font-weight:600;border:1px solid {color}33;">{spot_id} {icon}</span>'  # Append chip

        # Lot summary card HTML block follows
        st.markdown(f"""
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:14px;padding:24px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                <div>
                    <div style="font-size:18px;font-weight:700;color:#F0F0F5;">{lot_id}</div>
                    <div style="font-size:12px;color:#5A5E72;">Last updated: {lot_data.get('timestamp','—')}</div>
                </div>
                <div style="font-size:24px;font-weight:800;color:#FF3B3B;">{occ_pct:.0f}%</div>
            </div>
            <div style="margin-bottom:16px;">{badges}</div>
            <div style="height:6px;background:#2A2D3A;border-radius:3px;overflow:hidden;">
                <div style="width:{occ_pct}%;height:100%;background:linear-gradient(90deg,#FF3B3B,#FF5252);border-radius:3px;transition:width 0.5s ease;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:8px;">
                <span style="font-size:11px;color:#FFFFFF;">● {lot_data['empty_spots']} Available</span>
                <span style="font-size:11px;color:#8B5CF6;">● {lot_data['occupied_spots']} Occupied</span>
            </div>
        </div>
        """, unsafe_allow_html=True)  # Render lot card block


# ============================================
# SECTION: Page — Analytics (Enhanced)
# Detailed multi-lot dashboard with:
#   - Fleet-level KPI summary row
#   - Per-lot occupancy line charts (all 4 lots)
#   - Cross-lot utilization comparison bar chart
#   - Hourly heatmap across lots
#   - Peak hour detection per lot
#   - Raw data expandable per lot
# ============================================

import altair as alt
import pandas as pd
import numpy as np
from pathlib import Path

def page_analytics():
    st.markdown(
        '<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Analytics</div>',
        unsafe_allow_html=True,
    )

    lots = get_history_lots()

    if not lots:
        st.markdown("""
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:14px;
                    padding:48px;text-align:center;">
            <div style="font-size:18px;font-weight:600;color:#F0F0F5;margin-bottom:8px;">
                No Historical Data Available</div>
            <div style="font-size:14px;color:#8B8FA3;">
                Run the detection engine to start collecting analytics.</div>
        </div>""", unsafe_allow_html=True)
        return

    # ── Load all lot DataFrames ────────────────────────────────────────
    lot_dfs: dict[str, pd.DataFrame] = {}
    lot_capacities: dict[str, int] = {}

    for lot in lots:
        csv_path = REPORTING_DIR / f"{lot}_history.csv"
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if df.empty or "Timestamp" not in df.columns:
            continue
        spot_cols = [c for c in df.columns if c.startswith("SP")]
        if not spot_cols:
            continue
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df = df.dropna(subset=["Timestamp"]).sort_values("Timestamp")
        df["Occupied"]  = df[spot_cols].apply(lambda r: (r == "occupied").sum(), axis=1)
        df["Available"] = df[spot_cols].apply(lambda r: (r == "available").sum(), axis=1)
        df["Pct"]       = df["Occupied"] / len(spot_cols) * 100
        df["Hour"]      = df["Timestamp"].dt.hour
        df["Lot"]       = lot
        cap             = len(spot_cols)

        # ── Skip ghost/test lots (capacity < 5 AND avg occupancy = 0) ──
        if cap < 5 and df["Occupied"].mean() == 0:
            continue

        lot_dfs[lot]        = df
        lot_capacities[lot] = cap

    if not lot_dfs:
        st.warning("History files found but could not be parsed.")
        return

    # ── KPI card helper ────────────────────────────────────────────────
    def kpi_card(label, value, sub="", color="#FF3B3B"):
        return f"""
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:12px;
                    padding:20px 16px;text-align:center;">
            <div style="font-size:12px;color:#8B8FA3;text-transform:uppercase;
                        letter-spacing:0.8px;margin-bottom:6px;">{label}</div>
            <div style="font-size:26px;font-weight:700;color:{color};">{value}</div>
            <div style="font-size:12px;color:#8B8FA3;margin-top:4px;">{sub}</div>
        </div>"""

    # ── Fleet-level KPI row ────────────────────────────────────────────
    st.markdown("### 📊 Fleet Summary")
    total_capacity   = sum(lot_capacities.values())
    all_df           = pd.concat(lot_dfs.values(), ignore_index=True)
    fleet_avg_pct    = all_df.groupby("Timestamp")["Occupied"].sum().mean() / total_capacity * 100
    busiest_lot      = max(lot_dfs, key=lambda l: lot_dfs[l]["Pct"].mean())
    peak_hour_global = all_df.groupby("Hour")["Occupied"].mean().idxmax()

    cols = st.columns(4)
    metrics = [
        ("Total Capacity",    f"{total_capacity} spots", f"Across {len(lot_dfs)} lots",              "#4FC3F7"),
        ("Fleet Avg Occ.",    f"{fleet_avg_pct:.1f}%",   "All lots combined",                        "#FF3B3B"),
        ("Busiest Lot",       busiest_lot,                f"{lot_dfs[busiest_lot]['Pct'].mean():.1f}% avg", "#FF9800"),
        ("Peak Hour (Fleet)", f"{peak_hour_global:02d}:00", "Highest avg demand",                    "#66BB6A"),
    ]
    for col, (lbl, val, sub, clr) in zip(cols, metrics):
        col.markdown(kpi_card(lbl, val, sub, clr), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ───────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "📈 Occupancy Over Time",
        "📊 Lot Comparison",
        "🌡️ Hourly Heatmap",
    ])

    # ════════════════════════════════════════════════════════════════
    # TAB 1 — Per-lot line charts (2×2 grid), Y-axis auto-scaled
    # ════════════════════════════════════════════════════════════════
    with tab1:
        st.markdown("##### Occupancy % over time — one card per lot")
        lot_list = list(lot_dfs.keys())

        for i in range(0, len(lot_list), 2):
            row_cols = st.columns(2)
            for j, lot in enumerate(lot_list[i : i + 2]):
                df       = lot_dfs[lot]
                capacity = lot_capacities[lot]
                avg_pct  = df["Pct"].mean()
                peak_pct = df["Pct"].max()

                # Y-axis: start just below the data minimum, not at 0
                # Trim leading/trailing zeros before scaling Y-axis
                pct_series = df["Pct"]
                first_nonzero = pct_series[pct_series > 0].index.min()
                last_nonzero  = pct_series[pct_series > 0].index.max()
                if pd.notna(first_nonzero) and pd.notna(last_nonzero):
                    trimmed = pct_series.loc[first_nonzero:last_nonzero]
                else:
                    trimmed = pct_series
                y_min = max(0, trimmed.min() - 5)
                y_max = min(100, trimmed.max() + 5)

                with row_cols[j]:
                    st.markdown(f"""
                    <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:10px;
                                padding:12px 16px;margin-bottom:8px;display:flex;
                                justify-content:space-between;align-items:center;">
                        <div>
                            <span style="font-size:15px;font-weight:700;color:#F0F0F5;">{lot}</span>
                            <span style="font-size:12px;color:#8B8FA3;margin-left:8px;">
                                {capacity} spots</span>
                        </div>
                        <div style="display:flex;gap:20px;">
                            <div style="text-align:right;">
                                <div style="font-size:11px;color:#8B8FA3;">Avg</div>
                                <div style="font-size:16px;font-weight:700;color:#FF9800;">
                                    {avg_pct:.1f}%</div>
                            </div>
                            <div style="text-align:right;">
                                <div style="font-size:11px;color:#8B8FA3;">Peak</div>
                                <div style="font-size:16px;font-weight:700;color:#FF3B3B;">
                                    {peak_pct:.1f}%</div>
                            </div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                    chart_df = df[["Timestamp", "Pct", "Occupied", "Available"]].rename(
                        columns={"Timestamp": "time", "Pct": "pct",
                                 "Occupied": "occupied", "Available": "available"}
                    )
                    chart_df = chart_df[chart_df["pct"] > 0].reset_index(drop=True)

                    threshold_df = pd.DataFrame({
                        "time": [chart_df["time"].min(), chart_df["time"].max()],
                        "pct":  [80, 80],
                    })

                    base = alt.Chart(chart_df)

                    area = base.mark_area(
                        color="#FF3B3B", opacity=0.15, interpolate="monotone", clip=True
                    ).encode(
                        x=alt.X("time:T", title=None,
                                axis=alt.Axis(gridColor="#2A2D3A",
                                              labelColor="#8B8FA3", format="%H:%M")),
                        y=alt.Y("pct:Q", title="Occupancy %",
                                scale=alt.Scale(domain=[y_min, y_max], clamp=True),
                                axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3",
                                              titleColor="#8B8FA3")),
                        y2=alt.Y2(datum=y_min),
                        tooltip=[
                            alt.Tooltip("time:T",    title="Time",      format="%Y-%m-%d %H:%M"),
                            alt.Tooltip("pct:Q",     title="Occ %",     format=".1f"),
                            alt.Tooltip("occupied:Q",title="Occupied"),
                            alt.Tooltip("available:Q",title="Available"),
                        ],
                    )

                    line = base.mark_line(
                        color="#FF3B3B", strokeWidth=2, interpolate="monotone"
                    ).encode(
                        x="time:T",
                        y=alt.Y("pct:Q", scale=alt.Scale(domain=[y_min, y_max], clamp=True)),
                        tooltip=[
                            alt.Tooltip("time:T",     title="Time",      format="%Y-%m-%d %H:%M"),
                            alt.Tooltip("pct:Q",      title="Occ %",     format=".1f"),
                            alt.Tooltip("occupied:Q", title="Occupied"),
                            alt.Tooltip("available:Q",title="Available"),
                        ],
                    )

                    thresh = alt.Chart(threshold_df).mark_line(
                        color="#FF9800", strokeDash=[6, 3], strokeWidth=1
                    ).encode(x="time:T", y="pct:Q")

                    chart = (area + line + thresh).properties(height=220).configure_view(
                        strokeWidth=0
                    ).configure_axis(labelFontSize=11)

                    st.altair_chart(chart, use_container_width=True)

                    # ── Spot-level breakdown below each chart ──────────
                    spot_cols_list = [c for c in lot_dfs[lot].columns if c.startswith("SP")]
                    if spot_cols_list:
                        spot_stats = []
                        raw_df = lot_dfs[lot]
                        for sp in spot_cols_list:
                            occ_rate = (raw_df[sp] == "occupied").mean() * 100
                            spot_stats.append({"Spot": sp, "Occ Rate %": round(occ_rate, 1)})
                        spot_df = pd.DataFrame(spot_stats).sort_values("Occ Rate %", ascending=False)

                        spot_bar = alt.Chart(spot_df).mark_bar(
                            cornerRadiusTopLeft=3, cornerRadiusTopRight=3
                        ).encode(
                            x=alt.X("Spot:N", title=None, sort="-y",
                                    axis=alt.Axis(labelColor="#8B8FA3", labelAngle=-45,
                                                  gridColor="#2A2D3A")),
                            y=alt.Y("Occ Rate %:Q", title="Occ Rate %",
                                    scale=alt.Scale(domain=[0, 100]),
                                    axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3",
                                                  titleColor="#8B8FA3")),
                            color=alt.Color(
                                "Occ Rate %:Q",
                                scale=alt.Scale(domain=[0, 50, 80, 100],
                                                range=["#4FC3F7", "#66BB6A", "#FF9800", "#FF3B3B"]),
                                legend=None,
                            ),
                            tooltip=["Spot:N", alt.Tooltip("Occ Rate %:Q", format=".1f")],
                        ).properties(height=140, title=alt.TitleParams(
                            text="Individual Spot Occupancy Rate",
                            color="#8B8FA3", fontSize=12,
                        )).configure_view(strokeWidth=0)

                        st.altair_chart(spot_bar, use_container_width=True)

        st.markdown(
            '<span style="font-size:11px;color:#8B8FA3;">🟠 Dashed line = 80% capacity threshold</span>',
            unsafe_allow_html=True,
        )

    # ════════════════════════════════════════════════════════════════
    # TAB 2 — Grouped bars + cleaner summary table
    # ════════════════════════════════════════════════════════════════
    with tab2:
        st.markdown("##### Average vs Peak occupancy per lot")

        summary_rows = []
        for lot, df in lot_dfs.items():
            summary_rows.append({"Lot": lot, "metric": "Average", "occupied": df["Pct"].mean()})
            summary_rows.append({"Lot": lot, "metric": "Peak",    "occupied": df["Pct"].max()})
        summary_df = pd.DataFrame(summary_rows)

        grouped_bar = (
            alt.Chart(summary_df)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("Lot:N", title="Parking Lot",
                         axis=alt.Axis(labelColor="#8B8FA3", titleColor="#8B8FA3",
                                       gridColor="#2A2D3A", labelAngle=0)),
                y=alt.Y("occupied:Q", title="Occupancy %",
                         scale=alt.Scale(domain=[0, 100]),
                         axis=alt.Axis(gridColor="#2A2D3A", labelColor="#8B8FA3",
                                       titleColor="#8B8FA3")),
                color=alt.Color(
                    "metric:N",
                    scale=alt.Scale(domain=["Average", "Peak"],
                                    range=["#4FC3F7", "#FF3B3B"]),
                    legend=alt.Legend(labelColor="#8B8FA3", titleColor="#8B8FA3",
                                      orient="top-right"),
                ),
                xOffset="metric:N",
                tooltip=["Lot:N", "metric:N",
                          alt.Tooltip("occupied:Q", title="Occupancy %", format=".1f")],
            )
            .properties(height=320)
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(grouped_bar, use_container_width=True)

        st.markdown("##### Utilisation summary table")
        table_rows = []
        for lot, df in lot_dfs.items():
            cap = lot_capacities[lot]
            peak_h = df.groupby("Hour")["Occupied"].mean().idxmax()
            table_rows.append({
                "Lot":           lot,
                "Capacity":      cap,
                "Avg Occupancy": f"{df['Pct'].mean():.1f}%",
                "Peak Occ.":     f"{df['Pct'].max():.1f}%",
                "Peak Hour":     f"{peak_h:02d}:00",
                "Total Readings": len(df),
            })
        st.dataframe(
            pd.DataFrame(table_rows).set_index("Lot"),
            use_container_width=True,
        )

    # ════════════════════════════════════════════════════════════════
    # TAB 3 — Heatmap with all 24 hours filled (no gaps)
    # ════════════════════════════════════════════════════════════════
    with tab3:
        st.markdown("##### Average occupancy % by lot and hour of day")

        all_hours = pd.DataFrame({"Hour": range(24)})
        heat_rows = []
        for lot, df in lot_dfs.items():
            hourly = df.groupby("Hour")["Pct"].mean().reset_index()
            hourly = all_hours.merge(hourly, on="Hour", how="left").fillna(0)
            hourly["Lot"] = lot
            heat_rows.append(hourly)

        heat_df = pd.concat(heat_rows, ignore_index=True)
        heat_df["HourLabel"] = heat_df["Hour"].apply(lambda h: f"{h:02d}:00")

        heatmap = (
            alt.Chart(heat_df)
            .mark_rect(cornerRadius=2)
            .encode(
                x=alt.X("HourLabel:O", title="Hour of Day",
                          sort=[f"{h:02d}:00" for h in range(24)],
                          axis=alt.Axis(labelColor="#8B8FA3", titleColor="#8B8FA3",
                                         labelAngle=-45)),
                y=alt.Y("Lot:N", title="Parking Lot",
                          axis=alt.Axis(labelColor="#8B8FA3", titleColor="#8B8FA3")),
                color=alt.Color(
                    "Pct:Q",
                    title="Avg Occ %",
                    scale=alt.Scale(domain=[0, 50, 80, 100],
                                    range=["#1A1D27", "#4FC3F7", "#FF9800", "#FF3B3B"]),
                    legend=alt.Legend(labelColor="#8B8FA3", titleColor="#8B8FA3"),
                ),
                tooltip=[
                    "Lot:N",
                    alt.Tooltip("HourLabel:O", title="Hour"),
                    alt.Tooltip("Pct:Q",       title="Avg Occ %", format=".1f"),
                ],
            )
            .properties(height=180)
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(heatmap, use_container_width=True)

        st.markdown(
            '<span style="font-size:11px;color:#8B8FA3;">'
            "⬛ No data &nbsp;→&nbsp; 🔵 Low &nbsp;→&nbsp; 🟠 Busy &nbsp;→&nbsp; 🔴 Full</span>",
            unsafe_allow_html=True,
        )

# ============================================
# SECTION: Page — About
# Project info and tech stack
# ============================================
# • Shows a hero banner with the project name and capstone note
# • Displays four step cards that explain the pipeline at a glance
# • Lists the tech stack and model details in a simple HTML table
# ============================================

def page_about():  # Static project information page
    # Hero banner HTML block follows
    st.markdown("""
    <div style="background:linear-gradient(135deg, #1A1D27, #11131A);border:1px solid #2A2D3A;border-radius:16px;padding:40px;text-align:center;margin-bottom:24px;">
        <div style="font-size:48px;margin-bottom:12px;">🅿️</div>
        <div style="font-size:28px;font-weight:800;color:#F0F0F5;letter-spacing:-0.5px;">Parking Helper</div>
        <div style="font-size:14px;color:#8B8FA3;margin-top:8px;">Real-Time Smart Parking Detection System</div>
        <div style="margin-top:16px;display:inline-block;background:#FF3B3B22;color:#FF3B3B;padding:4px 14px;border-radius:8px;font-size:12px;font-weight:600;border:1px solid #FF3B3B33;">AIE1014 Capstone — Cambrian College</div>
    </div>
    """, unsafe_allow_html=True)  # Render hero banner

    steps = [  # Four pipeline steps tuples
        ("📍", "1", "Define Spots", "ROI mapping tool draws parking boundaries"),  # Step one
        ("📸", "2", "Capture", "Camera feeds or uploaded images"),  # Step two
        ("🧠", "3", "Detect", "YOLO26 finds vehicles with bounding boxes"),  # Step three
        ("📊", "4", "Report", "Dashboard shows real-time availability"),  # Step four
    ]
    c1, c2, c3, c4 = st.columns(4)  # Four equal columns
    for col, (icon, n, title, desc) in zip([c1, c2, c3, c4], steps):  # Pair columns with steps
        with col:  # Step card column
            # Step card HTML follows
            st.markdown(f"""
            <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:12px;padding:20px;text-align:center;height:160px;">
                <div style="font-size:28px;margin-bottom:8px;">{icon}</div>
                <div style="font-size:13px;font-weight:700;color:#FF3B3B;margin-bottom:4px;">STEP {n}</div>
                <div style="font-size:14px;font-weight:600;color:#F0F0F5;">{title}</div>
                <div style="font-size:12px;color:#8B8FA3;margin-top:4px;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)  # Render one step card

    st.markdown("---")  # Horizontal rule markdown
    st.markdown("**Tech Stack**")  # Heading markdown
    st.markdown("YOLO26 (Ultralytics), FastAPI, OpenCV, Shapely, Streamlit, Docker, Python 3.10")  # Tech list text
    st.markdown("---")  # Second horizontal rule
    st.markdown("**Model Details**")  # Table section heading

    model_rows = [  # Table rows as pairs
        ("Model", "YOLO26x (Ultralytics)"),  # Model name row
        ("Task", "Vehicle Object Detection"),  # Task row
        ("Classes", "Car, Motorcycle, Bus, Truck"),  # Classes row
        ("Confidence Threshold", "0.15"),  # Threshold row
        ("Inference Resolution", "1920px"),  # Resolution row
        ("Geometry Engine", "Shapely (Polygon IoU)"),  # Geometry row
    ]
    table_html = '<table style="width:100%;border-collapse:collapse;border-radius:10px;overflow:hidden;border:1px solid #2A2D3A;">'  # Open table tag
    table_html += '<tr style="background:#FF3B3B22;color:#FF3B3B;"><th style="padding:12px;text-align:left;font-weight:700;">Field</th><th style="padding:12px;text-align:left;">Value</th></tr>'  # Header row HTML
    for i, (k, v) in enumerate(model_rows):  # Loop rows with index
        bg = "#1A1D27" if i % 2 == 0 else "#22252F"  # Zebra stripe color
        table_html += f'<tr style="background:{bg};"><td style="padding:12px;color:#8B8FA3;">{k}</td><td style="padding:12px;color:#F0F0F5;">{v}</td></tr>'  # Append body row
    table_html += "</table>"  # Close table tag
    st.markdown(table_html, unsafe_allow_html=True)  # Render model table


def page_home():  # Public landing page before authentication
    st.markdown(
        """
        <div style="background:linear-gradient(135deg, #1A1D27, #11131A);border:1px solid #2A2D3A;border-radius:18px;padding:44px;margin-bottom:24px;">
            <div style="font-size:12px;color:#FF3B3B;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:12px;">Parking Helper</div>
            <div style="font-size:34px;font-weight:800;color:#F0F0F5;letter-spacing:-0.8px;line-height:1.15;margin-bottom:12px;">
                Smart parking access starts here.
            </div>
            <div style="font-size:15px;color:#8B8FA3;max-width:700px;line-height:1.7;">
                Sign in or create an account to access live parking availability, reserve a spot, manage your profile,
                and receive reservation confirmations.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    cards = [
        ("Live Access", "View protected parking data only after login for a cleaner and safer flow."),
        ("Fast Reservations", "Reserve available spots from your authenticated account without re-entering your details."),
        ("Profile + Alerts", "Keep your profile updated and receive confirmation emails when configured."),
    ]
    for col, (title, desc) in zip([c1, c2, c3], cards):
        with col:
            st.markdown(
                f"""
                <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:14px;padding:20px;height:170px;">
                    <div style="font-size:16px;font-weight:700;color:#F0F0F5;margin-bottom:10px;">{title}</div>
                    <div style="font-size:13px;color:#8B8FA3;line-height:1.7;">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.info("Use the sidebar to sign in or create an account. Until then, the rest of the frontend stays locked.")


from chatbot import page_chatbot


def main():  # App entry builds layout and routes
    st.set_page_config(page_title="Parking Helper", page_icon="🅿️", layout="wide")  # Streamlit page options
    inject_css()  # Apply custom dark theme
    sync_auth_user(API_URL)  # Restore the signed-in user from the session token when available.

    # ============================================
    # SECTION: Sidebar
    # Branding, API status, navigation
    # ============================================
    # • Renders the logo header and version line at the top
    # • Radio buttons switch between Dashboard, Analyse, Reserve, Chatbot, and About
    # • Shows API online or offline with a colored status pill
    # • Optionally shows total available spots when JSON data exists
    # ============================================

    with st.sidebar:  # Left navigation column
        # Sidebar branding HTML block follows
        st.markdown("""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:24px;">
            <div style="width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,#FF3B3B,#CC2F2F);display:flex;align-items:center;justify-content:center;color:white;font-weight:800;font-size:18px;box-shadow:0 4px 14px rgba(255,59,59,0.3);">P</div>
            <div>
                <div style="font-size:18px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Parking Helper</div>
                <div style="font-size:11px;color:#5A5E72;">v1.0 — Cambrian College</div>
            </div>
        </div>
        """, unsafe_allow_html=True)  # Render sidebar header branding

        auth_user = st.session_state.get("auth_user")
        nav_options = ["Home"]
        if auth_user:
            nav_options.extend(["Dashboard", "Analyse Image", "Reserve a Spot", "My Profile", "Chatbot", "About"])
        else:
            nav_options.extend(["Login", "Sign Up"])

        pending_nav = st.session_state.pop("_nav_target", None)
        if pending_nav in nav_options:
            st.session_state["nav"] = pending_nav

        current_nav = st.session_state.get("nav")
        if current_nav not in nav_options:
            st.session_state["nav"] = nav_options[0]

        page = st.radio("Nav", nav_options, label_visibility="collapsed", key="nav")  # Page selection

        if auth_user:
            st.markdown("---")
            st.markdown(
                f"""
                <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:10px;padding:12px;margin-bottom:10px;">
                    <div style="font-size:11px;color:#8B8FA3;text-transform:uppercase;letter-spacing:0.8px;">Account</div>
                    <div style="font-size:14px;font-weight:700;color:#F0F0F5;margin-top:4px;">{auth_user.get("username", "")}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Logout", use_container_width=True, key="logout_btn"):
                clear_auth_state()
                request_nav("Home")
                st.rerun()

        st.divider()  # Visual separator
        if check_api_health():  # Probe FastAPI
            st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#1A1D27;border-radius:8px;border:1px solid #2A2D3A;"><div style="width:8px;height:8px;border-radius:50%;background:#B7EE85;box-shadow:0 0 6px #B7EE85;"></div><span style="font-size:12px;color:#8B8FA3;">API Online</span></div>', unsafe_allow_html=True)  # Green status HTML
            _detector_status_sidebar_fragment()
        else:  # Health check failed
            st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:#1A1D27;border-radius:8px;border:1px solid #2A2D3A;"><div style="width:8px;height:8px;border-radius:50%;background:#FF3B3B;box-shadow:0 0 6px #FF3B3B;"></div><span style="font-size:12px;color:#8B8FA3;">API Offline</span></div>', unsafe_allow_html=True)  # Red status HTML

        status = load_parking_status()  # Optional aggregate JSON
        if status:  # Data available
            avail = sum(s["empty_spots"] for s in status.values())  # Sum empties
            st.markdown("---")  # Separator before metric
            st.metric("Available Spots", avail)  # Sidebar KPI

        st.divider()  # Footer separator
        st.caption("Cambrian College | AIE1014 Capstone")  # Footer caption

    # ============================================
    # SECTION: Main — route to selected page
    # Dispatch sidebar choice to page functions
    # ============================================
    # • Reads the selected page name from the sidebar radio
    # • Calls exactly one page builder to fill the main area
    # • Uses the About page as the fallback when nothing else matches
    # ============================================

    if not auth_user and page not in {"Home", "Login", "Sign Up"}:
        page = "Home"

    if page == "Home":  # Public landing page selected
        page_home()  # Render home page
    elif page == "Dashboard":  # Dashboard selected
        page_dashboard()  # Render dashboard
    elif page == "Analyse Image":  # Analyse selected
        page_analyse()  # Render analyse page
    elif page == "Reserve a Spot":  # Reserve selected
        page_reserve()  # Render reservation page
    elif page == "Login":  # Login selected
        page_login(API_URL)  # Render login page
    elif page == "Sign Up":  # Sign up selected
        page_signup(API_URL)  # Render sign up page
    elif page == "My Profile":  # Profile selected
        page_profile(API_URL)  # Render profile page
    elif page == "Chatbot":  # Chatbot selected
        page_chatbot()  # Render parking assistant chatbot
    else:  # About or default
        page_about()  # Render about page


if __name__ == "__main__":  # Script entry point
    main()  # Start Streamlit app
