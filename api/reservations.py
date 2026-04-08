# ============================================
# SECTION: Reservation REST API — JSON gate plus SQLite holds
# • expire stale before reads • POST reserve GET list DELETE cancel GET available
# • register GET /reservations/history before GET /reservations/{lot_id} path order
# ============================================
import json  # load parking_status.json
from datetime import datetime, timedelta  # expiry timestamps
from pathlib import Path  # project-relative paths
from typing import Optional  # Optional query param for history

from fastapi import APIRouter, HTTPException, Body, Query  # routing
from .database import get_db  # sqlite connection
ROOT = Path(__file__).resolve().parents[1]  # project root
STATUS_JSON = ROOT / "data" / "parking_status.json"  # occupancy json path
router = APIRouter(tags=["reservations"])  # prefix="" so paths are /reserve /reservations /available/{lot_id} etc.


def _db_error(message: str, exc: Exception | None = None):
    raise HTTPException(status_code=500, detail=message) from exc


def _load_status():  # read json or None
    try:  # guard io
        with open(STATUS_JSON, "r", encoding="utf-8") as f:  # utf8 read
            return json.load(f)  # parsed dict
    except (OSError, json.JSONDecodeError, TypeError):  # missing or bad
        return None  # signal absent file
def _expire_stale(conn):  # flip overdue actives
    try:  # single update statement
        conn.execute("UPDATE reservations SET status='expired' WHERE status='active' AND expires_at < datetime('now')")  # sql
        conn.commit()  # persist
    except Exception as e:  # sqlite errors
        _db_error("Database error while expiring stale reservations.", e)
def _spot_empty(data, lot_id, spot_id):  # json gate for empty cell
    if not data or lot_id not in data:  # unknown lot
        return False  # not empty
    spots = data[lot_id].get("spots") or {}  # spot map
    return spots.get(spot_id) == "empty"  # must be literal empty
def _rows(conn, sql, params=()):  # run select to dicts
    try:  # query
        return [dict(r) for r in conn.execute(sql, params).fetchall()]  # rows
    except Exception as e:  # db failure
        _db_error("Database error while reading reservations.", e)
def _active_list(conn, lot_id=None):  # shared active query after expire
    _expire_stale(conn)  # stale cleanup first
    if lot_id is None:  # global list
        return _rows(conn, "SELECT * FROM reservations WHERE status='active' AND expires_at > datetime('now') ORDER BY lot_id, spot_id")  # all lots
    return _rows(conn, "SELECT * FROM reservations WHERE status='active' AND expires_at > datetime('now') AND lot_id=? ORDER BY spot_id", (lot_id,))  # one lot
@router.post("/reserve")  # book spot
def post_reserve(body=Body(...)):  # json body dict
    try:  # parse fields
        spot_id = str(body.get("spot_id") or "").strip()  # spot label
        lot_id = str(body.get("lot_id") or "").strip()  # lot label
        reserved_by = str(body.get("reserved_by") or "").strip()  # booker
        dm = int(body.get("duration_minutes") or 0)  # hold length
    except (TypeError, ValueError):  # bad types
        raise HTTPException(status_code=400, detail="Invalid reservation request.")  # bad request
    if not spot_id or not lot_id or not reserved_by or dm < 1:  # validate
        raise HTTPException(status_code=400, detail="spot_id, lot_id, reserved_by, and duration_minutes are required.")  # bad request
    data = _load_status()  # json snapshot
    if data is None:  # no json file
        raise HTTPException(status_code=503, detail="Live parking status is unavailable. Start the detector and try again.")  # unavailable
    if not _spot_empty(data, lot_id, spot_id):  # not empty in json
        raise HTTPException(status_code=409, detail="Spot is currently occupied")  # conflict
    exp_s = (datetime.utcnow() + timedelta(minutes=dm)).strftime("%Y-%m-%d %H:%M:%S")  # expiry string
    conn = get_db()  # db handle
    try:  # insert transaction
        _expire_stale(conn)  # clean stale first
        row = conn.execute("SELECT reserved_by, expires_at FROM reservations WHERE lot_id=? AND spot_id=? AND status='active' AND expires_at > datetime('now')", (lot_id, spot_id)).fetchone()  # conflict check
        if row:  # already held
            raise HTTPException(409, f"Spot is already reserved by {row['reserved_by']} until {row['expires_at']}")  # conflict message
        cur = conn.execute("INSERT INTO reservations (spot_id, lot_id, reserved_by, expires_at, status) VALUES (?,?,?,?, 'active')", (spot_id, lot_id, reserved_by, exp_s))  # insert row
        conn.commit()  # save
        return {"ok": True, "id": cur.lastrowid, "expires_at": exp_s}  # success payload
    except HTTPException:  # intended status codes
        raise  # propagate
    except Exception as e:  # other db errors
        try:  # rollback attempt
            conn.rollback()  # undo
        except Exception:  # rollback failed
            pass  # ignore
        _db_error("Database error while creating the reservation.", e)
    finally:  # always close
        conn.close()  # release handle
