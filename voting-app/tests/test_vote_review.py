"""
Tests for the voter review/confirm screen with countdown auto-confirm.
"""

import os
import sys
import tempfile

import pytest

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    app, init_db, get_db, hash_code, get_vote_confirm_seconds, set_setting,
)


@pytest.fixture
def client():
    """Create a test client with a temporary database."""
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
def voting_client(client):
    """Admin-created election with open voting and a valid code entered."""
    client.post("/admin/login", data={"password": "admin"})
    client.post("/admin/election/new", data={"name": "Test", "max_rounds": "1"})
    client.post("/admin/election/1/setup", data={
        "office_name": "Elder",
        "vacancies": "2",
        "max_selections": "2",
        "candidate_names": "Candidate A\nCandidate B\nCandidate C",
        "confirm_slate_override": "1",
    })
    client.post("/admin/election/1/codes", data={"count": "5"})
    client.post("/admin/election/1/participants", data={"participants": "5"})
    client.post("/admin/election/1/voting")

    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO codes (election_id, code_hash) VALUES (1, ?)",
            (hash_code("RVWTST"),)
        )
        db.commit()
    client.post("/vote", data={"code": "RVWTST"})
    return client


def _votes_count():
    with app.app_context():
        return get_db().execute("SELECT COUNT(*) FROM votes").fetchone()[0]


class TestReviewScreen:
    def test_first_submit_shows_review_not_cast(self, voting_client):
        resp = voting_client.post("/submit", data={"office_1": ["1", "2"]})
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Check your selection" in body
        assert "Candidate A" in body and "Candidate B" in body
        assert "Candidate C" not in body.split("Check your selection")[1].split("<form")[0]
        assert "cast automatically" in body
        assert "Change My Selection" in body
        # Nothing recorded yet, code not burned
        assert _votes_count() == 0
        with app.app_context():
            used = get_db().execute(
                "SELECT used FROM codes WHERE code_hash = ?",
                (hash_code("RVWTST"),)).fetchone()["used"]
        assert used == 0

    def test_confirmed_submit_casts(self, voting_client):
        resp = voting_client.post(
            "/submit", data={"office_1": ["1", "2"], "confirmed": "1"})
        assert resp.status_code == 302
        assert _votes_count() == 2
        with app.app_context():
            used = get_db().execute(
                "SELECT used FROM codes WHERE code_hash = ?",
                (hash_code("RVWTST"),)).fetchone()["used"]
        assert used == 1

    def test_legacy_confirm_partial_still_casts(self, voting_client):
        resp = voting_client.post(
            "/submit", data={"office_1": "1", "confirm_partial": "1"})
        assert resp.status_code == 302
        assert _votes_count() == 1

    def test_change_rerenders_ballot_with_selection(self, voting_client):
        resp = voting_client.post(
            "/submit", data={"office_1": "1", "change": "1"})
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Cast Your Vote" in body  # back on the ballot
        assert 'value="1"\n                       checked' in body or "checked" in body
        assert _votes_count() == 0

    def test_under_selection_warns_on_review(self, voting_client):
        resp = voting_client.post("/submit", data={"office_1": "1"})
        body = resp.data.decode()
        assert "Check your selection" in body
        assert "not used all your votes" in body

    def test_blank_ballot_review_shows_blank(self, voting_client):
        resp = voting_client.post("/submit", data={})
        body = resp.data.decode()
        assert "Check your selection" in body
        assert "No selection (blank)" in body

    def test_review_embeds_countdown_seconds(self, voting_client):
        with app.app_context():
            set_setting("vote_confirm_seconds", "12")
        resp = voting_client.post("/submit", data={"office_1": "1"})
        body = resp.data.decode()
        assert "var secs = 12" in body

    def test_over_selection_still_blocked(self, voting_client):
        resp = voting_client.post(
            "/submit", data={"office_1": ["1", "2", "3"]},
            follow_redirects=True)
        assert b"Too many selections" in resp.data
        assert _votes_count() == 0


class TestConfirmSecondsSetting:
    def test_default_and_clamping(self, client):
        with app.app_context():
            assert get_vote_confirm_seconds() == 8
            set_setting("vote_confirm_seconds", "1")
            assert get_vote_confirm_seconds() == 3
            set_setting("vote_confirm_seconds", "120")
            assert get_vote_confirm_seconds() == 60
            set_setting("vote_confirm_seconds", "junk")
            assert get_vote_confirm_seconds() == 8
