"""Auth pages and helpers for the Streamlit frontend."""

import requests
import streamlit as st


AUTH_TIMEOUT = 15


def _parse_error(resp) -> str:
    try:
        data = resp.json()
        return str(data.get("detail") or data)
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"


def ensure_auth_state() -> None:
    st.session_state.setdefault("auth_token", None)
    st.session_state.setdefault("auth_user", None)
    st.session_state.setdefault("_nav_target", None)


def get_auth_token() -> str | None:
    return st.session_state.get("auth_token")


def get_auth_headers() -> dict[str, str]:
    token = get_auth_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def clear_auth_state() -> None:
    st.session_state["auth_token"] = None
    st.session_state["auth_user"] = None


def request_nav(target: str) -> None:
    # Defer page redirects until the main app builds navigation on the next rerun.
    st.session_state["_nav_target"] = target


def fetch_current_user(api_url: str) -> tuple[dict | None, str | None]:
    token = get_auth_token()
    if not token:
        return None, "Not authenticated"
    try:
        resp = requests.get(f"{api_url}/auth/me", headers=get_auth_headers(), timeout=AUTH_TIMEOUT)
        if resp.status_code == 200:
            user = resp.json()
            st.session_state["auth_user"] = user
            return user, None
        if resp.status_code == 401:
            clear_auth_state()
        return None, _parse_error(resp)
    except Exception as exc:
        return None, str(exc)


def sync_auth_user(api_url: str) -> None:
    ensure_auth_state()
    token = get_auth_token()
    if not token:
        st.session_state["auth_user"] = None
        return
    if st.session_state.get("auth_user") is None:
        fetch_current_user(api_url)


def _store_token_and_user(api_url: str, token: str) -> tuple[dict | None, str | None]:
    st.session_state["auth_token"] = token
    user, err = fetch_current_user(api_url)
    if err:
        clear_auth_state()
        return None, err
    return user, None


def page_login(api_url: str) -> None:
    st.markdown(
        '<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Login</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:14px;color:#8B8FA3;margin-bottom:20px;">'
        "Sign in to manage your reservations and profile.</div>",
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        username = st.text_input("Email or username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submit = st.form_submit_button("Login", use_container_width=True)

    if submit:
        if not username.strip() or not password:
            st.error("Enter both username and password.")
            return
        try:
            resp = requests.post(
                f"{api_url}/auth/login",
                data={"username": username.strip(), "password": password},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=AUTH_TIMEOUT,
            )
        except Exception as exc:
            st.error(f"Login failed: {exc}")
            return

        if resp.status_code != 200:
            st.error(_parse_error(resp))
            return

        token = resp.json().get("access_token")
        if not token:
            st.error("Login succeeded but no access token was returned.")
            return

        user, err = _store_token_and_user(api_url, token)
        if err:
            st.error(err)
            return

        request_nav("My Profile")
        st.toast(f"Welcome back, {user.get('username', 'user')}!")
        st.rerun()


def page_signup(api_url: str) -> None:
    st.markdown(
        '<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Sign Up</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:14px;color:#8B8FA3;margin-bottom:20px;">'
        "Create an account to tie reservations to your profile.</div>",
        unsafe_allow_html=True,
    )

    with st.form("signup_form"):
        username = st.text_input("Email or username", key="signup_username")
        password = st.text_input("Password", type="password", key="signup_password")
        confirm = st.text_input("Confirm password", type="password", key="signup_confirm")
        full_name = st.text_input("Full name", key="signup_full_name")
        phone = st.text_input("Phone", key="signup_phone")
        submit = st.form_submit_button("Create Account", use_container_width=True)

    if submit:
        username = username.strip()
        if len(username) < 2:
            st.error("Username must be at least 2 characters.")
            return
        if len(password) < 4:
            st.error("Password must be at least 4 characters.")
            return
        if password != confirm:
            st.error("Passwords do not match.")
            return
        try:
            resp = requests.post(
                f"{api_url}/auth/register",
                json={
                    "username": username,
                    "password": password,
                    "full_name": full_name.strip() or None,
                    "phone": phone.strip() or None,
                },
                timeout=AUTH_TIMEOUT,
            )
        except Exception as exc:
            st.error(f"Sign up failed: {exc}")
            return

        if resp.status_code != 200:
            st.error(_parse_error(resp))
            return

        token = resp.json().get("access_token")
        if not token:
            st.error("Account created but no access token was returned.")
            return

        user, err = _store_token_and_user(api_url, token)
        if err:
            st.error(err)
            return

        request_nav("My Profile")
        st.toast(f"Account created for {user.get('username', username)}")
        st.rerun()


def page_profile(api_url: str) -> None:
    user = st.session_state.get("auth_user")
    if not user:
        user, err = fetch_current_user(api_url)
        if err:
            st.error(err)
            return

    st.markdown(
        '<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">My Profile</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:14px;color:#8B8FA3;margin-bottom:20px;">'
        "Review and update the profile stored in the backend.</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div style="background:#1A1D27;border:1px solid #2A2D3A;border-radius:12px;padding:16px;margin-bottom:18px;">
            <div style="font-size:12px;color:#8B8FA3;text-transform:uppercase;letter-spacing:0.8px;">Signed In As</div>
            <div style="font-size:18px;font-weight:700;color:#F0F0F5;margin-top:4px;">{user.get("username", "")}</div>
            <div style="font-size:13px;color:#8B8FA3;margin-top:6px;">Email: {user.get("email", user.get("username", ""))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("profile_form"):
        full_name = st.text_input("Full name", value=user.get("full_name") or "")
        phone = st.text_input("Phone", value=user.get("phone") or "")
        submit = st.form_submit_button("Save Profile", use_container_width=True)

    if submit:
        try:
            resp = requests.patch(
                f"{api_url}/auth/me",
                json={"full_name": full_name.strip() or None, "phone": phone.strip() or None},
                headers=get_auth_headers(),
                timeout=AUTH_TIMEOUT,
            )
        except Exception as exc:
            st.error(f"Profile update failed: {exc}")
            return

        if resp.status_code != 200:
            if resp.status_code == 401:
                clear_auth_state()
            st.error(_parse_error(resp))
            return

        st.session_state["auth_user"] = resp.json()
        st.toast("Profile updated")
        st.rerun()

    if st.button("Logout", use_container_width=True, key="profile_logout_btn"):
        clear_auth_state()
        request_nav("Home")
        st.rerun()
