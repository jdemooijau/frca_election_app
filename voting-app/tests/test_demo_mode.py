"""Tests for demo mode behaviours."""

import io
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db, set_setting, get_setting, generate_codes, hash_code


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
def admin_client(client):
    """A test client already logged in as admin."""
    client.post("/admin/login", data={"password": "admin"})
    return client


@pytest.fixture
def demo_client(admin_client):
    """A test client with demo mode enabled."""
    with app.app_context():
        set_setting("is_demo", "1")
    return admin_client


# ---------------------------------------------------------------------------
# Banner tests (removed — demo banner feature was dropped)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Name generation tests
# ---------------------------------------------------------------------------

from demo_names import generate_demo_names, FIRST_NAMES, FALLBACK_ELDER_CANDIDATES, FALLBACK_DEACON_CANDIDATES


def test_seed_demo_generates_ten_unique_candidates():
    names = generate_demo_names(count=10, member_names=[])
    assert len(names) == 10
    assert len(set(names)) == 10


def test_seed_demo_uses_fallback_when_no_member_database():
    names = generate_demo_names(count=10, member_names=[])
    expected = FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES
    assert names == expected


def test_seed_demo_candidates_do_not_match_member_database():
    member_names = ["Jan van Dijk", "Pieter de Groot", "Klaas Brouwer", "Hendrik Bakker"]
    names = generate_demo_names(count=8, member_names=member_names)
    assert len(names) == 8
    member_surnames = set()
    for m in member_names:
        parts = m.split()
        if len(parts) > 1:
            member_surnames.add(" ".join(parts[1:]).lower())
    for name in names:
        parts = name.split()
        if len(parts) > 1:
            generated_surname = " ".join(parts[1:]).lower()
            assert generated_surname not in member_surnames, f"Generated name '{name}' matches a member surname"


def test_name_generation_with_mashup():
    """When member names are provided, names should be mashed up (not fallback)."""
    member_names = [
        "Jan van Dijk", "Pieter de Groot", "Klaas Brouwer",
        "Hendrik Bakker", "Willem Visser", "Gerrit Mulder",
        "Cornelis Dijkstra", "Bastiaan Kempenaar",
    ]
    names = generate_demo_names(count=8, member_names=member_names)
    assert len(names) == 8
    expected_fallback = FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES
    assert names != expected_fallback


# ---------------------------------------------------------------------------
# Seed script tests
# ---------------------------------------------------------------------------

import subprocess


def _run_seed_script(input_text, db_path, env=None):
    """Helper to run seed_demo.py with given stdin and DB path override."""
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "scripts", "seed_demo.py")
    cmd_env = os.environ.copy()
    cmd_env["FRCA_DB_PATH"] = db_path
    cmd_env["FRCA_SKIP_PORT_CHECK"] = "1"
    if env:
        cmd_env.update(env)
    result = subprocess.run(
        [sys.executable, script_path],
        input=input_text,
        capture_output=True,
        text=True,
        env=cmd_env,
        timeout=30,
    )
    return result


def test_seed_demo_requires_confirmation(tmp_path):
    db_path = str(tmp_path / "test.db")
    result = _run_seed_script("NO\n", db_path)
    assert result.returncode != 0 or "Aborted" in result.stdout


