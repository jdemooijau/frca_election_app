"""
Shared PDF generation functions for the FRCA Election App.

Extracted from app.py so that both Flask routes and CLI scripts
can generate PDFs without code duplication.
"""

import io
import math
import os
import zipfile
from datetime import datetime

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from name_formatting import shorten_to_fit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NAVY = HexColor("#1A3353")
GOLD = HexColor("#D4A843")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_qr_image(url, size=120):
    """Generate a QR code image as a ReportLab-compatible ImageReader object."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    return ImageReader(img_buf)


# ---------------------------------------------------------------------------
# Warning strip (shared between front and back of dual-sided ballots)
# ---------------------------------------------------------------------------

_WARNING_STRIP_H = 6 * mm


def _draw_warning_strip(c, x, bottom_y, w, text):
    """Draw a grey warning strip with bold text at the bottom of a cell."""
    c.setFillColor(HexColor("#F0F0F0"))
    c.rect(x, bottom_y, w, _WARNING_STRIP_H, fill=1, stroke=0)
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(1.5)
    c.line(x, bottom_y + _WARNING_STRIP_H, x + w, bottom_y + _WARNING_STRIP_H)
    c.setLineWidth(1)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(HexColor("#000000"))
    c.drawCentredString(x + w / 2, bottom_y + 2 * mm, text)


# ---------------------------------------------------------------------------
# Code slip drawing (used by both dual-sided and standalone code slips PDFs)
# ---------------------------------------------------------------------------


def _calc_code_slip_height(wifi_password):
    """Calculate the content height needed for a code slip.

    Sized so 6 slips (3 rows x 2 cols) fit on A4 in dual-sided printing:
    rows = floor((297 - 16 + 6) / (cell_h + 6)) = floor(287 / 92.5) = 3.
    Total target: <= 89.67 mm.

    Layout: header / Step 1 (text-only WiFi info next to numbered
    circle) / Step 2 (numbered circle + 32 mm voting QR + connecting
    arrow + vertical divider framing the fallback-text column with
    "If QR fails" label sitting directly over the fallback text) /
    warning. Single-QR design after UAT showed two QRs confused
    voters; the rotated divider hint was unreadable so it became a
    horizontal arrow + over-text label, with arrow shaft tightened
    so the QR can stay at the 32 mm count-time-scan spec floor.
    """
    h = 0
    h += 10 * mm  # header ("Vote with phone" + rule + top padding)
    h += 18 * mm  # step 1 row (text-only WiFi line + password line)
    h += 53 * mm  # step 2 row (32 mm voting QR + arrow + fallback text)
    h += _WARNING_STRIP_H  # warning strip
    h += 1 * mm   # bottom padding
    return h


def draw_code_slip(c, x, top_y, w, cell_h, code, wifi_ssid, wifi_password,
                   base_url, qr_base_url=None):
    """Draw a modern B&W-optimised code slip in the given cell.

    Layout: "Vote with phone" header -> two-column body (Step 1 + Step 2
    QRs on the left, vertical divider, text on the right) -> warning.

    base_url is the human-readable URL printed on the slip (e.g.
    'http://church.vote'). qr_base_url, if given and different, is
    encoded in the QR code instead and shown as a fallback inline next
    to base_url. This lets us print a friendly hostname while encoding
    a literal IP in the QR, which avoids DNS routing issues on Android
    phones that keep cellular as the default DNS path.
    """
    def _strip_scheme(u):
        return u.replace("http://", "").replace("https://", "").rstrip("/")

    qr_url_for_encode = qr_base_url or base_url
    show_alt_url = bool(qr_base_url) and qr_base_url != base_url
    base_url_display = _strip_scheme(base_url)
    alt_url_display = _strip_scheme(qr_base_url) if show_alt_url else ""
    cx = x + w / 2
    tx = x + 3 * mm
    bottom_y = top_y - cell_h
    y = top_y - 5 * mm

    # --- Solid border (rounded) ---
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(1.5)
    c.roundRect(x, bottom_y, w, cell_h, 2 * mm)
    c.setLineWidth(1)

    # --- Header: "Vote with phone" + rule ---
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(HexColor("#000000"))
    c.drawCentredString(cx, y, "Vote with phone")
    y -= 3.5 * mm
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(1.5)
    c.line(x + 3 * mm, y, x + w - 3 * mm, y)
    c.setLineWidth(1)
    y -= 6 * mm

    # --- Step number circle helper. Black ring on white fill with a
    # bold black digit inside. UAT feedback: previous filled-black
    # circle with white digit looked too much like a generic icon
    # rather than a numbered step. ---
    def _step_circle(sx, sy, num):
        r = 5 * mm
        cy = sy + 1.5 * mm  # centre circle on text baseline
        c.setFillColor(HexColor("#FFFFFF"))
        c.setStrokeColor(HexColor("#000000"))
        c.setLineWidth(1.5)
        c.circle(sx + r, cy, r, fill=1, stroke=1)
        c.setFillColor(HexColor("#000000"))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(sx + r, cy - 1.9 * mm, str(num))
        c.setLineWidth(1)

    # --- Body layout: Step 1 is text-only (Connect to WiFi name and
    # password line) with the bigger numbered circle on the left;
    # Step 2 is the same step circle + voting QR + a prominent
    # horizontal arrow with an "If QR fails" label + manual fallback
    # text on the right. UAT (David, Matt) showed that a second QR
    # for WiFi-join confused voters who would not read the
    # instructions and just scanned whichever QR they saw first; the
    # standalone wifi handout at the sign-in table covers the
    # WiFi-QR convenience case separately. Later UAT showed the
    # rotated "If QR fails" hint on the divider was unreadable, so
    # the divider was replaced with a horizontal arrow that visibly
    # connects QR to fallback. ---
    content_top_y = y
    label_x = tx + 12 * mm  # left edge of Step-2 QR (after bigger circle)

    # === Step 1: Connect to WiFi (text only) ===
    # Drop step 1 a few mm below the header rule so the bigger numbered
    # circle does not crowd the rule.
    step1_top_y = content_top_y - 3 * mm
    _step_circle(tx, step1_top_y, 1)
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#777777"))
    c.drawString(label_x, step1_top_y, "Connect to WiFi")
    ssid_x = label_x + c.stringWidth("Connect to WiFi ", "Helvetica", 11)
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(HexColor("#000000"))
    c.drawString(ssid_x, step1_top_y, wifi_ssid)
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#888888"))
    if wifi_password:
        c.drawString(label_x, step1_top_y - 5 * mm,
                     f"Password: {wifi_password}")
    else:
        c.drawString(label_x, step1_top_y - 5 * mm, "No password needed")

    # === Step 2: Voting QR + manual fallback ===
    step2_top_y = step1_top_y - 18 * mm
    _step_circle(tx, step2_top_y, 2)

    # Voting QR at the 32 mm spec floor for count-time scan
    # throughput (see specs/2026-05-02-paper-scan-and-phone-receipt-
    # design.md). ERROR_CORRECT_H is retained.
    vote_qr_size = 32 * mm
    vote_qr_top = step2_top_y + 4 * mm
    vote_qr_bottom = vote_qr_top - vote_qr_size
    vote_url = f"{qr_url_for_encode}/v/{code}"
    vote_qr_img = _generate_qr_image(vote_url)
    c.drawImage(vote_qr_img, label_x, vote_qr_bottom,
                vote_qr_size, vote_qr_size)

    # Layout from QR right edge to text column, left to right:
    #   QR | gap | arrow | gap | divider line | gap | text
    # Arrow shaft is tight (4 mm) so the layout fits beside a 32 mm
    # QR; the divider line frames the fallback-text column and the
    # arrow stops just short of the line.
    divider_x = label_x + 41 * mm
    text_x = divider_x + 1 * mm

    # --- Connecting arrow between QR and the fallback-text column.
    # The shaft is vertically centred on the QR so it visibly
    # emerges from the QR and points at the fallback. Header labels
    # ("Scan QR with camera" over QR, "If QR fails" over text) sit
    # in the empty band above the QR top, parallel-construction so
    # the QR-vs-fallback alternative reads at a glance. ---
    arrow_y = (vote_qr_top + vote_qr_bottom) / 2
    arrow_x_start = label_x + vote_qr_size + 1 * mm
    arrow_x_tip = divider_x - 1 * mm
    arrow_head_w = 3 * mm
    arrow_head_h = 2.5 * mm
    shaft_x_end = arrow_x_tip - arrow_head_w
    c.setStrokeColor(HexColor("#000000"))
    c.setFillColor(HexColor("#000000"))
    c.setLineWidth(1.8)
    c.line(arrow_x_start, arrow_y, shaft_x_end, arrow_y)
    arrow_path = c.beginPath()
    arrow_path.moveTo(shaft_x_end, arrow_y + arrow_head_h / 2)
    arrow_path.lineTo(arrow_x_tip, arrow_y)
    arrow_path.lineTo(shaft_x_end, arrow_y - arrow_head_h / 2)
    arrow_path.close()
    c.drawPath(arrow_path, stroke=0, fill=1)
    c.setLineWidth(1)

    # Vertical divider framing the fallback-text column on its left.
    # Spans the QR vertical extent for visual symmetry with the QR.
    c.setStrokeColor(HexColor("#CCCCCC"))
    c.setLineWidth(0.75)
    c.line(divider_x, vote_qr_bottom, divider_x, vote_qr_top)
    c.setLineWidth(1)

    # Header labels in the empty band above the QR top.
    label_y = vote_qr_top + 1.5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(HexColor("#000000"))
    qr_mid_x = label_x + vote_qr_size / 2
    c.drawCentredString(qr_mid_x, label_y, "Scan QR with camera")
    c.drawString(text_x, label_y, "If QR fails")

    # Right-column text for Step 2 (no "Scan QR" preamble; modern
    # users know how QR works).
    text_y = vote_qr_top - 3 * mm
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#555555"))
    c.drawString(text_x, text_y, "Type")
    url_x = text_x + c.stringWidth("Type ", "Helvetica", 10)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(HexColor("#000000"))
    c.drawString(url_x, text_y, base_url_display)
    text_y -= 4.5 * mm

    if show_alt_url:
        alt_with_scheme = f"http://{alt_url_display}"
        c.setFont("Helvetica", 10)
        c.setFillColor(HexColor("#555555"))
        c.drawString(text_x, text_y, "(or")
        paren_x = text_x + c.stringWidth("(or ", "Helvetica", 10)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(HexColor("#000000"))
        c.drawString(paren_x, text_y, alt_with_scheme)
        after_x = paren_x + c.stringWidth(alt_with_scheme,
                                          "Helvetica-Bold", 10)
        c.setFont("Helvetica", 10)
        c.setFillColor(HexColor("#555555"))
        c.drawString(after_x, text_y, ")")
        text_y -= 4.5 * mm

    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#555555"))
    c.drawString(text_x, text_y, "into your browser")
    text_y -= 7 * mm

    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#555555"))
    c.drawString(text_x, text_y, "and enter this code:")
    text_y -= 6 * mm

    formatted_code = f"{code[:3]} {code[3:]}"
    c.setFont("Courier-Bold", 14)
    c.setFillColor(HexColor("#000000"))
    c.drawString(text_x, text_y, formatted_code)

    # === Step 3: Voted? Shred or tear up this card ===
    # Lives in the empty space below the voting QR and above the
    # warning strip. The bottom warning strip is the passive safety
    # net; Step 3 is the active instruction. Anchored well below the
    # QR so the bottom of the slip does not look top-heavy.
    step3_top_y = vote_qr_bottom - 13 * mm
    _step_circle(tx, step3_top_y, 3)
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(HexColor("#000000"))
    c.drawString(label_x, step3_top_y, "After casting your vote, tear up this card")

    # --- Warning strip at bottom ---
    _draw_warning_strip(
        c, x, bottom_y, w,
        "\u26A0 Do not submit the paper ballot if you voted with your phone"
    )


# ---------------------------------------------------------------------------
# Code Slips PDF
# ---------------------------------------------------------------------------


def generate_code_slips_pdf(codes, election_name, short_name, wifi_ssid,
                            wifi_password, base_url, is_demo=False,
                            qr_base_url=None):
    """Generate printable voting code cards. 6 per A4 page.

    Args:
        codes: list of voting code strings.
        election_name: name of the election.
        short_name: congregation short name (e.g. 'FRC Darling Downs').
        wifi_ssid: WiFi SSID to display.
        wifi_password: WiFi password to display (may be empty).
        base_url: human-readable voting URL printed on the slip.
        is_demo: if True, add demo watermark and header per page.
        qr_base_url: optional override for the URL encoded in the QR.
            When set and different from base_url, the slip prints both.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Layout: 2 columns x N rows
    cols = 2
    margin = 8 * mm
    h_gap = 6 * mm
    v_gap = 6 * mm
    card_w = (width - 2 * margin - h_gap) / cols
    card_h = _calc_code_slip_height(wifi_password)
    rows_per_page = max(1, int((height - 2 * margin + v_gap) / (card_h + v_gap)))
    cards_per_page = cols * rows_per_page

    for page_start in range(0, len(codes), cards_per_page):
        page_codes = codes[page_start:page_start + cards_per_page]


        for i, code in enumerate(page_codes):
            row = i // cols
            col = i % cols

            card_x = margin + col * (card_w + h_gap)
            card_top_y = height - margin - row * (card_h + v_gap)

            draw_code_slip(c, card_x, card_top_y, card_w, card_h, code,
                           wifi_ssid, wifi_password, base_url,
                           qr_base_url=qr_base_url)

        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Counter Sheet PDF
