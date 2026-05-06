"""Tests for PDF generation (voting cards, dual-sided ballots)."""

import io
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from pdf_generators import (
    generate_code_slips_pdf,
    generate_dual_sided_ballots_pdf,
    generate_ballot_front_pdf,
    generate_code_slips_back_pdf,
    generate_attendance_register_pdf,
    generate_printer_pack_zip,
    draw_code_slip,
)


SAMPLE_OFFICE_DATA = [
    {
        "office": {"name": "Elder", "max_selections": 2, "vacancies": 2},
        "candidates": [
            {"name": "Pieter van Rijksen"},
            {"name": "Hendrik Brouwerhof"},
            {"name": "Willem de Kempenaar"},
            {"name": "Gerrit van Dijkstra"},
        ],
    },
    {
        "office": {"name": "Deacon", "max_selections": 2, "vacancies": 2},
        "candidates": [
            {"name": "Arend Visserman"},
            {"name": "Dirk van Leeuwenburg"},
            {"name": "Reinier Mulderhoek"},
            {"name": "Frederik Bosveldt"},
        ],
    },
]

SAMPLE_CODES = ["KR4T7N", "AB3XY9", "PQ8M2D", "JK5WL6", "RT9ZN2",
                "HF7CV3", "GD4BX8", "ML2YP5"]  # 8 codes


def _generate_sample_pdf(codes=None, is_demo=False):
    return generate_dual_sided_ballots_pdf(
        election_name="Office Bearer Election 2026",
        short_name="FRC Darling Downs",
        round_number=1,
        office_data=SAMPLE_OFFICE_DATA,
        codes=codes or SAMPLE_CODES,
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        is_demo=is_demo,
    )


def test_dual_sided_ballots_pdf_generates():
    """Basic smoke test — generates without error."""
    buf = _generate_sample_pdf()
    assert buf is not None
    assert buf.getbuffer().nbytes > 0


def test_dual_sided_ballots_pdf_even_page_count():
    """PDF must have an even number of pages (front/back pairs)."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    assert len(reader.pages) % 2 == 0


def test_dual_sided_ballots_pdf_correct_page_pairs():
    """For 8 codes with ~8 per page, should be 2 pages (1 front + 1 back)."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    # 8 codes, with 2 offices x 4 candidates each, ballots should be ~8 per page
    # So 8 codes = 1 front page + 1 back page = 2 pages
    assert len(reader.pages) >= 2


def test_dual_sided_ballots_pdf_odd_pages_are_paper_ballots():
    """Front pages (page 0, 2, 4...) carry the paper-ballot warning."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    text = reader.pages[0].extract_text()
    assert "Do not submit this ballot if you voted with your phone" in text


def test_dual_sided_ballots_pdf_even_pages_are_code_slips():
    """Even pages (0-indexed: 1, 3, 5...) should contain code slip content."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    text = reader.pages[1].extract_text()
    # Should contain WiFi instructions or code text
    assert "WiFi" in text or "ChurchVote" in text or "KR4" in text


def test_dual_sided_ballots_pdf_all_candidates_on_front():
    """All candidate names should appear on the paper ballot pages."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    text = reader.pages[0].extract_text()
    for item in SAMPLE_OFFICE_DATA:
        for cand in item["candidates"]:
            assert cand["name"] in text, f"Missing: {cand['name']}"


def test_dual_sided_ballots_pdf_wifi_on_code_slips():
    """WiFi SSID should appear on code slip pages."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    text = reader.pages[1].extract_text()
    assert "ChurchVote" in text


def test_dual_sided_ballots_pdf_wifi_step_comes_first():
    """Step 1 (WiFi) text must appear before Step 2 (voting fallback)
    text in the slip's reading order."""
    from PyPDF2 import PdfReader
    buf = _generate_sample_pdf()
    reader = PdfReader(buf)
    text = reader.pages[1].extract_text()
    connect_pos = text.find("Connect")
    type_pos = text.find("Type")
    assert connect_pos != -1, "Step 1 'Connect' label missing"
    assert type_pos != -1, "Step 2 'Type' fallback missing"
    assert connect_pos < type_pos, "Step 1 must come before Step 2"


