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
    """A just-created election has only step 1 done; everything else either
    available, current, or locked depending on prerequisites.

    Note: `members` is skipped from auto-landing selection (it's app-global)
    so the current step lands on `offices`. Members itself is always
    reachable (no prerequisite chain), so its sidebar state is "available".
    """
    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    # Election header
    assert state["election"]["id"] == 1
    assert state["election"]["name"] == "Test Election"
    assert state["election"]["current_round"] == 1
    setup = next(g for g in state["groups"] if g["label"] == "Setup")
    states_by_slug = {item["slug"]: item["state"] for item in setup["entries"]}
    assert states_by_slug["details"] == "done"
    # Members is reachable (no prerequisite), but not current and not done
    # -> "available" (clickable, not the auto-landing pick).
    assert states_by_slug["members"] == "available"
    assert states_by_slug["offices"] == "current"
    # Codes prerequisites are not met (offices not done yet) -> locked.
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


def test_step_members_renders_with_sidebar(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/step/members")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Import Members" in body  # existing CSV upload form copy
    assert "wizard-sidebar" in body


def test_step_offices_renders_existing_office_with_candidates(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    rv = admin_client.get("/admin/election/1/step/offices")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Elder" in body
    # at least one candidate name visible
    assert "A" in body or "B" in body
    assert "wizard-sidebar" in body
    assert "Add Office" in body


def test_step_settings_renders_paper_count_toggle(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/step/settings")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "paper count" in body.lower() or "paper_count_enabled" in body
    assert "wizard-sidebar" in body


def test_step_codes_shows_status_and_printer_pack(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})
    rv = admin_client.get("/admin/election/1/step/codes")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Total Codes" in body or "10" in body
    assert "Printer Pack" in body
    assert "wizard-sidebar" in body


@pytest.fixture
def election_ready_for_attendance(admin_client):
    """An election with offices+candidates+codes but no attendance set yet."""
    admin_client.post("/admin/election/new", data={"name": "Ready", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})
    return admin_client


def test_step_attendance_shows_participants_form(election_ready_for_attendance):
    rv = election_ready_for_attendance.get("/admin/election/1/step/attendance")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Brothers Present" in body
    assert "wizard-sidebar" in body


@pytest.fixture
def election_with_codes(admin_client):
    """An election with offices+candidates+codes+attendance, ready to walk welcome/rules."""
    admin_client.post("/admin/election/new", data={"name": "Ready", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})
    admin_client.post("/admin/election/1/participants", data={"participants": "10"})
    return admin_client


def test_step_welcome_shows_projector_advance(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/step/welcome")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Welcome" in body or "Election Rules" in body
    assert "wizard-sidebar" in body


def test_close_voting_does_not_auto_reveal_results(election_with_codes):
    # Open voting
    election_with_codes.post("/admin/election/1/voting")
    # Close voting
    election_with_codes.post("/admin/election/1/voting")
    # show_results should remain 0
    from app import get_db
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT show_results FROM elections WHERE id = 1").fetchone()
    assert row["show_results"] == 0, "Closing voting must not auto-reveal results on the projector"


def test_step_voting_shows_open_close_button(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/step/voting")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Round" in body and "Open" in body
    assert "wizard-sidebar" in body


def test_step_count_shows_paper_inputs(election_with_codes):
    election_with_codes.post("/admin/election/1/voting")  # open
    election_with_codes.post("/admin/election/1/voting")  # close
    rv = election_with_codes.get("/admin/election/1/step/count")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Paper Ballots Received" in body or "paper_ballot_count" in body
    assert "Enter Paper Votes" in body
    assert "wizard-sidebar" in body


def test_step_decide_shows_options_after_close(election_with_codes):
    election_with_codes.post("/admin/election/1/voting")  # open
    election_with_codes.post("/admin/election/1/voting")  # close
    rv = election_with_codes.get("/admin/election/1/step/decide")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Start Round" in body or "Show Final Results" in body
    assert "wizard-sidebar" in body


def test_step_final_renders_when_phase_4(election_with_codes):
    # Force display_phase = 4
    election_with_codes.post("/admin/election/1/display-phase", data={"target": "4"})
    rv = election_with_codes.get("/admin/election/1/step/final")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Final" in body and "Result" in body
    assert "wizard-sidebar" in body


def test_step_minutes_links_to_docx(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/step/minutes")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Minutes" in body
    assert "/admin/election/1/minutes" in body or "minutes" in body.lower()
    assert "wizard-sidebar" in body


def test_old_manage_url_redirects_to_step(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/manage", follow_redirects=False)
    assert rv.status_code in (301, 302, 308)
    assert "/step/" in rv.location


def test_old_setup_url_redirects_to_offices_step(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/setup", follow_redirects=False)
    assert rv.status_code in (301, 302, 308)
    assert "/step/offices" in rv.location


def test_old_codes_url_redirects_to_codes_step(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/codes", follow_redirects=False)
    assert rv.status_code in (301, 302, 308)
    assert "/step/codes" in rv.location


def test_dashboard_manage_link_targets_step_open(election_with_codes):
    # Mark first-run setup complete so /admin renders the dashboard.
    from app import set_setting
    with app.app_context():
        set_setting("setup_complete", "1")
    rv = election_with_codes.get("/admin")
    body = rv.get_data(as_text=True)
    # The dashboard should have an "Open" link going to /admin/election/1 (or directly to a /step/ URL)
    assert "/admin/election/1" in body
    # Should NOT have a "Manage" link to the legacy URL
    assert "/admin/election/1/manage" not in body


def test_admin_election_open_redirects_to_current_step(election_with_codes):
    rv = election_with_codes.get("/admin/election/1", follow_redirects=False)
    assert rv.status_code in (301, 302, 308)
    assert "/step/" in rv.location