# ---------------------------------------------------------------------------


def generate_counter_sheet_pdf(election_name, congregation_name, offices_data,
                               member_count=0, is_demo=False):
    """Generate a counter sheet PDF for paper ballot counting.

    Args:
        election_name: name of the election.
        congregation_name: full congregation name.
        offices_data: list of dicts, each with keys:
            'office': dict with 'name', 'max_selections', 'id'
            'candidates': list of dicts with 'name'
        member_count: number of members (for tick box count).
        is_demo: if True, add demo watermark and header per page.

    Returns:
        BytesIO buffer containing the PDF.
    """
    max_votes = max(member_count, 50)  # at least 50 boxes

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    margin = 8 * mm
    box_size = 3.5 * mm
    box_gap = 0.8 * mm
    group_gap = 2.5 * mm  # wider gap between groups of 5
    group_size = 5
    tally_start = 55 * mm
    total_col = width - 25 * mm
    # Calculate how many groups of 5 fit per row
    avail_width = total_col - tally_start - 5 * mm
    group_width = group_size * (box_size + box_gap) - box_gap + group_gap
    groups_per_row = int(avail_width / group_width)
    boxes_per_row = groups_per_row * group_size

    for office_item in offices_data:
        office = office_item["office"]
        candidates = office_item["candidates"]
        if not candidates:
            continue


        # Each office gets its own page(s)
        # Header
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width / 2, height - 18 * mm, "Paper Ballot Counting Sheet")
        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#666666"))
        c.drawCentredString(width / 2, height - 25 * mm,
                            f"{congregation_name} \u2014 {election_name}")

        c.setFont("Helvetica", 8)
        c.drawString(margin, height - 33 * mm,
                     "Counter: _________________________")
        c.drawString(width / 2, height - 33 * mm,
                     "Date: _______________")

        # Office title
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, height - 42 * mm,
                     f"For {office['name']} (select {office['max_selections']})")

        y = height - 50 * mm

        for cand in candidates:
            # Calculate rows needed for this candidate
            row_height_est = box_size + box_gap + 1 * mm
            rows_needed = math.ceil(max_votes / boxes_per_row)
            candidate_height = 6 * mm + rows_needed * row_height_est + 8 * mm

            # Page break if needed
            if y - candidate_height < 25 * mm:
                c.showPage()
                y = height - 20 * mm

            # Candidate name -- shortened to fit between the left margin
            # and the start of the tally grid (with a small visual buffer).
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 10)
            name_max_w = tally_start - margin - 4 * mm
            display_name = shorten_to_fit(
                cand["name"], name_max_w, "Helvetica-Bold", 10)
            c.drawString(margin, y, display_name)

            # Total box (right side)
            c.setStrokeColor(NAVY)
            c.setFont("Helvetica", 7)
            c.setFillColor(HexColor("#666666"))
            c.drawString(total_col, y, "Total")
            c.rect(total_col, y - rows_needed * row_height_est - 2 * mm,
                   12 * mm, rows_needed * row_height_est + 2 * mm)

            y -= 5 * mm

            # Draw tick box grid -- groups of 5, rows wrap on group boundaries
            row_height = box_size + box_gap + 1 * mm
            c.setStrokeColor(HexColor("#CCCCCC"))
            boxes_drawn = 0
            row = 0
            while boxes_drawn < max_votes:
                col_in_row = 0
                for g in range(groups_per_row):
                    if boxes_drawn >= max_votes:
                        break
                    gx = tally_start + g * group_width
                    by = y - row * row_height
                    for b in range(group_size):
                        if boxes_drawn >= max_votes:
                            break
                        bx = gx + b * (box_size + box_gap)
                        c.rect(bx, by, box_size, box_size)
                        boxes_drawn += 1
                        col_in_row += 1

                    # Group number label under the group
                    if boxes_drawn > 0 and boxes_drawn % group_size == 0:
                        c.setFont("Helvetica", 4.5)
                        c.setFillColor(HexColor("#BBBBBB"))
                        label_x = gx + (group_size * (box_size + box_gap) - box_gap) / 2
                        c.drawCentredString(label_x, by - 2.5 * mm, str(boxes_drawn))
                        c.setFillColor(NAVY)
                        c.setStrokeColor(HexColor("#CCCCCC"))

                row += 1

            actual_rows = row
            y -= actual_rows * row_height + 4 * mm

        # Footer
        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#999999"))
        c.drawCentredString(width / 2, 12 * mm,
                            "Compare both counter sheets. Totals must match before entering into the app.")

        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Paper Ballot PDF
# ---------------------------------------------------------------------------