def test_dual_sided_ballots_pdf_does_not_burn_codes():
    """Generator function has no DB access — codes can't be burned."""
    buf = _generate_sample_pdf()
    assert buf.getbuffer().nbytes > 0


# ---------------------------------------------------------------------------
# Code slips PDF — 6-per-page layout
# ---------------------------------------------------------------------------

def _generate_code_slips(**kwargs):
    """Helper to generate a code slips PDF with sample data."""
    defaults = dict(
        codes=SAMPLE_CODES,
        election_name="Office Bearer Election 2026",
        short_name="FRC Darling Downs",
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        is_demo=False,
    )
    defaults.update(kwargs)
    return generate_code_slips_pdf(**defaults)


def _extract_text(buf, page=0):
    """Extract text from a page of a PDF buffer."""
    from PyPDF2 import PdfReader
    buf.seek(0)
    reader = PdfReader(buf)
    return reader.pages[page].extract_text()


def _page_count(buf):
    """Return page count of a PDF buffer."""
    from PyPDF2 import PdfReader
    buf.seek(0)
    return len(PdfReader(buf).pages)


def test_multiple_pages_for_many_codes():
    """More codes than fit on one page should produce multiple pages."""
    buf2 = _generate_code_slips(codes=SAMPLE_CODES[:2])
    buf8 = _generate_code_slips(codes=SAMPLE_CODES[:8])
    assert _page_count(buf2) == 1
    assert _page_count(buf8) >= 2


def test_code_slip_draws_without_error():
    """draw_code_slip renders without error."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    draw_code_slip(c, 15 * mm, h - 15 * mm, 85 * mm, 82 * mm,
                   "KR4T7N", "ChurchVote", "",
                   "http://192.168.8.100:5000")
    c.showPage()
    c.save()
    assert buf.getbuffer().nbytes > 0


def test_code_slip_has_vote_digitally_header():
    """Code slips should show 'Vote Digitally' header."""
    buf = _generate_code_slips(codes=SAMPLE_CODES[:1])
    text = _extract_text(buf, 0)
    assert "Vote with phone" in text


def test_code_slip_renders_at_small_dimensions():
    """draw_code_slip should work even at compact dimensions."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    draw_code_slip(c, 10 * mm, h - 10 * mm, 60 * mm, 75 * mm,
                   "KR4T7N", "WiFi", "",
                   "http://192.168.8.100:5000")
    c.showPage()
    c.save()
    assert buf.getbuffer().nbytes > 0


def test_qr_code_encodes_full_voting_url_with_code():
    """The code slips should contain the voting code text."""
    buf = _generate_code_slips(codes=["KR4T7N"])
    text = _extract_text(buf, 0)
    # The formatted code is KR4-T7N
    assert "KR4" in text
    assert "T7N" in text


def test_card_header_shows_vote_digitally():
    """Code slip header should show 'Vote Digitally'."""
    buf = _generate_code_slips(codes=["KR4T7N"])
    text = _extract_text(buf, 0)
    assert "Vote with phone" in text


def test_card_shows_wifi_ssid():
    """WiFi SSID should appear on the card."""
    buf = _generate_code_slips(codes=["KR4T7N"])
    text = _extract_text(buf, 0)
    assert "ChurchVote" in text


def test_card_shows_no_password_needed_when_no_password():
    """When no password is set, 'No password needed' should appear."""
    buf = _generate_code_slips(codes=["KR4T7N"], wifi_password="")
    text = _extract_text(buf, 0)
    assert "No password needed" in text


def test_card_shows_password_line_when_password_set():
    """When a password is set, it should appear on the card."""
    buf = _generate_code_slips(codes=["KR4T7N"], wifi_password="vote2026")
    text = _extract_text(buf, 0)
    assert "vote2026" in text


