"""
Tests for FRCA Election Rules compliance (Articles 1-13).
Each test references the specific article it validates.
"""

import io
import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    app, init_db, migrate_db, get_db, generate_codes, hash_code,
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


# ---------------------------------------------------------------------------
# Article 6 — Threshold calculations (unit tests)
# ---------------------------------------------------------------------------

class TestArticle6Thresholds:
    """Article 6: candidates must meet BOTH threshold conditions."""

    def test_threshold_6a_basic(self):
        """Art 6a: 80 valid votes, 2 vacancies -> threshold = 20.0, votes=21 passes, 20 fails."""
        t6a, t6b = calculate_thresholds(2, 80, 50)
        assert t6a == 20.0
        _, p6a, _ = check_candidate_elected(21, t6a, t6b)
        assert p6a is True
        _, p6a, _ = check_candidate_elected(20, t6a, t6b)
        assert p6a is False  # strict greater than

    def test_threshold_6a_boundary_strict_greater_than(self):
        """Art 6a: votes exactly equal to threshold must FAIL (strict >)."""
        t6a, _ = calculate_thresholds(2, 60, 100)
        # 60 / (2*2) = 15.0
        assert t6a == 15.0
        _, p6a, _ = check_candidate_elected(15, t6a, 0)
        assert p6a is False  # exactly equal, must fail
        _, p6a, _ = check_candidate_elected(16, t6a, 0)
        assert p6a is True

    def test_threshold_6a_fractional(self):
        """Art 6a: 75 votes, 3 vacancies -> 75/(2*3)=12.5, votes=12 fails, 13 passes."""
        t6a, _ = calculate_thresholds(3, 75, 100)
        assert t6a == 12.5
        _, p6a, _ = check_candidate_elected(12, t6a, 0)
        assert p6a is False
        _, p6a, _ = check_candidate_elected(13, t6a, 0)
        assert p6a is True

    def test_threshold_6b_basic(self):
        """Art 6b: 85 participants -> ceil(85*2/5)=ceil(34.0)=34."""
        _, t6b = calculate_thresholds(1, 100, 85)
        assert t6b == 34
        _, _, p6b = check_candidate_elected(34, 0, t6b)
        assert p6b is True
        _, _, p6b = check_candidate_elected(33, 0, t6b)
        assert p6b is False

    def test_threshold_6b_rounding_up(self):
        """Art 6b/7: fractions round upwards. 31 participants -> ceil(31*2/5)=ceil(12.4)=13."""
        _, t6b = calculate_thresholds(1, 100, 31)
        assert t6b == 13  # 12.4 rounds up

    def test_threshold_6b_exact_integer(self):
        """Art 6b: 30 participants -> ceil(30*2/5)=ceil(12.0)=12."""
        _, t6b = calculate_thresholds(1, 100, 30)
        assert t6b == 12

    def test_both_conditions_required(self):
        """Art 6: candidate must meet BOTH 6a and 6b to be elected."""
        # 60 valid votes, 2 vacancies, 30 participants
        # 6a threshold: 60/(2*2) = 15.0 -> need > 15
        # 6b threshold: ceil(30*2/5) = 12 -> need >= 12
        t6a, t6b = calculate_thresholds(2, 60, 30)

        # Passes 6a but fails 6b (votes=16, but only 11 < 12)
        # Actually 16 > 15 (6a pass) and 16 >= 12 (6b pass) — both pass
        # Let me construct a proper case: need someone who passes one but not the other
        # With these thresholds: 6a needs > 15, 6b needs >= 12
        # A candidate with 11 votes: 11 < 15 (6a fail), 11 < 12 (6b fail)
        # A candidate with 14 votes: 14 < 15 (6a fail), 14 >= 12 (6b pass)
        elected, p6a, p6b = check_candidate_elected(14, t6a, t6b)
        assert p6a is False
        assert p6b is True
        assert elected is False  # fails 6a even though passes 6b

    def test_passes_6a_fails_6b(self):
        """Art 6: passes 6a but fails 6b -> not elected."""
        # 10 valid votes, 1 vacancy, 30 participants
        # 6a: 10/(2*1) = 5.0 -> need > 5
        # 6b: ceil(30*2/5) = 12 -> need >= 12
        t6a, t6b = calculate_thresholds(1, 10, 30)
        elected, p6a, p6b = check_candidate_elected(6, t6a, t6b)
        assert p6a is True   # 6 > 5
        assert p6b is False  # 6 < 12
        assert elected is False

    def test_single_vacancy(self):
        """Art 6: single vacancy, standard calculation."""
        # 40 valid votes, 1 vacancy, 40 participants
        # 6a: 40/(2*1) = 20.0 -> need > 20
        # 6b: ceil(40*2/5) = 16 -> need >= 16
        t6a, t6b = calculate_thresholds(1, 40, 40)
        assert t6a == 20.0
        assert t6b == 16

        elected, _, _ = check_candidate_elected(21, t6a, t6b)
        assert elected is True
        elected, _, _ = check_candidate_elected(20, t6a, t6b)
        assert elected is False  # exactly 20, need > 20

    def test_zero_vacancies_safe(self):
        """Edge case: zero vacancies should not crash."""
        t6a, t6b = calculate_thresholds(0, 60, 30)
        assert t6a == 0
        assert t6b == 0


