"""
Shared PDF generation functions for the FRCA Election App.

Extracted from app.py so that both Flask routes and CLI scripts
can generate PDFs without code duplication.
"""

import io
import math
import zipfile
from datetime import datetime

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

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


def draw_demo_watermark(c, page_width, page_height):
    """Draw diagonal 'DEMO' text in light grey across the page."""
    c.saveState()
    c.setFont("Helvetica-Bold", 100)
    c.setFillColor(HexColor("#CCCCCC"))
    c.setFillAlpha(0.3)
    c.translate(page_width / 2, page_height / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, "DEMO")
    c.restoreState()


def draw_demo_header(c, page_width, page_height):
    """Draw 'DEMO MODE -- Practice Election' at top of page in red."""
    c.saveState()
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(HexColor("#C0392B"))
    c.drawCentredString(page_width / 2, page_height - 10 * mm,
                        "DEMO MODE \u2014 Practice Election")
    c.restoreState()


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
    """Calculate the content height needed for a code slip."""
    h = 0
    h += 10 * mm  # header ("Vote Digitally" + rule + top padding)
    h += 17 * mm  # step 1 (WiFi) + gap to step 2
    h += 3.5 * mm  # password / "No password needed" line
    h += 32 * mm  # step 2 (QR row: label + QR/code side by side)
    h += 17 * mm  # dashed separator + step 3 (fallback)
    h += _WARNING_STRIP_H  # warning strip
    h += 2 * mm   # bottom padding
    return h


