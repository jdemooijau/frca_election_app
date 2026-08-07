"""Screenshot-and-assert harness for the projector display screens.

Seeds a scratch db with the demo maximum (10 elder / 8 deacon candidates),
serves the app on port 5001 with a monkeypatched DB_PATH (the real
data/frca_election.db is never touched), then drives Playwright through
the display states at 1920x1080 and 1280x720. Each state must fit its
viewport: no page overflow, no clipped candidate rows, and no content
panel hanging below the fold.

Usage:
    cd voting-app
    python scripts/check_display_fit.py

The port must be free. Stop any running dev server first, or point the
harness elsewhere with FIT_CHECK_PORT=5057.

Exit code 0 = all states fit. Screenshots are written to
display_fit_output/ for eyeballing either way.
"""

import os
import random
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime

_VOTING_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _VOTING_APP_DIR not in sys.path:
    sys.path.insert(0, _VOTING_APP_DIR)

import app as app_module
from app import app, _init_db_on, _migrate_db_on
from demo_names import generate_demo_names

PORT = int(os.environ.get("FIT_CHECK_PORT", "5001"))
BASE = f"http://127.0.0.1:{PORT}"
OUT = os.path.join(_VOTING_APP_DIR, "display_fit_output")
DB = os.path.join(OUT, "fit_check.db")
VIEWPORTS = [(1920, 1080), (1280, 720)]


def require_free_port():
    """Refuse to run if something already listens on PORT.

    Without this the harness could silently screenshot whatever other
    server owns the port and report a green run against the wrong app.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1)
    try:
        in_use = probe.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        probe.close()
    if in_use:
        print(f"ERROR: port {PORT} is already in use. Stop the process"
              f" listening on 127.0.0.1:{PORT} (usually a dev server), or"
              f" rerun with FIT_CHECK_PORT set to a free port.")
        sys.exit(2)


def seed():
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    _init_db_on(conn)
    _migrate_db_on(conn)

    for k, v in {
        "congregation_name": "Free Reformed Church of Darling Downs",
        "congregation_short": "FRC Darling Downs",
        "wifi_ssid": "ChurchVote",
        "voting_base_url": "http://10.0.0.2",
        "setup_complete": "1",
    }.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (k, v))

    today = datetime.now().strftime("%Y-%m-%d")
    cur = conn.execute(
        "INSERT INTO elections (name, max_rounds, current_round, voting_open,"
        " show_results, display_phase, election_date)"
        " VALUES (?, 2, 1, 1, 1, 3, ?)",
        ("Office Bearer Election (Fit Check)", today))
    eid = cur.lastrowid

    names = generate_demo_names(count=18, member_names=None)
    for office_name, cands, vac, sort in (
            ("Elder", names[:10], 5, 1), ("Deacon", names[10:18], 4, 2)):
        cur = conn.execute(
            "INSERT INTO offices (election_id, name, max_selections,"
            " vacancies, sort_order) VALUES (?, ?, ?, ?, ?)",
            (eid, office_name, vac, vac, sort))
        office_id = cur.lastrowid
        for i, n in enumerate(cands):
            conn.execute(
                "INSERT INTO candidates (office_id, name, sort_order)"
                " VALUES (?, ?, ?)", (office_id, n, i + 1))

    conn.execute(
        "INSERT OR REPLACE INTO round_counts (election_id, round_number,"
        " participants, paper_ballot_count, digital_ballot_count)"
        " VALUES (?, 1, 110, 0, 95)", (eid,))

    random.seed(42)
    for c in conn.execute("SELECT id FROM candidates").fetchall():
        for _ in range(random.randint(15, 70)):
            conn.execute(
                "INSERT INTO votes (election_id, round_number, candidate_id,"
                " source) VALUES (?, 1, ?, 'digital')", (eid, c["id"]))
    conn.commit()
    conn.close()


def set_state(**cols):
    conn = sqlite3.connect(DB)
    sets = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(f"UPDATE elections SET {sets}", tuple(cols.values()))
    conn.commit()
    conn.close()


def set_runoff_shape():
    """Round 2 with a fat runoff: 6 elder + 4 deacon names remain."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    for office_name, keep, vac in (("Elder", 6, 3), ("Deacon", 4, 2)):
        office = conn.execute(
            "SELECT id FROM offices WHERE name = ?", (office_name,)
        ).fetchone()
        cands = conn.execute(
            "SELECT id FROM candidates WHERE office_id = ? ORDER BY sort_order",
            (office["id"],)).fetchall()
        for i, c in enumerate(cands):
            conn.execute("UPDATE candidates SET active = ? WHERE id = ?",
                         (1 if i < keep else 0, c["id"]))
        conn.execute(
            "UPDATE offices SET vacancies = ?, max_selections = ?"
            " WHERE id = ?", (vac, vac, office["id"]))
    conn.commit()
    conn.close()