# ---------------------------------------------------------------------------
# Article 2 — Slate size validation
# ---------------------------------------------------------------------------

class TestArticle2SlateValidation:
    """Article 2: slate should be twice the number of vacancies."""

    def test_correct_slate_size_no_warning(self, admin_client):
        """4 candidates for 2 vacancies — no warning."""
        admin_client.post("/admin/election/new", data={
            "name": "Test", "max_rounds": "1"
        })
        resp = admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder",
            "vacancies": "2",
            "candidate_names": "A\nB\nC\nD"
        }, follow_redirects=True)
        assert b"Article 2 requires" not in resp.data  # no warning flash
        assert b"added" in resp.data

    def test_wrong_slate_size_shows_warning(self, admin_client):
        """3 candidates for 2 vacancies — Article 2 warning."""
        admin_client.post("/admin/election/new", data={
            "name": "Test", "max_rounds": "1"
        })
        resp = admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder",
            "vacancies": "2",
            "candidate_names": "A\nB\nC"
        }, follow_redirects=True)
        assert b"Article 2" in resp.data

    def test_override_slate_warning(self, admin_client):
        """Override Article 2 warning with confirmation (Article 13)."""
        admin_client.post("/admin/election/new", data={
            "name": "Test", "max_rounds": "1"
        })
        resp = admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder",
            "vacancies": "2",
            "candidate_names": "A\nB\nC",
            "confirm_slate_override": "1"
        }, follow_redirects=True)
        assert b"Article 13 deviation" in resp.data
        assert b"added" in resp.data


# ---------------------------------------------------------------------------
# Article 7 — Partial ballots and over-selection
# ---------------------------------------------------------------------------

class TestArticle7Ballots:
    """Article 7: partial ballots valid, over-selection blocked."""

    def test_partial_ballot_valid(self, admin_client):
        """Art 7: selecting fewer than max is a valid vote."""
        admin_client.post("/admin/election/new", data={
            "name": "Test", "max_rounds": "1"
        })
        admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder", "vacancies": "2",
            "candidate_names": "A\nB\nC\nD"
        })
        admin_client.post("/admin/election/1/codes", data={"count": "5"})
        admin_client.post("/admin/election/1/voting")

        # Create a test code and vote for only 1 candidate (max is 2)
        test_code = "PARTST"
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO codes (election_id, code_hash) VALUES (1, ?)",
                (hash_code(test_code),)
            )
            db.commit()

        admin_client.post("/vote", data={"code": test_code})
        # First submit triggers partial warning
        resp = admin_client.post("/submit", data={"office_1": "1"})
        assert resp.status_code == 200  # Re-rendered ballot with warning
        # Second submit with confirm
        resp = admin_client.post("/submit", data={"office_1": "1", "confirm_partial": "1"})
        assert resp.status_code == 302  # Redirect to confirmation

        with app.app_context():
            db = get_db()
            votes = db.execute("SELECT COUNT(*) FROM votes WHERE candidate_id = 1").fetchone()[0]
            assert votes == 1

    def test_over_selection_blocked(self, admin_client):
        """Art 7: selecting more than max is rejected server-side."""
        admin_client.post("/admin/election/new", data={
            "name": "Test", "max_rounds": "1"
        })
        admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder", "vacancies": "1",
            "candidate_names": "A\nB",
        })
        admin_client.post("/admin/election/1/codes", data={"count": "5"})
        admin_client.post("/admin/election/1/voting")

        test_code = "OVRTST"
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO codes (election_id, code_hash) VALUES (1, ?)",
                (hash_code(test_code),)
            )
            db.commit()

        admin_client.post("/vote", data={"code": test_code})
        # Try selecting 2 candidates when max is 1
        resp = admin_client.post("/submit", data={
            "office_1": ["1", "2"]
        }, follow_redirects=True)
        assert b"Too many selections" in resp.data


# ---------------------------------------------------------------------------
# Article 10 — Retiring office bearer flag
# ---------------------------------------------------------------------------

class TestArticle10:
    """Article 10: retiring office bearer flag."""

    def test_retiring_flag_stored(self, admin_client):
        """Retiring flag should be stored on candidates."""
        admin_client.post("/admin/election/new", data={
            "name": "Test", "max_rounds": "1"
        })
        # For now, retiring flag is set via direct DB (UI enhancement pending)
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO offices (election_id, name, max_selections, vacancies, sort_order) VALUES (1, 'Elder', 1, 1, 1)"
            )
            db.execute(
                "INSERT INTO candidates (office_id, name, sort_order, retiring_office_bearer) VALUES (1, 'Test', 1, 1)"
            )
            db.commit()
            cand = db.execute("SELECT * FROM candidates WHERE id = 1").fetchone()
            assert cand["retiring_office_bearer"] == 1