def draw_code_slip(c, x, top_y, w, cell_h, code, wifi_ssid, wifi_password,
                   base_url):
    """Draw a modern B&W-optimised code slip in the given cell.

    Layout: "Vote Digitally" header → Step 1 WiFi → Step 2 QR+code →
    Step 3 fallback URL (subdued) → warning strip.
    """
    cx = x + w / 2
    tx = x + 3 * mm
    bottom_y = top_y - cell_h
    y = top_y - 5 * mm

    # --- Solid border (rounded) ---
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(1.5)
    c.roundRect(x, bottom_y, w, cell_h, 2 * mm)
    c.setLineWidth(1)

    # --- Header: "Vote Digitally" + rule ---
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(HexColor("#000000"))
    c.drawCentredString(cx, y, "Vote Digitally")
    y -= 3.5 * mm
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(1.5)
    c.line(x + 3 * mm, y, x + w - 3 * mm, y)
    c.setLineWidth(1)
    y -= 6 * mm

    # --- Step number circle helper ---
    def _step_circle(sx, sy, num, active=True):
        r = 3.5 * mm
        cy = sy + 1 * mm  # centre circle on text baseline
        if active:
            c.setFillColor(HexColor("#000000"))
        else:
            c.setFillColor(HexColor("#DDDDDD"))
        c.circle(sx + r, cy, r, fill=1, stroke=0)
        if active:
            c.setFillColor(HexColor("#FFFFFF"))
        else:
            c.setFillColor(HexColor("#555555"))
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(sx + r, cy - 1.2 * mm, str(num))

    # --- Step 1: Connect to WiFi ---
    _step_circle(tx, y, 1)
    label_x = tx + 9 * mm
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#777777"))
    c.drawString(label_x, y, "Connect to WiFi")
    ssid_x = label_x + c.stringWidth("Connect to WiFi ", "Helvetica", 10)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(HexColor("#000000"))
    c.drawString(ssid_x, y, wifi_ssid)
    y -= 4 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#888888"))
    if wifi_password:
        c.drawString(label_x, y, f"Password: {wifi_password}")
    else:
        c.drawString(label_x, y, "No password needed")
    y -= 7 * mm

    # --- Step 2: Scan QR code ---
    _step_circle(tx, y, 2)
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#777777"))
    c.drawString(label_x, y, "Scan QR code with your phone camera")
    y -= 4 * mm

    # QR image only (voting code moved to step 3)
    qr_size = 24 * mm
    vote_url = f"{base_url}/v/{code}"
    qr_img = _generate_qr_image(vote_url)
    qr_x = label_x
    c.drawImage(qr_img, qr_x, y - qr_size, qr_size, qr_size)

    y -= qr_size + 2 * mm

    # --- OR divider + manual fallback (anchored above warning) ---
    y3 = bottom_y + _WARNING_STRIP_H + 14 * mm
    or_y = y3 + 7 * mm  # centre line for the OR pill

    # Draw line on each side of the "OR" pill
    or_text = "OR"
    c.setFont("Helvetica-Bold", 8)
    or_w = c.stringWidth(or_text, "Helvetica-Bold", 8) + 6 * mm  # pill width
    line_left = tx + 2 * mm
    line_right = x + w - 5 * mm
    pill_cx = x + w / 2
    pill_left = pill_cx - or_w / 2
    pill_right = pill_cx + or_w / 2

    c.setStrokeColor(HexColor("#CCCCCC"))
    c.setLineWidth(0.75)
    c.line(line_left, or_y, pill_left - 1 * mm, or_y)
    c.line(pill_right + 1 * mm, or_y, line_right, or_y)

    # Draw "OR" pill (rounded rect with dark fill)
    pill_h = 4.5 * mm
    c.setFillColor(HexColor("#333333"))
    c.roundRect(pill_left, or_y - pill_h / 2, or_w, pill_h,
                pill_h / 2, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.drawCentredString(pill_cx, or_y - 1.3 * mm, or_text)

    # Fallback text: "Go to <url> and enter:"
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#555555"))
    c.drawString(tx, y3, "Go to")
    url_x = tx + c.stringWidth("Go to ", "Helvetica", 10)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(HexColor("#000000"))
    c.drawString(url_x, y3, base_url)
    after_x = url_x + c.stringWidth(base_url + " ", "Helvetica-Bold", 10)
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#555555"))
    c.drawString(after_x, y3, "and enter:")
    y3 -= 5 * mm
    formatted_code = f"{code[:3]} {code[3:]}"
    c.setFont("Courier-Bold", 18)
    c.setFillColor(HexColor("#000000"))
    c.drawString(tx, y3, formatted_code)

    # --- Warning strip at bottom ---
    _draw_warning_strip(
        c, x, bottom_y, w,
        "\u26A0 Do not submit the paper ballot if you voted digitally"
    )


# ---------------------------------------------------------------------------
# Code Slips PDF
# ---------------------------------------------------------------------------


def generate_code_slips_pdf(codes, election_name, short_name, wifi_ssid,
                            wifi_password, base_url, is_demo=False):
    """Generate printable voting code cards — 6 per A4 page.

    Args:
        codes: list of voting code strings.
        election_name: name of the election.
        short_name: congregation short name (e.g. 'FRC Darling Downs').
        wifi_ssid: WiFi SSID to display.
        wifi_password: WiFi password to display (may be empty).
        base_url: voting base URL (e.g. 'http://192.168.8.100:5000').
        is_demo: if True, add demo watermark and header per page.

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

        if is_demo:
            draw_demo_watermark(c, width, height)
            draw_demo_header(c, width, height)

        for i, code in enumerate(page_codes):
            row = i // cols
            col = i % cols

            card_x = margin + col * (card_w + h_gap)
            card_top_y = height - margin - row * (card_h + v_gap)

            draw_code_slip(c, card_x, card_top_y, card_w, card_h, code,
                           wifi_ssid, wifi_password, base_url)

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

        if is_demo:
            draw_demo_watermark(c, width, height)
            draw_demo_header(c, width, height)

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
                if is_demo:
                    draw_demo_watermark(c, width, height)
                    draw_demo_header(c, width, height)
                y = height - 20 * mm

            # Candidate name
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, y, cand["name"])

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

    # Side-by-side office layout: split offices into two columns
    mid = (len(office_data) + 1) // 2
    left_offices = office_data[:mid]
    right_offices = office_data[mid:]

    def _col_body_height(offices):
        h = 0
        for item in offices:
            h += 4 * mm + len(item["candidates"]) * 5 * mm + 1 * mm
        return h

    body_height = max(_col_body_height(left_offices),
                      _col_body_height(right_offices) if right_offices else 0)

    header_height = 14 * mm
    if round_number > 1:
        header_height += 5 * mm
    padding = 6 * mm
    ballot_h = header_height + body_height + padding

    # Grid layout: 2 columns, as many rows as fit
    margin = 8 * mm
    col_gap = 6 * mm
    row_gap = 4 * mm
    col_w = (width - 2 * margin - col_gap) / 2
    usable_height = height - 2 * margin
    rows_per_page = max(1, int((usable_height + row_gap) / (ballot_h + row_gap)))
    ballots_per_page = rows_per_page * 2

    sub_gap = 3 * mm
    sub_w = (col_w - sub_gap) / 2

    # Generate enough pages
    total_ballots = max(member_count + 10, 30) if member_count > 0 else 30

    ballot_index = 0
    while ballot_index < total_ballots:
        if is_demo:
            draw_demo_watermark(c, width, height)
            draw_demo_header(c, width, height)

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

            # Content
            cx = x + col_w / 2
            y = ballot_top - 5 * mm

            # Title
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(cx, y, election_name)
            y -= 4 * mm

            c.setFont("Helvetica", 7)
            c.setFillColor(HexColor("#666666"))
            c.drawCentredString(cx, y, f"Paper Ballot \u2014 Round {round_number}")
            y -= 4 * mm

            if round_number > 1:
                c.setFont("Helvetica-Bold", 6.5)
                c.setFillColor(HexColor("#C0392B"))
                c.drawCentredString(cx, y, "Vote ONLY for candidates announced by the chairman")
                y -= 4 * mm

            # Draw offices side by side
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
                    c.setFont("Helvetica-Bold", 7)
                    c.drawString(ox, oy,
                                 f"For {office['name']} (select {office['max_selections']})")
                    oy -= 4 * mm

                    for cand in candidates:
                        c.setStrokeColor(NAVY)
                        c.setFillColor(HexColor("#FFFFFF"))
                        c.rect(ox + 1 * mm, oy - 0.5 * mm, 3 * mm, 3 * mm)

                        c.setFillColor(NAVY)
                        c.setFont("Helvetica", 7.5)
                        c.drawString(ox + 6 * mm, oy, cand["name"])
                        oy -= 5 * mm

                    oy -= 1 * mm

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

    def _add_watermarks(canvas_obj, doc):
        """Callback for SimpleDocTemplate to add demo watermarks."""
        if is_demo:
            draw_demo_watermark(canvas_obj, A4[0], A4[1])
            draw_demo_header(canvas_obj, A4[0], A4[1])

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

    if is_demo:
        doc.build(elements, onFirstPage=_add_watermarks,
                  onLaterPages=_add_watermarks)
    else:
        doc.build(elements)

    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Dual Ballot Handout PDF
# ---------------------------------------------------------------------------


def generate_dual_ballot_handout_pdf(election_name, congregation_name,
                                     office_data, codes, wifi_ssid,
                                     wifi_password, base_url):
    """Generate a dual ballot handout PDF.

    Page 1 is an explanation page. Pages 2-21 each contain a dual ballot:
    top half is a traditional paper ballot, bottom half is an online code
    ballot with QR code.

    Args:
        election_name: name of the election.
        congregation_name: full congregation name.
        office_data: list of dicts with 'office' and 'candidates' keys.
        codes: list of plaintext 6-character code strings (up to 20).
        wifi_ssid: WiFi SSID to display.
        wifi_password: WiFi password (may be empty for open network).
        base_url: voting base URL.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 10 * mm

    # -----------------------------------------------------------------------
    # Page 1 — Explanation page
    # -----------------------------------------------------------------------
    draw_demo_watermark(c, width, height)

    y = height - 20 * mm

    # Title
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, election_name)
    y -= 7 * mm
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#444444"))
    c.drawCentredString(width / 2, y, congregation_name)
    y -= 14 * mm

    # Explanation text — line by line
    def draw_line(text, font="Helvetica", size=10, color=HexColor("#333333"),
                  indent=0, spacing=4.5):
        nonlocal y
        c.setFont(font, size)
        c.setFillColor(color)
        c.drawString(margin + indent, y, text)
        y -= size * 0.35 + spacing
        return y

    draw_line("What you have received", font="Helvetica-Bold", size=12,
              color=NAVY, spacing=6)

    draw_line("As a council member, you have received a sheet with two voting options.")
    draw_line("Both options allow you to cast the same vote for the same election.")
    draw_line("You only need to choose one.", font="Helvetica-Bold", spacing=8)

    y -= 2 * mm
    draw_line("Option A — Traditional Paper Ballot (top half)",
              font="Helvetica-Bold", size=11, color=NAVY, spacing=5)
    draw_line("The top half of each page is a familiar paper ballot.")
    draw_line("Mark your selections with an X in the checkbox next to each candidate.")
    draw_line("Fold the ballot and submit it to the secretary of council.", spacing=8)

    y -= 2 * mm
    draw_line("Option B — Online Code Ballot (bottom half)",
              font="Helvetica-Bold", size=11, color=NAVY, spacing=5)
    draw_line("The bottom half contains a unique voting code and QR code.")
    draw_line("Scan the QR code with your phone, or connect to the WiFi and open the URL.")
    draw_line("Enter your code and vote on-screen. Results are tallied automatically.",
              spacing=8)

    y -= 4 * mm
    draw_line("Why both?", font="Helvetica-Bold", size=12, color=NAVY, spacing=6)

    draw_line("This election app is being proposed as an option for future elections.")
    draw_line("Providing both methods lets you experience the digital option while")
    draw_line("retaining the familiar paper ballot as a fallback.")
    draw_line("The council will decide which method to adopt going forward.", spacing=8)

    y -= 4 * mm
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(HexColor("#888888"))
    c.drawString(margin, y, "This is a DEMO election with fictional candidates.")
    y -= 5 * mm
    c.drawString(margin, y, "No real election data is used. Results do not count.")
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(NAVY)
    c.drawString(margin, y, "Try both methods if you like! The demo is here for you to explore.")

    c.showPage()

    # -----------------------------------------------------------------------
    # Pages 2-21 — Dual ballot pages (one per code)
    # -----------------------------------------------------------------------
    midpoint = height / 2
    half_height = (height - 2 * margin) / 2
    qr_size = 35 * mm

    for code in codes[:20]:
        draw_demo_watermark(c, width, height)

        # ===================================================================
        # TOP HALF — Traditional Paper Ballot
        # ===================================================================
        top_y = height - margin

        # Congregation header
        c.setFillColor(HexColor("#666666"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, top_y, congregation_name)
        top_y -= 5 * mm

        # Election name
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(width / 2, top_y, election_name)
        top_y -= 5 * mm

        # Instruction
        c.setFont("Helvetica", 8)
        c.setFillColor(HexColor("#555555"))
        c.drawCentredString(width / 2, top_y, "Mark your selections with an X")
        top_y -= 7 * mm

        # Offices and candidates
        for item in office_data:
            office = item["office"]
            candidates = item["candidates"]

            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin + 5 * mm, top_y,
                         f"For {office['name']} (select {office['max_selections']})")
            top_y -= 5 * mm

            for cand in candidates:
                # Checkbox
                c.setStrokeColor(NAVY)
                c.setFillColor(HexColor("#FFFFFF"))
                c.rect(margin + 7 * mm, top_y - 0.5 * mm, 3.5 * mm, 3.5 * mm)

                # Candidate name
                c.setFillColor(NAVY)
                c.setFont("Helvetica", 9)
                c.drawString(margin + 13 * mm, top_y, cand["name"])
                top_y -= 5.5 * mm

            top_y -= 2 * mm

        # Footer
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(HexColor("#999999"))
        c.drawCentredString(width / 2, midpoint + 5 * mm,
                            "Fold and submit to the secretary of council")

        # ===================================================================
        # SEPARATOR — dotted cut line
        # ===================================================================
        c.setStrokeColor(HexColor("#AAAAAA"))
        c.setDash(4, 3)
        c.line(margin, midpoint, width - margin, midpoint)
        c.setDash()

        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#AAAAAA"))
        c.drawCentredString(width / 2, midpoint - 4 * mm,
                            "(both options are provided \u2014 choose the one you prefer)")

        # ===================================================================
        # BOTTOM HALF — Online Code Ballot
        # ===================================================================
        bot_y = midpoint - 12 * mm

        # Congregation header
        c.setFillColor(HexColor("#666666"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, bot_y, congregation_name)
        bot_y -= 5 * mm

        # Election name
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(width / 2, bot_y, election_name)
        bot_y -= 10 * mm

        # QR code (centred)
        vote_url = f"{base_url}/v/{code}"
        qr_img = _generate_qr_image(vote_url)
        qr_x = (width - qr_size) / 2
        c.drawImage(qr_img, qr_x, bot_y - qr_size, qr_size, qr_size)
        bot_y -= qr_size + 5 * mm

        # Code in large bold monospace
        formatted_code = f"{code[:3]} {code[3:]}"
        c.setFont("Courier-Bold", 22)
        c.setFillColor(NAVY)
        c.drawCentredString(width / 2, bot_y, formatted_code)
        bot_y -= 8 * mm

        # WiFi info
        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#333333"))
        c.drawCentredString(width / 2, bot_y,
                            f"WiFi: {wifi_ssid}   |   "
                            f"{'Password: ' + wifi_password if wifi_password else 'Open network'}")
        bot_y -= 5 * mm

        # Fallback URL
        c.setFont("Helvetica", 8)
        c.setFillColor(HexColor("#555555"))
        c.drawCentredString(width / 2, bot_y, f"Or open: {vote_url}")
        bot_y -= 6 * mm

        # Instructions
        c.setFont("Helvetica", 8)
        c.setFillColor(HexColor("#555555"))
        c.drawCentredString(width / 2, bot_y,
                            "Scan QR or connect to WiFi and open the URL")
        bot_y -= 8 * mm

        # Footer
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(HexColor("#999999"))
        c.drawCentredString(width / 2, margin + 2 * mm, "Keep this slip private")

        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Shared ballot card drawing (used by grid-based and printer exports)
# ---------------------------------------------------------------------------


def _draw_ballot_card(c, x, top_y, card_w, card_h, election_name,
                      left_offices, right_offices, sub_w, sub_gap):
    """Draw a single paper ballot card at the given position.

    Args:
        c: ReportLab canvas.
        x: left edge of card.
        top_y: top edge of card.
        card_w: width of card.
        card_h: height of card.
        election_name: election title text.
        left_offices: list of office dicts for the left sub-column.
        right_offices: list of office dicts for the right sub-column.
        sub_w: width of each office sub-column.
        sub_gap: gap between the two office sub-columns.
    """
    cx = x + card_w / 2
    bottom_y = top_y - card_h

    # Dashed cut border
    c.setStrokeColor(HexColor("#CCCCCC"))
    c.setDash(2, 2)
    c.rect(x, bottom_y, card_w, card_h)
    c.setDash()

    y = top_y - 5 * mm

    # Title
    c.setFillColor(HexColor("#000000"))
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(cx, y, election_name)
    y -= 4.5 * mm

    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#666666"))
    c.drawCentredString(cx, y, "Paper Ballot")
    y -= 4.5 * mm

    # Draw offices side by side
    body_y = y
    for ci, offices in enumerate([left_offices, right_offices]):
        if not offices:
            continue
        ox = x + ci * (sub_w + sub_gap) + 2 * mm
        oy = body_y

        for item in offices:
            office = item["office"]
            candidates = item["candidates"]

            c.setFillColor(HexColor("#000000"))
            c.setFont("Helvetica-Bold", 10)
            c.drawString(ox, oy,
                         f"For {office['name']} (select {office['max_selections']})")
            oy -= 5.5 * mm

            for cand in candidates:
                c.setStrokeColor(HexColor("#000000"))
                c.setFillColor(HexColor("#FFFFFF"))
                c.rect(ox + 1 * mm, oy - 0.5 * mm, 4.5 * mm, 4.5 * mm)

                c.setFillColor(HexColor("#000000"))
                c.setFont("Helvetica", 10)
                c.drawString(ox + 7.5 * mm, oy, cand["name"])
                oy -= 6 * mm

            oy -= 1 * mm

    # Warning strip at bottom
    _draw_warning_strip(
        c, x, bottom_y, card_w,
        "\u26A0 Do not submit this ballot if you voted digitally (see reverse)"
    )


# ---------------------------------------------------------------------------
# Dual-Sided Ballots PDF (grid-based, for duplex printing)
# ---------------------------------------------------------------------------


def generate_dual_sided_ballots_pdf(election_name, short_name, round_number,
                                     office_data, codes, wifi_ssid,
                                     wifi_password, base_url,
                                     member_count=0, is_demo=False):
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
    total_cards = max(member_count + 10, 30) if member_count > 0 else len(codes)
    codes = codes[:total_cards]

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
                           wifi_ssid, wifi_password, base_url)
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

    if is_demo:
        draw_demo_watermark(c, col_w, cell_h)

    _draw_ballot_card(c, 0, cell_h, col_w, cell_h, election_name,
                      left, right, sub_w, sub_gap)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def generate_code_slips_back_pdf(codes, wifi_ssid, wifi_password, base_url,
                                 office_data, member_count=0, is_demo=False):
    """Generate card-sized PDF with one code slip per page.

    Each page has a unique voting code + QR. The printer cannot duplicate
    these — each page is different.

    Returns:
        BytesIO buffer containing the PDF.
    """
    col_w, cell_h, _, _, _, _ = _calc_card_dimensions(office_data,
                                                       wifi_password)

    total_cards = max(member_count + 10, 30) if member_count > 0 else len(codes)
    codes = codes[:total_cards]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(col_w, cell_h))

    for code_str in codes:
        if is_demo:
            draw_demo_watermark(c, col_w, cell_h)
        draw_code_slip(c, 0, cell_h, col_w, cell_h, code_str,
                       wifi_ssid, wifi_password, base_url)
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