def reset_full_slate():
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE candidates SET active = 1")
    conn.execute(
        "UPDATE offices SET vacancies = CASE WHEN name='Elder' THEN 5 ELSE 4"
        " END, max_selections = CASE WHEN name='Elder' THEN 5 ELSE 4 END")
    conn.commit()
    conn.close()


# (state_name, setup_callable, settle_seconds)
STATES = [
    ("open_live_tally", lambda: (reset_full_slate(), set_state(
        current_round=1, voting_open=1, show_results=1, display_phase=3)), 3),
    ("closed_results", lambda: (reset_full_slate(), set_state(
        current_round=1, voting_open=0, show_results=1, display_phase=3)), 3),
    ("slate_phase2", lambda: (reset_full_slate(), set_state(
        current_round=1, voting_open=0, show_results=0, display_phase=2)), 3),
    ("round2_instructions", lambda: (set_runoff_shape(), set_state(
        current_round=2, voting_open=1, show_results=0, display_phase=3)), 3),
]

# Panels that hold the variable-length content. A panel whose box ends
# below the fold is clipped: the display screens set overflow:hidden, so
# scrollHeight alone never reports it (it stays pinned at the viewport
# height) and a row-level check misses screens that render names as prose
# rather than as .display-candidate rows.
PANEL_SELECTORS = (".display-offices, .display-office, .display-instructions,"
                   " .office-candidates, .candidate-list, .display-results")

OVERFLOW_JS = """
(panelSelectors) => {
    const doc = document.documentElement;
    const tolerance = 2;
    const pageOverflow = doc.scrollHeight - window.innerHeight;
    let clipped = [];
    document.querySelectorAll(
        '.display-candidate, .candidate-list li, .display-office h2'
    ).forEach(el => {
        if (el.offsetParent === null) return;  // hidden (rotated out)
        const r = el.getBoundingClientRect();
        if (r.bottom > window.innerHeight + tolerance) {
            clipped.push(el.textContent.trim().slice(0, 40));
        }
    });
    let overhang = [];
    document.querySelectorAll(panelSelectors).forEach(el => {
        if (el.offsetParent === null) return;  // hidden (rotated out)
        const r = el.getBoundingClientRect();
        if (r.height === 0) return;
        const over = Math.round(r.bottom - window.innerHeight);
        if (over > tolerance) {
            overhang.push(
                (el.className || 'panel').toString().slice(0, 30)
                + ' +' + over + 'px');
        }
    });
    return {pageOverflow, clipped, overhang};
}
"""


def main():
    require_free_port()
    seed()
    app_module.DB_PATH = DB

    from waitress import serve
    threading.Thread(
        target=lambda: serve(app, host="127.0.0.1", port=PORT),
        daemon=True).start()
    time.sleep(2)

    from playwright.sync_api import sync_playwright

    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width, height in VIEWPORTS:
            page = browser.new_page(viewport={"width": width,
                                              "height": height})
            for name, setup, settle in STATES:
                setup()
                page.goto(f"{BASE}/display")
                time.sleep(settle)
                shot = os.path.join(OUT, f"{name}_{width}x{height}.png")
                page.screenshot(path=shot)
                result = page.evaluate(OVERFLOW_JS, PANEL_SELECTORS)
                ok = (result["pageOverflow"] <= 2
                      and not result["clipped"]
                      and not result["overhang"])
                print(f"  {'OK  ' if ok else 'FAIL'} {name} at "
                      f"{width}x{height}  overflow={result['pageOverflow']}"
                      f" clipped={result['clipped']}"
                      f" overhang={result['overhang']}")
                if not ok:
                    failures.append(f"{name} at {width}x{height}")
            page.close()
        browser.close()

    print()
    if failures:
        print("FAILED states: " + ", ".join(failures))
        sys.exit(1)
    print(f"All display states fit. Screenshots in {OUT}")
    sys.exit(0)


if __name__ == "__main__":
    main()