def generate_paper_ballot_pdf(election_name, round_number, office_data,
                              member_count=0, is_demo=False):
    """Generate printable paper ballot forms.

    Args:
        election_name: name of the election.
        round_number: voting round number.
        office_data: list of dicts, each with keys:
            'office': dict with 'name', 'max_selections'
            'candidates': list of dicts with 'name'
        member_count: number of members (determines total ballots printed).
        is_demo: if True, add demo watermark and header per page.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    n_offices = len(office_data)
    max_cands_in_office = (
        max(len(o["candidates"]) for o in office_data) if office_data else 0
    )

    # Single office uses the full ballot width; multiple offices split
    # left/right within the tile.
    two_office_cols = n_offices >= 2

    # Tile geometry (mm) — needed up front to compute the scale cap from
    # actual text widths.
    page_w_mm = 210
    margin_mm = 8
    col_gap_mm = 6
    sub_gap_mm = 3
    col_w_mm = (page_w_mm - 2 * margin_mm - col_gap_mm) / 2  # 94mm
    if two_office_cols:
        sub_w_mm = (col_w_mm - sub_gap_mm) / 2  # 45.5mm
    else:
        sub_w_mm = col_w_mm - 4  # ~90mm (single office, with side padding)

    # Compute the largest scale that keeps every candidate name and office
    # title inside its sub-column, AND fits 6 ballots per A4. The cand row
    # is: checkbox(3*scale mm) + 3mm gap + name. The office title is left-
    # aligned and must fit sub_w_mm. We aim for 6 ballots per A4 (3 rows
    # by 2 cols) so the printer can plan sheet count as ceil(ballots / 6).
    text_caps = [99.0]
    for item in office_data:
        office = item["office"]
        title = f"For {office['name']} (select {office['max_selections']})"
        title_w_mm = stringWidth(title, "Helvetica-Bold", 7) / mm
        if title_w_mm > 0:
            text_caps.append(sub_w_mm / title_w_mm)
        for cand in item["candidates"]:
            name_w_mm = stringWidth(cand["name"], "Helvetica", 7.5) / mm
            if name_w_mm > 0:
                # name_w * scale + box(3*scale) + 5mm padding <= sub_w
                text_caps.append((sub_w_mm - 5) / (name_w_mm + 3))
    text_fit_cap = min(text_caps)

    # Page-fit cap (target 6 ballots per A4, 3 rows of 2 cols, ballot_h<=91mm).
    # Tile height splits into a fixed part and a part that scales with the font:
    #   header  = 5 (top inset) + (1.85*scale + 3) gap + 5 (EXTRA_ABOVE_BODY_MM)
    #             + 4 more in round 2 only, for the round-2 warning slot
    #   body    = 5*n*scale + 4 (tail_mm), for n = max_cands_in_office
    #   padding = 6
    # so ballot_h = fixed_h_mm + scale*(1.85 + 5*n), where fixed_h_mm is
    # 23 in round 1 and 27 in round 2. The round-2 term must be included
    # here or page-fit-bound round-2 tiles overshoot 91mm and drop to 4 per
    # A4. Note the max(4, 1.85*scale + 3) in the code below is inert while
    # scale >= 1 (1.85 + 3 = 4.85 > 4), and scale is floored at 1.0, so the
    # 1.85*scale + 3 branch always wins.
    # Solving fixed_h_mm + scale*(1.85 + 5*n) <= 91 gives the cap below.
    fixed_h_mm = 23 + (4 if round_number > 1 else 0)
    if max_cands_in_office > 0:
        page_fit_cap = (91 - fixed_h_mm) / (1.85 + 5 * max_cands_in_office)
    else:
        page_fit_cap = 99.0

    # Apply the smaller cap with a small safety margin (so text doesn't
    # touch the tile edge), and clamp to a reasonable range. 0.97 keeps
    # enough margin for descender/spacing while letting the font fill the
    # available width.
    scale = min(text_fit_cap, page_fit_cap) * 0.97
    scale = max(1.0, min(scale, 5.0))

    # Sparse offices (<=2 candidates) hit the page-fit cap so loosely
    # that the resulting font is comically large. Trim 40% so the body
    # stays proportionate; residual slack moves into row spacing and
    # vertical centering further down.
    if max_cands_in_office <= 2:
        scale = max(1.0, scale * 0.6)

    if two_office_cols:
        mid = (n_offices + 1) // 2
        left_offices = office_data[:mid]
        right_offices = office_data[mid:]
    else:
        left_offices = office_data
        right_offices = []

    # Heading row (title, optional round-2 warning) stays at base sizes
    # regardless of body scale — otherwise long election names overflow the
    # tile width into the adjacent ballot.
    title_pt = 9
    warning_pt = 6.5
    # Body elements scale together so checkboxes, names, and gaps grow
    # proportionally.
    box_mm = 3 * scale
    row_mm = 5 * scale
    office_header_mm = 4 * scale
    office_pad_mm = 1 * scale
    office_title_pt = 7 * scale
    cand_pt = 7.5 * scale
    # Fixed breathing room below the last candidate of an office. Without
    # this, drawing decrements `row_mm` after every candidate including the
    # last one, which (when row_mm is stretched) becomes a big empty band
    # at the bottom of the tile.
    tail_mm = 4

    def _col_body_height(offices):
        h = 0
        for item in offices:
            n = len(item["candidates"])
            if n == 0:
                h += (office_header_mm + office_pad_mm) * mm
            else:
                h += (office_header_mm + (n - 1) * row_mm + tail_mm + office_pad_mm) * mm
        return h

    body_height = max(_col_body_height(left_offices),
                      _col_body_height(right_offices) if right_offices else 0)

    # The body office-title ascender grows with scale, so reserve enough
    # clearance under the heading to keep "For Elder (select X)" from
    # crowding the election title.
    # Always reserve EXTRA breathing room above the body so the first
    # candidate doesn't sit right under the heading, regardless of how
    # densely packed the body is.
    EXTRA_ABOVE_BODY_MM = 5
    heading_to_body_gap = (
        max(4, 1.85 * scale + 3) + EXTRA_ABOVE_BODY_MM
    ) * mm
    # Header height = top inset + (round-2 warning slot) + heading-to-body gap.
    # Subtitle has been removed.
    header_height = 5 * mm + heading_to_body_gap
    if round_number > 1:
        header_height += 4 * mm
    padding = 6 * mm
    natural_ballot_h = header_height + body_height + padding
    # Standardize at 6 ballots per A4 so the printer can plan sheet count
    # as ceil(ballots / 6) regardless of slate shape. Fixed target is
    # ((usable_h + row_gap) / 3) - row_gap = 91mm.
    TARGET_BALLOT_H_MM = 91
    ballot_h = max(natural_ballot_h, TARGET_BALLOT_H_MM * mm)
    # First, increase office_header_mm (the gap between "For Elder (select N)"
    # and the first candidate) — more extra for fewer candidates, capped so
    # the body still fits inside the tile.
    natural_row_mm = row_mm  # save for cap below
    target_body_h_mm = (ballot_h - header_height - padding) / mm
    if max_cands_in_office > 0:
        natural_body_no_extras_mm = (
            office_header_mm
            + max(0, max_cands_in_office - 1) * natural_row_mm
            + tail_mm + office_pad_mm
        )
        max_office_extra_mm = max(0, target_body_h_mm - natural_body_no_extras_mm)
        # Sparse → bigger extra. N=2 → 8mm, N=4 → 6mm, N=6 → 4mm, N=8 → 3mm.
        desired_office_extra_mm = max(3, 10 - max_cands_in_office)
        office_header_mm += min(desired_office_extra_mm, max_office_extra_mm)

    # Then stretch the inter-candidate row spacing (only the gaps BETWEEN
    # candidates, not the trailing space) to fill what's left, capped at
    # 1.5x natural so we don't end up with comically large gaps. Any
    # residual slack gets centered evenly above and below.
    if max_cands_in_office > 1:
        candidate_room_mm = target_body_h_mm - office_header_mm - tail_mm - office_pad_mm
        stretched_row_mm = candidate_room_mm / (max_cands_in_office - 1)
        cap_row_mm = 1.5 * natural_row_mm
        row_mm = min(max(natural_row_mm, stretched_row_mm), cap_row_mm)
    # Recompute body_height with the chosen office_header and row spacing.
    body_height = max(_col_body_height(left_offices),
                      _col_body_height(right_offices) if right_offices else 0)
    # Centered residual slack — split evenly above and below the body.
    vcenter_offset = max(0, (ballot_h - (header_height + body_height + padding)) / 2)

    # Grid layout: 2 columns, as many rows as fit
    margin = 8 * mm
    col_gap = 6 * mm
    row_gap = 4 * mm
    col_w = (width - 2 * margin - col_gap) / 2
    usable_height = height - 2 * margin
    rows_per_page = max(1, int((usable_height + row_gap) / (ballot_h + row_gap)))
    ballots_per_page = rows_per_page * 2

    sub_gap = 3 * mm
    if two_office_cols:
        sub_w = (col_w - sub_gap) / 2
    else:
        sub_w = col_w - 4 * mm  # full width minus inset padding

    # Generate enough pages
    total_ballots = max(member_count + 10, 30) if member_count > 0 else 30

    ballot_index = 0
    while ballot_index < total_ballots:

        for slot in range(ballots_per_page):
            if ballot_index >= total_ballots:
                break

            col = slot % 2
            row = slot // 2

            x = margin + col * (col_w + col_gap)
            ballot_top = height - margin - row * (ballot_h + row_gap)

            # Dotted border
            c.setStrokeColor(HexColor("#CCCCCC"))
            c.setDash(2, 2)
            c.rect(x, ballot_top - ballot_h, col_w, ballot_h)
            c.setDash()

            # Content \u2014 heading row uses base font sizes regardless of body
            # scale. The heading-to-body gap is scale-aware so the body
            # office title doesn't crowd the heading at large scales.
            # vcenter_offset shifts everything down so the body sits in the
            # middle of the padded tile instead of being flushed to the top.
            cx = x + col_w / 2
            y = ballot_top - 5 * mm - vcenter_offset

            # Title
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", title_pt)
            c.drawCentredString(cx, y, election_name)
            line_inset = 4 * mm
            line_y = y - 2 * mm
            c.setStrokeColor(NAVY)
            c.setLineWidth(0.5)
            c.line(x + line_inset, line_y, x + col_w - line_inset, line_y)

            if round_number > 1:
                y -= 4 * mm
                c.setFont("Helvetica-Bold", warning_pt)
                c.setFillColor(HexColor("#C0392B"))
                c.drawCentredString(cx, y, "Vote ONLY for candidates announced by the chairman")

            y -= heading_to_body_gap

            # Draw offices side by side (or single column for one office)
            body_y = y
            for ci, offices in enumerate([left_offices, right_offices]):
                if not offices:
                    continue
                ox = x + ci * (sub_w + sub_gap) + 2 * mm
                oy = body_y

                for item in offices:
                    office = item["office"]
                    candidates = item["candidates"]

                    c.setFillColor(NAVY)
                    c.setFont("Helvetica-Bold", office_title_pt)
                    c.drawString(ox, oy,
                                 f"For {office['name']} (select {office['max_selections']})")
                    oy -= office_header_mm * mm

                    name_max_w = sub_w - (box_mm + 5) * mm
                    last_idx = len(candidates) - 1
                    for ci_, cand in enumerate(candidates):
                        c.setStrokeColor(NAVY)
                        c.setFillColor(HexColor("#FFFFFF"))
                        c.rect(ox + 1 * mm, oy - 0.5 * mm, box_mm * mm, box_mm * mm)

                        c.setFillColor(NAVY)
                        c.setFont("Helvetica", cand_pt)
                        display_name = shorten_to_fit(
                            cand["name"], name_max_w, "Helvetica", cand_pt)
                        c.drawString(ox + (box_mm + 3) * mm, oy, display_name)
                        # Advance row_mm only BETWEEN candidates; after the
                        # last one, advance just `tail_mm` so we don't leave
                        # a row-sized empty band at the bottom of the office.
                        oy -= (row_mm if ci_ < last_idx else tail_mm) * mm

                    oy -= office_pad_mm * mm

            ballot_index += 1

        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Results PDF
# ---------------------------------------------------------------------------


def generate_results_pdf(election_name, rounds_data, is_demo=False):
    """Export election results as a PDF.

    Args:
        election_name: name of the election.
        rounds_data: list of dicts, one per round, each with keys:
            'round_number': int
            'used_codes': int (digital votes cast)
            'offices': list of dicts, each with:
                'name': office name
                'candidates': list of dicts with 'name', 'digital', 'paper',
                              optional 'postal', and 'total'
        is_demo: if True, add demo watermark and header per page.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title_style = styles["Title"]
    title_style.textColor = NAVY
    elements.append(Paragraph(election_name, title_style))
    elements.append(Paragraph(
        f"Results as at {datetime.now().strftime('%d %B %Y %H:%M')}", styles["Normal"]
    ))
    elements.append(Spacer(1, 10 * mm))

    # Results for each round
    for round_data in rounds_data:
        round_num = round_data["round_number"]
        used_codes = round_data["used_codes"]

        postal_voter_count = round_data.get("postal_voter_count", 0)

        elements.append(Paragraph(f"Round {round_num}", styles["Heading2"]))
        summary = f"Digital votes cast: {used_codes}"
        if postal_voter_count:
            summary += f" &nbsp;|&nbsp; Postal voters: {postal_voter_count}"
        elements.append(Paragraph(summary, styles["Normal"]))
        elements.append(Spacer(1, 5 * mm))

        for office in round_data["offices"]:
            elements.append(Paragraph(f"{office['name']}", styles["Heading3"]))

            has_postal = any(c.get("postal", 0) > 0 for c in office["candidates"])

            candidates = office["candidates"]
            sum_digital = sum(c["digital"] for c in candidates)
            sum_paper = sum(c["paper"] for c in candidates)
            sum_postal = sum(c.get("postal", 0) for c in candidates)
            sum_total = sum(c["total"] for c in candidates)

            if has_postal:
                table_data = [["Candidate", "Digital", "Paper", "Postal", "Total"]]
                for cand in candidates:
                    table_data.append([
                        cand["name"],
                        str(cand["digital"]),
                        str(cand["paper"]),
                        str(cand.get("postal", 0)),
                        str(cand["total"]),
                    ])
                table_data.append([
                    "TOTAL", str(sum_digital), str(sum_paper),
                    str(sum_postal), str(sum_total),
                ])
                col_widths = [180, 65, 65, 65, 65]
            else:
                table_data = [["Candidate", "Digital", "Paper", "Total"]]
                for cand in candidates:
                    table_data.append([
                        cand["name"],
                        str(cand["digital"]),
                        str(cand["paper"]),
                        str(cand["total"]),
                    ])
                table_data.append([
                    "TOTAL", str(sum_digital), str(sum_paper), str(sum_total),
                ])
                col_widths = [200, 70, 70, 70]

            total_row = len(table_data) - 1
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2),
                 [colors.white, HexColor("#F5F5F5")]),
                ("FONTNAME", (0, total_row), (-1, total_row), "Helvetica-Bold"),
                ("BACKGROUND", (0, total_row), (-1, total_row), HexColor("#E0E0E0")),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 8 * mm))

    doc.build(elements)

    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Shared ballot card drawing (used by grid-based and printer exports)
# ---------------------------------------------------------------------------