def test_seed_demo_sets_demo_flag(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    result = _run_seed_script("YES\n", db_path)
    assert result.returncode == 0, f"Script failed: {result.stderr}\n{result.stdout}"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT value FROM settings WHERE key = 'is_demo'").fetchone()
    conn.close()
    assert row is not None
    assert row["value"] == "1"


def test_seed_demo_creates_demo_election(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    result = _run_seed_script("YES\n", db_path)
    assert result.returncode == 0, f"Script failed: {result.stderr}\n{result.stdout}"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    election = conn.execute("SELECT * FROM elections LIMIT 1").fetchone()
    conn.close()
    assert election is not None
    assert "DEMO" in election["name"]


def test_seed_demo_creates_twenty_codes(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    _run_seed_script("YES\n", db_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
    conn.close()
    assert count == 20


def test_seed_demo_sets_congregation_to_darling_downs(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    _run_seed_script("YES\n", db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT value FROM settings WHERE key = 'congregation_name'").fetchone()
    conn.close()
    assert "Darling Downs" in row["value"]


# ---------------------------------------------------------------------------
# Reset script tests
# ---------------------------------------------------------------------------

def _run_reset_script(input_text, db_path):
    """Helper to run reset_app.py with given stdin and DB path override."""
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "scripts", "reset_app.py")
    cmd_env = os.environ.copy()
    cmd_env["FRCA_DB_PATH"] = db_path
    cmd_env["FRCA_SKIP_PORT_CHECK"] = "1"
    result = subprocess.run(
        [sys.executable, script_path],
        input=input_text, capture_output=True, text=True,
        env=cmd_env, timeout=30,
    )
    return result


def test_reset_app_requires_confirmation(tmp_path):
    db_path = str(tmp_path / "test.db")
    _run_seed_script("YES\n", db_path)
    result = _run_reset_script("NO\n", db_path)
    assert result.returncode != 0 or "Aborted" in result.stdout


def test_reset_app_clears_demo_flag(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    _run_seed_script("YES\n", db_path)
    _run_reset_script("YES\n", db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT value FROM settings WHERE key = 'is_demo'").fetchone()
    conn.close()
    assert row is None or row["value"] == "0"


def test_reset_app_clears_settings(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    _run_seed_script("YES\n", db_path)
    _run_reset_script("YES\n", db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT value FROM settings WHERE key = 'setup_complete'").fetchone()
    conn.close()
    assert row is not None and row["value"] == "0"


# ---------------------------------------------------------------------------
# Lenient code entry tests
# ---------------------------------------------------------------------------

@pytest.fixture
def demo_election(demo_client):
    """Set up a demo election with offices, candidates, and codes."""
    demo_client.post("/admin/election/new", data={
        "name": "Demo Election (DEMO)", "max_rounds": "2",
    })
    demo_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "2", "max_selections": "2",
        "candidate_names": "Pieter van Rijksen\nHendrik Brouwerhof\nWillem de Kempenaar\nGerrit van Dijkstra",
    })
    demo_client.post("/admin/election/1/codes", data={"count": "20"})
    demo_client.post("/admin/election/1/voting")
    return demo_client


def test_demo_mode_accepts_invalid_code_with_notice(demo_election):
    resp = demo_election.post("/vote", data={"code": "XXXXXX"}, follow_redirects=True)
    assert b"Demo mode" in resp.data or b"demo" in resp.data.lower()


def test_demo_mode_accepts_blank_code_with_notice(demo_election):
    resp = demo_election.post("/vote", data={"code": ""}, follow_redirects=True)
    assert b"Demo mode" in resp.data or b"demo" in resp.data.lower()


def test_production_mode_rejects_invalid_code_strictly(client):
    client.post("/admin/login", data={"password": "admin"})
    client.post("/admin/election/new", data={"name": "Real Election", "max_rounds": "2"})
    client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "Real Candidate A\nReal Candidate B",
    })
    client.post("/admin/election/1/codes", data={"count": "10"})
    client.post("/admin/election/1/voting")
    resp = client.post("/vote", data={"code": "XXXXXX"}, follow_redirects=True)
    assert b"Invalid code" in resp.data


def test_production_mode_rejects_blank_code(client):
    client.post("/admin/login", data={"password": "admin"})
    client.post("/admin/election/new", data={"name": "Real Election", "max_rounds": "2"})
    client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "Real Candidate A\nReal Candidate B",
    })
    client.post("/admin/election/1/codes", data={"count": "10"})
    client.post("/admin/election/1/voting")
    resp = client.post("/vote", data={"code": ""}, follow_redirects=True)
    assert b"valid 6-character code" in resp.data


def test_demo_mode_handles_exhausted_code_pool(demo_client):
    """When all demo codes are used, voter still gets the standard invalid code error."""
    demo_client.post("/admin/election/new", data={
        "name": "Demo Election (DEMO)", "max_rounds": "2",
    })
    demo_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "Candidate A\nCandidate B",
    })
    demo_client.post("/admin/election/1/codes", data={"count": "1"})
    demo_client.post("/admin/election/1/voting")
    # Mark all codes as used
    with app.app_context():
        db = get_db()
        db.execute("UPDATE codes SET used = 1")
        db.commit()
    resp = demo_client.post("/vote", data={"code": "XXXXXX"}, follow_redirects=True)
    assert b"Invalid code" in resp.data


# ---------------------------------------------------------------------------
# Admin button tests
# ---------------------------------------------------------------------------

def test_load_demo_button_visible_when_no_real_election(admin_client):
    with app.app_context():
        set_setting("setup_complete", "1")
    resp = admin_client.get("/admin")
    assert b"Load Demo Election" in resp.data


def test_exit_demo_button_only_visible_in_demo_mode(admin_client):
    with app.app_context():
        set_setting("setup_complete", "1")
    resp = admin_client.get("/admin")
    assert b"Exit Demo" not in resp.data
    with app.app_context():
        set_setting("is_demo", "1")
    resp = admin_client.get("/admin")
    assert b"Exit Demo" in resp.data


def test_load_demo_button_requires_typed_confirmation(admin_client):
    resp = admin_client.post("/admin/load-demo", data={
        "confirm_text": "WRONG TEXT", "password": "admin",
    }, follow_redirects=True)
    assert b"LOAD DEMO" in resp.data or b"confirmation" in resp.data.lower()


def test_load_demo_button_requires_password_reentry(admin_client):
    resp = admin_client.post("/admin/load-demo", data={
        "confirm_text": "LOAD DEMO", "password": "wrong_password",
    }, follow_redirects=True)
    assert b"password" in resp.data.lower() or b"incorrect" in resp.data.lower()


def test_load_demo_button_runs_seed_logic(admin_client):
    resp = admin_client.post("/admin/load-demo", data={
        "confirm_text": "LOAD DEMO", "password": "admin",
    }, follow_redirects=True)
    assert b"Demo election loaded" in resp.data
    with app.app_context():
        assert get_setting("is_demo") == "1"


def test_exit_demo_button_requires_typed_confirmation(demo_client):
    resp = demo_client.post("/admin/exit-demo", data={
        "confirm_text": "WRONG", "password": "admin",
    }, follow_redirects=True)
    assert b"RESET" in resp.data or b"confirmation" in resp.data.lower()


def test_exit_demo_button_runs_reset_logic(demo_client):
    demo_client.post("/admin/load-demo", data={
        "confirm_text": "LOAD DEMO", "password": "admin",
    })
    resp = demo_client.post("/admin/exit-demo", data={
        "confirm_text": "RESET", "password": "admin",
    }, follow_redirects=True)
    with app.app_context():
        assert get_setting("is_demo", "0") == "0"


# ---------------------------------------------------------------------------
# Dual Ballot Handout PDF tests
# ---------------------------------------------------------------------------

def test_dual_ballot_pdf_only_available_in_demo_mode(admin_client):
    admin_client.post("/admin/election/new", data={"name": "Test", "max_rounds": "2"})
    resp = admin_client.get("/admin/election/1/dual-ballot-pdf")
    assert resp.status_code == 403


def test_dual_ballot_pdf_returns_403_in_production_mode(admin_client):
    admin_client.post("/admin/election/new", data={"name": "Test", "max_rounds": "2"})
    resp = admin_client.get("/admin/election/1/dual-ballot-pdf")
    assert resp.status_code == 403


def test_dual_ballot_pdf_generates_in_demo_mode(demo_client):
    demo_client.post("/admin/load-demo", data={
        "confirm_text": "LOAD DEMO", "password": "admin",
    })
    with app.app_context():
        db = get_db()
        election = db.execute("SELECT * FROM elections LIMIT 1").fetchone()
    resp = demo_client.get(f"/admin/election/{election['id']}/dual-ballot-pdf")
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