# ---------------------------------------------------------------------------
# Article 6a — Reading A (council-confirmed)
# ---------------------------------------------------------------------------

class TestArticle6aReadingA:
    """
    Reading A: "valid votes cast" in Article 6a means the per-office sum
    of ticks recorded for candidates. Blank ballots/slots and spoilt
    ballots do NOT count toward the denominator.

    See voting-app/docs/ELECTION_RULES.md for rule text and decision
    provenance.
    """

    def test_threshold_uses_candidate_tick_sum_not_ballots(self):
        """The chairman's worked example: 100 ballots, 1 vacancy, 4 cands,
        Br. A 49, B 32, C 10, D 4, blanks 3, spoilts 2.

        Reading A: valid_votes_cast = 95 (sum of ticks). Threshold = 47.5.
        Br. A at 49 passes (would have failed under "all ballots count").
        """
        t6a, _ = calculate_thresholds(1, 95, 100)
        assert t6a == 47.5
        # Br. A at 49 passes Reading A
        _, p6a, _ = check_candidate_elected(49, t6a, 0)
        assert p6a is True
        # Same candidate, but if we'd used "all ballots" (100), threshold
        # would have been 50.0 and Br. A would have failed.
        t6a_old, _ = calculate_thresholds(1, 100, 100)
        assert t6a_old == 50.0
        _, p6a_old, _ = check_candidate_elected(49, t6a_old, 0)
        assert p6a_old is False

    def test_blank_ballots_excluded_from_denominator(self):
        """A protest scenario: 100 brothers, 50 blank, 50 vote 26/24.

        Under Reading A, valid_votes_cast = 50. Threshold = 25.
        Br. A at 26 PASSES Article 6a alone — but Article 6b is
        designed to catch this: it uses participants (100), so the
        floor is 40, and A at 26 fails 6b. Test that 6a is permissive
        but 6b is the safety net.
        """
        t6a, t6b = calculate_thresholds(1, 50, 100)
        assert t6a == 25.0
        assert t6b == 40
        meets, p6a, p6b = check_candidate_elected(26, t6a, t6b)
        assert p6a is True   # passes 6a
        assert p6b is False  # fails 6b — caught by participation floor
        assert meets is False

    def test_multi_vacancy_per_office_denominator(self):
        """2 vacancies, 4 cands, 100 ballots all fully filled (200 ticks).

        Reading A: per-office threshold = 200 / (2 * 2) = 50.
        """
        t6a, _ = calculate_thresholds(2, 200, 100)
        assert t6a == 50.0


# ---------------------------------------------------------------------------
# Spoilt ballots — schema, persistence, threshold isolation
# ---------------------------------------------------------------------------

class TestSpoiltBallots:
    """
    Spoilt ballots are wrongly-filled paper ballots (Article 7). They are
    counted toward attendance but excluded from "valid votes cast" by
    definition. Tracked separately from blank ballots for audit clarity.
    """

    def test_spoilt_table_exists(self, client):
        """Migration creates office_spoilt_ballots table with correct schema."""
        with app.app_context():
            db = get_db()
            cols = [r["name"] for r in db.execute(
                "PRAGMA table_info(office_spoilt_ballots)"
            ).fetchall()]
            assert "election_id" in cols
            assert "round_number" in cols
            assert "office_id" in cols
            assert "count" in cols

    def test_spoilt_count_persists_via_paper_votes_form(self, admin_client):
        """POSTing spoilt_<office_id> on paper-votes form saves the count."""
        admin_client.post(
            "/admin/election/new",
            data={"name": "T", "max_rounds": "1"},
        )
        admin_client.post(
            "/admin/election/1/setup",
            data={
                "office_name": "Elder",
                "vacancies": "1",
                "max_selections": "1",
                "candidate_names": "A\nB",
                "confirm_slate_override": "1",
            },
        )
        admin_client.post("/admin/election/1/codes", data={"count": "5"})

        # POST paper-votes with spoilt count for office 1
        admin_client.post(
            "/admin/election/1/paper-votes",
            data={"paper_1": "0", "paper_2": "0", "spoilt_1": "3"},
        )

        with app.app_context():
            db = get_db()
            row = db.execute(
                "SELECT count FROM office_spoilt_ballots "
                "WHERE election_id = 1 AND round_number = 1 AND office_id = 1"
            ).fetchone()
            assert row is not None
            assert row["count"] == 3

    def test_spoilt_count_does_not_affect_threshold(self):
        """Spoilt ballots are excluded by definition. The threshold formula
        takes only the per-office candidate-tick sum; spoilts never enter."""
        # 95 candidate ticks, 100 ballots, 5 of which are spoilt.
        # threshold = 95 / 2 = 47.5 regardless of how many were spoilt vs blank.
        t6a, _ = calculate_thresholds(1, 95, 100)
        assert t6a == 47.5