def _draw_ballot_card(c, x, top_y, card_w, card_h, election_name,
                      left_offices, right_offices, sub_w, sub_gap):
    """Draw a single paper ballot card at the given position.

    Mirrors the dynamic-scale layout used by generate_paper_ballot_pdf:
    no subtitle, scale derived from actual text widths and available
    vertical room, sparse-aware office_header_mm, capped row stretching,
    and vertical centering of any residual slack. Single-office cards
    use the full card width (sub_w/sub_gap from the caller are ignored
    in that case).

    Args:
        c: ReportLab canvas.
        x: left edge of card.
        top_y: top edge of card.
        card_w: width of card.
        card_h: height of card.
        election_name: election title text.
        left_offices: list of office dicts for the left sub-column.
        right_offices: list of office dicts for the right sub-column (may
            be empty for single-office layouts).
        sub_w: width of each office sub-column (used only when both left
            and right have offices).
        sub_gap: gap between the two office sub-columns (same).
    """
    cx = x + card_w / 2
    bottom_y = top_y - card_h

    # Dashed cut border
    c.setStrokeColor(HexColor("#CCCCCC"))
    c.setDash(2, 2)
    c.rect(x, bottom_y, card_w, card_h)
    c.setDash()

    office_data_combined = list(left_offices) + list(right_offices)

    # Always draw the warning strip at the bottom; even an empty card
    # gets it.
    warning_text = "\u26A0 Do not submit this ballot if you voted with your phone (see reverse)"
    if not office_data_combined:
        # Title only, then warning.
        c.setFillColor(HexColor("#000000"))
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(cx, top_y - 5 * mm, election_name)
        _draw_warning_strip(c, x, bottom_y, card_w, warning_text)
        return

    n_offices = len(office_data_combined)
    two_office_cols = n_offices >= 2
    max_cands_in_office = max(len(o["candidates"]) for o in office_data_combined)

    # Single office uses the full card width; multi-office uses the
    # caller-supplied sub_w/sub_gap.
    if two_office_cols:
        sub_w_eff = sub_w
        sub_gap_eff = sub_gap
    else:
        sub_w_eff = card_w - 4 * mm
        sub_gap_eff = 0

    # Compute the largest scale that keeps every name and office title
    # inside its sub-column AND the body (heading + offices + warning)
    # fits the card height. Same approach as generate_paper_ballot_pdf.
    text_caps = [99.0]
    for item in office_data_combined:
        office = item["office"]
        title = f"For {office['name']} (select {office['max_selections']})"
        title_w_mm = stringWidth(title, "Helvetica-Bold", 7) / mm
        if title_w_mm > 0:
            text_caps.append((sub_w_eff / mm) / title_w_mm)
        for cand in item["candidates"]:
            name_w_mm = stringWidth(cand["name"], "Helvetica", 7.5) / mm
            if name_w_mm > 0:
                text_caps.append((sub_w_eff / mm - 5) / (name_w_mm + 3))
    text_fit_cap = min(text_caps)

    # Page-fit cap based on actual card_h. Solve for scale so:
    #   heading + body + bottom_padding + warning <= card_h
    # heading \u2248 5 + max(4, 1.85*scale + 3) + 5(extra)
    # body \u2248 scale * 5 * N + 4 (with tail_mm=4)
    # bottom_padding = 6, warning = _WARNING_STRIP_H_mm
    warn_h_mm = _WARNING_STRIP_H / mm
    fixed_h_mm = 5 + 5 + 3 + 4 + 6 + warn_h_mm  # baseline non-scale fixed parts
    available_for_scale_mm = (card_h / mm) - fixed_h_mm
    if available_for_scale_mm > 0 and max_cands_in_office > 0:
        page_fit_cap = available_for_scale_mm / (1.85 + 5 * max_cands_in_office)
    else:
        page_fit_cap = 1.0
    page_fit_cap = max(0.5, page_fit_cap)

    scale = min(text_fit_cap, page_fit_cap) * 0.97
    scale = max(1.0, min(scale, 5.0))

    # Sparse offices (<=2 candidates): trim 40% so the body font stays
    # proportionate. Slack moves into row spacing and vertical centering.
    if max_cands_in_office <= 2:
        scale = max(1.0, scale * 0.6)

    # Per-element sizes (heading at base point sizes; body scales)
    title_pt = 12  # cards are larger than grid tiles, keep title at 12pt
    box_mm = 3 * scale
    natural_row_mm = 5 * scale
    row_mm = natural_row_mm
    natural_office_header_mm = 4 * scale
    office_header_mm = natural_office_header_mm
    office_pad_mm = 1 * scale
    office_title_pt = 7 * scale
    cand_pt = 7.5 * scale
    tail_mm = 4

    EXTRA_ABOVE_BODY_MM = 5
    heading_to_body_gap = (
        max(4, 1.85 * scale + 3) + EXTRA_ABOVE_BODY_MM
    ) * mm
    header_height = 5 * mm + heading_to_body_gap
    padding = 6 * mm
    warning_h = _WARNING_STRIP_H

    # Body region height = card_h - heading - padding - warning
    target_body_h_mm = (card_h - header_height - padding - warning_h) / mm

    # Sparse-aware office_header extra: more space above first cand for
    # fewer candidates. Capped so the body still fits.
    natural_body_no_extras_mm = (
        office_header_mm
        + max(0, max_cands_in_office - 1) * natural_row_mm
        + tail_mm + office_pad_mm
    )
    max_office_extra_mm = max(0, target_body_h_mm - natural_body_no_extras_mm)
    desired_office_extra_mm = max(3, 10 - max_cands_in_office)
    office_header_mm += min(desired_office_extra_mm, max_office_extra_mm)

    # Stretch row_mm (between candidates only), capped at 1.5x natural.
    if max_cands_in_office > 1:
        candidate_room_mm = target_body_h_mm - office_header_mm - tail_mm - office_pad_mm
        stretched_row_mm = candidate_room_mm / (max_cands_in_office - 1)
        cap_row_mm = 1.5 * natural_row_mm
        row_mm = min(max(natural_row_mm, stretched_row_mm), cap_row_mm)

    # Body height after choices \u2014 for centering
    def _col_body_h_mm(offices):
        h = 0
        for item in offices:
            n = len(item["candidates"])
            if n == 0:
                h += office_header_mm + office_pad_mm
            else:
                h += office_header_mm + (n - 1) * row_mm + tail_mm + office_pad_mm
        return h

    body_height = max(
        _col_body_h_mm(left_offices),
        _col_body_h_mm(right_offices) if right_offices else 0
    ) * mm
    vcenter_offset = max(0, (card_h - header_height - body_height - padding - warning_h) / 2)

    # ---- Draw heading ----
    cx = x + card_w / 2
    y = top_y - 5 * mm - vcenter_offset

    c.setFillColor(HexColor("#000000"))
    c.setFont("Helvetica-Bold", title_pt)
    c.drawCentredString(cx, y, election_name)
    line_inset = 6 * mm
    line_y = y - 2 * mm
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(0.5)
    c.line(x + line_inset, line_y, x + card_w - line_inset, line_y)
    y -= heading_to_body_gap

    # ---- Draw offices ----
    body_y = y
    cols_to_draw = [left_offices, right_offices] if two_office_cols else [left_offices]
    for ci, offices in enumerate(cols_to_draw):
        if not offices:
            continue
        if two_office_cols:
            ox = x + ci * (sub_w_eff + sub_gap_eff) + 2 * mm
        else:
            ox = x + 2 * mm
        oy = body_y

        for item in offices:
            office = item["office"]
            candidates = item["candidates"]

            c.setFillColor(HexColor("#000000"))
            c.setFont("Helvetica-Bold", office_title_pt)
            c.drawString(ox, oy,
                         f"For {office['name']} (select {office['max_selections']})")
            oy -= office_header_mm * mm

            name_max_w = sub_w_eff - (box_mm + 5) * mm
            last_idx = len(candidates) - 1
            for ci_, cand in enumerate(candidates):
                c.setStrokeColor(HexColor("#000000"))
                c.setFillColor(HexColor("#FFFFFF"))
                c.rect(ox + 1 * mm, oy - 0.5 * mm, box_mm * mm, box_mm * mm)

                c.setFillColor(HexColor("#000000"))
                c.setFont("Helvetica", cand_pt)
                display_name = shorten_to_fit(
                    cand["name"], name_max_w, "Helvetica", cand_pt)
                c.drawString(ox + (box_mm + 3) * mm, oy, display_name)
                oy -= (row_mm if ci_ < last_idx else tail_mm) * mm

            oy -= office_pad_mm * mm

    # Warning strip at bottom
    _draw_warning_strip(c, x, bottom_y, card_w, warning_text)


# ---------------------------------------------------------------------------
# Dual-Sided Ballots PDF (grid-based, for duplex printing)
# ---------------------------------------------------------------------------


def generate_dual_sided_ballots_pdf(election_name, short_name, round_number,
                                     office_data, codes, wifi_ssid,
                                     wifi_password, base_url,
                                     member_count=0, is_demo=False,
                                     qr_base_url=None):
    """Generate grid-based dual-sided ballots PDF for duplex printing.

    Odd pages contain a grid of mini paper ballots. Even pages contain a grid
    of mini code slips at mirrored positions. When printed duplex long-edge on
    A4 and cut, each card has a paper ballot on one side and a code slip on
    the other.

    Args:
        election_name: e.g. "Office Bearer Election 2026"
        short_name: e.g. "FRC Darling Downs"
        round_number: current voting round (int)
        office_data: list of dicts, each with:
            'office': dict with 'name', 'max_selections', 'vacancies'
            'candidates': list of dicts with 'name'
        codes: list of plaintext 6-character code strings
        wifi_ssid: WiFi network name
        wifi_password: WiFi password (empty string for open network)
        base_url: e.g. "http://192.168.8.100:5000"
        member_count: number of members (limits cards printed to member_count + 10)
        is_demo: if True, add DEMO watermarks on every page

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    margin = 8 * mm
    h_gap = 6 * mm
    v_gap = 6 * mm
    cols = 2
    col_w = (width - 2 * margin - h_gap) / cols

    # --- Side-by-side office layout ---
    mid = (len(office_data) + 1) // 2
    left_offices = office_data[:mid]
    right_offices = office_data[mid:]
    sub_gap = 3 * mm
    sub_w = (col_w - sub_gap) / 2

    # --- Calculate front (ballot) content height ---
    def _col_body_height(offices):
        h = 0
        for item in offices:
            h += 5.5 * mm + len(item["candidates"]) * 6 * mm + 1 * mm
        return h

    front_header_h = 5 * mm + 4.5 * mm + 4.5 * mm  # top pad + title + subtitle
    body_height = max(
        _col_body_height(left_offices),
        _col_body_height(right_offices) if right_offices else 0
    )
    front_h = front_header_h + body_height + _WARNING_STRIP_H + 2 * mm

    # --- Calculate back (code slip) content height ---
    back_h = _calc_code_slip_height(wifi_password)

    # --- cell_h = max of both sides ---
    cell_h = max(front_h, back_h)

    rows_per_page = max(1, int((height - 2 * margin + v_gap) / (cell_h + v_gap)))
    cards_per_page = cols * rows_per_page

    # Limit cards to member_count + 10 (spare), but never more than available codes
    total_cards = len(codes)

    # --- Helper: compute x, y for a grid slot ---
    def _slot_xy(slot, is_back):
        row = slot // cols
        if is_back:
            col = 1 - (slot % cols)  # mirror for long-edge duplex
        else:
            col = slot % cols
        x = margin + col * (col_w + h_gap)
        top_y = height - margin - row * (cell_h + v_gap)
        return x, top_y

    # --- Helper: draw a mini paper ballot in a cell (FRONT) ---
    def _draw_mini_ballot(slot):
        x, top_y = _slot_xy(slot, is_back=False)
        _draw_ballot_card(c, x, top_y, col_w, cell_h, election_name,
                          left_offices, right_offices, sub_w, sub_gap)

    # --- Generate pages ---
    for batch_start in range(0, len(codes), cards_per_page):
        batch_codes = codes[batch_start:batch_start + cards_per_page]

        # ODD PAGE: paper ballots (front)
        for slot in range(len(batch_codes)):
            _draw_mini_ballot(slot)
        c.showPage()

        # EVEN PAGE: code slips (back, columns mirrored)
        for slot, code_str in enumerate(batch_codes):
            sx, stop_y = _slot_xy(slot, is_back=True)
            draw_code_slip(c, sx, stop_y, col_w, cell_h, code_str,
                           wifi_ssid, wifi_password, base_url,
                           qr_base_url=qr_base_url)
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Printer Pack — individual card-sized PDFs for professional printing
# ---------------------------------------------------------------------------


def _calc_card_dimensions(office_data, wifi_password):
    """Calculate card width, height, sub-column width and gap.

    Returns (col_w, cell_h, sub_w, sub_gap, left_offices, right_offices).
    Shared by grid-based and printer-pack generators.
    """
    h_gap = 6 * mm
    cols = 2
    width, _ = A4
    margin = 8 * mm
    col_w = (width - 2 * margin - h_gap) / cols

    mid = (len(office_data) + 1) // 2
    left_offices = office_data[:mid]
    right_offices = office_data[mid:]
    sub_gap = 3 * mm
    sub_w = (col_w - sub_gap) / 2

    def _col_body_height(offices):
        h = 0
        for item in offices:
            h += 5.5 * mm + len(item["candidates"]) * 6 * mm + 1 * mm
        return h

    front_header_h = 5 * mm + 4.5 * mm + 4.5 * mm
    body_height = max(
        _col_body_height(left_offices),
        _col_body_height(right_offices) if right_offices else 0
    )
    front_h = front_header_h + body_height + _WARNING_STRIP_H + 2 * mm
    back_h = _calc_code_slip_height(wifi_password)
    cell_h = max(front_h, back_h)

    return col_w, cell_h, sub_w, sub_gap, left_offices, right_offices


def generate_ballot_front_pdf(election_name, office_data, wifi_password,
                              is_demo=False):
    """Generate a single-page card-sized PDF with one paper ballot.

    The front is identical for all cards — the printer duplicates it.

    Returns:
        BytesIO buffer containing the PDF.
    """
    col_w, cell_h, sub_w, sub_gap, left, right = _calc_card_dimensions(
        office_data, wifi_password)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(col_w, cell_h))

    _draw_ballot_card(c, 0, cell_h, col_w, cell_h, election_name,
                      left, right, sub_w, sub_gap)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def generate_code_slips_back_pdf(codes, wifi_ssid, wifi_password, base_url,
                                 office_data, member_count=0, is_demo=False,
                                 qr_base_url=None):
    """Generate card-sized PDF with one code slip per page.

    Each page has a unique voting code + QR. The printer cannot duplicate
    these — each page is different.

    Returns:
        BytesIO buffer containing the PDF.
    """
    col_w, cell_h, _, _, _, _ = _calc_card_dimensions(office_data,
                                                       wifi_password)

    total_cards = len(codes)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(col_w, cell_h))

    for code_str in codes:
        draw_code_slip(c, 0, cell_h, col_w, cell_h, code_str,
                       wifi_ssid, wifi_password, base_url,
                       qr_base_url=qr_base_url)
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


def generate_cards_duplex_pdf(election_name, office_data, codes, wifi_ssid,
                              wifi_password, base_url, member_count=0,
                              is_demo=False, qr_base_url=None):
    """Generate a card-sized PDF with interleaved front/back pages.

    Page layout: front, back, front, back, ... — 2N pages for N cards.
    Print duplex; no imposition setup needed. Each consecutive pair of
    pages produces one finished card.

    Returns:
        BytesIO buffer containing the PDF.
    """
    col_w, cell_h, sub_w, sub_gap, left, right = _calc_card_dimensions(
        office_data, wifi_password)

    total_cards = len(codes)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(col_w, cell_h))

    for code_str in codes:
        # Front (ballot)
        _draw_ballot_card(c, 0, cell_h, col_w, cell_h, election_name,
                          left, right, sub_w, sub_gap)
        c.showPage()

        # Back (unique code + QR)
        draw_code_slip(c, 0, cell_h, col_w, cell_h, code_str,
                       wifi_ssid, wifi_password, base_url,
                       qr_base_url=qr_base_url)
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# Attendance register layout. Each sheet must fit on a single A4 page so
# every signing station gets exactly one physical sheet (a steward can mind
# two adjacent sheets). Rows are sized to leave comfortable room to sign;
# rows-per-sheet is what fits one page alongside the title, surname banner,
# table header and tally footer.
ATTENDANCE_ROW_HEIGHT = 13 * mm
ATTENDANCE_ROWS_PER_SHEET = 16


def attendance_register_sheet_count(member_count):
    """Number of one-page sheets the attendance register prints on."""
    return max(1, math.ceil(member_count / ATTENDANCE_ROWS_PER_SHEET))


def generate_attendance_register_pdf(members):
    """Generate a printable attendance register PDF from a member list.

    The list is split into near-equal alphabetical chunks of at most
    ATTENDANCE_ROWS_PER_SHEET names, one single-page sheet per chunk, each
    headed by a surname-range banner so it doubles as station signage.

    Args:
        members: list of dicts with 'first_name' and 'last_name', sorted
            alphabetically by surname.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm,
                            bottomMargin=15 * mm, leftMargin=15 * mm,
                            rightMargin=15 * mm)
    elements = []
    styles = getSampleStyleSheet()

    title_style = styles["Title"]
    title_style.textColor = NAVY
    title_style.fontSize = 16

    range_style = ParagraphStyle(
        "SurnameRange", parent=styles["Heading1"], textColor=NAVY,
        fontSize=22, leading=26, alignment=1, borderColor=GOLD,
        borderWidth=2, borderPadding=8, spaceBefore=4, spaceAfter=8,
    )

    sections = attendance_register_sheet_count(len(members))
    # Near-equal contiguous chunks; the list arrives surname-sorted.
    base, rem = divmod(len(members), sections)
    chunks = []
    start = 0
    for i in range(sections):
        size = base + (1 if i < rem else 0)
        if size:
            chunks.append(members[start:start + size])
        start += size

    counter = 0
    for sheet_no, chunk in enumerate(chunks, 1):
        if sheet_no > 1:
            elements.append(PageBreak())

        title = "Attendance Register"
        if len(chunks) > 1:
            title += f" \u2014 Sheet {sheet_no} of {len(chunks)}"
        elements.append(Paragraph(title, title_style))

        if len(chunks) > 1:
            first = chunk[0]["last_name"].strip()
            last = chunk[-1]["last_name"].strip()
            elements.append(Paragraph(
                f"Surnames: {first} \u2013 {last}", range_style))

        elements.append(Spacer(1, 3 * mm))

        table_data = [["#", "Name", "Signature"]]
        for member in chunk:
            counter += 1
            name = f"{member['last_name']}, {member['first_name']}"
            table_data.append([str(counter), name, ""])

        col_widths = [30, 200, 280]
        row_heights = [11 * mm] + [ATTENDANCE_ROW_HEIGHT] * len(chunk)
        table = Table(table_data, colWidths=col_widths,
                      rowHeights=row_heights, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 12),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, HexColor("#F5F5F5")]),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 5 * mm))
        elements.append(Paragraph(
            "Signatures on this sheet: ____________ "
            "(count after the doors close, then add up all sheets)",
            styles["Normal"]))

    doc.build(elements)
    buf.seek(0)
    return buf


