"""Capture screenshots of the FRCA Election App for documentation.

Walks the wizard-sidebar admin flow end-to-end (Setup -> Round -> Finish),
plus the voter-on-mobile flow, then captures the projector display.
Starts the app server automatically, runs against a fresh DB, then cleans up
and restores any pre-existing database.
"""
import os
import shutil
import subprocess
import sys
import time
import random
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5000"
OUT = "screenshots"
VOTING_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voting-app")
DATA_DIR = os.path.join(VOTING_APP_DIR, "data")


def start_server():
    """Start the waitress server as a subprocess and wait for it to be ready."""
    db_path = os.path.join(DATA_DIR, "frca_election.db")
    backup_path = None
    if os.path.exists(db_path):
        backup_path = db_path + ".screenshots_backup"
        shutil.copy2(db_path, backup_path)
        os.remove(db_path)
        secret_key = os.path.join(DATA_DIR, ".secret_key")
        if os.path.exists(secret_key):
            os.remove(secret_key)
        print(f"  Backed up existing database to {os.path.basename(backup_path)}")

    proc = subprocess.Popen(
        [sys.executable, "-m", "waitress", "--host=127.0.0.1", "--port=5000", "app:app"],
        cwd=VOTING_APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    import socket
    for _ in range(30):
        try:
            s = socket.create_connection(("127.0.0.1", 5000), timeout=1)
            s.close()
            print("  Server is ready.")
            return proc, backup_path
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Server failed to start within 15 seconds")


def stop_server(proc, backup_path):
    """Stop the server and clean up the screenshot database."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    db_path = os.path.join(DATA_DIR, "frca_election.db")
    secret_key = os.path.join(DATA_DIR, ".secret_key")

    # Windows can hold the DB file briefly after the waitress subprocess
    # exits. Retry a few times before giving up.
    def _remove(path):
        for _ in range(10):
            if not os.path.exists(path):
                return True
            try:
                os.remove(path)
                return True
            except PermissionError:
                time.sleep(0.5)
        return False

    if not _remove(db_path):
        print(f"  Warning: could not remove {db_path}; restore manually.")
    _remove(secret_key)

    if backup_path and os.path.exists(backup_path):
        try:
            shutil.move(backup_path, db_path)
            print("  Restored original database.")
        except OSError as exc:
            print(f"  Warning: could not restore backup ({exc}); "
                  f"backup is at {backup_path}")


def shot(page, name, mobile=False):
    if mobile:
        page.set_viewport_size({"width": 375, "height": 812})
    else:
        page.set_viewport_size({"width": 1280, "height": 800})
    page.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    print(f"  -> {name}.png")


def add_candidate_tag(page, name):
    search = page.locator('#candidate_search')
    search.fill(name)
    search.press('Enter')
    time.sleep(0.3)


def main():
    print("Starting server...")
    proc, backup_path = start_server()
    try:
        _capture_all()
    finally:
        print("\nStopping server...")
        stop_server(proc, backup_path)


def _capture_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        # --- 01: Voter splash before any election (mobile)
        print("01. Voter splash (no election)")
        page.goto(f"{BASE}/")
        shot(page, "01_voter_not_open", mobile=True)

        # --- 02: Admin login
        print("02. Admin login")
        page.goto(f"{BASE}/admin/login")
        page.wait_for_load_state("networkidle")
        shot(page, "02_admin_login")

        page.fill('input[name="password"]', 'admin')
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # --- 03/04: First-run setup wizard
        print("03. Setup wizard (blank)")
        shot(page, "03_setup_wizard_blank")
        page.fill('#congregation_name', 'Free Reformed Church of Baldivis')
        page.fill('#congregation_short', 'Baldivis')
        page.fill('#wifi_ssid', 'FRCA-Election')
        page.fill('#new_password', 'council2026')
        page.fill('#confirm_password', 'council2026')
        print("04. Setup wizard (filled)")
        shot(page, "04_setup_wizard_filled")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # --- 05: Dashboard, no elections yet
        print("05. Dashboard (empty)")
        shot(page, "05_dashboard_empty")

        # --- 06: New election form
        print("06. New election form")
        page.click('a:has-text("New Election")')
        page.wait_for_load_state("networkidle")
        page.fill('input[name="name"]', 'Annual Election 2026')
        max_rounds = page.locator('input[name="max_rounds"]')
        if max_rounds.count() > 0:
            max_rounds.fill('3')
        date_field = page.locator('input[name="election_date"]')
        if date_field.count() > 0:
            date_field.fill('20 October 2026')
        shot(page, "06_create_election")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # After creation, the wizard lands on Election details. Capture the
        # election id from the URL so we can navigate to specific steps.
        # URL forms seen: /admin/election/<id>/details or
        # /admin/election/<id>/step/<name> - extract the integer right
        # after the "election" segment.
        parts = page.url.rstrip("/").split("/")
        eid = next(int(p) for i, p in enumerate(parts)
                   if i > 0 and parts[i - 1] == "election" and p.isdigit())
        print(f"  Created election id={eid}")

        # --- 07: Offices step (empty)
        print("07. Offices step (empty)")
        page.goto(f"{BASE}/admin/election/{eid}/step/offices")
        page.wait_for_load_state("networkidle")
        shot(page, "07_election_setup_empty")

        # --- 08: Add Elder office mid-fill
        print("08. Add Elder office")
        page.fill('#office_name', 'Elder')
        page.fill('#vacancies', '2')
        for name in ['H. de Vries', 'J. van der Berg',
                     'P. Kloosterman', 'W. Hoekstra']:
            add_candidate_tag(page, name)
        shot(page, "08_add_elder_office")
        page.click('#add-office-form button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # --- Add Deacon office, then capture both offices saved
        page.fill('#office_name', 'Deacon')
        page.fill('#vacancies', '1')
        for name in ['R. Dijkstra', 'A. Visser']:
            add_candidate_tag(page, name)
        page.click('#add-office-form button[type="submit"]')
        page.wait_for_load_state("networkidle")
        print("09. Offices step (both offices saved)")
        shot(page, "09_election_setup_complete")

        # --- 10: Codes step. Visiting the page auto-generates codes
        # the first time (when offices exist and no codes yet).
        print("10. Codes step (auto-generated)")
        page.goto(f"{BASE}/admin/election/{eid}/step/codes")
        page.wait_for_load_state("networkidle")
        shot(page, "10_codes_generated")

        # Codes are no longer rendered on the page (security: plaintext
        # codes do not leak into the admin UI). Read them directly from
        # the SQLite db (the screenshot run is against a throwaway DB).
        import sqlite3
        db_path = os.path.join(DATA_DIR, "frca_election.db")
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT plaintext FROM codes WHERE election_id = ? "
                "AND plaintext IS NOT NULL ORDER BY id",
                (eid,),
            ).fetchall()
        codes = [r[0] for r in rows if r[0]]
        print(f"  Captured {len(codes)} codes from the database")

        # --- Set attendance on the Attendance step
        print("    Set attendance count")
        page.goto(f"{BASE}/admin/election/{eid}/step/attendance")
        page.wait_for_load_state("networkidle")
        page.fill('#participants', '35')
        page.locator('form[action*="/participants"] button:has-text("Save")').first.click()
        page.wait_for_load_state("networkidle")

        # --- 11: Voting step before opening the round
        print("11. Voting step (before opening)")
        page.goto(f"{BASE}/admin/election/{eid}/step/voting")
        page.wait_for_load_state("networkidle")
        shot(page, "11_manage_before_voting")

        # --- 12: Open the round, capture admin view
        print("12. Voting step (round open, no ballots yet)")
        # Submit the form directly to dodge the confirm() dialog that
        # the button uses; the route also flips display_phase to 3.
        toggle_form = page.locator(
            'form[action$="/voting"]:has(button:has-text("Open Round"))')
        toggle_form.evaluate("f => f.submit()")
        page.wait_for_load_state("networkidle")
        shot(page, "12_manage_voting_open")

        # --- 13-17: Voter flow in a fresh isolated context (so the
        # voter session does not inherit the admin session cookie).
        if not codes:
            print("  !! No codes captured, skipping voter flow")
        else:
            voter_ctx = browser.new_context()
            print("13. Voter (enter code)")
            voter = voter_ctx.new_page()
            voter.goto(f"{BASE}/")
            voter.wait_for_load_state("networkidle")
            shot(voter, "13_voter_enter_code", mobile=True)

            voter.fill('input[name="code"]', codes[0])
            print("14. Voter (code entered)")
            shot(voter, "14_voter_code_entered", mobile=True)
            voter.click('button[type="submit"]')
            voter.wait_for_load_state("networkidle")

            print("15. Voter (ballot)")
            shot(voter, "15_voter_ballot", mobile=True)

            cbs = voter.locator('input[type="checkbox"]')
            n = cbs.count()
            print(f"   {n} checkboxes on ballot")
            if n >= 5:
                cbs.nth(0).check()
                cbs.nth(1).check()
                cbs.nth(4).check()
            print("16. Voter (ballot selected)")
            shot(voter, "16_voter_ballot_selected", mobile=True)

            voter.click('button[type="submit"]')
            voter.wait_for_load_state("networkidle")
            print("17. Voter (confirmation)")
            shot(voter, "17_voter_confirmation", mobile=True)
            voter.close()

            # --- Cast extra random votes so the live tally has volume.
            # Each vote uses a fresh context so its session is isolated.
            print("    Casting 11 extra votes for liveness")
            cast = 0
            for code in codes[1:12]:
                vctx = browser.new_context()
                vp = vctx.new_page()
                vp.goto(f"{BASE}/")
                vp.wait_for_load_state("networkidle")
                if vp.locator('input[name="code"]').count() == 0:
                    vctx.close()
                    continue
                vp.fill('input[name="code"]', code)
                vp.click('button[type="submit"]')
                vp.wait_for_load_state("networkidle")
                cbs = vp.locator('input[type="checkbox"]')
                n = cbs.count()
                if n >= 5:
                    for e in random.sample(range(4), 2):
                        cbs.nth(e).check()
                    cbs.nth(random.choice([4, 5])).check()
                    vp.click('button[type="submit"]')
                    vp.wait_for_load_state("networkidle")
                    cast += 1
                vctx.close()
            voter_ctx.close()
            print(f"    {cast} extra votes cast")

        # --- 18: Voting step with live ballots flowing in
        print("18. Voting step (live ballots)")
        page.goto(f"{BASE}/admin/election/{eid}/step/voting")
        page.wait_for_load_state("networkidle")
        shot(page, "18_manage_votes_live")

        # --- 19: Close the round, capture the closed-round voting view
        print("19. Voting step (round closed)")
        page.click('button:has-text("Close Round")')
        page.wait_for_load_state("networkidle")
        shot(page, "19_manage_results_closed")

        # --- 20: Count step with results toggled on the projector
        print("20. Count step (results visible on projector)")
        page.goto(f"{BASE}/admin/election/{eid}/step/count")
        page.wait_for_load_state("networkidle")
        show_btn = page.locator('button:has-text("Show Results on Projector")').first
        if show_btn.count() > 0:
            show_btn.click()
            page.wait_for_load_state("networkidle")
        shot(page, "20_manage_results_showing")

        # --- 21: Projector display
        print("21. Projector display")
        disp = ctx.new_page()
        disp.goto(f"{BASE}/display")
        disp.set_viewport_size({"width": 1920, "height": 1080})
        time.sleep(3)
        disp.screenshot(path=f"{OUT}/21_projector_display.png", full_page=True)
        print("  -> 21_projector_display.png")
        disp.close()

        # --- 22: Dashboard with the election now listed
        print("22. Dashboard (with election)")
        page.goto(f"{BASE}/admin")
        page.wait_for_load_state("networkidle")
        shot(page, "22_dashboard_with_election")

        browser.close()
        print("\nAll screenshots captured!")


if __name__ == "__main__":
    main()
