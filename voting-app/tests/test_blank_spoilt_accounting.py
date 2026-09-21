"""Blank votes and spoilt ballots are accounted for on every results
surface: the admin tally, the historical round results page, the
projector, and the minutes. Blanks and spoilt ballots stay outside the
Article 6a denominator; this is accounting only.

Seed: one office (Elder, 3 selections), 4 paper ballots, no digital,
no postal. Candidate ticks 4 + 2 + 2 = 8. One spoilt ballot = 3 spoilt
selections. Possible = 4 x 3 = 12, so blank = 12 - 8 - 3 = 1.
"""
import os
import sys
from io import BytesIO

import re

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app, get_db, init_db  # noqa: E402
import app as app_module  # noqa: E402
import tempfile  # noqa: E402


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    flask_app.config["TESTING"] = True
    original = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with flask_app.test_client() as c:
        with flask_app.app_context():
            init_db()
        yield c
    app_module.DB_PATH = original
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _seed(db, spoilt=1, ticks=(4, 2, 2), show_results=0, current_round=1):
    cur = db.execute(
        "INSERT INTO elections (name, election_date, current_round, max_rounds, "
        "voting_open, show_results, display_phase, paper_count_enabled) "
        "VALUES (?, ?, ?, 3, 0, ?, 3, 0)",
        ("Blank Spoilt Election", "2026-10-18", current_round, show_results),
    )
    eid = cur.lastrowid
    cur = db.execute(
        "INSERT INTO offices (election_id, name, max_selections, vacancies, "
        "original_vacancies, sort_order) VALUES (?, 'Elder', 3, 3, 3, 1)",
        (eid,),
    )
    oid = cur.lastrowid
    for i, n in enumerate(ticks):
        cur = db.execute(
            "INSERT INTO candidates (office_id, name, active, sort_order) "
            "VALUES (?, ?, 1, ?)",
            (oid, f"Brother {i}", i),
        )
        db.execute(
            "INSERT INTO paper_votes (election_id, round_number, candidate_id, count) "
            "VALUES (?, 1, ?, ?)",
            (eid, cur.lastrowid, n),
        )
    db.execute(
        "INSERT INTO round_counts (election_id, round_number, participants, "
        "paper_ballot_count, digital_ballot_count) VALUES (?, 1, 10, 4, 0)",
        (eid,),
    )
    if spoilt:
        db.execute(
            "INSERT INTO office_spoilt_ballots (election_id, round_number, office_id, count) "
            "VALUES (?, 1, ?, ?)",
            (eid, oid, spoilt),
        )
    db.commit()
    return eid


@pytest.fixture
def admin(client):
    with client.session_transaction() as sess:
        sess["admin"] = True
    return client


def test_admin_tally_shows_blank_and_spoilt_rows_and_full_total(admin):
    with flask_app.app_context():
        eid = _seed(get_db())
    body = admin.get(f"/admin/election/{eid}/step/count").get_data(as_text=True)
    assert "Blank votes" in body
    assert "Spoilt ballots" in body
    assert "1 ballot (3 selections)" in body
    assert re.search(r"12\s*<span[^>]*>= 4 ballots × 3 selections", body), "Total row"


def test_admin_tally_shows_zero_rows_when_nothing_blank_or_spoilt(admin):
    with flask_app.app_context():
        eid = _seed(get_db(), spoilt=0, ticks=(4, 4, 4))
    body = admin.get(f"/admin/election/{eid}/step/count").get_data(as_text=True)
    assert "Blank votes" in body
    assert "Spoilt ballots" in body
    assert re.search(r"12\s*<span[^>]*>= 4 ballots × 3 selections", body), "Total row"


def test_round_results_page_shows_blank_and_spoilt_rows(admin):
    # The historical round page only serves rounds before the current one.
    with flask_app.app_context():
        eid = _seed(get_db(), current_round=2)
    body = admin.get(f"/admin/election/{eid}/round/1/results").get_data(as_text=True)
    assert "Blank votes" in body
    assert "1 ballot (3 selections)" in body
    assert re.search(r"12\s*<span[^>]*>= 4 ballots × 3 selections", body), "Total row"


def test_projector_shows_spoilt_in_both_units(client):
    with flask_app.app_context():
        eid = _seed(get_db(), show_results=1)
    body = client.get("/display").get_data(as_text=True)
    assert "Blank votes" in body
    assert "1 ballot (3 selections)" in body


def test_minutes_table_and_narrative_account_for_blank_and_spoilt(admin):
    from docx import Document
    with flask_app.app_context():
        eid = _seed(get_db())
    resp = admin.get(f"/admin/election/{eid}/minutes-docx")
    assert resp.status_code == 200
    doc = Document(BytesIO(resp.data))
    table = [t for t in doc.tables if t.rows[0].cells[0].text == "Candidate"][-1]
    rows = [[c.text for c in r.cells] for r in table.rows]
    labels = [r[0] for r in rows]
    assert "Blank votes" in labels
    assert "Spoilt ballots" in labels
    assert "Total" in labels
    by_label = {r[0]: r[-1] for r in rows}
    assert by_label["Blank votes"] == "1"
    assert by_label["Spoilt ballots"] == "1 (3)"
    assert by_label["Total"] == "12"
    text = " ".join(p.text for p in doc.paragraphs)
    assert "left blank" in text and "spoilt" in text
