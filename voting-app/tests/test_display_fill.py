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
    def test_single_office_cap_and_safe_centering(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=3)  # phase 3 -> projector.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Single-office scale cap is 2.2 (rotating cap stays 3.4). A brief
        # raise to 3.0 over-scaled dense offices (wrapped names, clipped rows).
        assert "3.4 : 2.2" in html
        assert "3.4 : 3.0" not in html
        # Office content centres within its cell, but "safe" so a list taller
        # than the cell top-aligns instead of clipping the header off-screen.
        assert "Vertically centre each office" in html
        assert "safe center" in html
        # The reload guard must be phase/show_results-aware, not "reload on
        # any phase != 3" (which reset the office rotation every second in
        # phase 4 so it never advanced to the next office).
        assert "stillProjector" in html

    def test_scaler_floor_and_viewport_clamp(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=3)
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Floor lowered so a 10-candidate office + summary strip fits 720p.
        assert "Math.max(0.45," in html
        assert "Math.max(0.6," not in html
        # Available height is clamped to the visible viewport, not just
        # the container's clientHeight.
        assert "window.innerHeight - rcTop" in html


class TestProjectorWelcomePanel:
    def test_prevote_panel_enlarged(self, election_with_codes):
        client = election_with_codes
        # Phase 3 but voting NOT opened and 0 ballots -> the pre-vote panel shows.
        _set_phase(1, display_phase=3, voting_open=0)
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Voting will begin shortly" in html
        assert 'id="prevote-welcome"' in html


class TestWelcomeScreenFill:
    def test_welcome_wraps_and_scales(self, election_with_codes):
        client = election_with_codes  # display_phase defaults to 1 -> welcome.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'id="welcome-fit"' in html
        assert "fitWelcome" in html


class TestWaitingScreenFill:
    def test_waiting_block_fills_and_centers(self):
        with open(CSS_PATH, encoding="utf-8") as f:
            css = f.read()
        idx = css.find(".display-waiting {")
        assert idx != -1
        block = css[idx:idx + 320]
        assert "flex: 1" in block
        assert "justify-content: center" in block
        assert "align-items: center" in block


class TestSlateScreen:
    def test_phase2_renders_candidate_slate_not_rules(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=2)  # phase 2 -> slate.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Candidate slate is shown (an office heading) with the vote threshold.
        assert "For Elder" in html
        assert "To be elected" in html
        # Election Rules article prose is gone.
        assert "Election Rules" not in html
        assert "Subsequent Rounds" not in html
        assert "Objections of a formal nature" not in html
        # Scale-to-fit scaler survives the rename with its tuned constants.
        assert "autoSizeSlate" in html
        assert "* 0.96)" in html
        assert "hScale, 2.4)" in html

    def test_slate_two_col_list_and_shrink_floor(self, admin_client):
        # A 10-candidate office flows its name list into two columns and
        # the scaler may shrink below 1 so the slate always fits a beamer.
        admin_client.post("/admin/election/new", data={
            "name": "Slate Fit", "max_rounds": "2",
        })
        admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder",
            "vacancies": "5",
            "max_selections": "5",
            "candidate_names": "\n".join(
                f"Candidate {i}" for i in range(1, 11)),
            "confirm_slate_override": "1",
        })
        _set_phase(1, display_phase=2)
        resp = admin_client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Two-column list kicks in at 6+ candidates.
        assert 'candidate-list two-col' in html
        assert "column-count: 2" in html
        # Shrink floor replaced the old grow-only clamp.
        assert "Math.max(0.6, scale)" in html
        assert "Math.max(1, scale)" not in html
