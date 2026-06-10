"""
Tests for the steward check-in flow, the sectioned attendance register PDF,
and the projector office-rotation setting.
"""

import io
import math
import os
import sys
import tempfile

import pytest

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db, get_display_rotate_seconds, set_setting
from pdf_generators import (
    generate_attendance_register_pdf,
    attendance_register_sheet_count,
    ATTENDANCE_ROWS_PER_SHEET,
)


MEMBER_CSV = (
    "Last name,First name\n"
    "Aalders,Adam\n"
    "Bakker,Ben\n"
    "Cremer,Carl\n"
    "De Jong,Dirk\n"
    "Evers,Evert\n"
    "Faber,Frank\n"
    "Groen,Gert\n"
    "Hofman,Hans\n"
    "Jansen,Jan\n"
)


@pytest.fixture
def client():
    """Create a test client with a temporary database."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF for tests

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
    client.post("/admin/login", data={"password": "admin"})
    return client


@pytest.fixture
def election_with_members(admin_client):
    """An election plus an imported member list."""
    admin_client.post("/admin/election/new", data={
        "name": "Test Election",
        "max_rounds": "2"
    })
    admin_client.post(
        "/admin/members",
        data={"csv_file": (io.BytesIO(MEMBER_CSV.encode()), "members.csv")},
        content_type="multipart/form-data",
    )
    return admin_client


def _steward_token(admin_client):
    """Visit the attendance step (which mints the token), then read it back."""
    resp = admin_client.get("/admin/election/1/step/attendance")
    assert resp.status_code == 200
    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'steward_token'"
        ).fetchone()
    assert row is not None
    return row["value"]


# ---------------------------------------------------------------------------
# Steward check-in
# ---------------------------------------------------------------------------

class TestStewardCheckin:
    def test_wrong_token_404s(self, election_with_members):
        _steward_token(election_with_members)
        resp = election_with_members.get("/checkin/not-the-token")
        assert resp.status_code == 404

    def test_no_token_minted_yet_404s(self, election_with_members):
        resp = election_with_members.get("/checkin/anything")
        assert resp.status_code == 404

    def test_checkin_page_lists_members(self, election_with_members):
        token = _steward_token(election_with_members)
        resp = election_with_members.get(f"/checkin/{token}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Bakker, Ben" in body
        assert "Attendance check-in" in body

    def test_toggle_and_data_roundtrip(self, election_with_members):
        token = _steward_token(election_with_members)

        resp = election_with_members.post(
            f"/checkin/{token}/toggle", data={"member_id": "1", "present": "1"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 1

        resp = election_with_members.post(
            f"/checkin/{token}/toggle", data={"member_id": "2", "present": "1"}
        )
        assert resp.get_json()["count"] == 2

        data = election_with_members.get(f"/checkin/{token}/data").get_json()
        assert data["active"] is True
        assert data["count"] == 2
        assert sorted(data["checked_ids"]) == [1, 2]

        # Undo
        resp = election_with_members.post(
            f"/checkin/{token}/toggle", data={"member_id": "1", "present": "0"}
        )
        assert resp.get_json()["count"] == 1

    def test_toggle_is_idempotent(self, election_with_members):
        token = _steward_token(election_with_members)
        for _ in range(3):
            resp = election_with_members.post(
                f"/checkin/{token}/toggle", data={"member_id": "3", "present": "1"}
            )
        assert resp.get_json()["count"] == 1

    def test_unknown_member_rejected(self, election_with_members):
        token = _steward_token(election_with_members)
        resp = election_with_members.post(
            f"/checkin/{token}/toggle", data={"member_id": "999", "present": "1"}
        )
        assert resp.status_code == 400

    def test_attendance_step_prefills_from_checkins(self, election_with_members):
        token = _steward_token(election_with_members)
        for member_id in ("1", "2", "3"):
            election_with_members.post(
                f"/checkin/{token}/toggle",
                data={"member_id": member_id, "present": "1"},
            )
        resp = election_with_members.get("/admin/election/1/step/attendance")
        body = resp.data.decode()
        assert 'value="3"' in body
        assert "Pre-filled from the steward check-in" in body

    def test_attendance_step_keeps_saved_value_over_checkins(self, election_with_members):
        token = _steward_token(election_with_members)
        election_with_members.post(
            f"/checkin/{token}/toggle", data={"member_id": "1", "present": "1"}
        )
        election_with_members.post(
            "/admin/election/1/participants", data={"participants": "42"}
        )
        resp = election_with_members.get("/admin/election/1/step/attendance")
        assert 'value="42"' in resp.data.decode()


# ---------------------------------------------------------------------------
# Sectioned attendance register PDF
# ---------------------------------------------------------------------------

SAMPLE_MEMBERS = [
    {"last_name": ln, "first_name": fn}
    for ln, fn in [
        ("Aalders", "Adam"), ("Bakker", "Ben"), ("Cremer", "Carl"),
        ("De Jong", "Dirk"), ("Evers", "Evert"), ("Faber", "Frank"),
        ("Groen", "Gert"), ("Hofman", "Hans"), ("Jansen", "Jan"),
    ]
]


def _page_texts(buf):
    from PyPDF2 import PdfReader
    reader = PdfReader(buf)
    return [page.extract_text() for page in reader.pages]


def _many_members(n):
    return [
        {"last_name": f"Surname{i:03d}", "first_name": f"First{i:03d}"}
        for i in range(n)
    ]


class TestAutoPaginatedRegisterPdf:
    def test_small_list_single_page_no_sheet_numbering(self):
        buf = generate_attendance_register_pdf(members=SAMPLE_MEMBERS)
        texts = _page_texts(buf)
        assert len(texts) == 1
        assert "Sheet 1 of" not in texts[0]
        assert "Aalders, Adam" in texts[0]

    def test_header_cruft_removed(self):
        buf = generate_attendance_register_pdf(members=SAMPLE_MEMBERS)
        text = _page_texts(buf)[0]
        assert "Article 4" not in text
        assert "Free Reformed" not in text

    def test_sheet_count_follows_rows_per_sheet(self):
        assert attendance_register_sheet_count(0) == 1
        assert attendance_register_sheet_count(ATTENDANCE_ROWS_PER_SHEET) == 1
        assert attendance_register_sheet_count(ATTENDANCE_ROWS_PER_SHEET + 1) == 2
        assert attendance_register_sheet_count(111) == math.ceil(
            111 / ATTENDANCE_ROWS_PER_SHEET)

    def test_each_sheet_is_exactly_one_page(self):
        # 111 members (the real congregation size) — every chunk must fit
        # its page: total pages == sheet count, with sheet headers intact.
        members = _many_members(111)
        buf = generate_attendance_register_pdf(members=members)
        texts = _page_texts(buf)
        expected = attendance_register_sheet_count(111)
        assert len(texts) == expected
        assert f"Sheet 1 of {expected}" in texts[0]
        assert f"Sheet {expected} of {expected}" in texts[-1]
        # First and last member appear on first and last sheet
        assert "Surname000" in texts[0]
        assert "Surname110" in texts[-1]
        # Surname-range banner and per-sheet tally on every sheet
        for t in texts:
            assert "Surnames:" in t
            assert "Signatures on this sheet" in t

    def test_full_sheet_does_not_spill(self):
        # Exactly one full sheet of members must stay on one page.
        buf = generate_attendance_register_pdf(
            members=_many_members(ATTENDANCE_ROWS_PER_SHEET))
        assert len(_page_texts(buf)) == 1

    def test_route_generates_pdf(self, election_with_members):
        resp = election_with_members.get("/admin/members/attendance-pdf")
        assert resp.status_code == 200
        assert resp.mimetype == "application/pdf"


# ---------------------------------------------------------------------------
# Per-election settings: steward check-in toggle
# ---------------------------------------------------------------------------

class TestPerElectionSettings:
    def test_new_election_defaults(self, election_with_members):
        with app.app_context():
            row = get_db().execute(
                "SELECT steward_checkin_enabled FROM elections WHERE id = 1"
            ).fetchone()
        assert row["steward_checkin_enabled"] == 1

    def test_settings_roundtrip(self, election_with_members):
        election_with_members.post(
            "/admin/election/1/settings",
            data={},  # steward checkbox unticked
        )
        with app.app_context():
            row = get_db().execute(
                "SELECT steward_checkin_enabled FROM elections WHERE id = 1"
            ).fetchone()
        assert row["steward_checkin_enabled"] == 0

    def test_steward_disabled_hides_section_and_blocks_routes(self, election_with_members):
        token = _steward_token(election_with_members)  # minted while enabled
        election_with_members.post(
            "/admin/election/1/settings",
            data={},  # steward checkbox unticked
        )
        body = election_with_members.get(
            "/admin/election/1/step/attendance"
        ).data.decode()
        assert "Steward check-in" not in body
        assert election_with_members.get(f"/checkin/{token}").status_code == 404
        resp = election_with_members.post(
            f"/checkin/{token}/toggle", data={"member_id": "1", "present": "1"}
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Projector rotation setting
# ---------------------------------------------------------------------------

class TestRotateSetting:
    def test_default_is_5(self, client):
        with app.app_context():
            assert get_display_rotate_seconds() == 5

    def test_clamped(self, client):
        with app.app_context():
            set_setting("display_rotate_seconds", "1")
            assert get_display_rotate_seconds() == 2
            set_setting("display_rotate_seconds", "120")
            assert get_display_rotate_seconds() == 60
            set_setting("display_rotate_seconds", "junk")
            assert get_display_rotate_seconds() == 5

    def test_projector_embeds_rotation_interval(self, election_with_members):
        with app.app_context():
            db = get_db()
            db.execute("UPDATE elections SET display_phase = 3 WHERE id = 1")
            db.commit()
            set_setting("display_rotate_seconds", "8")
        resp = election_with_members.get("/display")
        body = resp.data.decode()
        assert "ROTATE_MS = 8 * 1000" in body
        assert "applyRotation" in body
        # Article rules are for the chairman, not the projector
        assert "Article 6a" not in body
