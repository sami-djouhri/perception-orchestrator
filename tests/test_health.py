import sqlite3

from fastapi.testclient import TestClient

from app import health
from app.main import app

client = TestClient(app)


def setup_function() -> None:
    health.clear_checks()


def teardown_function() -> None:
    health.clear_checks()


def test_health_ok_without_checks():
    # Rueckwaertskompatibel: ohne registrierte Checks reiner Liveness-Ping.
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "service" in data
    assert "checks" not in data


def test_health_ok_with_passing_check():
    health.register_check("db", lambda: None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["checks"]["db"] == "ok"


def test_health_degraded_on_failing_check():
    def boom() -> None:
        raise RuntimeError("db unreachable")

    health.register_check("db", boom)
    r = client.get("/health")
    assert r.status_code == 503
    data = r.json()
    assert data["status"] == "degraded"
    assert "db unreachable" in data["checks"]["db"]


def test_sqlite_check_ok(tmp_path):
    db = tmp_path / "app.db"
    sqlite3.connect(str(db)).close()
    health.register_check("db", health.sqlite_check(str(db)))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["checks"]["db"] == "ok"


def test_sqlite_check_unreachable_path():
    health.register_check("db", health.sqlite_check("/nonexistent-dir/app.db"))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