def generate_av_instructions_pdf(election_name, wifi_ssid, wifi_password,
                                 base_url, qr_base_url=None):
    """Generate a one-page A4 instruction sheet for the AV team.

    The election admin prints this and hands it to the person running the
    liturgy screen on election day. It explains how to put the /display page
    onto the screen from the AV booth PC.

    Args:
        election_name: name of the election (used as the page title).
        wifi_ssid: SSID of the election WiFi network.
        wifi_password: password for the election WiFi network.
        base_url: configured voting base URL (e.g. "http://church.vote").
        qr_base_url: optional alternative URL (typically the laptop's
            literal IP). When set and different from base_url, the
            handout shows both as fallbacks for the AV team to try.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm,
                            bottomMargin=18 * mm, leftMargin=20 * mm,
                            rightMargin=20 * mm)
    elements = []
    styles = getSampleStyleSheet()

    # Title bar
    title_style = styles["Title"]
    title_style.textColor = NAVY
    title_style.fontSize = 26
    title_style.leading = 32
    elements.append(Paragraph("Notes for the AV team", title_style))
    subtitle_style = styles["Heading3"]
    subtitle_style.textColor = HexColor("#666666")
    subtitle_style.fontSize = 14
    subtitle_style.leading = 18
    elements.append(Paragraph(
        f"{election_name}: liturgy screen", subtitle_style))
    elements.append(Spacer(1, 8 * mm))

    # Step content styles
    h_style = getSampleStyleSheet()["Heading3"]
    h_style.textColor = NAVY
    h_style.fontSize = 18
    h_style.leading = 22
    h_style.spaceAfter = 2
    body_style = getSampleStyleSheet()["Normal"]
    body_style.fontSize = 14
    body_style.leading = 19

    display_url = f"{base_url.rstrip('/')}/display"
    alt_display_url = ""
    if qr_base_url and qr_base_url.rstrip("/") != base_url.rstrip("/"):
        alt_display_url = f"{qr_base_url.rstrip('/')}/display"
    password_text = wifi_password if wifi_password else "none"

    if alt_display_url:
        open_in_chrome_body = (
            f"<b>{display_url}</b><br/>"
            f"<font size=\"11\" color=\"#666666\">or "
            f"<b>{alt_display_url}</b> if the first does not load.</font>"
        )
    else:
        open_in_chrome_body = f"<b>{display_url}</b>"

    sections = [
        ("Connect to WiFi",
         f"Network: <b>{wifi_ssid}</b><br/>"
         f"Password: <b>{password_text}</b>"),
        ("Open in Chrome", open_in_chrome_body),
        ("Press F11 for fullscreen",
         "Adjust zoom with <b>Ctrl +</b> / <b>Ctrl -</b>. "
         "<b>Ctrl 0</b> resets to 100%."),
        ("Leave on for the meeting",
         "The page updates automatically."),
        ("If anything doesn't display",
         f"Check you're still on the <b>{wifi_ssid}</b> WiFi, then press "
         "<b>F5</b> to refresh."),
    ]

    # Build a 2-column table: [numbered badge] [heading + body]
    badge_style = getSampleStyleSheet()["Normal"]
    badge_style.fontName = "Helvetica-Bold"
    badge_style.fontSize = 28
    badge_style.leading = 32
    badge_style.textColor = colors.white
    badge_style.alignment = 1  # center

    rows = []
    for idx, (heading, body) in enumerate(sections, 1):
        badge = Paragraph(str(idx), badge_style)
        content = [Paragraph(heading, h_style), Paragraph(body, body_style)]
        rows.append([badge, content])

    table = Table(rows, colWidths=[20 * mm, None])
    style_cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (1, 0), (1, -1), 12),
        # Navy badges in column 0
        ("BACKGROUND", (0, 0), (0, -1), NAVY),
        # Thin separator lines between rows
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, HexColor("#DDDDDD")),
        # Outer card border
        ("BOX", (0, 0), (-1, -1), 1, HexColor("#CCCCCC")),
    ]
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)

    doc.build(elements)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Voter handout (7_voter_handout.pdf): A4 duplex, one per voter
# ---------------------------------------------------------------------------

# Target of the "More information?" QR in the front-page footer.
_HANDOUT_INFO_URL = (
    "https://github.com/jdemooijau/frca_election_app"
    "/blob/main/voting-app/docs/FAQ.pdf"
)

# Illustrative only. Every voter gets the same handout, so a real code
# printed here would be a code the whole congregation could use.
_HANDOUT_SAMPLE_CODE = "K7MQ4X"

_HANDOUT_CREAM = HexColor("#FFF8E1")
_HANDOUT_CREAM_EDGE = HexColor("#FFD980")
_HANDOUT_CREAM_TEXT = HexColor("#5A3000")
_HANDOUT_MINT = HexColor("#F4FAF6")
_HANDOUT_MINT_EDGE = HexColor("#B8E0C8")
_HANDOUT_PANEL = HexColor("#F7F9FB")
_HANDOUT_RULE = HexColor("#D4D4D4")
_HANDOUT_GREY = HexColor("#6C757D")
_HANDOUT_BODY = HexColor("#333333")

_HANDOUT_REMINDER = (
    "Reminder: bring your phone, and switch it to silent before the "
    "worship service."
)

_HANDOUT_PREAMBLE = [
    "Sign the attendance register when you arrive.",
    "Wait for the chairman to open the meeting.",
    "You'll be handed a single card. One side is a paper ballot; the "
    "other side is a slip with a six-character code and a QR code for "
    "voting on your phone.",
]

_HANDOUT_PICK_ONE = (
    "You vote one way only - paper or phone, whichever you prefer. If "
    "anything goes wrong with your phone, just use the paper ballot "
    "instead."
)

_HANDOUT_FAQ_INTRO = (
    "Phone voting is new. Below are the safeguards that make sure no "
    "brother can vote twice, no vote is lost, and the count always "
    "reconciles. Voting on paper continues to work exactly as before; "
    "phone voting is opt-in."
)

_HANDOUT_FAQ = [
    ("Can a code be used more than once?",
     "Once you vote on your phone, that code is marked as used. Trying "
     "to use it again shows “this code has already been used.” "
     "Guessing a valid code is also mathematically nearly impossible: "
     "only the codes pre-generated for this meeting are accepted, out "
     "of close to a billion possible six-character codes."),
    ("What if someone votes on both phone and paper?",
     "This risk has always been there on paper: someone could fill in "
     "two ballots, and the number of ballots would then exceed the "
     "number of brothers signed in at the register. If the count does "
     "not match, the chairman decides how to handle it. He can scan "
     "every paper ballot against the record of votes already cast on "
     "phones and set aside any whose code was used twice; or declare "
     "the round void and have everyone vote again; or, where a single "
     "extra ballot cannot change the outcome, record it and let the "
     "result stand."),
    ("Is my vote anonymous?",
     "Only the code and the choice are recorded - never who the code was "
     "given to. Codes are randomly printed and handed out, so no vote "
     "can be traced back to a specific brother."),
    ("What if the WiFi or the system fails?",
     "The WiFi for this election is a small local router set up just for "
     "the meeting; it has nothing to do with the internet or home "
     "broadband. It runs off a single power point and is very unlikely "
     "to fail. Even if it does, paper voting is always available and the "
     "chairman can switch to paper-only at any time, so the meeting "
     "continues without disruption."),
    ("What if my phone won't connect to the WiFi?",
     "Use the paper side of your card. Paper and phone votes are counted "
     "together; either way works."),
    ("What if we need a second round?",
     "If no candidate is elected, the council calls a second round. "
     "You'll be given a new card with a new code; the previous code no "
     "longer works. Vote the same way as before."),
]

_HANDOUT_FAQ_FOOTER = (
    "<b>Still have a question?</b> Speak to your office bearers and/or "
    "scan the QR on the front of this sheet."
)


def _hd_escape(text):
    """Escape a value that is interpolated into Paragraph markup."""
    return (str(text).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _hd_select_hint(office_data):
    """Per-office selection limits, e.g. "Elder: up to 5; Deacon: up to 4"."""
    parts = []
    for item in office_data:
        office = item["office"]
        parts.append("%s: up to %s" % (_hd_escape(office["name"]),
                                       office["max_selections"]))
    return "; ".join(parts)


def _hd_style(name, font, size, leading, color, align=0, **kwargs):
    """Build a handout paragraph style. align: 0 left, 1 centre."""
    return ParagraphStyle(name, fontName=font, fontSize=size,
                          leading=leading, textColor=color,
                          alignment=align, **kwargs)


def _hd_para_height(c, para, w):
    """Height the paragraph needs at width w."""
    return para.wrapOn(c, w, 10000)[1]


def _hd_draw_para(c, para, x, y_top, w):
    """Draw a paragraph with its top edge at y_top; return its bottom y."""
    height = para.wrapOn(c, w, 10000)[1]
    para.drawOn(c, x, y_top - height)
    return y_top - height


def _hd_steps(texts, size=10.5):
    """Numbered step paragraphs with a hanging indent."""
    style = _hd_style("hd_step", "Times-Roman", size, size + 3.4,
                      _HANDOUT_BODY, leftIndent=5 * mm, bulletIndent=0,
                      bulletFontName="Times-Roman", bulletFontSize=size)
    return [Paragraph(text, style, bulletText="%d." % idx)
            for idx, text in enumerate(texts, 1)]


def _hd_panel(c, x, y_bottom, w, h, fill, edge, radius=3 * mm, line=1.5):
    """Rounded panel with a fill and a border."""
    c.setFillColor(fill)
    c.setStrokeColor(edge)
    c.setLineWidth(line)
    c.roundRect(x, y_bottom, w, h, radius, stroke=1, fill=1)
    c.setLineWidth(1)


def _hd_draw_scaled(c, draw_fn, nat_w, nat_h, box_x, box_y_bottom,
                    box_w, box_h):
    """Draw a natural-size card scaled to fit a box, centred in it.

    The card generators (_draw_ballot_card, draw_code_slip) lay
    themselves out for a real card. Drawing them at natural size under a
    canvas scale gives an exact miniature of the printed article, so the
    handout thumbnail cannot drift from what the voter is handed.
    """
    scale = min(box_w / nat_w, box_h / nat_h)
    c.saveState()
    c.translate(box_x + (box_w - nat_w * scale) / 2,
                box_y_bottom + (box_h - nat_h * scale) / 2)
    c.scale(scale, scale)
    draw_fn(nat_w, nat_h)
    c.restoreState()


def _hd_ballot_thumb(c, office_data, election_name, wifi_password,
                     box_x, box_y_bottom, box_w, box_h):
    """Miniature of this election's paper ballot, real slate and all."""
    nat_w, nat_h, sub_w, sub_gap, left, right = _calc_card_dimensions(
        office_data, wifi_password)

    def _draw(w, h):
        _draw_ballot_card(c, 0, h, w, h, election_name,
                          left, right, sub_w, sub_gap)

    _hd_draw_scaled(c, _draw, nat_w, nat_h, box_x, box_y_bottom,
                    box_w, box_h)


