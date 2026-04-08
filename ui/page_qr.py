# QR codes — attach token to reservation and show PNG
import io
import streamlit as st
import requests


def page_qr():
    import app_ui as _a

    base = getattr(_a, "API_URL", "http://localhost:8000")
    st.markdown("### QR Codes")
    rid = st.number_input("Reservation ID", min_value=1, step=1, value=1)
    tok = st.text_input("Bearer token (optional, from /auth/login)", type="password", key="qr_bearer")
    if st.button("Generate QR token"):
        h = {"Authorization": f"Bearer {tok}"} if tok.strip() else {}
        r = requests.post(f"{base}/qr/reservation/{int(rid)}", headers=h, timeout=15)
        if r.status_code >= 400:
            st.error(r.text or str(r.status_code))
        else:
            data = r.json()
            token = data.get("qr_token")
            st.success(f"Token saved on reservation {rid}")
            if token:
                img_r = requests.get(f"{base}/qr/image/{token}", timeout=15)
                if img_r.ok:
                    st.image(io.BytesIO(img_r.content), caption="QR")
