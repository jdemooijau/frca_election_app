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