def generate_attendance_register_pdf(members, congregation_name,
                                     election_name=None, election_date=None):
    """Generate a printable attendance register PDF from a member list.

    Args:
        members: list of dicts with 'first_name' and 'last_name'.
        congregation_name: e.g. "Free Reformed Church of Darling Downs".
        election_name: optional election name for the header.
        election_date: optional election date string.

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
    elements.append(Paragraph("Attendance Register", title_style))
    elements.append(Paragraph(congregation_name, styles["Heading2"]))

    if election_name:
        details = election_name
        if election_date:
            details += f" \u2014 {election_date}"
        elements.append(Paragraph(details, styles["Normal"]))

    elements.append(Paragraph(
        "Article 4: All male communicant members present must sign this "
        "register.", styles["Normal"]))
    elements.append(Spacer(1, 5 * mm))

    table_data = [["#", "Name", "Signature"]]
    for i, member in enumerate(members, 1):
        name = f"{member['last_name']}, {member['first_name']}"
        table_data.append([str(i), name, ""])

    col_widths = [30, 200, 260]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, HexColor("#F5F5F5")]),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT", (0, 1), (-1, -1), 36),
    ]))
    elements.append(table)

    doc.build(elements)
    buf.seek(0)
    return buf


def generate_printer_pack_zip(election_name, short_name, round_number,
                              office_data, codes, wifi_ssid, wifi_password,
                              base_url, congregation_name, members,
                              election_date=None, member_count=0,
                              is_demo=False):
    """Generate a ZIP containing all PDFs needed for professional printing.

    Contents:
        ballot_front.pdf         — 1 page, card-sized paper ballot (duplicate this)
        code_slips_back.pdf      — N pages, card-sized unique code slips
        dual_sided_ballots.pdf   — grid layout for home duplex printing
        counter_sheet.pdf        — tally sheet for counting paper ballots
        attendance_register.pdf  — sign-in sheet for election day
        INSTRUCTIONS.txt         — explanation of each file

    Returns:
        BytesIO buffer containing the ZIP.
    """
    # 1. Ballot front (1 page, card-sized)
    front_buf = generate_ballot_front_pdf(
        election_name, office_data, wifi_password, is_demo=is_demo)

    # 2. Code slips back (N pages, card-sized)
    back_buf = generate_code_slips_back_pdf(
        codes, wifi_ssid, wifi_password, base_url, office_data,
        member_count=member_count, is_demo=is_demo)

    # 3. Dual-sided grid layout (for home printing fallback)
    dual_buf = generate_dual_sided_ballots_pdf(
        election_name, short_name, round_number, office_data, codes,
        wifi_ssid, wifi_password, base_url,
        member_count=member_count, is_demo=is_demo)

    # 4. Counter sheet
    counter_buf = generate_counter_sheet_pdf(
        election_name, congregation_name, office_data,
        member_count=member_count, is_demo=is_demo)

    # 5. Attendance register
    attendance_buf = generate_attendance_register_pdf(
        members, congregation_name,
        election_name=election_name, election_date=election_date)

    # 6. Instructions
    total_cards = max(member_count + 10, 30) if member_count > 0 else len(codes)
    total_cards = min(total_cards, len(codes))
    instructions = f"""\
