# ============================================
# SECTION: Helpers — HTTP wrapper plus JSON lot and spot map readers
# • request_json • lot_keys • load_lot_spots
# ============================================

# Reservation page for end users: available spots, active holds, history, and lot-wide status chips.
import json  # Parse parking_status for lot dropdown and overview
import streamlit as st  # Build reservation UI pages
import requests  # Call FastAPI reservation endpoints
from pathlib import Path  # Resolve data paths from this file location
from datetime import datetime, timezone  # Parse expiry and show time remaining

from page_auth import get_auth_headers
from notifications import looks_like_email, send_reservation_confirmation

DATA = Path(__file__).resolve().parent.parent / "data"  # Project data directory path
PJ = DATA / "parking_status.json"  # Live occupancy JSON sibling to SQLite db
TO = 15  # Request timeout seconds for offline API handling
C = "background:#1A1D27;border:1px solid #2A2D3A;border-radius:12px;padding:14px;"  # Card CSS reuse
def request_json(method, path, **kw):  # Return (data-or-None, error-or-None) tuple shape
    try:  # Network failures should not crash the page
        import app_ui as _au  # defer import avoids circular import at module load
        base = getattr(_au, "API_URL", None) or "http://localhost:8000"  # match dashboard base URL
        if not getattr(request_json, "_dbg", False):  # log once per process
            print("page_reserve: APIRouter prefix=no prefix; UI GET", base + "/reservations", base + "/available/PL03", "POST", base + "/reserve")  # noqa: T201
            request_json._dbg = True  # mark logged
        headers = dict(kw.pop("headers", {}) or {})
        headers.update(get_auth_headers())
        if headers:
            kw["headers"] = headers
        r = requests.request(method, base + path, timeout=TO, **kw)  # Single round trip
        if r.status_code >= 400:  # HTTP error responses from API
            try:  # Prefer JSON detail when present
                d = r.json()  # Parse error body if JSON
                err = d.get("detail", r.text)  # FastAPI detail key
            except Exception:  # Non-JSON error bodies
                err = r.text or str(r.status_code)  # Fallback short text
            return None, err  # Signal failure to caller
        if not r.text.strip():  # Empty body responses
            return {}, None  # Normalize to dict
        return r.json(), None  # Parsed success payload
    except Exception as e:  # Offline timeout etc
        return None, str(e)  # Human readable for st.error
def lot_keys():  # List lot ids from JSON or empty if missing
    try:  # File may not exist yet
        with open(PJ, encoding="utf-8") as f:  # Read snapshot
            return list(json.load(f).keys())  # Lot id strings
    except Exception:  # Missing or invalid JSON
        return []  # Disables booking UI only
def load_lot_spots(lot_id):  # Spots dict or None if JSON unusable
    try:  # Guard file access
        with open(PJ, encoding="utf-8") as f:  # Read snapshot
            d = json.load(f)  # Full dict
            return (d.get(lot_id) or {}).get("spots")  # Spot map
    except Exception:  # Read errors
        return None  # Overview shows info message


def load_full_parking_status():  # Entire parking_status dict for multi-lot overview
    try:  # Read once for all lots
        with open(PJ, encoding="utf-8") as f:  # UTF-8 snapshot
            return json.load(f)  # lot_id -> lot payload
    except Exception:  # Missing or bad file
        return {}  # Empty overview


