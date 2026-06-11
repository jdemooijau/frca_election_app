"""Render-level guards for the projector screen-fill changes.

These assert the structural hooks (wrappers, scaler functions, tuned
constants) are present in the rendered templates / static CSS. Visual
correctness (does it actually fill the screen) is verified by running the
app at projector resolution, per the spec's manual testing section.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_db
# Reuse fixtures: pytest discovers them via this import.
from tests.test_app import client, admin_client, election_with_codes  # noqa: F401

CSS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "css", "style.css",
)


def _set_phase(election_id, **cols):
    """Directly set election columns (display_phase, voting_open, ...)."""
    assigns = ", ".join(f"{k} = ?" for k in cols)
    with app.app_context():
        db = get_db()
        db.execute(
            f"UPDATE elections SET {assigns} WHERE id = ?",
            (*cols.values(), election_id),
        )
        db.commit()


class TestFinalResultsFill:
    def test_final_results_wraps_and_centers(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, voting_open=0, show_results=0, display_phase=4)
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Content wrapped for zoom-based scale-to-fit:
        assert 'id="final-fit"' in html
        # The one-shot scaler is present:
        assert "fitFinal" in html
        # Vertical centring: the top-anchoring inline style is gone:
        assert "justify-content: flex-start" not in html


class TestProjectorLiveResultsFill:
    def test_single_office_cap_raised_and_office_centered(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=3)  # phase 3 -> projector.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Single-office scale cap raised 2.2 -> 3.0 (rotating cap stays 3.4):
        assert "3.4 : 3.0" in html
        assert "3.4 : 2.2" not in html
        # Office content is vertically centred within its results cell:
        assert "Vertically centre each office" in html
