# Live monitor — latest frame from detection engine
# Simple page that streams the latest detector JPEG through the FastAPI live endpoint.
import io
import streamlit as st
import requests


def page_live():
    import app_ui as _a

    base = getattr(_a, "API_URL", "http://localhost:8000")
    st.markdown("### Live Monitor")
    st.caption("Requires `main/main.py` detection loop saving `data/latest_frame.jpg` each second.")
    try:
        # Pulling through the API keeps auth and deployment behavior consistent with the admin dashboard.
        r = requests.get(f"{base}/live/latest", timeout=10)
        if r.status_code == 200:
            st.image(io.BytesIO(r.content), use_container_width=True)
        else:
            st.warning(r.text or f"HTTP {r.status_code}")
    except Exception as e:
        st.error(str(e))