def _hd_slip_thumb(c, office_data, wifi_ssid, wifi_password, base_url,
                   qr_base_url, box_x, box_y_bottom, box_w, box_h):
    """Miniature of the code slip, with a placeholder code."""
    nat_w, nat_h, _, _, _, _ = _calc_card_dimensions(
        office_data, wifi_password)

    def _draw(w, h):
        draw_code_slip(c, 0, h, w, h, _HANDOUT_SAMPLE_CODE,
                       wifi_ssid, wifi_password, base_url,
                       qr_base_url=qr_base_url)

    _hd_draw_scaled(c, _draw, nat_w, nat_h, box_x, box_y_bottom,
                    box_w, box_h)


def _hd_column(c, x, y_top, w, h, title, thumb_h, thumb_fn, steps):
    """Draw one bordered column: heading, thumbnail strip, numbered steps."""
    _hd_panel(c, x, y_top - h, w, h, _HANDOUT_PANEL, NAVY)

    pad_x = 5 * mm
    inner_x = x + pad_x
    inner_w = w - 2 * pad_x
    y = y_top - 4 * mm

    c.setFont("Times-Bold", 16)
    c.setFillColor(NAVY)
    c.drawCentredString(x + w / 2, y - 5.6 * mm, title)
    y -= 7.6 * mm
    c.setStrokeColor(GOLD)
    c.setLineWidth(2)
    c.line(inner_x, y, inner_x + inner_w, y)
    c.setLineWidth(1)
    y -= 3 * mm

    thumb_fn(inner_x, y - thumb_h, inner_w, thumb_h)
    y -= thumb_h + 4 * mm

    for step in steps:
        y = _hd_draw_para(c, step, inner_x, y, inner_w) - 1.8 * mm


def _draw_handout_front(c, election_name, office_data, wifi_ssid,
                        wifi_password, base_url, qr_base_url):
    """Front page: how to vote, on paper or on a phone."""
    page_w, page_h = A4
    margin = 12 * mm
    content_w = page_w - 2 * margin
    cx = page_w / 2
    y = page_h - margin

    c.setFont("Times-Bold", 26)
    c.setFillColor(NAVY)
    c.drawCentredString(cx, y - 7.6 * mm, "How to Vote")
    y -= 9.6 * mm

    c.setFont("Times-Italic", 13)
    c.setFillColor(_HANDOUT_GREY)
    c.drawCentredString(cx, y - 4.0 * mm, election_name)
    y -= 6.5 * mm

    # Reminder strip
    reminder = Paragraph(
        _HANDOUT_REMINDER,
        _hd_style("hd_reminder", "Times-Italic", 11, 15,
                  _HANDOUT_CREAM_TEXT, align=1))
    strip_h = _hd_para_height(c, reminder, content_w - 10 * mm) + 5 * mm
    _hd_panel(c, margin, y - strip_h, content_w, strip_h,
              _HANDOUT_CREAM, _HANDOUT_CREAM_EDGE, radius=2 * mm, line=1)
    _hd_draw_para(c, reminder, margin + 5 * mm, y - 2.5 * mm,
                  content_w - 10 * mm)
    y -= strip_h + 3 * mm

    # "Before you vote" box
    heading = Paragraph(
        "BEFORE YOU VOTE",
        _hd_style("hd_pre_h", "Times-Bold", 12, 15, NAVY))
    items = _hd_steps(_HANDOUT_PREAMBLE, size=11)
    inner_w = content_w - 10 * mm
    box_h = (_hd_para_height(c, heading, inner_w) + 1.5 * mm
             + sum(_hd_para_height(c, p, inner_w) + 1 * mm for p in items)
             + 5 * mm)
    _hd_panel(c, margin, y - box_h, content_w, box_h,
              _HANDOUT_MINT, _HANDOUT_MINT_EDGE)
    inner_y = _hd_draw_para(c, heading, margin + 5 * mm, y - 3 * mm,
                            inner_w) - 1.5 * mm
    for item in items:
        inner_y = _hd_draw_para(c, item, margin + 5 * mm, inner_y,
                                inner_w) - 1 * mm
    y -= box_h + 4 * mm

    # "One way only" line
    pick_one = Paragraph(
        _HANDOUT_PICK_ONE,
        _hd_style("hd_pick", "Times-Italic", 12, 16, NAVY, align=1))
    y = _hd_draw_para(c, pick_one, margin, y, content_w) - 4 * mm

    # The footer sits on the bottom margin; the columns fill what is
    # left, so the front page is one A4 side whatever the slate size.
    qr_size = 20 * mm
    footer_h = qr_size + 4 * mm
    footer_top = margin + footer_h
    col_h = y - (footer_top + 4 * mm)

    gutter = 18 * mm
    col_w = (content_w - gutter) / 2
    right_x = margin + col_w + gutter

    select_hint = _hd_select_hint(office_data)
    tick_step = ("Tick the box next to the candidates you choose, up to "
                 "the number the office allows")
    if select_hint:
        tick_step += " (%s)" % select_hint
    paper_steps = _hd_steps([
        tick_step + ".",
        "Fold the card and hand it in for counting.",
    ])
    wifi_note = ("the password is on the code slip" if wifi_password
                 else "no password")
    phone_steps = _hd_steps([
        "Connect your phone to the <b>%s</b> WiFi (%s). The network "
        "name is on the code slip." % (_hd_escape(wifi_ssid), wifi_note),
        "Scan the QR code on the code slip with your phone camera, or "
        "type the URL shown into your browser.",
        "Tick your candidates and tap <b>Cast Your Vote</b>. A check "
        "screen shows your selection. Confirm it (or change it), and "
        "your vote is registered.",
        "<b>Tear up the card.</b> Your phone vote is the one counted; "
        "do not also submit the paper ballot.",
    ])

    # Thumbnail strip. Both thumbnails are miniatures of the same card
    # shape, so the height that makes them exactly as wide as the column
    # is the largest they can usefully be; anything taller just adds
    # blank space around them. Clamped by what the steps leave, so a
    # long SSID or URL cannot push the page over.
    col_inner_w = col_w - 10 * mm
    steps_h = max(
        sum(_hd_para_height(c, p, col_inner_w) + 1.8 * mm
            for p in paper_steps),
        sum(_hd_para_height(c, p, col_inner_w) + 1.8 * mm
            for p in phone_steps),
    )
    chrome_h = 4 * mm + 7.6 * mm + 3 * mm + 4 * mm + 4 * mm
    card_w, card_h = _calc_card_dimensions(office_data, wifi_password)[:2]
    thumb_h = min(card_h * col_inner_w / card_w,
                  col_h - chrome_h - steps_h)

    def _paper_thumb(bx, by, bw, bh):
        _hd_ballot_thumb(c, office_data, election_name, wifi_password,
                         bx, by, bw, bh)

    def _phone_thumb(bx, by, bw, bh):
        _hd_slip_thumb(c, office_data, wifi_ssid, wifi_password, base_url,
                       qr_base_url, bx, by, bw, bh)

    _hd_column(c, margin, y, col_w, col_h, "Paper ballot",
               thumb_h, _paper_thumb, paper_steps)
    _hd_column(c, right_x, y, col_w, col_h, "Phone",
               thumb_h, _phone_thumb, phone_steps)

    c.setFont("Times-Bold", 22)
    c.setFillColor(HexColor("#000000"))
    c.drawCentredString(margin + col_w + gutter / 2,
                        y - col_h / 2 - 3 * mm, "OR")

    # Footer: information line plus the QR to the full FAQ.
    c.setStrokeColor(_HANDOUT_RULE)
    c.line(margin, footer_top, margin + content_w, footer_top)
    c.setFont("Times-Bold", 11)
    c.setFillColor(NAVY)
    c.drawString(margin, footer_top - 6 * mm, "More information?")
    c.setFont("Times-Roman", 10)
    c.setFillColor(_HANDOUT_BODY)
    c.drawString(margin, footer_top - 10.5 * mm,
                 "Speak to your office bearers and/or scan the QR.")
    c.drawImage(_generate_qr_image(_HANDOUT_INFO_URL),
                margin + content_w - qr_size, margin,
                qr_size, qr_size, mask="auto")


def _draw_handout_back(c):
    """Back page: the safeguards FAQ. Nothing here depends on the slate."""
    page_w, page_h = A4
    margin = 12 * mm
    content_w = page_w - 2 * margin
    y = page_h - margin

    title = Paragraph(
        "Phone voting: frequently asked questions",
        _hd_style("hd_faq_title", "Times-Bold", 26, 30, NAVY, align=1))
    y = _hd_draw_para(c, title, margin, y, content_w) - 6 * mm

    intro = Paragraph(
        _HANDOUT_FAQ_INTRO,
        _hd_style("hd_faq_intro", "Times-Roman", 12, 18, NAVY))
    y = _hd_draw_para(c, intro, margin, y, content_w) - 6 * mm

    bar_x = margin
    text_x = margin + 4 * mm
    text_w = content_w - 4 * mm
    for question, answer in _HANDOUT_FAQ:
        q_para = Paragraph(
            question, _hd_style("hd_faq_q", "Times-Bold", 13, 16, NAVY))
        a_para = Paragraph(
            answer,
            _hd_style("hd_faq_a", "Times-Roman", 11, 16.5, _HANDOUT_BODY))
        block_h = (_hd_para_height(c, q_para, text_w) + 1.5 * mm
                   + _hd_para_height(c, a_para, text_w))
        c.setStrokeColor(GOLD)
        c.setLineWidth(3)
        c.line(bar_x, y, bar_x, y - block_h)
        c.setLineWidth(1)
        inner_y = _hd_draw_para(c, q_para, text_x, y, text_w) - 1.5 * mm
        _hd_draw_para(c, a_para, text_x, inner_y, text_w)
        y -= block_h + 5 * mm

    y -= 1 * mm
    c.setStrokeColor(_HANDOUT_RULE)
    c.line(margin, y, margin + content_w, y)
    footer = Paragraph(
        _HANDOUT_FAQ_FOOTER,
        _hd_style("hd_faq_foot", "Times-Roman", 10, 15, _HANDOUT_BODY))
    _hd_draw_para(c, footer, margin, y - 4 * mm, content_w)


