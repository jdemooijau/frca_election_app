"""Tests for the paper-ballot QR scan endpoint.

The endpoint is /admin/elections/<id>/scan-ballot-result. It accepts
a JSON body {code: "..."} and returns one of:
- {"result": "match"}        when the code is currently used in the election
- {"result": "paper_only"}   when the code exists but is not used
- {"result": "unknown"}      when the code is not in this election

Match also decrements paper_ballot_count for the current round and
writes a voter_audit_log entry with result='paper_set_aside_at_count'.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db
import app as app_module


@pytest.fixture
def client():
    """Test client with a temporary database, admin session pre-set."""
    import tempfile
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with app.test_client() as c:
        with app.app_context():
            init_db()
        with c.session_transaction() as sess:
            sess["admin"] = True
        yield c
    app_module.DB_PATH = original_db_path
    import os as _os
    _os.close(db_fd)
    _os.unlink(db_path)


@pytest.fixture
def scan_election(client):
    """A seeded election in the count phase with one used and one unused code."""
    from tests.test_app import _seed_count_phase_election
    with app.app_context():
        db = get_db()
        election = _seed_count_phase_election(
            db, used_codes=["KR4T7N"], unused_codes=["AB3XY9"]
        )
    return election


def _post_scan(client, election_id, code):
    return client.post(
        f"/admin/elections/{election_id}/scan-ballot-result",
        json={"code": code},
    )


def test_match_decrements_paper_count_and_logs_audit(client, scan_election):
    eid = scan_election["id"]
    used_code = scan_election["used_codes"][0]

    rv = _post_scan(client, eid, used_code)
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "match"}

    # paper_ballot_count must have decremented by exactly 1.
    from app import app as flask_app, get_db
    with flask_app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT paper_ballot_count FROM round_counts "
            "WHERE election_id = ? AND round_number = 1",
            (eid,)
        ).fetchone()
        assert row["paper_ballot_count"] == 4  # was seeded at 5

        # An audit row must exist with the correct result string.
        audit = db.execute(
            "SELECT result, code FROM voter_audit_log "
            "WHERE election_id = ? AND result = 'paper_set_aside_at_count'",
            (eid,)
        ).fetchall()
        assert len(audit) == 1
        assert audit[0]["code"] == used_code


def test_paper_only_no_decrement_no_audit(client, scan_election):
    eid = scan_election["id"]
    unused_code = scan_election["unused_codes"][0]

    rv = _post_scan(client, eid, unused_code)
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "paper_only"}

    from app import app as flask_app, get_db
    with flask_app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT paper_ballot_count FROM round_counts "
            "WHERE election_id = ? AND round_number = 1",
            (eid,)
        ).fetchone()
        assert row["paper_ballot_count"] == 5  # unchanged

        audit_count = db.execute(
            "SELECT COUNT(*) AS n FROM voter_audit_log "
            "WHERE election_id = ? AND result = 'paper_set_aside_at_count'",
            (eid,)
        ).fetchone()["n"]
        assert audit_count == 0


def test_unknown_code_returns_unknown(client, scan_election):
    eid = scan_election["id"]
    rv = _post_scan(client, eid, "ZZZZZZ")
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "unknown"}


def test_empty_code_returns_unknown(client, scan_election):
    eid = scan_election["id"]
    rv = _post_scan(client, eid, "")
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "unknown"}


def test_endpoint_rejects_when_voting_open(client):
    from app import app as flask_app, get_db
    from tests.test_app import _seed_count_phase_election
    with flask_app.app_context():
        db = get_db()
        info = _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=[])
        db.execute("UPDATE elections SET voting_open = 1 WHERE id = ?", (info["id"],))
        db.commit()

    rv = _post_scan(client, info["id"], "KR4T7N")
    assert rv.status_code == 409
    body = rv.get_json() or {}
    assert "count phase" in (body.get("error") or "").lower()


def test_endpoint_rejects_when_finalised(client):
    from app import app as flask_app, get_db
    from tests.test_app import _seed_count_phase_election
    with flask_app.app_context():
        db = get_db()
        info = _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=[])
        db.execute("UPDATE elections SET display_phase = 4 WHERE id = ?", (info["id"],))
        db.commit()

    rv = _post_scan(client, info["id"], "KR4T7N")
    assert rv.status_code == 409
    body = rv.get_json() or {}
    assert "count phase" in (body.get("error") or "").lower()


