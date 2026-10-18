"""Tests for the admin network check page and its helpers."""

import os
import socket
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import network_check
from network_check import url_host, host_matches, local_ipv4_addresses, port80_serves_this_app
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


@pytest.fixture
def admin_client(client):
    client.post("/admin/login", data={"password": "admin"})
    return client


def test_url_with_port():
    assert url_host("http://10.0.0.2:5000/v/AB") == "10.0.0.2"


def test_url_host_lowercases_and_handles_empty():
    assert url_host("http://Church.Vote/") == "church.vote"
    assert url_host("") == ""


def test_host_matches_any_address():
    assert host_matches("http://10.0.0.2", ["192.168.1.20", "10.0.0.2"]) is True


def test_host_mismatch():
    assert host_matches("http://10.0.0.2", ["192.168.8.100"]) is False


def test_hostname_is_unknown():
    assert host_matches("http://church.vote", ["10.0.0.2"]) is None


def test_local_addresses_exclude_loopback():
    addresses = local_ipv4_addresses()
    assert addresses == sorted(set(addresses))
    assert not any(a.startswith("127.") for a in addresses)


def test_port80_probe_false_when_nothing_answers(monkeypatch):
    # Point the probe at a port nothing listens on.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setattr(network_check, "PROBE_PORT", free_port)
    assert port80_serves_this_app("abc", timeout=0.5) is False


def test_instance_route_returns_id(client):
    import app as app_module
    resp = client.get("/api/instance")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == app_module.INSTANCE_ID


def test_reach_test_is_public(client):
    resp = client.get("/reach-test")
    assert resp.status_code == 200
    assert "This phone can reach the voting app" in resp.get_data(as_text=True)


def test_network_check_mismatch_warning(admin_client, monkeypatch):
    monkeypatch.setattr(network_check, "local_ipv4_addresses", lambda: ["192.168.8.100"])
    monkeypatch.setattr(network_check, "port80_serves_this_app", lambda *a, **k: False)
    body = admin_client.get("/admin/network-check").get_data(as_text=True)
    assert "192.168.8.100" in body
    assert "Code slips printed now will not work on this network." in body
    assert "http://10.0.0.2 will not reach the app" in body


def test_network_check_all_good(admin_client, monkeypatch):
    monkeypatch.setattr(network_check, "local_ipv4_addresses", lambda: ["10.0.0.2"])
    monkeypatch.setattr(network_check, "port80_serves_this_app", lambda *a, **k: True)
    body = admin_client.get("/admin/network-check").get_data(as_text=True)
    assert "Code slips printed now will not work on this network." not in body
    assert "will not reach the app" not in body
    assert "/reach-test" in body


def test_network_check_requires_admin(client):
    resp = client.get("/admin/network-check")
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]


def test_setup_links_to_network_check(admin_client):
    body = admin_client.get("/admin/setup").get_data(as_text=True)
    assert 'href="/admin/network-check"' in body
