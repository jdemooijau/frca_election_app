"""Tests for the one-click sample-offices helper (10 elder + 8 deacon)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_db
# Reuse fixtures: pytest discovers them via this import.
from tests.test_app import client, admin_client  # noqa: F401


def test_load_sample_offices_seeds_ten_elders_eight_deacons(admin_client):
    admin_client.post("/admin/election/new", data={
        "name": "Sample Test", "max_rounds": "2",
    })
    resp = admin_client.post(
        "/admin/election/1/load-sample-offices", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        db = get_db()
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = 1 ORDER BY sort_order"
        ).fetchall()
        assert len(offices) == 2
        elder, deacon = offices
        assert elder["name"] == "Elder"
        assert (elder["vacancies"], elder["max_selections"]) == (5, 5)
        assert deacon["name"] == "Deacon"
        assert (deacon["vacancies"], deacon["max_selections"]) == (4, 4)
        n_elder = db.execute(
            "SELECT COUNT(*) FROM candidates WHERE office_id = ?",
            (elder["id"],)).fetchone()[0]
        n_deacon = db.execute(
            "SELECT COUNT(*) FROM candidates WHERE office_id = ?",
            (deacon["id"],)).fetchone()[0]
        assert n_elder == 10
        assert n_deacon == 8
