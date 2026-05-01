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
    location = resp.headers["Location"]
    assert location.startswith("http://")
    assert location.endswith("/")
    assert "church.vote" in location


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


def test_captive_portal_api_advertises_portal(client):
    resp = client.get("/api/captive-portal")
    assert resp.status_code == 200
    assert resp.content_type == "application/captive+json"
    import json
    data = json.loads(resp.data)
    assert data["captive"] is True
    assert data["user-portal-url"].startswith("http")
    assert "church.vote" in data["user-portal-url"]


def test_well_known_captive_portal_advertises_portal(client):
    resp = client.get("/.well-known/captive-portal")
    assert resp.status_code == 200
    import json
    data = json.loads(resp.data)
    assert data["captive"] is True
    assert "user-portal-url" in data


def test_foreign_host_is_redirected_to_canonical(client):
    resp = client.get("/", headers={"Host": "bbc.com"})
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("http://church.vote")


def test_foreign_host_redirect_preserves_path_and_query(client):
    resp = client.get("/vote?code=ABC123", headers={"Host": "example.com"})
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("http://church.vote")
    assert "/vote" in location
    assert "code=ABC123" in location


def test_canonical_host_is_not_redirected(client):
    resp = client.get("/admin/login", headers={"Host": "church.vote"})
    assert resp.status_code == 200
    assert b"password" in resp.data.lower()


def test_ip_literal_host_is_not_redirected(client):
    resp = client.get("/admin/login", headers={"Host": "192.168.8.100:5000"})
    assert resp.status_code == 200
    assert b"password" in resp.data.lower()


def test_localhost_is_not_redirected(client):
    resp = client.get("/admin/login", headers={"Host": "localhost"})
    assert resp.status_code == 200
    assert b"password" in resp.data.lower()


def test_cpd_probe_serves_directly_on_foreign_host(client):
    resp = client.get("/generate_204", headers={"Host": "connectivitycheck.gstatic.com"})
    assert resp.status_code == 204


def test_apple_cpd_probe_serves_directly_on_foreign_host(client):
    resp = client.get("/hotspot-detect.html", headers={"Host": "captive.apple.com"})
    assert resp.status_code == 200
    assert b"Success" in resp.data


def test_static_files_not_redirected_on_foreign_host(client):
    resp = client.get("/static/css/style.css", headers={"Host": "bbc.com"})
    assert resp.status_code == 200


def test_landing_with_no_open_election_shows_waiting_message(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "voting" in body
    assert "when voting opens" in body or "you'll be handed a card" in body


def test_landing_with_no_open_election_mentions_wifi_ssid(client):
    from app import set_setting
    with app.app_context():
        set_setting("wifi_ssid", "ChurchVote")
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"ChurchVote" in resp.data


def test_qr_scan_with_no_open_election_shows_waiting_message(client):
    resp = client.get("/v/ABCDEF")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "when voting opens" in body or "you'll be handed a card" in body


def _seed_election(voting_open, display_phase):
    """Insert a single election with the given gating fields. Returns its id."""
    from app import get_db
    with app.app_context():
        db = get_db()
        cur = db.execute(
            "INSERT INTO elections (name, max_rounds, voting_open, display_phase) "
            "VALUES (?, ?, ?, ?)",
            ("Test Election", 2, voting_open, display_phase),
        )
        db.commit()
        return cur.lastrowid


def test_landing_voting_open_phase_1_shows_waiting(client):
    """Chairman opened voting then flipped projector back to Welcome - voters wait."""
    _seed_election(voting_open=1, display_phase=1)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "when voting opens" in body or "you'll be handed a card" in body
    assert b'name="code"' not in resp.data


def test_landing_voting_open_phase_2_shows_waiting(client):
    """Chairman opened voting but is still on Rules phase - voters wait."""
    _seed_election(voting_open=1, display_phase=2)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "when voting opens" in body or "you'll be handed a card" in body
    assert b'name="code"' not in resp.data


def test_landing_voting_open_phase_3_shows_form(client):
    """Voting open and projector on voting phase - show the code entry form."""
    _seed_election(voting_open=1, display_phase=3)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'name="code"' in resp.data
    assert b"Submit Code" in resp.data


def test_landing_voting_closed_phase_3_shows_waiting(client):
    """Voting closed (between rounds) even with phase 3 still set - voters wait."""
    _seed_election(voting_open=0, display_phase=3)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "when voting opens" in body or "you'll be handed a card" in body
    assert b'name="code"' not in resp.data


def test_wait_page_mentions_qr_card_and_paper_ballot(client):
    """Wait-page copy should tell voters about the QR code, the card, and the paper alternative."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "qr" in body
    assert "card" in body
    assert "paper ballot" in body


def test_wait_page_warns_against_double_voting(client):
    """A red warning must tell voters not to submit paper if they voted online."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Vote one way only" in body
    # Warning is rendered with a red accent (border colour or text colour).
    assert "#C0392B" in body


def _seed_election_with_candidates(voting_open, show_results, display_phase=3):
    """Insert an election with one office and two candidates, return its id."""
    from app import get_db
    with app.app_context():
        db = get_db()
        cur = db.execute(
            "INSERT INTO elections (name, max_rounds, voting_open, show_results, "
            "display_phase, current_round) VALUES (?, ?, ?, ?, ?, ?)",
            ("Test Election", 2, voting_open, show_results, display_phase, 1),
        )
        eid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO offices (election_id, name, vacancies, max_selections, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (eid, "Elder", 1, 1, 1),
        )
        oid = cur.lastrowid
        db.execute(
            "INSERT INTO candidates (office_id, name, active) VALUES (?, ?, 1)",
            (oid, "Smith John"),
        )
        db.execute(
            "INSERT INTO candidates (office_id, name, active) VALUES (?, ?, 1)",
            (oid, "Doe Jane"),
        )
        db.commit()
        return eid


def test_phone_display_hides_candidates_while_voting_open(client):
    """Phone display must not leak candidate names or counts during a live round
    even if the chairman has flipped show_results on."""
    _seed_election_with_candidates(voting_open=1, show_results=1)
    resp = client.get("/displayphone")
    assert resp.status_code == 200
    assert b"Smith John" not in resp.data
    assert b"Doe Jane" not in resp.data


def test_phone_display_hides_candidates_while_voting_open_show_results_off(client):
    _seed_election_with_candidates(voting_open=1, show_results=0)
    resp = client.get("/displayphone")
    assert resp.status_code == 200
    assert b"Smith John" not in resp.data
    assert b"Doe Jane" not in resp.data


def test_phone_display_shows_candidates_when_round_closed(client):
    """Once voting is closed, candidate names appear on the phone display."""
    _seed_election_with_candidates(voting_open=0, show_results=1)
    resp = client.get("/displayphone")
    assert resp.status_code == 200
    assert b"Smith John" in resp.data
    assert b"Doe Jane" in resp.data


def test_phone_display_shows_ballot_progress_while_voting_open(client):
    """Progress block (ballots / participating) must still render while voting is open."""
    _seed_election_with_candidates(voting_open=1, show_results=0)
    resp = client.get("/displayphone")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8").lower()
    assert "ballots" in body
    assert "participating" in body