def generate_voter_handout_pdf(election_name, office_data, wifi_ssid,
                               wifi_password, base_url, qr_base_url=None):
    """Generate the 2-page A4 voter handout for this election.

    Front: how to vote on paper or on a phone, with a miniature of this
    election's actual ballot card and code slip. Back: the safeguards
    FAQ. Printed duplex (long edge), one sheet per voter.

    Everything naming a candidate, an office, the WiFi or the URL is
    drawn from the arguments, so the handout cannot show a stale slate.

    Args:
        election_name: election title, shown under the heading and on
            the ballot thumbnail.
        office_data: list of {"office": ..., "candidates": [...]} as
            passed to the ballot generators.
        wifi_ssid: SSID of the election WiFi network.
        wifi_password: password for the election WiFi ("" if open).
        base_url: voting URL printed on the code slip.
        qr_base_url: optional alternative URL encoded in the slip QR.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    _draw_handout_front(c, election_name, office_data, wifi_ssid,
                        wifi_password, base_url, qr_base_url)
    c.showPage()
    _draw_handout_back(c)
    c.showPage()

    c.save()
    buf.seek(0)
    return buf


def generate_printer_pack_zip(election_name, short_name, round_number,
                              office_data, codes, wifi_ssid, wifi_password,
                              base_url, congregation_name, members,
                              election_date=None, member_count=0,
                              is_demo=False, qr_base_url=None):
    """Generate a ZIP containing all PDFs needed for professional printing.

    Contents (filenames prefixed so they sort in the order described
    in 0_INSTRUCTIONS.txt — read that first):

        0_INSTRUCTIONS.txt        — explanation of each file (read first)
        1_ballot_front.pdf        — card-sized paper ballot (duplicate this)
        2_code_slips_back.pdf     — N pages, card-sized unique code slips
        3_cards_duplex.pdf        — 2N pages, card-sized, interleaved front/back
        4_dual_sided_ballots.pdf  — grid layout for home duplex printing
        5_counter_sheet.pdf       — tally sheet for counting paper ballots
        6_attendance_register.pdf — sign-in sheet for election day
        7_voter_handout.pdf       — A4 duplex (how-to-vote / safeguards FAQ); 1 per voter
        8_av_instructions.pdf     — handout for the AV team

    Returns:
        BytesIO buffer containing the ZIP.
    """
    # 1. Ballot front (1 page, card-sized)
    front_buf = generate_ballot_front_pdf(
        election_name, office_data, wifi_password, is_demo=is_demo)

    # 2. Code slips back (N pages, card-sized)
    back_buf = generate_code_slips_back_pdf(
        codes, wifi_ssid, wifi_password, base_url, office_data,
        member_count=member_count, is_demo=is_demo,
        qr_base_url=qr_base_url)

    # 3. Cards duplex (interleaved front/back, card-sized, 2N pages)
    cards_duplex_buf = generate_cards_duplex_pdf(
        election_name, office_data, codes,
        wifi_ssid, wifi_password, base_url,
        member_count=member_count, is_demo=is_demo,
        qr_base_url=qr_base_url)

    # 4. Dual-sided grid layout (for home A4 printing fallback)
    dual_buf = generate_dual_sided_ballots_pdf(
        election_name, short_name, round_number, office_data, codes,
        wifi_ssid, wifi_password, base_url,
        member_count=member_count, is_demo=is_demo,
        qr_base_url=qr_base_url)

    # 4. Counter sheet
    counter_buf = generate_counter_sheet_pdf(
        election_name, congregation_name, office_data,
        member_count=member_count, is_demo=is_demo)

    # 5. Attendance register
    attendance_buf = generate_attendance_register_pdf(members)

    # 6. Voter handout: 2-page A4 (front = how-to-vote on paper or
    #    phone, back = the safeguards FAQ). Drawn for this election, so
    #    its ballot and code-slip thumbnails show the slate the voter is
    #    actually handed.
    handout_buf = generate_voter_handout_pdf(
        election_name, office_data, wifi_ssid, wifi_password, base_url,
        qr_base_url=qr_base_url)

    # 7. AV team instructions (handout for the liturgy screen operator)
    av_buf = generate_av_instructions_pdf(
        election_name, wifi_ssid, wifi_password, base_url,
        qr_base_url=qr_base_url)

    # 8. Instructions
    # One card per generated code. Multi-round elections generate codes
    # for all rounds at once (members x max_rounds), so the printer pack
    # produces all the cards needed for the whole election.
    total_cards = len(codes)
    total_cards_x2 = total_cards * 2
    member_count_for_print = str(member_count) if member_count else "N"
    attendance_sheets = attendance_register_sheet_count(len(members))
    if attendance_sheets > 1:
        attendance_split_note = (
            f"\n   Split into {attendance_sheets} single-page alphabetical"
            "\n   sheets (surname ranges printed on each) so sign-in can run"
            "\n   at parallel stations — one pen per sheet, and one steward"
            "\n   can mind two adjacent sheets."
        )
    else:
        attendance_split_note = ""
    instructions = f"""\
PRINTER PACK — {election_name}
{'=' * 60}

Thank you for printing the materials for our office bearer election.
Your work helps the congregation cast their votes on election day,
and we are grateful for your care and skill.

This ZIP contains everything needed to print materials for the
church office bearer election. Below is a description of each file.


CHOOSING A FORMAT
─────────────────
Three printing workflows are provided. Pick ONE based on your equipment:

  • Pro print shop with imposition software:    use #1 + #2
  • Card-size duplex printer, no imposition:    use #3
  • A4 home/office printer, no card media:      use #4


1. 1_ballot_front.pdf  (1 page)
   ─────────────────────────────
   The FRONT side of the voting card. Shows the election name,
   offices, and candidate checkboxes.

   This page is IDENTICAL for all cards. Your imposition software
   should duplicate it to produce {total_cards} copies, arranged on
   sheets for cutting. Card size: ~94 x 88 mm.

   Use this WITH file #2. Skip if using #3 or #4.


2. 2_code_slips_back.pdf  ({total_cards} pages)
   ─────────────────────────────
   The BACK side of the voting card. Each page has a UNIQUE voting
   code and QR code — one per card. Do NOT duplicate these pages.

   Page 1 pairs with copy 1 of the front, page 2 with copy 2, etc.
   Same card size as the front (~94 x 88 mm).

   Print these duplex with the front, matching page order:
   Front copy 1 + Back page 1, Front copy 2 + Back page 2, etc.

   Use this WITH file #1. Skip if using #3 or #4.


3. 3_cards_duplex.pdf  ({total_cards_x2} pages)
   ─────────────────────────────
   ALL-IN-ONE alternative to #1 + #2. Card-sized, with front and back
   interleaved on consecutive pages: page 1 is the front of card 1,
   page 2 is the back of card 1, page 3 is the front of card 2, etc.

   No imposition setup needed: send to a duplex printer that accepts
   card-size media and you get {total_cards} finished cards.

   Use INSTEAD of #1 + #2 if your printer can do card-size duplex.


4. 4_dual_sided_ballots.pdf
   ─────────────────────────────
   A4 FALLBACK for home/office printing without card media. Contains
   the same ballots in a 6-per-page grid layout, ready for duplex
   printing on A4 with long-edge binding. Cut along the dashed lines
   after printing.

   Use INSTEAD of #1 + #2 or #3 if you only have an A4 printer.


5. 5_counter_sheet.pdf
   ─────────────────────────────
   Tally sheet for counting paper ballots by hand. One page per
   office, with tick boxes for each candidate. Print on A4.


6. 6_attendance_register.pdf
   ─────────────────────────────
   Sign-in sheet listing all members. Each attendee signs next to
   their name upon arrival. Required per Article 4 of the church
   order. Print on A4.{attendance_split_note}


7. 7_voter_handout.pdf  (2 pages, duplex)
   ─────────────────────────────
   A4 voter handout. Front: how to vote on paper or on the phone.
   Back: "Phone voting: frequently asked questions" answering the
   common voter questions about codes, anonymity, double voting,
   WiFi failure, and second rounds. Designed to be emailed to
   members ahead of the meeting AND/OR printed and handed out at
   the sign-in table. Print one duplex copy per voter (long-edge
   binding).


8. 8_av_instructions.pdf  (1 page)
   ─────────────────────────────
   One-page handout for the AV team running the liturgy screen.
   The election admin gives this to the AV operator on the day.
   Print on A4. Not needed in bulk: 1-2 copies is enough.