PRINTER PACK — {election_name}
{'=' * 60}

This ZIP contains everything needed to print materials for the
church office bearer election. Below is a description of each file.


1. ballot_front.pdf  (1 page)
   ─────────────────────────────
   The FRONT side of the voting card. Shows the election name,
   offices, and candidate checkboxes.

   This page is IDENTICAL for all cards. Your imposition software
   should duplicate it to produce {total_cards} copies, arranged on
   sheets for cutting. Card size: ~94 x 88 mm.


2. code_slips_back.pdf  ({total_cards} pages)
   ─────────────────────────────
   The BACK side of the voting card. Each page has a UNIQUE voting
   code and QR code — one per card. Do NOT duplicate these pages.

   Page 1 pairs with copy 1 of the front, page 2 with copy 2, etc.
   Same card size as the front (~94 x 88 mm).

   Print these duplex with the front, matching page order:
   Front copy 1 + Back page 1, Front copy 2 + Back page 2, etc.


3. dual_sided_ballots.pdf
   ─────────────────────────────
   FALLBACK for home/office printing. Contains the same ballots in a
   6-per-page grid layout, ready for duplex printing on A4 with
   long-edge binding. Cut along the dashed lines after printing.

   Use this if professional printing is not available.


4. counter_sheet.pdf
   ─────────────────────────────
   Tally sheet for counting paper ballots by hand. One page per
   office, with tick boxes for each candidate. Print on A4.


