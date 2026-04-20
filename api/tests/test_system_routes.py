# Integration tests reload the API modules against an isolated in-memory database and test data directory.
import importlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_ctx(monkeypatch):
    tests_root = Path.cwd() / "data" / "test_runtime"
    tests_root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    db_path = f"file:parking_helper_test_{run_id}?mode=memory&cache=shared"
    data_dir = tests_root
    status_json = data_dir / "parking_status.json"
    status_json.write_text(
        json.dumps(
            {
                "PL11": {
                    "timestamp": "2026-04-07 10:00:00",
                    "total_spots": 2,
                    "empty_spots": 2,
                    "occupied_spots": 0,
                    "spots": {"SP1": "empty", "SP2": "empty"},
                }
            }
        ),
        encoding="utf-8",
    )

    # Environment variables are patched before reload so module-level startup code binds to the test runtime.
    monkeypatch.setenv("PARKING_HELPER_DB_PATH", db_path)
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("LIVE_ADMIN_SECRET", "admin-token")

    import api.database as database
    import api.auth as auth
    import api.reservations as reservations
    import api.live_routes as live_routes
    import api.app as app_module

    database = importlib.reload(database)
    auth = importlib.reload(auth)
    reservations = importlib.reload(reservations)
    live_routes = importlib.reload(live_routes)

    reservations.STATUS_JSON = status_json
    live_routes.ROOT = tests_root
    live_routes.FRAME_PATH = data_dir / "latest_frame.jpg"
    live_routes.FRAME_PATH_ROI = data_dir / "latest_frame_roi.jpg"
    live_routes.LOG_PATH = data_dir / "detector.log"
    live_routes.PID_PATH = data_dir / f"detector_{run_id}.pid"
    live_routes.STATUS_PATH = status_json

    keepalive = database.get_db()
    database.init_db()
    app_module = importlib.reload(app_module)
    client = TestClient(app_module.app)
    try:
        yield {
            "client": client,
            "database": database,
            "status_json": status_json,
            "data_dir": data_dir,
            "live_routes": live_routes,
        }
    finally:
        keepalive.close()


def _register_and_login(client: TestClient, username: str, password: str = "pass1234"):
    register = client.post(
        "/auth/register",
        json={"username": username, "password": password, "full_name": "Test User"},
    )
    assert register.status_code == 200, register.text
    login = client.post(
        "/auth/login",
        data={"username": username, "password": password},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _insert_active_reservation(database, lot_id: str, spot_id: str, reserved_by: str):
    conn = database.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO reservations (spot_id, lot_id, reserved_by, expires_at, status) "
            "VALUES (?, ?, ?, datetime('now', '+30 minutes'), 'active')",
            (spot_id, lot_id, reserved_by),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_auth_register_login_and_profile(app_ctx):
    client = app_ctx["client"]
    headers = _register_and_login(client, "owner@example.com")

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["username"] == "owner@example.com"

    updated = client.patch("/auth/me", json={"phone": "555-1234"}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["phone"] == "555-1234"


def test_reservations_create_available_cancel_and_history(app_ctx):
    client = app_ctx["client"]

    available = client.get("/available/PL11")
    assert available.status_code == 200, available.text
    assert available.json()["spots"] == ["SP1", "SP2"]

    created = client.post(
        "/reserve",
        json={
            "spot_id": "SP1",
            "lot_id": "PL11",
            "reserved_by": "owner@example.com",
            "duration_minutes": 15,
        },
    )
    assert created.status_code == 200, created.text
    reservation_id = created.json()["id"]

    available_after = client.get("/available/PL11")
    assert available_after.status_code == 200, available_after.text
    assert available_after.json()["spots"] == ["SP2"]

    active = client.get("/reservations")
    assert active.status_code == 200, active.text
    assert len(active.json()) == 1
    assert active.json()[0]["spot_id"] == "SP1"

    cancelled = client.delete(f"/reserve/{reservation_id}")
    assert cancelled.status_code == 200, cancelled.text

    history = client.get("/reservations/history")
    assert history.status_code == 200, history.text
    assert any(row["status"] == "cancelled" for row in history.json())


def test_live_routes_require_admin_token_and_report_files(app_ctx):
    client = app_ctx["client"]
    data_dir = app_ctx["data_dir"]

    frame_path = data_dir / "latest_frame.jpg"
    roi_frame_path = data_dir / "latest_frame_roi.jpg"
    log_path = data_dir / "detector.log"

    frame_path.write_bytes(b"fake-jpeg")
    roi_frame_path.write_bytes(b"fake-jpeg")
    log_path.write_text("line1\nline2\n", encoding="utf-8")

    denied = client.get("/live/latest")
    assert denied.status_code == 401, denied.text

    latest = client.get("/live/latest", headers={"X-Admin-Token": "admin-token"})
    assert latest.status_code == 200, latest.text
    assert latest.content == b"fake-jpeg"

    roi = client.get("/live/roi/latest", headers={"X-Admin-Token": "admin-token"})
    assert roi.status_code == 200, roi.text

    logs = client.get("/live/logs", headers={"X-Admin-Token": "admin-token"})
    assert logs.status_code == 200, logs.text
    assert "line1" in logs.json()["logs"]

    status = client.get("/live/status", headers={"X-Admin-Token": "admin-token"})
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["file_exists"] is True
    assert payload["metrics"]["total"] == 2
