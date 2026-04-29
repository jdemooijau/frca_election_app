"""Tests for the admin wizard sidebar shell."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db
import app as app_module


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
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


@pytest.fixture
def fresh_election(admin_client):
    """Election created, no offices, no codes, no members."""
    admin_client.post("/admin/election/new", data={
        "name": "Test Election",
        "max_rounds": "2",
    })
    return admin_client


def test_sidebar_state_fresh_election_has_only_details_done(fresh_election):
    """A just-created election has only step 1 done; everything else locked or current."""
    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    # Election header
    assert state["election"]["id"] == 1
    assert state["election"]["name"] == "Test Election"
    assert state["election"]["current_round"] == 1
    # Setup group: details done, members locked (no members yet),
    # offices locked, settings locked, codes locked
    setup = next(g for g in state["groups"] if g["label"] == "Setup")
    states_by_slug = {item["slug"]: item["state"] for item in setup["entries"]}
    assert states_by_slug["details"] == "done"
    assert states_by_slug["members"] in ("current", "locked")
    assert states_by_slug["offices"] == "locked"
    assert states_by_slug["codes"] == "locked"


def test_sidebar_state_with_offices_codes_marks_them_done(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder",
        "vacancies": "1",
        "max_selections": "1",
        "candidate_names": "Cand A\nCand B\nCand C",
        "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})

    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    setup = next(g for g in state["groups"] if g["label"] == "Setup")
    states = {it["slug"]: it["state"] for it in setup["entries"]}
    assert states["offices"] == "done"
    assert states["codes"] == "done"


def test_sidebar_state_attendance_done_when_participants_set(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})
    admin_client.post("/admin/election/1/participants", data={"participants": "10"})

    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    round_group = next(g for g in state["groups"] if g["label"].startswith("Round"))
    states = {it["slug"]: it["state"] for it in round_group["entries"]}
    assert states["attendance"] == "done"


def test_step_details_renders_form(admin_client):
    admin_client.post("/admin/election/new", data={"name": "Details Test", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/step/details")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Details Test" in body
    assert "Election details" in body
    # Sidebar should be present
    assert "wizard-sidebar" in body