def _minutes_left(expires_raw):  # Minutes until expiry; naive vs aware consistent
    if not expires_raw:  # Missing
        return 0  # No remaining time
    s = str(expires_raw).strip()  # Normalize string
    try:  # Prefer ISO with optional Z
        if s.endswith("Z"):  # UTC suffix from some APIs
            exp = datetime.fromisoformat(s.replace("Z", "+00:00"))  # Aware UTC
            now = datetime.now(timezone.utc)  # Match aware
            return max(0, int((exp - now).total_seconds() // 60))  # Whole minutes
        exp = datetime.fromisoformat(s)  # May be aware or naive
        if exp.tzinfo is not None:  # Timezone-aware expiry
            now = datetime.now(timezone.utc)  # UTC now for comparison
            return max(0, int((exp - now).total_seconds() // 60))  # Aware minus aware
        now = datetime.utcnow()  # API stores naive UTC strings from utcnow()
        return max(0, int((exp - now).total_seconds() // 60))  # Both naive UTC
    except Exception:  # fromisoformat failed
        try:  # Fixed-width SQL-like timestamps
            exp = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")  # Naive parse
            now = datetime.utcnow()  # Match API UTC storage
            return max(0, int((exp - now).total_seconds() // 60))  # Fallback path
        except Exception:  # Unparseable
            return 0  # Safe default


def _cancel_reservation_on_click(rid):  # DELETE only when this callback runs (real click)
    _, cerr = request_json("DELETE", f"/reserve/{rid}")  # Single cancel request
    if cerr:  # Server error
        st.session_state["_cancel_err_msg"] = str(cerr)  # Show next run
    else:  # Success path
        st.session_state["_cancel_ok_toast"] = True  # Show toast next run
        st.rerun()  # Refresh lists


def _confirmation_target(auth_username: str, typed_email: str, fallback_name: str) -> str:
    if looks_like_email(auth_username):
        return auth_username
    if looks_like_email(typed_email):
        return typed_email.strip()
    if looks_like_email(fallback_name):
        return fallback_name.strip()
    return ""


# ============================================
# SECTION: Page — reserve book list overview three panels one lot key
# ============================================
def page_reserve():  # Fifth Streamlit page registered in app_ui main
    auth_user = st.session_state.get("auth_user") or {}
    auth_username = (auth_user.get("username") or "").strip()
    st.markdown('<div style="font-size:28px;font-weight:700;color:#F0F0F5;">Reserve a Parking Spot</div>', unsafe_allow_html=True)  # Title
    st.markdown('<div style="font-size:14px;color:#8B8FA3;margin-bottom:20px;">Book a spot in advance — reservation holds for your selected duration</div>', unsafe_allow_html=True)  # Subtitle
    if st.session_state.pop("_cancel_ok_toast", False):  # After successful cancel callback
        st.toast("Cancelled")  # Feedback only after explicit cancel
    if "_cancel_err_msg" in st.session_state:  # Failed cancel message
        st.error(st.session_state.pop("_cancel_err_msg"))  # One-shot error display
    # ============================================
    # SECTION: Select & Reserve — lot pick GET available POST reserve
    # • warn if no JSON • green spot buttons • toast on success
    # ============================================

    keys = lot_keys()  # Lot ids for selectbox
    if not keys:  # No parking_status.json
        st.warning("No parking_status.json — reservations disabled; history may still load.")  # Limitation note
    lot = st.selectbox("Parking lot", keys or [""], disabled=len(keys) == 0, key="rv_lot")  # Reserve section lot
    if st.session_state.get("_rv_name_reset"):  # Clear name before text_input instantiates
        st.session_state["rv_user_name"] = ""  # Reset value for next run
        del st.session_state["_rv_name_reset"]  # One-shot flag
    if st.session_state.get("_rv_spot_reset"):  # Clear spot before widgets use rv_spot
        st.session_state["rv_spot"] = None  # Reset selection
        del st.session_state["_rv_spot_reset"]  # One-shot flag
    if st.session_state.get("_rv_email_reset"):
        st.session_state["rv_user_email"] = ""
        del st.session_state["_rv_email_reset"]
    if auth_username:
        st.session_state["rv_user_name"] = auth_username
        st.text_input("Your account", value=auth_username, disabled=True, key="rv_user_name_display")
        st.caption("Reservations created while signed in are linked to your account.")
        user_name = auth_username
    else:
        user_name = st.text_input("Your name or email", key="rv_user_name")  # Single name for reserve and my list
    user_email = st.text_input(
        "Confirmation email (optional)",
        key="rv_user_email",
        disabled=looks_like_email(auth_username),
        placeholder="Enter an email if you want a reservation confirmation",
    )
    if looks_like_email(auth_username):
        st.caption(f"Confirmation emails will be sent to {auth_username}.")
    avail, aerr = request_json("GET", f"/available/{lot}") if lot else (None, "no lot")  # Free spots
    if aerr and lot:  # API error when lot set
        st.error(aerr)  # Non-fatal
    spots = (avail or {}).get("spots") or []  # Bookable ids
    st.session_state.setdefault("rv_spot", None)  # Selected spot id
    st.caption("Available spots (tap to select)")  # Hint
    cols = st.columns(8)  # Button grid
    for i, sid in enumerate(spots):  # One button per spot
        if cols[i % 8].button(sid, key=f"av_{lot}_{sid}"):  # Click handler
            st.session_state.rv_spot = sid  # Store selection
    if st.session_state.rv_spot and lot:  # Form after pick
        st.markdown(f'<div style="{C}"><span style="color:#B7EE85;">Selected: {st.session_state.rv_spot}</span></div>', unsafe_allow_html=True)  # Pick label
        dur_labels = ["5 min", "10 min", "15 min", "30 min", "45 min", "1 hour"]  # Shown labels
        dur_minutes = {"5 min": 5, "10 min": 10, "15 min": 15, "30 min": 30, "45 min": 45, "1 hour": 60}  # API minutes
        lab = st.selectbox("Duration", dur_labels, key="rv_dm")  # Picked label string
        dm = dur_minutes[lab]  # Integer minutes for POST
        if st.button("Confirm Reservation", key="rv_go"):  # Submit
            if not user_name.strip():
                st.error("Enter your name or sign in before reserving a spot.")
                return
            body = {"spot_id": st.session_state.rv_spot, "lot_id": lot, "reserved_by": user_name, "duration_minutes": dm}  # Payload
            out, err = request_json("POST", "/reserve", json=body)  # Create row
            if err:  # Conflict or server error
                st.error(err)  # Show detail
            else:  # Success
                st.toast(f"Reserved #{out.get('id')} until {out.get('expires_at')}")  # Toast
                target_email = _confirmation_target(auth_username, user_email, user_name)
                if target_email:
                    ok, msg = send_reservation_confirmation(
                        to_email=target_email,
                        reserved_by=auth_user.get("full_name") or user_name,
                        lot_id=lot,
                        spot_id=st.session_state.rv_spot,
                        duration_minutes=dm,
                        expires_at=str(out.get("expires_at", "")),
                        reservation_id=out.get("id", ""),
                    )
                    if ok:
                        st.success(f"Confirmation email sent to {target_email}")
                    else:
                        st.warning(f"Reservation saved but email failed: {msg}")
                else:
                    st.info("Reservation saved. Add a valid email if you want confirmation emails.")
                st.session_state["_rv_spot_reset"] = True  # Defer clear until before widgets next run
                if not auth_username:
                    st.session_state["_rv_name_reset"] = True  # Defer clear until before text_input next run
                st.session_state["_rv_email_reset"] = True
                st.rerun()  # Refresh
    # ============================================
    # SECTION: My Reservations — filter actives cancel DELETE history expander
    # • GET /reservations • DELETE /reserve/id • GET /reservations/history
    # ============================================

    st.markdown("---")  # Separator
    st.markdown("### My Reservations")  # Heading
    rows, rerr = request_json("GET", "/reservations")  # Active rows
    if rerr:  # API offline
        st.error(rerr)  # Error box
    name_for_list = auth_username or st.session_state.get("rv_user_name", "")  # Prefer the authenticated account when available.
    act = [x for x in (rows or []) if name_for_list.lower() in (x.get("reserved_by") or "").lower()] if name_for_list else (rows or [])  # Filtered actives
    for x in act:  # Cards
        exp = x.get("expires_at")  # Expiry string from API
        rem = _minutes_left(exp)  # Consistent datetime math
        rb = x.get("reserved_by") or "—"  # Booker name from row
        st.markdown(  # Lot spot name times remaining
            f'<div style="{C}margin-bottom:8px;"><b>{x.get("lot_id")}</b> · {x.get("spot_id")}<br/>'
            f'<span style="color:#F0F0F5;font-size:13px;">Reserved by: {rb}</span><br/>'
            f'<span style="color:#8B8FA3;font-size:12px;">Reserved {x.get("reserved_at")}<br/>'
            f"Expires {exp} · ~{rem} min left</span></div>",
            unsafe_allow_html=True,
        )  # Card HTML
        rid = x.get("id")  # Primary key for cancel
        try:  # Coerce for key and callback
            rid = int(rid)  # Integer id
        except (TypeError, ValueError):  # Bad row
            continue  # Skip cancel for malformed row
        st.button(  # No if st.button — only on_click fires DELETE (avoids false clicks on lot change)
            "Cancel Reservation",
            key=f"cx_{rid}",
            on_click=_cancel_reservation_on_click,
            args=(rid,),
        )  # Callback-only cancel; key is unique per reservation id
    with st.expander("Expired / cancelled", expanded=False):  # No name required; GET all inactive from API
        hist_raw, herr = request_json("GET", "/reservations/history")  # GET /reservations/history (no query)
        if herr:  # API offline or error
            st.caption("Could not load history.")  # Short message
        else:  # Parse list response
            hist = hist_raw if isinstance(hist_raw, list) else []  # Rows from DB
            inactive = [r for r in hist if r.get("status") in ("expired", "cancelled")]  # Skip active and completed in UI
            if inactive:  # Show rows
                for r in inactive:  # Each past reservation
                    lid = r.get("lot_id") or "—"  # Lot id
                    sp = r.get("spot_id") or "—"  # Spot id
                    stt = r.get("status") or "—"  # Status string
                    who = r.get("reserved_by") or ""  # Booker
                    ra = r.get("reserved_at") or ""  # When booked
                    st.markdown(  # Same card class as before
                        f'<div style="{C}margin-bottom:6px;"><b>{lid} · {sp}</b> — {stt} — {who} — {ra}</div>',
                        unsafe_allow_html=True,
                    )  # One line per row
            else:  # Nothing to show
                st.caption("No expired or cancelled reservations.")  # Empty state
    # ============================================
    # SECTION: Lot Overview — green free red occupied orange reserved
    # • JSON spots • GET reservations lot for held set • combined chips
    # ============================================

    st.markdown("---")  # Separator
    st.markdown("### Lot Overview")  # Heading
    status = load_full_parking_status()  # Full dict: PL03, PL02, PL011, BRIGHTON_SKI, etc.
    res_by_lot = {}  # lot_id -> reserved spot ids from same GET /reservations as above
    for z in (rows or []):  # Reuse active list already fetched for My Reservations
        lid = z.get("lot_id")  # Lot key
        sp = z.get("spot_id")  # Spot key
        if lid and sp:  # Valid pair
            res_by_lot.setdefault(lid, set()).add(sp)  # Add to set
    if not status:  # No JSON
        st.info("No spot data (parking_status.json missing or invalid).")  # Explain
    else:  # Stack every lot vertically; order matches parking_status.json keys
        for lot_id, lot_data in status.items():  # Not the reserve dropdown — all lots
            smap = (lot_data or {}).get("spots") or {}  # Spots map for this lot only
            rset = res_by_lot.get(lot_id, set())  # Reserved spot ids this lot
            st.markdown(f"**{lot_id}**")  # Visible lot name before badges
            html = ""  # Chips for this lot
            for sid in sorted(smap.keys(), key=lambda s: (len(s), s)):  # Sorted spots
                stt = smap.get(sid)  # JSON occupancy
                if stt == "occupied":  # Car detected
                    bg, fg, lab = "#FF3B3B44", "#FF3B3B", "occupied"  # Red
                elif sid in rset:  # Active hold in DB
                    bg, fg, lab = "#FFB30044", "#FFB300", "reserved"  # Orange
                else:  # Empty and unheld
                    bg, fg, lab = "#B7EE8544", "#B7EE85", "free"  # Green
                html += f'<span style="background:{bg};color:{fg};padding:4px 10px;border-radius:8px;margin:3px;display:inline-block;font-size:11px;font-weight:600;border:1px solid {fg}55;">{sid} {lab}</span>'  # Chip
            st.markdown(f'<div style="{C}">{html}</div>', unsafe_allow_html=True)  # Lot badge row
