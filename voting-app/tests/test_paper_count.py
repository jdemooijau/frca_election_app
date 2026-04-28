"""Tests for the paper ballot co-counting feature."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db


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


def test_paper_count_enabled_column_exists(client):
    with app.app_context():
        cols = [r["name"] for r in get_db().execute("PRAGMA table_info(elections)")]
        assert "paper_count_enabled" in cols


def test_count_sessions_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_sessions'"
        ).fetchone()
        assert rows is not None


def test_count_session_helpers_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_session_helpers'"
        ).fetchone()
        assert rows is not None


def test_count_session_tallies_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_session_tallies'"
        ).fetchone()
        assert rows is not None


def test_count_session_results_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_session_results'"
        ).fetchone()
        assert rows is not None


def _create_election(client):
    """Helper: log in as admin and create an election. Returns election_id."""
    with client.session_transaction() as sess:
        sess["admin"] = True
    resp = client.post("/admin/election/new", data={
        "name": "Test", "max_rounds": "2", "election_date": "2026-04-28"
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        row = get_db().execute("SELECT id FROM elections ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"]


def test_paper_count_toggle_via_settings_post(client):
    election_id = _create_election(client)
    # Default off
    with app.app_context():
        row = get_db().execute(
            "SELECT paper_count_enabled FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        assert row["paper_count_enabled"] == 0
    # Enable
    resp = client.post(f"/admin/election/{election_id}/settings", data={
        "paper_count_enabled": "1"
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        row = get_db().execute(
            "SELECT paper_count_enabled FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        assert row["paper_count_enabled"] == 1
    # Disable
    resp = client.post(f"/admin/election/{election_id}/settings", data={})
    assert resp.status_code in (200, 302)
    with app.app_context():
        row = get_db().execute(
            "SELECT paper_count_enabled FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        assert row["paper_count_enabled"] == 0


# ---------------------------------------------------------------------------
# Helper join + lazy session creation (Task 3)
# ---------------------------------------------------------------------------

def _setup_paper_count_election(client):
    """Create election, enable paper count, add 1 office with 4 candidates,
    set attendance, generate codes. Returns (id, list[plaintext codes]).
    """
    election_id = _create_election(client)
    client.post(f"/admin/election/{election_id}/settings", data={"paper_count_enabled": "1"})
    client.post(f"/admin/election/{election_id}/setup", data={
        "office_name": "Elder", "vacancies": "2", "max_selections": "2",
        "candidate_names": "Smith\nJones\nBrown\nWhite",
        "confirm_slate_override": "1",
    })
    client.post(f"/admin/election/{election_id}/codes", data={"count": "3"})
    # Attendance is required before voting can be opened (Article 4 prerequisite).
    client.post(f"/admin/election/{election_id}/participants", data={"participants": "10"})
    with app.app_context():
        codes = get_db().execute(
            "SELECT plaintext FROM codes WHERE election_id = ?", (election_id,)
        ).fetchall()
        return election_id, [c["plaintext"] for c in codes]


def test_count_join_creates_session_and_helper(client):
    election_id, codes = _setup_paper_count_election(client)
    # Open then close voting (toggle twice). Route is /admin/election/<id>/voting.
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    # Simulate burned-code session for a non-admin
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
        sess.pop("admin", None)
    resp = client.post("/count/join", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/count/")
    with app.app_context():
        sess_row = get_db().execute(
            "SELECT * FROM count_sessions WHERE election_id = ?", (election_id,)
        ).fetchone()
        assert sess_row is not None
        assert sess_row["status"] == "active"
        helper_row = get_db().execute(
            "SELECT * FROM count_session_helpers WHERE session_id = ?", (sess_row["id"],)
        ).fetchone()
        assert helper_row["voter_code"] == codes[0]
        assert helper_row["short_id"] == codes[0][-6:].upper()


def test_count_join_idempotent(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
    client.post("/count/join")
    client.post("/count/join")
    with app.app_context():
        n = get_db().execute("SELECT COUNT(*) AS n FROM count_session_helpers").fetchone()["n"]
        assert n == 1


def test_count_join_blocked_when_disabled(client):
    election_id = _create_election(client)
    # Need attendance + at least one office/code path is irrelevant here: we
    # simply need an existing election with paper_count_enabled = 0 and try to
    # join. Voting state doesn't matter since the disabled check fires first.
    with client.session_transaction() as sess:
        sess["used_code"] = "DUMMYCODE"
        sess["election_id"] = election_id
    resp = client.post("/count/join")
    assert resp.status_code in (400, 403)


def test_count_helper_page_shows_candidates(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")  # USE THE CORRECT ROUTE
    client.post(f"/admin/election/{election_id}/voting")
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
    join_resp = client.post("/count/join")
    assert join_resp.status_code == 302
    helper_resp = client.get(join_resp.headers["Location"])
    assert helper_resp.status_code == 200
    body = helper_resp.get_data(as_text=True)
    # Header shows last 6 chars of code
    assert codes[0][-6:].upper() in body
    # Candidates appear (surnames only)
    assert "Smith" in body
    assert "Jones" in body
    # The −1 pill text appears at least once per candidate
    assert body.count("−1") >= 4


# ---------------------------------------------------------------------------
# Tap, Done, Heartbeat endpoints (Task 5)
# ---------------------------------------------------------------------------

def _join_count(client, election_id, code):
    with client.session_transaction() as sess:
        sess["used_code"] = code
        sess["election_id"] = election_id
    resp = client.post("/count/join", follow_redirects=False)
    return int(resp.headers["Location"].rsplit("/", 1)[-1])


def _candidate_ids(election_id):
    with app.app_context():
        rows = get_db().execute(
            "SELECT c.id FROM candidates c "
            "JOIN offices o ON c.office_id = o.id "
            "WHERE o.election_id = ? ORDER BY c.id",
            (election_id,)
        ).fetchall()
        return [r["id"] for r in rows]


def test_count_tap_increments_and_decrements(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 200
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 200
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": -1})
    assert r.status_code == 200
    with app.app_context():
        row = get_db().execute(
            "SELECT count FROM count_session_tallies WHERE candidate_id = ?", (cands[0],)
        ).fetchone()
        assert row["count"] == 1


def test_count_tap_clamps_at_zero(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": -1})
    assert r.status_code == 200
    with app.app_context():
        row = get_db().execute(
            "SELECT count FROM count_session_tallies WHERE candidate_id = ?", (cands[0],)
        ).fetchone()
        assert row["count"] == 0


def test_count_done_marks_helper_and_locks_taps(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    r = client.post(f"/count/{sid}/done", json={})
    assert r.status_code == 200
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 403


def test_count_heartbeat_returns_session_status(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    r = client.get(f"/count/{sid}/heartbeat")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["session_status"] == "active"
    assert payload["helper_done"] is False


def test_confirmation_shows_assist_button_when_active(client):
    election_id, codes = _setup_paper_count_election(client)
    # Open then close voting
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    # Set a burned-code session
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
    resp = client.get("/confirmation")
    assert resp.status_code == 200
    assert b"Assist with Paper Counting" in resp.data


def test_confirmation_hides_assist_when_disabled(client):
    election_id = _create_election(client)
    # Do NOT enable paper_count_enabled
    client.post(f"/admin/election/{election_id}/setup", data={
        "office_name": "Elder", "vacancies": "2", "max_selections": "2",
        "candidate_names": "Smith\nJones\nBrown\nWhite",
        "confirm_slate_override": "1",
    })
    client.post(f"/admin/election/{election_id}/codes", data={"count": "1"})
    client.post(f"/admin/election/{election_id}/participants", data={"participants": "10"})
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    with app.app_context():
        codes = get_db().execute(
            "SELECT plaintext FROM codes WHERE election_id = ?", (election_id,)
        ).fetchall()
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]["plaintext"]
        sess["election_id"] = election_id
    resp = client.get("/confirmation")
    assert resp.status_code == 200
    assert b"Assist with Paper Counting" not in resp.data


def test_confirmation_shows_assist_even_while_voting_open(client):
    """The assist button is visible whenever paper_count_enabled is on and the
    session is not yet persisted/cancelled. Voting state does not gate it,
    so voters who finish early can opt in without waiting for voting to close.
    """
    election_id, codes = _setup_paper_count_election(client)
    # Open voting and leave open
    client.post(f"/admin/election/{election_id}/voting")
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
    resp = client.get("/confirmation")
    assert resp.status_code == 200
    assert b"Assist with Paper Counting" in resp.data


def test_real_voter_submit_keeps_election_id_for_assist_button(client):
    """Regression: voter_submit must not strip election_id from session, or
    /confirmation has no way to look up paper_count_enabled and the assist
    button never renders. Drives the real voter flow end-to-end (POST /vote,
    POST /submit, then admin closes voting, then GET /confirmation).
    """
    election_id, codes = _setup_paper_count_election(client)
    # Open voting (single toggle - leave open so we can submit a vote).
    client.post(f"/admin/election/{election_id}/voting")

    # Real voter flow: enter code, then submit ballot.
    resp = client.post("/vote", data={"code": codes[0]})
    assert resp.status_code in (200, 302)
    resp = client.post("/submit", data={"confirm_partial": "1"})
    assert resp.status_code in (200, 302)
    # Voter has been redirected to /confirmation. election_id MUST still be in
    # the session at this point.
    with client.session_transaction() as sess:
        assert sess.get("election_id") == election_id, (
            "voter_submit stripped election_id from session - confirmation "
            "page cannot determine paper_count_enabled"
        )
        assert sess.get("used_code") == codes[0]

    # Admin closes voting so paper-count assist becomes active.
    client.post(f"/admin/election/{election_id}/voting")

    # /confirmation should now show the assist button.
    resp = client.get("/confirmation")
    assert resp.status_code == 200
    assert b"Assist with Paper Counting" in resp.data

    # And /count/join should succeed (it also reads election_id from session).
    resp = client.post("/count/join", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/count/")


# ---------------------------------------------------------------------------
# Admin paper count dashboard skeleton (Task 8)
# ---------------------------------------------------------------------------

def test_admin_count_dashboard_renders(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    with client.session_transaction() as sess:
        sess["admin"] = True
    resp = client.get(f"/admin/election/{election_id}/count/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Paper Count - Round 1" in body
    assert "Persist Paper Ballot Count" in body


def test_admin_count_dashboard_404_when_disabled(client):
    election_id = _create_election(client)
    # Don't enable paper count
    with client.session_transaction() as sess:
        sess["admin"] = True
    resp = client.get(f"/admin/election/{election_id}/count/1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# State endpoint + consensus calculation (Task 9)
# ---------------------------------------------------------------------------

def test_state_endpoint_returns_consensus(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sids = []
    cands = _candidate_ids(election_id)
    for c in codes[:3]:
        sids.append(_join_count(client, election_id, c))
        client.post(f"/count/{sids[-1]}/tap", json={"candidate_id": cands[0], "delta": 1})
        client.post(f"/count/{sids[-1]}/tap", json={"candidate_id": cands[0], "delta": 1})
    sid = sids[0]
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    assert r.status_code == 200
    data = r.get_json()
    assert data["helper_count"] == 3
    cand_state = next(c for c in data["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "ok"
    assert cand_state["consensus"]["value"] == 2


def test_state_endpoint_marks_mismatch(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    cands = _candidate_ids(election_id)
    for i, c in enumerate(codes[:3]):
        sid = _join_count(client, election_id, c)
        n = 2 if i == 2 else 1
        for _ in range(n):
            client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    data = r.get_json()
    cand_state = next(c for c in data["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "mismatch"


def test_state_endpoint_excludes_idle_helpers(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    cands = _candidate_ids(election_id)
    for c in codes[:3]:
        sid = _join_count(client, election_id, c)
        client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    data = r.get_json()
    cand_state = next(c for c in data["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "ok"
    assert cand_state["consensus"]["value"] == 1


def test_disregard_excludes_helper_from_consensus(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    cands = _candidate_ids(election_id)
    # 3 helpers; third one wildly off
    for i, c in enumerate(codes[:3]):
        sid = _join_count(client, election_id, c)
        n = 5 if i == 2 else 1
        for _ in range(n):
            client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})

    with app.app_context():
        third = get_db().execute(
            "SELECT id FROM count_session_helpers WHERE voter_code = ?", (codes[2],)
        ).fetchone()
        third_id = third["id"]

    with client.session_transaction() as sess:
        sess["admin"] = True
    # Mismatch before
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    cand_state = next(c for c in r.get_json()["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "mismatch"

    # Disregard third
    r = client.post(f"/admin/election/{election_id}/count/1/disregard", json={
        "helper_id": third_id, "disregard": True
    })
    assert r.status_code == 200

    # After disregarding the mismatched helper, only 2 helpers remain reporting on cand[0],
    # so consensus is "insufficient" (need 3+)
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    cand_state = next(c for c in r.get_json()["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "insufficient"

    # Restore
    r = client.post(f"/admin/election/{election_id}/count/1/disregard", json={
        "helper_id": third_id, "disregard": False
    })
    assert r.status_code == 200
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    cand_state = next(c for c in r.get_json()["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "mismatch"


def test_persist_writes_results_and_marks_session(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    cands = _candidate_ids(election_id)
    for c in codes[:3]:
        sid = _join_count(client, election_id, c)
        client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
        client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
        client.post(f"/count/{sid}/done", json={})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 2}
    })
    assert r.status_code == 200
    with app.app_context():
        sess = get_db().execute(
            "SELECT * FROM count_sessions WHERE election_id = ?", (election_id,)
        ).fetchone()
        assert sess["status"] == "persisted"
        results = get_db().execute(
            "SELECT * FROM count_session_results WHERE session_id = ?", (sess["id"],)
        ).fetchall()
        cand0 = next(r for r in results if r["candidate_id"] == cands[0])
        assert cand0["final_count"] == 2


def test_persist_rejected_when_already_persisted(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 1}
    })
    assert r.status_code == 200
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 1}
    })
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Soft / hard reset integration (Task 13)
# ---------------------------------------------------------------------------

def test_soft_reset_cancels_active_count_session(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(
        f"/admin/election/{election_id}/soft-reset",
        data={"confirm_text": "RESET", "password": "admin"},
    )
    assert r.status_code in (200, 302)
    with app.app_context():
        s = get_db().execute(
            "SELECT * FROM count_sessions WHERE election_id = ?", (election_id,)
        ).fetchone()
        assert s["status"] == "cancelled"


def test_hard_reset_deletes_count_data(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")
    sid = _join_count(client, election_id, codes[0])
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(
        f"/admin/election/{election_id}/hard-reset",
        data={"confirm_text": "HARD RESET", "password": "admin"},
    )
    assert r.status_code in (200, 302)
    with app.app_context():
        n_sess = get_db().execute(
            "SELECT COUNT(*) AS n FROM count_sessions WHERE election_id = ?",
            (election_id,)
        ).fetchone()["n"]
        n_helpers = get_db().execute(
            "SELECT COUNT(*) AS n FROM count_session_helpers"
        ).fetchone()["n"]
        assert n_sess == 0
        assert n_helpers == 0


# ---------------------------------------------------------------------------
# Final audit: regression + feature-flag isolation (Task 15)
# ---------------------------------------------------------------------------

def test_persist_does_not_disturb_existing_vote_tables(client):
    """Regression: persisting paper count must not modify votes / paper_votes /
    codes tables. Drives a real digital vote first so votes and codes both have
    rows, then runs a count session through to persist, then asserts the row
    counts in the existing tables are unchanged.
    """
    election_id, codes = _setup_paper_count_election(client)
    cands = _candidate_ids(election_id)

    # Open voting and submit a real digital vote so /votes table has rows and
    # /codes has a used=1 row.
    client.post(f"/admin/election/{election_id}/voting")
    resp = client.post("/vote", data={"code": codes[0]})
    assert resp.status_code in (200, 302)
    resp = client.post("/submit", data={
        f"office_{_office_id(election_id)}": str(cands[0]),
        "confirm_partial": "1",
    })
    assert resp.status_code in (200, 302)

    # Snapshot row counts before paper-count persist
    with app.app_context():
        db = get_db()
        before_votes = db.execute("SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
        before_paper = db.execute("SELECT COUNT(*) AS n FROM paper_votes").fetchone()["n"]
        before_codes_used = db.execute(
            "SELECT COUNT(*) AS n FROM codes WHERE used = 1"
        ).fetchone()["n"]
    assert before_votes >= 1, "digital vote did not insert any rows"
    assert before_codes_used >= 1, "digital vote did not burn any code"

    # Close voting
    client.post(f"/admin/election/{election_id}/voting")

    # Run a count session through to persist using a different code
    sid = _join_count(client, election_id, codes[1])
    client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    client.post(f"/count/{sid}/done", json={})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 1}
    })
    assert r.status_code == 200

    # Snapshot AFTER persist
    with app.app_context():
        db = get_db()
        after_votes = db.execute("SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
        after_paper = db.execute("SELECT COUNT(*) AS n FROM paper_votes").fetchone()["n"]
        after_codes_used = db.execute(
            "SELECT COUNT(*) AS n FROM codes WHERE used = 1"
        ).fetchone()["n"]

    assert before_votes == after_votes, (
        f"votes row count changed from {before_votes} to {after_votes}"
    )
    assert before_paper == after_paper, (
        f"paper_votes row count changed from {before_paper} to {after_paper}"
    )
    assert before_codes_used == after_codes_used, (
        f"codes used count changed from {before_codes_used} to {after_codes_used}"
    )


def _office_id(election_id):
    with app.app_context():
        row = get_db().execute(
            "SELECT id FROM offices WHERE election_id = ? ORDER BY id LIMIT 1",
            (election_id,)
        ).fetchone()
        return row["id"]


def test_feature_is_invisible_when_disabled(client):
    """When paper_count_enabled=0, none of the new UI/routes are accessible."""
    election_id = _create_election(client)
    # Do NOT enable paper_count_enabled
    client.post(f"/admin/election/{election_id}/setup", data={
        "office_name": "Elder", "vacancies": "2", "max_selections": "2",
        "candidate_names": "Smith\nJones\nBrown\nWhite",
        "confirm_slate_override": "1",
    })
    client.post(f"/admin/election/{election_id}/codes", data={"count": "3"})
    client.post(f"/admin/election/{election_id}/participants", data={"participants": "10"})
    client.post(f"/admin/election/{election_id}/voting")
    client.post(f"/admin/election/{election_id}/voting")

    with app.app_context():
        plain_codes = [r["plaintext"] for r in get_db().execute(
            "SELECT plaintext FROM codes WHERE election_id = ?", (election_id,)
        ).fetchall()]
    with client.session_transaction() as sess:
        sess["used_code"] = plain_codes[0]
        sess["election_id"] = election_id
        sess.pop("admin", None)

    # /confirmation has no assist button
    resp = client.get("/confirmation")
    assert resp.status_code == 200
    assert b"Assist with Paper Counting" not in resp.data

    # /count/join is rejected (400 from disabled flag check)
    resp = client.post("/count/join")
    assert resp.status_code == 400

    # Admin dashboard is 404
    with client.session_transaction() as sess:
        sess["admin"] = True
    resp = client.get(f"/admin/election/{election_id}/count/1")
    assert resp.status_code == 404
