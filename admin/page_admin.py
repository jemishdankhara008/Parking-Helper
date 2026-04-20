# Admin panel — password gate
"""Legacy admin page kept as a minimal password-gated placeholder beside the richer admin_app.py dashboard."""

import streamlit as st


def page_admin():
    st.markdown("### Admin")
    st.caption("Restricted area")
    if st.session_state.get("admin_ok"):
        st.success("Signed in as admin")
        st.write("Use Swagger at `/docs` for auth, reservation, and live endpoints.")
    else:
        pw = st.text_input("Password", type="password", key="admin_pw")
        if st.button("Enter"):
            if pw == "admin123":
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Wrong password")