PRINTING SUMMARY
{'=' * 60}

  File                        Size        Print     Yields              Paper
  ──────────────────────────  ──────────  ───────   ──────────────────  ──────
  1_ballot_front.pdf          Card-sized  x1        duplicated to {total_cards:<5}  Duplex (with #2)
  2_code_slips_back.pdf       Card-sized  x1        {total_cards} unique cards   Duplex (with #1)
  3_cards_duplex.pdf          Card-sized  x1        {total_cards} cards          Duplex (replaces #1+#2)
  4_dual_sided_ballots.pdf    A4          x1        {total_cards} cards (cut)    Duplex (A4 fallback)
  5_counter_sheet.pdf         A4          x2-3      tally sheet         Simplex
  6_attendance_register.pdf   A4          x1-2      sign-in sheet       Simplex
  7_voter_handout.pdf         A4          x{member_count_for_print:<3}      voter handout       Duplex
  8_av_instructions.pdf       A4          x1-2      AV handout          Simplex

For questions, contact the election administrator.
"""

    # Assemble ZIP. Filenames are prefixed 1_..8_ so they sort in the
    # order described in INSTRUCTIONS.txt when extracted.
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("1_ballot_front.pdf", front_buf.getvalue())
        zf.writestr("2_code_slips_back.pdf", back_buf.getvalue())
        zf.writestr("3_cards_duplex.pdf", cards_duplex_buf.getvalue())
        zf.writestr("4_dual_sided_ballots.pdf", dual_buf.getvalue())
        zf.writestr("5_counter_sheet.pdf", counter_buf.getvalue())
        zf.writestr("6_attendance_register.pdf", attendance_buf.getvalue())
        zf.writestr("7_voter_handout.pdf", handout_buf.getvalue())
        zf.writestr("8_av_instructions.pdf", av_buf.getvalue())
        zf.writestr("0_INSTRUCTIONS.txt", instructions)

    zip_buf.seek(0)
    return zip_buf


# ---------------------------------------------------------------------------
# DOCX generation — Secretary's election minutes
# ---------------------------------------------------------------------------

def generate_minutes_docx(
    congregation_name,
    election_name,
    election_date,
    rounds_data,
    elected_summary,
    is_demo=False,
):
    """Generate a DOCX election minutes document for the secretary.

    Args:
        congregation_name: e.g. "Free Reformed Church of Darling Downs"
        election_name: e.g. "Office Bearer Election 2026"
        election_date: e.g. "4 October 2026"
        rounds_data: list of dicts per round, each with:
            'round_number': int
            'participants': int (in-person + postal)
            'in_person': int
            'postal_voter_count': int
            'used_codes': int
            'paper_ballot_count': int
            'total_ballots': int
            'offices': list of dicts, each with:
                'name': str
                'vacancies': int
                'max_selections': int
                'threshold_6a': float
                'threshold_6b': int
                'candidates': list of dicts with
                    'name', 'digital', 'paper', 'postal', 'total',
                    'elected' (bool)
        elected_summary: list of dicts with 'office' and 'names' (list of str)
        is_demo: if True, adds DEMO notice to header

    Returns:
        BytesIO buffer containing the DOCX file.
    """
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT

    doc = Document()

    # -- Page margins --
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # -- Styles --
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(6)

    navy = RGBColor(0x1A, 0x33, 0x53)

    # -- Helper: add a heading with navy colour --
    def _heading(text, level=1):
        h = doc.add_heading(text, level=level)
        for run in h.runs:
            run.font.color.rgb = navy
        return h

    # -- Helper: add a paragraph --
    def _para(text, bold=False, italic=False):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = bold
        run.italic = italic
        return p

    # -- Helper: add a placeholder the secretary fills in --
    def _placeholder(text):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.italic = True
        run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        return p

    # -- Helper: join names grammatically ("Brs A, B and C") --
    def _join_brs(names):
        names = list(names)
        if not names:
            return ""
        if len(names) == 1:
            return f"Br {names[0]}"
        return "Brs " + ", ".join(names[:-1]) + f" and {names[-1]}"

    def _vacancy_phrase(n):
        return f"{n} vacanc{'y' if n == 1 else 'ies'}"

    # =====================================================================
    # TITLE
    # =====================================================================
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(congregation_name)
    run.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = navy

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Minutes of the Congregational Meeting "
        "for the Election of Office Bearers"
    )
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = navy

    if election_date:
        date_p = doc.add_paragraph()
        date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = date_p.add_run(election_date)
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_paragraph()  # spacer

    # =====================================================================
    # 1. OPENING
    # =====================================================================
    _heading("1. Opening", level=2)
    _placeholder(
        "[The Chairman, Br [name]] opened the meeting at [time] and "
        "welcomed all present. The Congregation sang from [hymn]. He "
        "read from [scripture reference] and led in prayer."
    )

    # =====================================================================
    # 2. VOTING - narrative lead-in, then one sub-section per round
    # =====================================================================
    _heading("2. Voting", level=2)

    round1 = rounds_data[0] if rounds_data else None

    _para(
        "The Secretary, Br [name], read out Articles 4, 6 and 12 of the "
        "Rules for the Election of Office Bearers."
    )

    if round1:
        in_person = round1["in_person"]
        postal = round1["postal_voter_count"]
        if postal > 0:
            _para(
                f"The Chairman advised that a total of {in_person} male "
                "communicant members present had signed the attendance "
                f"register and that {postal} postal vote"
                f"{'' if postal == 1 else 's'} had been received. "
                "Brs [name] and [name] were appointed to assist with the "
                "collection and counting of votes."
            )
        else:
            _para(
                f"The Chairman advised that a total of {in_person} male "
                "communicant members present had signed the attendance "
                "register. Brs [name] and [name] were appointed to assist "
                "with the collection and counting of votes."
            )

    total_rounds = len(rounds_data)

    for rd_idx, rd in enumerate(rounds_data):
        round_num = rd["round_number"]
        is_last_round = (rd_idx == total_rounds - 1)
        _heading(f"2.{rd_idx + 1} Round {round_num}", level=3)

        # Narrative introduction to the round
        office_phrases = [
            f"the office of {o['name']} ({_vacancy_phrase(o['vacancies'])})"
            for o in rd["offices"]
        ]
        if round_num == 1:
            if len(office_phrases) == 1:
                intro = f"Voting was conducted for {office_phrases[0]}."
            elif len(office_phrases) == 2:
                intro = (
                    f"Voting was conducted for {office_phrases[0]} "
                    f"and {office_phrases[1]}."
                )
            else:
                intro = (
                    "Voting was conducted for "
                    + ", ".join(office_phrases[:-1])
                    + f", and {office_phrases[-1]}."
                )
        else:
            parts = []
            for o in rd["offices"]:
                names = [c["name"] for c in o["candidates"]]
                parts.append(
                    f"the office of {o['name']} "
                    f"({_vacancy_phrase(o['vacancies'])} remaining) "
                    f"between {_join_brs(names)}"
                )
            if len(parts) == 1:
                intro = f"A further ballot was conducted for {parts[0]}."
            else:
                intro = (
                    "A further ballot was conducted for "
                    + "; and for ".join(parts)
                    + "."
                )
        _para(intro)

        # Brief threshold mention per office
        for o in rd["offices"]:
            t6a = o.get("threshold_6a")
            t6b = o.get("threshold_6b")
            if t6a is not None and t6b is not None:
                _para(
                    f"For the office of {o['name']}, a candidate required "
                    f"more than {t6a:.2f} votes (Article 6a) and at least "
                    f"{t6b} votes (Article 6b) to be elected."
                )

        # Round-level ballot totals with digital / in-person / postal split
        rd_total = rd.get("total_ballots", 0)
        rd_digital = rd.get("used_codes", 0)
        rd_paper = rd.get("paper_ballot_count", 0)
        rd_postal = rd.get("postal_voter_count", 0)
        if rd_total > 0:
            def _pct(n):
                return f"{(100 * n / rd_total):.1f}%"
            if rd_postal > 0:
                _para(
                    f"A total of {rd_total} ballots were cast in this round: "
                    f"{rd_digital} digital ({_pct(rd_digital)}), "
                    f"{rd_paper} in-person ({_pct(rd_paper)}), "
                    f"and {rd_postal} postal ({_pct(rd_postal)})."
                )
            else:
                _para(
                    f"A total of {rd_total} ballots were cast in this round: "
                    f"{rd_digital} digital ({_pct(rd_digital)}) "
                    f"and {rd_paper} in-person ({_pct(rd_paper)})."
                )

        # Vote tables per office. The candidate breakdown is always shown
        # as Digital + In-person, with Postal added in round 1 when any
        # postal votes were received.
        for o in rd["offices"]:
            p = doc.add_paragraph()
            run = p.add_run(o["name"])
            run.bold = True
            run.font.size = Pt(11)
            p.paragraph_format.space_after = Pt(2)

            cands = o["candidates"]
            if not cands:
                _placeholder(f"[No candidates stood for {o['name']} this round.]")
                continue

            has_postal = round_num == 1 and any(
                c.get("postal", 0) > 0 for c in cands
            )

            if has_postal:
                headers = ["Candidate", "Digital", "In-person", "Postal", "Total"]
                col_widths = [Cm(6.0), Cm(2.5), Cm(2.5), Cm(2.5), Cm(2.5)]
            else:
                headers = ["Candidate", "Digital", "In-person", "Total"]
                col_widths = [Cm(7.0), Cm(3.0), Cm(3.0), Cm(3.0)]
            col_count = len(headers)

            table = doc.add_table(rows=1 + len(cands), cols=col_count)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            table.allow_autofit = False
            for row in table.rows:
                for ci, width in enumerate(col_widths):
                    row.cells[ci].width = width

            for i, hdr in enumerate(headers):
                cell = table.rows[0].cells[i]
                cell.text = hdr
                if i > 0:
                    for paragraph in cell.paragraphs:
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.size = Pt(10)

            for row_idx, cand in enumerate(cands):
                row = table.rows[row_idx + 1]
                row.cells[0].text = f"Br {cand['name']}"
                row.cells[1].text = str(cand.get("digital", 0))
                row.cells[2].text = str(cand.get("paper", 0))
                if has_postal:
                    row.cells[3].text = str(cand.get("postal", 0))
                    row.cells[4].text = str(cand["total"])
                else:
                    row.cells[3].text = str(cand["total"])
                for ci in range(1, col_count):
                    for paragraph in row.cells[ci].paragraphs:
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for ci in range(col_count):
                    for paragraph in row.cells[ci].paragraphs:
                        for run in paragraph.runs:
                            run.font.size = Pt(10)
                if cand.get("elected"):
                    for ci in range(col_count):
                        for paragraph in row.cells[ci].paragraphs:
                            for run in paragraph.runs:
                                run.bold = True

            # Accountability rows. Every selection on every ballot is
            # accounted for: a tick for a candidate, a blank (unused)
            # selection, or a selection on a spoilt ballot. Neither blank
            # nor spoilt counts toward the Article 6a denominator.
            office_max = o.get("max_selections") or 1
            possible = rd.get("total_ballots", 0) * office_max
            spoilt = o.get("spoilt_count", 0) or 0
            spoilt_slots = spoilt * office_max
            ticks = sum(c["total"] for c in cands)
            blank = max(possible - ticks - spoilt_slots, 0)
            for label, value, bold in (
                ("Blank votes", str(blank), False),
                ("Spoilt ballots", f"{spoilt} ({spoilt_slots})", False),
                ("Total", str(possible), True),
            ):
                row = table.add_row()
                for ci, width in enumerate(col_widths):
                    row.cells[ci].width = width
                row.cells[0].text = label
                row.cells[col_count - 1].text = value
                for paragraph in row.cells[col_count - 1].paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for ci in range(col_count):
                    for paragraph in row.cells[ci].paragraphs:
                        for run in paragraph.runs:
                            run.font.size = Pt(10)
                            run.italic = not bold
                            run.bold = bold
            _para(
                f"For the office of {o['name']}, "
                f"{blank} selection{'' if blank == 1 else 's'} "
                f"{'was' if blank == 1 else 'were'} left blank and "
                f"{spoilt} ballot{'' if spoilt == 1 else 's'} "
                f"{'was' if spoilt == 1 else 'were'} spoilt. "
                f"Spoilt ballots are shown as ballots, with the number of "
                f"selections they carried in brackets."
            )

        # Declaration sentence
        elected_clauses = []
        remaining_offices = []
        for o in rd["offices"]:
            elected_names = [c["name"] for c in o["candidates"] if c.get("elected")]
            unfilled = o["vacancies"] - len(elected_names)
            if elected_names:
                elected_clauses.append({
                    "office": o["name"],
                    "names": elected_names,
                })
            if unfilled > 0:
                remaining_offices.append((o["name"], unfilled))

        if elected_clauses:
            def _clause_text(c):
                return f"for the office of {c['office']}, {_join_brs(c['names'])}"
            if len(elected_clauses) == 1:
                names = elected_clauses[0]["names"]
                verb = "were" if len(names) > 1 else "was"
                _para(
                    f"The Chairman declared that {_join_brs(names)} {verb} "
                    f"elected for the office of {elected_clauses[0]['office']}."
                )
            else:
                joined = "; and ".join(_clause_text(c) for c in elected_clauses)
                _para(
                    "The Chairman declared that the following brothers "
                    f"were elected: {joined}."
                )
        else:
            _para(
                "The Chairman declared that no candidate was elected in "
                "this round, and a further ballot would be required."
            )

        # Outcome after this round
        if is_last_round:
            if remaining_offices:
                parts = [
                    f"{name} ({count} unfilled)"
                    for name, count in remaining_offices
                ]
                _para(
                    "The election for " + ", ".join(parts) +
                    " concluded without all vacancies being filled."
                )
            else:
                _para("All vacancies were now filled.")

            # Final result sentence (end-of-voting summary). Skip when
            # there was only one round — the chairman's declaration above
            # already lists the same brothers and the repetition reads
            # awkwardly. Multi-round elections still get the summary so
            # readers don't have to assemble it from each round's
            # declaration.
            if elected_summary and total_rounds > 1:
                clauses = []
                for item in elected_summary:
                    if item["names"]:
                        clauses.append(
                            f"for the office of {item['office']}, "
                            f"{_join_brs(item['names'])}"
                        )
                if clauses:
                    p = doc.add_paragraph()
                    run = p.add_run(
                        "The final result of the election is: "
                        + "; and ".join(clauses)
                        + "."
                    )
                    run.bold = True
        elif remaining_offices:
            parts = [
                f"the office of {name} ({count} vacanc{'y' if count == 1 else 'ies'} to fill)"
                for name, count in remaining_offices
            ]
            _para(
                "A further ballot was required for "
                + ", ".join(parts) + "."
            )

    # =====================================================================
    # 3. ARTICLE 12 - Objections
    # =====================================================================
    _heading("3. Objections (Article 12)", level=2)
    _placeholder(
        "The Chairman provided opportunity for any objections to be "
        "raised, noting that Article 12 of the Rules requires that any "
        "objections of a formal nature against procedure must be lodged "
        "at the meeting. [No objections were raised. / Record any "
        "objections here.]"
    )

    # =====================================================================
    # 4. CLOSING
    # =====================================================================
    _heading("4. Closing", level=2)
    _placeholder(
        "Br [name] led in prayer, and the Chairman closed the meeting "
        "at [time]."
    )

    # =====================================================================
    # SIGNATURE BLOCK
    # =====================================================================
    doc.add_paragraph()
    doc.add_paragraph()

    sig_table = doc.add_table(rows=2, cols=2)
    sig_table.alignment = WD_TABLE_ALIGNMENT.CENTER

    sig_table.rows[0].cells[0].text = "Chairman:"
    sig_table.rows[0].cells[1].text = "Secretary:"
    sig_table.rows[1].cells[0].text = "\n\n____________________________"
    sig_table.rows[1].cells[1].text = "\n\n____________________________"

    for row in sig_table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(11)

    # =====================================================================
    # Footer note
    # =====================================================================
    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run(
        "This document was generated by the FRCA Election App. "
        "The secretary should verify all details and complete the "
        "sections marked in grey before filing in the minute book."
    )
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