5. attendance_register.pdf
   ─────────────────────────────
   Sign-in sheet listing all members. Each attendee signs next to
   their name upon arrival. Required per Article 4 of the church
   order. Print on A4.


PRINTING SUMMARY
{'=' * 60}

  File                      Size        Copies    Paper
  ────────────────────────  ──────────  ────────  ──────
  ballot_front.pdf          Card-sized  x{total_cards:<6}  Duplex
  code_slips_back.pdf       Card-sized  x1        Duplex
  counter_sheet.pdf         A4          x2-3      Simplex
  attendance_register.pdf   A4          x1-2      Simplex

For questions, contact the election administrator.
"""

    # Assemble ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ballot_front.pdf", front_buf.getvalue())
        zf.writestr("code_slips_back.pdf", back_buf.getvalue())
        zf.writestr("dual_sided_ballots.pdf", dual_buf.getvalue())
        zf.writestr("counter_sheet.pdf", counter_buf.getvalue())
        zf.writestr("attendance_register.pdf", attendance_buf.getvalue())
        zf.writestr("INSTRUCTIONS.txt", instructions)

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
    if is_demo:
        demo_p = doc.add_paragraph()
        demo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = demo_p.add_run("DEMO MODE \u2014 This is not an official document")
        run.bold = True
        run.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
        run.font.size = Pt(12)

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

        # Vote tables per office. Round 1 with postal votes gets a
        # 'In-person | Postal | Total' breakdown; everything else stays
        # single-column to match the reference minutes style.
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
                headers = ["Candidate", "In-person", "Postal", "Total"]
            else:
                headers = ["Candidate", "# votes"]
            col_count = len(headers)

            table = doc.add_table(rows=1 + len(cands), cols=col_count)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER

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
                if has_postal:
                    in_person = cand.get("digital", 0) + cand.get("paper", 0)
                    row.cells[1].text = str(in_person)
                    row.cells[2].text = str(cand.get("postal", 0))
                    row.cells[3].text = str(cand["total"])
                else:
                    row.cells[1].text = str(cand["total"])
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

            # Final result sentence (end-of-voting summary)
            if elected_summary:
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
