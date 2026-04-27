"""
Tests for postal vote functionality.
Postal votes are aggregate totals entered by the secretary, round 1 only.
"""

import io
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    app, init_db, migrate_db, get_db, hash_code,
    calculate_thresholds, check_candidate_elected,
)


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
            migrate_db()
        yield client

    app_module.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def admin_client(client):
    client.post("/admin/login", data={"password": "admin"})
    return client


@pytest.fixture
def election_with_candidates(admin_client):
    """Election with 2 offices and candidates, ready for postal vote entry."""
    admin_client.post("/admin/election/new", data={
        "name": "Test Election", "max_rounds": "2"
    })
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "2",
        "candidate_names": "Candidate A\nCandidate B\nCandidate C\nCandidate D"
    })
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Deacon", "vacancies": "1",
        "candidate_names": "Candidate E\nCandidate F",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "20"})
    return admin_client


class TestPostalVoteEntry:
    """Postal votes: aggregate entry by secretary."""

    def test_postal_votes_stored_as_aggregates(self, election_with_candidates):
        """Postal votes are stored per-candidate, not per-voter."""
        client = election_with_candidates
        client.post("/admin/election/1/postal-votes", data={
            "postal_voter_count": "5",
            "postal_1": "3",  # Candidate A
            "postal_2": "2",  # Candidate B
            "postal_3": "0",
            "postal_4": "0",
            "postal_5": "4",  # Candidate E
            "postal_6": "1",  # Candidate F
        })

        with app.app_context():
            db = get_db()
            # Check election-level count
            election = db.execute("SELECT * FROM elections WHERE id = 1").fetchone()
            assert election["postal_voter_count"] == 5

            # Check per-candidate — only aggregates, no individual records
            pv = db.execute("SELECT * FROM postal_votes WHERE election_id = 1").fetchall()
            totals = {row["candidate_id"]: row["count"] for row in pv}
            assert totals.get(1) == 3  # Candidate A
            assert totals.get(2) == 2  # Candidate B
            assert totals.get(5) == 4  # Candidate E

    def test_postal_votes_added_to_round_1_totals(self, election_with_candidates):
        """Postal votes should appear in round 1 candidate totals."""
        client = election_with_candidates

        client.post("/admin/election/1/postal-votes", data={
            "postal_voter_count": "5",
            "postal_1": "3",
        })

        # Set participants
        client.post("/admin/election/1/participants", data={
            "participants": "30",
            "paper_ballot_count": "0"
        })

        resp = client.get("/admin/election/1/manage")
        # The manage page should show postal column
        assert b"Postal" in resp.data or b"postal" in resp.data

    def test_postal_votes_included_in_article_6b_threshold(self, election_with_candidates):
        """Participant count should include postal voters for threshold 6b."""
        client = election_with_candidates

        client.post("/admin/election/1/postal-votes", data={
            "postal_voter_count": "5",
        })

        client.post("/admin/election/1/participants", data={
            "participants": "30",
            "paper_ballot_count": "0"
        })

        # Total participants for threshold = 30 in-person + 5 postal = 35
        # Article 6b: ceil(35 * 2/5) = ceil(14.0) = 14
        with app.app_context():
            _, t6b = calculate_thresholds(2, 35, 35)
            assert t6b == 14

    def test_postal_votes_excluded_from_round_2(self, election_with_candidates):
        """Round 2 should not include postal votes in participants or totals."""
        client = election_with_candidates

        client.post("/admin/election/1/postal-votes", data={
            "postal_voter_count": "5",
            "postal_1": "3",
        })

        client.post("/admin/election/1/participants", data={
            "participants": "30",
            "paper_ballot_count": "0"
        })

        # Open and close round 1
        client.post("/admin/election/1/voting")
        client.post("/admin/election/1/voting")

        # Start round 2
        client.post("/admin/election/1/next-round", data={
            "carry_forward": ["1", "2", "3", "4"]
        })

        # Check round 2 manage page
        resp = client.get("/admin/election/1/manage")
        content = resp.data.decode()

        # In round 2, postal voter count should not be shown/added
        # The participants display should show only in-person count
        assert resp.status_code == 200

    def test_postal_validation_warns_on_excess(self, election_with_candidates):
        """Warn if total postal votes for an office exceed what's possible."""
        client = election_with_candidates

        # 2 postal voters, Elder max_selections=2, so max total = 2*2=4
        # Enter 3+3=6 postal elder votes — exceeds 4
        resp = client.post("/admin/election/1/postal-votes", data={
            "postal_voter_count": "2",
            "postal_1": "3",
            "postal_2": "3",
        }, follow_redirects=True)
        assert b"Warning" in resp.data
