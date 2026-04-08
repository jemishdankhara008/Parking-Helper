# ============================================
# SECTION: QR — token for reservations
# ============================================

import secrets
import io
import os
from typing import Optional

import qrcode
from fastapi import APIRouter, HTTPException, Depends, Header, status
from fastapi.responses import Response

from .database import get_db
from .auth import get_current_username_optional

router = APIRouter(prefix="/qr", tags=["qr"])


def _is_admin_request(x_admin_token: Optional[str]) -> bool:
    secret = (os.environ.get("LIVE_ADMIN_SECRET") or "").strip()
    return bool(secret and x_admin_token and x_admin_token.strip() == secret)


def _assert_qr_access(row, username: str | None, x_admin_token: Optional[str]) -> None:
    if _is_admin_request(x_admin_token):
        return
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticate as the reservation owner or send a valid X-Admin-Token.",
        )
    reserved_by = str(row["reserved_by"]).strip()
    if username.strip() != reserved_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the reservation owner or admin can access this QR.",
        )


@router.post("/reservation/{reservation_id}")
def attach_qr_token(
    reservation_id: int,
    username: str | None = Depends(get_current_username_optional),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Reservation not found")
        _assert_qr_access(row, username, x_admin_token)
        token = secrets.token_urlsafe(16)
        conn.execute("UPDATE reservations SET qr_token=? WHERE id=?", (token, reservation_id))
        conn.commit()
        return {"ok": True, "reservation_id": reservation_id, "qr_token": token}
    finally:
        conn.close()


@router.get("/image/{token}")
def qr_image_png(
    token: str,
    username: str | None = Depends(get_current_username_optional),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM reservations WHERE qr_token=? AND status='active'",
            (token,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Invalid or expired")
        _assert_qr_access(row, username, x_admin_token)
    finally:
        conn.close()
    buf = io.BytesIO()
    qrcode.make(token).save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/data/{token}")
def qr_data(
    token: str,
    username: str | None = Depends(get_current_username_optional),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM reservations WHERE qr_token=? AND status='active'",
            (token,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Invalid or expired")
        _assert_qr_access(row, username, x_admin_token)
        return dict(row)
    finally:
        conn.close()
