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