@router.get("/reservations")  # all active reservations
def get_reservations_all():  # sorted list
    conn = get_db()  # db handle
    try:  # read path
        return _active_list(conn)  # helper includes expire
    except HTTPException:  # expire errors
        raise  # propagate
    finally:  # cleanup
        conn.close()  # release handle
@router.get("/reservations/history")  # must precede {lot_id} route; path is GET /reservations/history
def get_reservations_history(reserved_by: Optional[str] = Query(default=None)):  # omit = all inactive rows
    conn = get_db()  # db handle
    try:  # query
        if reserved_by:  # Filter by booker name or email
            return _rows(conn, "SELECT * FROM reservations WHERE reserved_by=? ORDER BY reserved_at DESC", (reserved_by,))  # Per-user history
        return _rows(conn, "SELECT * FROM reservations WHERE status IN ('expired','cancelled','completed') ORDER BY reserved_at DESC", ())  # All inactive
    finally:  # cleanup
        conn.close()  # release handle
@router.get("/reservations/{lot_id}")  # active per lot
def get_reservations_lot(lot_id):  # lot filter
    conn = get_db()  # db handle
    try:  # read path
        return _active_list(conn, lot_id)  # lot scoped list
    except HTTPException:  # expire errors
        raise  # propagate
    finally:  # cleanup
        conn.close()  # release handle
@router.delete("/reserve/{reservation_id}")  # cancel reservation
def delete_reserve(reservation_id):  # path id
    try:  # coerce int
        rid = int(reservation_id)  # pk
    except (TypeError, ValueError):  # bad id
        raise HTTPException(status_code=404, detail="Reservation not found.")  # not found
    conn = get_db()  # db handle
    try:  # update row
        row = conn.execute("SELECT * FROM reservations WHERE id=? AND status='active' AND expires_at > datetime('now')", (rid,)).fetchone()  # must be active
        if not row:  # cannot cancel
            raise HTTPException(status_code=404, detail="Reservation not found or no longer active.")  # not found
        conn.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (rid,))  # soft cancel
        conn.commit()  # save
        return {"ok": True, "reservation": dict(row)}  # old row snapshot
    except HTTPException:  # http path
        raise  # propagate
    except Exception as e:  # db errors
        try:  # rollback
            conn.rollback()  # undo
        except Exception:  # ignore
            pass  # ok
        _db_error("Database error while cancelling the reservation.", e)
    finally:  # cleanup
        conn.close()  # release handle
@router.get("/available/{lot_id}")  # empty minus held
def get_available(lot_id):  # lot id
    data = _load_status()  # json snapshot
    if data is None or lot_id not in (data or {}):  # unknown lot
        return {"spots": []}  # no spots
    spots = data[lot_id].get("spots") or {}  # all spots
    empty = [k for k, v in spots.items() if v == "empty"]  # empty keys
    conn = get_db()  # db handle
    try:  # combine json and db
        _expire_stale(conn)  # expire first
        held = {r["spot_id"] for r in conn.execute("SELECT spot_id FROM reservations WHERE lot_id=? AND status='active' AND expires_at > datetime('now')", (lot_id,)).fetchall()}  # reserved set
        return {"spots": [s for s in sorted(empty) if s not in held]}  # free list
    except HTTPException:  # expire errors
        raise  # propagate
    except Exception as e:  # other db errors
        _db_error("Database error while reading available spots.", e)
    finally:  # cleanup
        conn.close()  # release handle
