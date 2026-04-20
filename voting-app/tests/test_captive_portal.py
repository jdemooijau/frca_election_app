"""Tests for captive portal probe routes.

CPD probes return the expected "success" responses so phones stay connected
to the WiFi.  The DNS wildcard redirects all other traffic to the voting page.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    import app as app_module
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path

    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client

    app_module.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)


def test_hotspot_detect_html_returns_success(client):
    resp = client.get("/hotspot-detect.html")
    assert resp.status_code == 200
    assert b"Success" in resp.data


def test_generate_204_returns_204(client):
    resp = client.get("/generate_204")
    assert resp.status_code == 204


def test_connecttest_txt_returns_expected(client):
    resp = client.get("/connecttest.txt")
    assert resp.status_code == 200
    assert b"Microsoft Connect Test" in resp.data


def test_success_txt_returns_expected(client):
    resp = client.get("/success.txt")
    assert resp.status_code == 200
    assert b"success" in resp.data


def test_catch_all_unknown_path_redirects_home(client):
    resp = client.get("/some/random/nonexistent/path")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_captive_portal_routes_return_no_cache_headers(client):
    resp = client.get("/hotspot-detect.html")
    assert "no-store" in resp.headers.get("Cache-Control", "")
    assert "no-cache" in resp.headers.get("Pragma", "")


def test_captive_portal_routes_accessible_without_authentication(client):
    resp = client.get("/generate_204")
    assert resp.status_code == 204  # success, not 401/403


def test_known_routes_take_precedence_over_catch_all(client):
    resp = client.get("/admin/login")
    assert resp.status_code == 200
    assert b"password" in resp.data.lower()


def test_catch_all_does_not_interfere_with_static_files(client):
    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200


def test_captive_portal_api_returns_not_captive(client):
    resp = client.get("/api/captive-portal")
    assert resp.status_code == 200
    assert resp.content_type == "application/captive+json"
    import json
    data = json.loads(resp.data)
    assert data["captive"] is False