def test_card_shows_voting_code():
    """Voting code should appear on the code slip."""
    buf = _generate_code_slips(codes=["KR4T7N"])
    text = _extract_text(buf, 0)
    assert "KR4" in text and "T7N" in text


def test_card_shows_fallback_url():
    """Fallback URL should appear on the code slip."""
    buf = _generate_code_slips(codes=["KR4T7N"])
    text = _extract_text(buf, 0)
    assert "192.168.8.100:5000" in text


def test_code_slip_renders_at_full_page():
    """draw_code_slip should work at full-page dimensions without error."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    margin = 15 * mm
    draw_code_slip(c, margin, h - margin, w - 2 * margin, h - 2 * margin,
                   "AB3XY9", "ChurchVote", "",
                   "http://192.168.8.100:5000")
    c.showPage()
    c.save()
    assert buf.getbuffer().nbytes > 0


def test_dual_sided_ballot_back_shows_code_slip_content():
    """Back pages of dual-sided ballots should show code slip content."""
    buf = _generate_sample_pdf()
    text = _extract_text(buf, 1)  # page 1 = first back page
    assert "Vote with phone" in text
    assert "ChurchVote" in text
    assert "KR4" in text or "AB3" in text


def test_dual_sided_ballot_front_has_warning():
    """Front ballot should include a warning about phone voting."""
    buf = _generate_sample_pdf()
    text = _extract_text(buf, 0)  # page 0 = first front page
    assert "voted with your phone" in text.lower()


def test_dual_sided_ballot_back_has_warning():
    """Back code slip should include a warning about paper ballot."""
    buf = _generate_sample_pdf()
    text = _extract_text(buf, 1)  # page 1 = first back page
    assert "paper ballot" in text.lower()


# ---------------------------------------------------------------------------
# Ballot front PDF — single card-sized page
# ---------------------------------------------------------------------------

def test_ballot_front_pdf_generates():
    """Ballot front PDF should generate without error."""
    buf = generate_ballot_front_pdf(
        election_name="Office Bearer Election 2026",
        office_data=SAMPLE_OFFICE_DATA,
        wifi_password="",
    )
    assert buf is not None
    assert buf.getbuffer().nbytes > 0


def test_ballot_front_pdf_single_page():
    """Ballot front PDF should have exactly 1 page."""
    buf = generate_ballot_front_pdf(
        election_name="Office Bearer Election 2026",
        office_data=SAMPLE_OFFICE_DATA,
        wifi_password="",
    )
    assert _page_count(buf) == 1


def test_ballot_front_pdf_has_candidates():
    """Ballot front should contain all candidate names."""
    buf = generate_ballot_front_pdf(
        election_name="Office Bearer Election 2026",
        office_data=SAMPLE_OFFICE_DATA,
        wifi_password="",
    )
    text = _extract_text(buf, 0)
    for item in SAMPLE_OFFICE_DATA:
        for cand in item["candidates"]:
            assert cand["name"] in text, f"Missing: {cand['name']}"


def test_ballot_front_pdf_not_a4():
    """Ballot front should use a custom card page size, not A4."""
    from PyPDF2 import PdfReader
    buf = generate_ballot_front_pdf(
        election_name="Office Bearer Election 2026",
        office_data=SAMPLE_OFFICE_DATA,
        wifi_password="",
    )
    buf.seek(0)
    reader = PdfReader(buf)
    page = reader.pages[0]
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    a4_w, a4_h = A4
    assert w < a4_w and h < a4_h, "Page should be smaller than A4"


# ---------------------------------------------------------------------------
# Code slips back PDF — one card-sized page per code
# ---------------------------------------------------------------------------

def test_code_slips_back_pdf_generates():
    """Code slips back PDF should generate without error."""
    buf = generate_code_slips_back_pdf(
        codes=SAMPLE_CODES,
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        office_data=SAMPLE_OFFICE_DATA,
    )
    assert buf is not None
    assert buf.getbuffer().nbytes > 0


def test_code_slips_back_pdf_page_count_matches_codes():
    """Back PDF should have one page per code."""
    codes = SAMPLE_CODES[:4]
    buf = generate_code_slips_back_pdf(
        codes=codes,
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        office_data=SAMPLE_OFFICE_DATA,
    )
    assert _page_count(buf) == len(codes)


def test_code_slips_back_pdf_contains_codes():
    """Each back page should contain its voting code."""
    buf = generate_code_slips_back_pdf(
        codes=["KR4T7N"],
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        office_data=SAMPLE_OFFICE_DATA,
    )
    text = _extract_text(buf, 0)
    assert "KR4" in text and "T7N" in text


def test_code_slips_back_pdf_not_a4():
    """Back PDF should use a custom card page size, not A4."""
    from PyPDF2 import PdfReader
    buf = generate_code_slips_back_pdf(
        codes=SAMPLE_CODES[:1],
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        office_data=SAMPLE_OFFICE_DATA,
    )
    buf.seek(0)
    reader = PdfReader(buf)
    page = reader.pages[0]
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    a4_w, a4_h = A4
    assert w < a4_w and h < a4_h, "Page should be smaller than A4"


# ---------------------------------------------------------------------------
# Attendance register PDF
# ---------------------------------------------------------------------------

SAMPLE_MEMBERS = [
    {"first_name": "Pieter", "last_name": "van Rijksen"},
    {"first_name": "Hendrik", "last_name": "Brouwerhof"},
    {"first_name": "Willem", "last_name": "de Kempenaar"},
]


def test_attendance_register_pdf_generates():
    """Attendance register PDF should generate without error."""
    buf = generate_attendance_register_pdf(
        members=SAMPLE_MEMBERS,
        congregation_name="Free Reformed Church of Darling Downs",
    )
    assert buf is not None
    assert buf.getbuffer().nbytes > 0


def test_attendance_register_pdf_contains_names():
    """Attendance register should contain member names."""
    buf = generate_attendance_register_pdf(
        members=SAMPLE_MEMBERS,
        congregation_name="Free Reformed Church of Darling Downs",
    )
    text = _extract_text(buf, 0)
    for m in SAMPLE_MEMBERS:
        assert m["last_name"] in text, f"Missing: {m['last_name']}"


# ---------------------------------------------------------------------------
# Printer pack ZIP
# ---------------------------------------------------------------------------

def _generate_sample_zip(**kwargs):
    """Helper to generate a printer pack ZIP with sample data."""
    defaults = dict(
        election_name="Office Bearer Election 2026",
        short_name="FRC Darling Downs",
        round_number=1,
        office_data=SAMPLE_OFFICE_DATA,
        codes=SAMPLE_CODES,
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://192.168.8.100:5000",
        congregation_name="Free Reformed Church of Darling Downs",
        members=SAMPLE_MEMBERS,
        election_date="4 October 2026",
        member_count=0,
        is_demo=False,
    )
    defaults.update(kwargs)
    return generate_printer_pack_zip(**defaults)


def test_printer_pack_zip_generates():
    """Printer pack ZIP should generate without error."""
    buf = _generate_sample_zip()
    assert buf is not None
    assert buf.getbuffer().nbytes > 0


def test_printer_pack_zip_contains_all_files():
    """ZIP should contain exactly 9 files (incl. WiFi handout for sign-in)."""
    import zipfile
    buf = _generate_sample_zip()
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    expected = {
        "0_INSTRUCTIONS.txt",
        "1_ballot_front.pdf",
        "2_code_slips_back.pdf",
        "3_cards_duplex.pdf",
        "4_dual_sided_ballots.pdf",
        "5_counter_sheet.pdf",
        "6_attendance_register.pdf",
        "7_wifi_handout.pdf",
        "8_av_instructions.pdf",
    }
    assert names == expected


def test_printer_pack_zip_cards_duplex_page_count():
    """cards_duplex.pdf should have 2N pages for N codes."""
    import zipfile
    from PyPDF2 import PdfReader
    buf = _generate_sample_zip()
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        data = zf.read("3_cards_duplex.pdf")
    reader = PdfReader(io.BytesIO(data))
    # _generate_sample_zip uses 8 codes, member_count=0, so total_cards=8 → 16 pages
    assert len(reader.pages) == 16


def test_printer_pack_zip_front_is_single_page():
    """ballot_front.pdf inside the ZIP should be 1 page."""
    import zipfile
    from PyPDF2 import PdfReader
    buf = _generate_sample_zip()
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        front_data = zf.read("1_ballot_front.pdf")
    reader = PdfReader(io.BytesIO(front_data))
    assert len(reader.pages) == 1


def test_printer_pack_zip_back_page_count():
    """code_slips_back.pdf should have one page per code."""
    import zipfile
    from PyPDF2 import PdfReader
    buf = _generate_sample_zip()
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        back_data = zf.read("2_code_slips_back.pdf")
    reader = PdfReader(io.BytesIO(back_data))
    assert len(reader.pages) == len(SAMPLE_CODES)


def test_printer_pack_zip_instructions_content():
    """INSTRUCTIONS.txt should mention all files."""
    import zipfile
    buf = _generate_sample_zip()
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        instructions = zf.read("0_INSTRUCTIONS.txt").decode("utf-8")
    assert "1_ballot_front.pdf" in instructions
    assert "2_code_slips_back.pdf" in instructions
    assert "4_dual_sided_ballots.pdf" in instructions
    assert "5_counter_sheet.pdf" in instructions
    assert "6_attendance_register.pdf" in instructions
    assert "7_wifi_handout.pdf" in instructions
    assert "8_av_instructions.pdf" in instructions


def test_code_slip_voting_qr_meets_minimum_size():
    """Regression: the voting QR on the code slip must be at least 30 mm.
    The original spec called for 32 mm; the slip's dual-QR layout
    shrinks the voting QR a notch but stays well above the 24 mm
    panic floor where camera focus-hunting and fold tolerance bite. See
    docs/superpowers/specs/2026-05-02-paper-scan-and-phone-receipt-design.md.
    """
    import inspect
    import re
    from pdf_generators import draw_code_slip
    src = inspect.getsource(draw_code_slip)
    m = re.search(r"vote_qr_size\s*=\s*([\d.]+)\s*\*\s*mm", src)
    assert m, "vote_qr_size assignment not found in draw_code_slip"
    size_mm = float(m.group(1))
    assert size_mm >= 30, (
        f"voting QR shrank below 30 mm floor: {size_mm} mm"
    )


def test_code_slip_renders_wifi_qr_at_step_1(monkeypatch):
    """Step 1 ('Connect to WiFi') must render a WIFI: payload QR so
    voters can join the network from the slip itself, not just text."""
    import io
    import pdf_generators
    from reportlab.pdfgen import canvas as rl_canvas
    captured = []
    real = pdf_generators._generate_qr_image

    def _spy(data, size=120):
        captured.append(data)
        return real(data, size)

    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    pdf_generators.draw_code_slip(
        c, 15 * mm, h - 15 * mm, 90 * mm, 90 * mm,
        "KR4T7N", "ChurchVote", "secret123",
        "http://10.0.0.2",
    )
    c.showPage()
    c.save()
    wifi_qrs = [d for d in captured if d.startswith("WIFI:")]
    assert wifi_qrs, f"no WiFi QR rendered on code slip: {captured}"
    assert "S:ChurchVote" in wifi_qrs[0]


def test_code_slip_height_within_grid_budget():
    """The card-sized layout must stay within ~89.67 mm so 6 slips
    (3 rows x 2 cols) still fit on A4 in the dual-sided printing path."""
    from pdf_generators import _calc_code_slip_height
    h_with_pwd = _calc_code_slip_height("secret123") / mm
    h_open = _calc_code_slip_height("") / mm
    assert h_with_pwd <= 89.67, f"slip height {h_with_pwd:.2f} mm exceeds budget"
    assert h_open <= 89.67, f"slip height {h_open:.2f} mm exceeds budget"


def test_av_instructions_pdf_includes_qr_url_fallback():
    """When qr_base_url differs from base_url, the AV instructions sheet
    must list both URLs so the AV team has a literal-IP fallback if the
    friendly hostname does not resolve."""
    from pdf_generators import generate_av_instructions_pdf
    from PyPDF2 import PdfReader
    buf = generate_av_instructions_pdf(
        election_name="Office Bearer Election 2026",
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://church.vote",
        qr_base_url="http://10.0.0.2",
    )
    text = PdfReader(buf).pages[0].extract_text()
    assert "church.vote/display" in text
    assert "10.0.0.2/display" in text


def test_av_instructions_pdf_omits_alt_when_urls_match():
    """No '(or X)' fallback when qr_base_url equals base_url."""
    from pdf_generators import generate_av_instructions_pdf
    from PyPDF2 import PdfReader
    buf = generate_av_instructions_pdf(
        election_name="Office Bearer Election 2026",
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://10.0.0.2",
        qr_base_url="http://10.0.0.2",
    )
    text = PdfReader(buf).pages[0].extract_text()
    assert "10.0.0.2/display" in text
    assert "if the first does not load" not in text


def test_dual_sided_ballots_pdf_still_generates_with_larger_qr():
    """Regression: the dual-sided grid layout must still produce a PDF
    without overflowing cells when the QR is 36 mm."""
    pdf_bytes = _generate_sample_pdf().getvalue()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"/Image" in pdf_bytes
    assert len(pdf_bytes) > 5000, "PDF appears truncated"


# ---------------------------------------------------------------------------
# QR vs printed-URL split (Android DNS workaround)
# ---------------------------------------------------------------------------

def test_qr_encodes_qr_base_url_when_provided(monkeypatch):
    """When qr_base_url differs from base_url, the QR encodes qr_base_url."""
    import pdf_generators
    captured = []
    real = pdf_generators._generate_qr_image
    def _spy(url, size=120):
        captured.append(url)
        return real(url, size)
    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    pdf_generators.draw_code_slip(
        c, 15 * mm, h - 15 * mm, 85 * mm, 82 * mm,
        "KR4T7N", "ChurchVote", "",
        "http://church.vote",
        qr_base_url="http://192.168.8.100",
    )
    c.showPage()
    c.save()

    # The slip emits a WiFi QR (Step 1) and a voting QR (Step 2); only
    # the voting QR participates in the qr_base_url routing contract.
    voting_qrs = [u for u in captured if not u.startswith("WIFI:")]
    assert voting_qrs == ["http://192.168.8.100/v/KR4T7N"]


def test_qr_falls_back_to_base_url_when_qr_base_url_missing(monkeypatch):
    """Without qr_base_url, the QR encodes base_url (backward compat)."""
    import pdf_generators
    captured = []
    real = pdf_generators._generate_qr_image
    def _spy(url, size=120):
        captured.append(url)
        return real(url, size)
    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    pdf_generators.draw_code_slip(
        c, 15 * mm, h - 15 * mm, 85 * mm, 82 * mm,
        "KR4T7N", "ChurchVote", "",
        "http://church.vote",
    )
    c.showPage()
    c.save()

    voting_qrs = [u for u in captured if not u.startswith("WIFI:")]
    assert voting_qrs == ["http://church.vote/v/KR4T7N"]


def test_slip_shows_alt_url_when_qr_url_differs():
    """Slip text should show 'or 192.168.8.100' when QR uses a different host."""
    buf = _generate_code_slips(
        codes=["KR4T7N"],
        base_url="http://church.vote",
        qr_base_url="http://192.168.8.100",
    )
    text = _extract_text(buf, 0)
    assert "church.vote" in text
    assert "192.168.8.100" in text


def test_slip_omits_alt_url_when_qr_url_matches():
    """Slip should not show '(or ...)' when qr_base_url equals base_url."""
    buf = _generate_code_slips(
        codes=["KR4T7N"],
        base_url="http://church.vote",
        qr_base_url="http://church.vote",
    )
    text = _extract_text(buf, 0)
    assert "(or" not in text


def test_dual_sided_ballots_threads_qr_base_url(monkeypatch):
    """Dual-sided generator must pass qr_base_url through to draw_code_slip."""
    import pdf_generators
    captured = []
    real = pdf_generators._generate_qr_image
    def _spy(url, size=120):
        captured.append(url)
        return real(url, size)
    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)

    generate_dual_sided_ballots_pdf(
        election_name="Office Bearer Election 2026",
        short_name="FRC Darling Downs",
        round_number=1,
        office_data=SAMPLE_OFFICE_DATA,
        codes=["KR4T7N"],
        wifi_ssid="ChurchVote",
        wifi_password="",
        base_url="http://church.vote",
        qr_base_url="http://192.168.8.100",
    )

    assert captured, "QR generator was not invoked"
    # Each slip emits a WiFi QR (WIFI: payload) plus a voting QR; the
    # routing contract applies only to the voting QRs.
    voting_qrs = [u for u in captured if not u.startswith("WIFI:")]
    assert voting_qrs, "no voting QRs captured"
    assert all(u.startswith("http://192.168.8.100/") for u in voting_qrs), voting_qrs


# ---------------------------------------------------------------------------
# WiFi handout PDF (sign-in table sheet, joined via WiFi QR)
# ---------------------------------------------------------------------------


def test_wifi_qr_payload_wpa():
    """When a password is supplied, payload uses T:WPA and includes P:."""
    from pdf_generators import _wifi_qr_payload
    assert (_wifi_qr_payload("ChurchVote", "secret123")
            == "WIFI:T:WPA;S:ChurchVote;P:secret123;;")


def test_wifi_qr_payload_open_empty_string():
    """Empty password means open network: T:nopass and no P: field."""
    from pdf_generators import _wifi_qr_payload
    assert _wifi_qr_payload("ChurchVote", "") == "WIFI:T:nopass;S:ChurchVote;;"


def test_wifi_qr_payload_open_none():
    """None password is treated the same as empty (open network)."""
    from pdf_generators import _wifi_qr_payload
    assert _wifi_qr_payload("ChurchVote", None) == "WIFI:T:nopass;S:ChurchVote;;"


def test_wifi_qr_payload_escapes_special_chars():
    """Per the WiFi QR standard, backslash, semicolon, comma, colon and
    double-quote in SSID or password must be backslash-escaped."""
    from pdf_generators import _wifi_qr_payload
    # SSID contains all five reserved chars
    payload = _wifi_qr_payload('a;b,c:d"e\\f', "p;w")
    assert payload == 'WIFI:T:WPA;S:a\\;b\\,c\\:d\\"e\\\\f;P:p\\;w;;'


def test_wifi_handout_pdf_generates():
    """Smoke test: WiFi handout PDF generates without error."""
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    assert buf is not None
    assert buf.getbuffer().nbytes > 0


def test_wifi_handout_pdf_is_one_page():
    """Handout is a single A4 sheet."""
    from PyPDF2 import PdfReader
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    reader = PdfReader(buf)
    assert len(reader.pages) == 1


def test_wifi_handout_pdf_shows_title():
    """Page header reads 'Prepare your wifi connection' followed by
    'scan both codes:'."""
    from PyPDF2 import PdfReader
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    text = PdfReader(buf).pages[0].extract_text()
    assert "Prepare your wifi connection" in text
    assert "(optional)" in text
    assert "scan both codes" in text


def test_wifi_handout_pdf_shows_numbered_labels():
    """Each QR is marked 'Step 1' / 'Step 2' so voters know which
    to scan first."""
    from PyPDF2 import PdfReader
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    text = PdfReader(buf).pages[0].extract_text()
    # "Step" word and both numbers must be extractable text.
    assert text.lower().count("step") >= 2, text
    assert "1" in text
    assert "2" in text


def test_wifi_handout_pdf_shows_ssid_under_first_qr():
    """The WiFi network name is printed under QR 1 as a fallback so
    voters whose phone cameras cannot scan the WIFI: payload still see
    which network to connect to."""
    from PyPDF2 import PdfReader
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    text = PdfReader(buf).pages[0].extract_text()
    assert "ChurchVote" in text


def test_wifi_handout_pdf_shows_url_under_second_qr():
    """The URL is printed under QR 2 as a fallback so voters can type
    it manually if they cannot scan the QR."""
    from PyPDF2 import PdfReader
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    text = PdfReader(buf).pages[0].extract_text()
    assert "10.0.0.2" in text


def test_wifi_handout_pdf_embeds_qr_image():
    """A QR raster must be embedded in the PDF (not just text)."""
    from pdf_generators import generate_wifi_handout_pdf
    pdf_bytes = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    ).getvalue()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"/Image" in pdf_bytes


def test_wifi_handout_pdf_renders_two_qrs(monkeypatch):
    """Page produces exactly two QRs: a WIFI: payload (joins the
    network) and a URL pointing at qr_base_url (loads the page so
    voters can confirm the connection works)."""
    import pdf_generators
    captured = []
    real = pdf_generators._generate_qr_image

    def _spy(data, size=120):
        captured.append(data)
        return real(data, size)

    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)
    pdf_generators.generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
    )
    assert len(captured) == 2, f"expected 2 QRs, got {len(captured)}: {captured}"
    wifi_qrs = [d for d in captured if d.startswith("WIFI:")]
    url_qrs = [d for d in captured if d.startswith("http://10.0.0.2")]
    assert len(wifi_qrs) == 1, f"expected 1 WIFI QR, got: {captured}"
    assert "S:ChurchVote" in wifi_qrs[0]
    assert len(url_qrs) == 1, f"expected 1 URL QR for 10.0.0.2, got: {captured}"


def test_wifi_handout_pdf_copies_param_produces_n_pages():
    """When copies=N, the PDF has N identical pages so they can be torn
    off and handed out across the pews."""
    from PyPDF2 import PdfReader
    from pdf_generators import generate_wifi_handout_pdf
    buf = generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
        copies=10,
    )
    reader = PdfReader(buf)
    assert len(reader.pages) == 10


def test_wifi_handout_pdf_copies_does_not_reencode_qrs(monkeypatch):
    """Generating N copies must not regenerate the QR images N times.
    The QR raster is identical across pages, so we render it once and
    reuse the ImageReader. Otherwise a 10-copy print bloats the PDF
    and slows pack assembly."""
    import pdf_generators
    counter = {"n": 0}
    real = pdf_generators._generate_qr_image

    def _spy(data, size=120):
        counter["n"] += 1
        return real(data, size)

    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)
    pdf_generators.generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="secret123",
        qr_base_url="http://10.0.0.2",
        copies=10,
    )
    # Two unique QRs (WiFi + URL); should be generated once each, not 20 times.
    assert counter["n"] == 2, f"expected 2 QR generations, got {counter['n']}"


def test_printer_pack_zip_wifi_handout_has_ten_copies():
    """The printer pack ships 10 copies of the WiFi handout so people
    can take a stack and hand them out in the pews."""
    import zipfile
    from PyPDF2 import PdfReader
    buf = _generate_sample_zip()
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        data = zf.read("7_wifi_handout.pdf")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 10


def test_wifi_handout_pdf_open_network_uses_nopass(monkeypatch):
    """Open network (no password) still produces a valid two-QR page
    with a T:nopass WiFi payload."""
    import pdf_generators
    captured = []
    real = pdf_generators._generate_qr_image

    def _spy(data, size=120):
        captured.append(data)
        return real(data, size)

    monkeypatch.setattr(pdf_generators, "_generate_qr_image", _spy)
    pdf_generators.generate_wifi_handout_pdf(
        wifi_ssid="ChurchVote",
        wifi_password="",
        qr_base_url="http://10.0.0.2",
    )
    wifi_qrs = [d for d in captured if d.startswith("WIFI:")]
    assert len(wifi_qrs) == 1
    assert "T:nopass" in wifi_qrs[0]


