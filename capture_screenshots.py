"""Capture screenshots of the FRCA Election App for documentation.

Starts the app server automatically, captures all screenshots, then cleans up.
"""
import os
import shutil
import signal
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
    # Back up existing data dir if it has a database
    db_path = os.path.join(DATA_DIR, "frca_election.db")
    backup_path = None
    if os.path.exists(db_path):
        backup_path = db_path + ".screenshots_backup"
        shutil.copy2(db_path, backup_path)
        os.remove(db_path)
        # Also remove secret key so setup wizard uses a fresh session
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

    # Wait for server to accept connections
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

    # Remove the screenshot database
    db_path = os.path.join(DATA_DIR, "frca_election.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    secret_key = os.path.join(DATA_DIR, ".secret_key")
    if os.path.exists(secret_key):
        os.remove(secret_key)

    # Restore backup if one existed
    if backup_path and os.path.exists(backup_path):
        shutil.move(backup_path, db_path)
        print("  Restored original database.")


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

        # 1. Voter: voting not open (mobile)
        print("1. Voter landing (voting closed)")
        page.goto(f"{BASE}/")
        shot(page, "01_voter_not_open", mobile=True)

        # 2. Admin login
        print("2. Admin login")
        page.goto(f"{BASE}/admin/login")
        page.wait_for_load_state("networkidle")
        shot(page, "02_admin_login")

        page.fill('input[name="password"]', 'admin')
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # 3. Setup wizard
        print("3. Setup wizard")
        shot(page, "03_setup_wizard_blank")
        page.fill('#congregation_name', 'Free Reformed Church of Baldivis')
        page.fill('#congregation_short', 'Baldivis')
        page.fill('#wifi_ssid', 'FRCA-Election')
        page.fill('#new_password', 'council2026')
        page.fill('#confirm_password', 'council2026')
        shot(page, "04_setup_wizard_filled")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # 4. Dashboard (empty)
        print("4. Dashboard (empty)")
        shot(page, "05_dashboard_empty")

        # 5. Create election
        print("5. Create election")
        page.click('a:has-text("New Election")')
        page.wait_for_load_state("networkidle")
        page.fill('input[name="name"]', 'Annual Election 2026')
        page.fill('input[name="max_rounds"]', '3')
        shot(page, "06_create_election")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # 6. Election setup
        print("6. Election setup")
        shot(page, "07_election_setup_empty")

        # Add Elder office with candidates
        page.fill('#office_name', 'Elder')
        page.fill('#vacancies', '2')
        for name in ['H. de Vries', 'J. van der Berg',
                     'P. Kloosterman', 'W. Hoekstra']:
            add_candidate_tag(page, name)
        shot(page, "08_add_elder_office")
        page.click('button:has-text("Add Office")')
        page.wait_for_load_state("networkidle")

        # Add Deacon office
        page.fill('#office_name', 'Deacon')
        page.fill('#vacancies', '1')
        for name in ['R. Dijkstra', 'A. Visser']:
            add_candidate_tag(page, name)
        page.click('button:has-text("Add Office")')
        page.wait_for_load_state("networkidle")
        shot(page, "09_election_setup_complete")

        # 7. Codes tab - generate codes and CAPTURE them from page
        print("7. Code generation")
        page.click('a:has-text("Codes")')
        page.wait_for_load_state("networkidle")
        page.fill('input[name="count"]', '50')
        page.click('button:has-text("Generate")')
        page.wait_for_load_state("networkidle")
        shot(page, "10_codes_generated")

        # Extract plaintext codes from the generated codes section
        code_divs = page.locator('.card:has-text("Generated Codes") div[style*="break-inside"]')
        codes = []
        for i in range(code_divs.count()):
            txt = code_divs.nth(i).text_content().strip()
            if txt:
                codes.append(txt)
        print(f"  -> Captured {len(codes)} codes from page")

        # 8. Manage tab
        print("8. Manage tab (before voting)")
        page.click('a:has-text("Manage")')
        page.wait_for_load_state("networkidle")
        shot(page, "11_manage_before_voting")

        # Open voting
        page.click('button:has-text("Open Voting")')
        page.wait_for_load_state("networkidle")
        shot(page, "12_manage_voting_open")

        # 9. Voter enter code (mobile)
        print("9. Voter: enter code")
        if not codes:
            print("  !! No codes available, skipping voter flow")
        else:
            voter = ctx.new_page()
            voter.goto(f"{BASE}/")
            shot(voter, "13_voter_enter_code", mobile=True)

            voter.fill('input[name="code"]', codes[0])
            shot(voter, "14_voter_code_entered", mobile=True)
            voter.click('button[type="submit"]')
            voter.wait_for_load_state("networkidle")

            # 10. Ballot
            print("10. Voter: ballot")
            shot(voter, "15_voter_ballot", mobile=True)

            cbs = voter.locator('input[type="checkbox"]')
            n = cbs.count()
            print(f"   {n} checkboxes found")
            if n >= 5:
                cbs.nth(0).check()
                cbs.nth(1).check()
                cbs.nth(4).check()
            shot(voter, "16_voter_ballot_selected", mobile=True)

            voter.click('button[type="submit"]')
            voter.wait_for_load_state("networkidle")

            # 11. Confirmation
            print("11. Voter: confirmation")
            shot(voter, "17_voter_confirmation", mobile=True)
            voter.close()

            # 12. Cast extra votes
            print("12. Casting extra votes")
            cast = 0
            for code in codes[1:12]:
                vp = ctx.new_page()
                vp.goto(f"{BASE}/")
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
                vp.close()
            print(f"  -> {cast} extra votes cast")

        # 13. Manage with votes
        print("13. Manage with votes")
        page.goto(f"{BASE}/admin")
        page.wait_for_load_state("networkidle")
        page.click('a:has-text("Manage")')
        page.wait_for_load_state("networkidle")
        shot(page, "18_manage_votes_live")

        # Close voting (accept the confirm() dialog)
        page.on("dialog", lambda d: d.accept())
        page.click('button:has-text("Close Voting")')
        page.wait_for_load_state("networkidle")

        # Set participants
        pi = page.locator('#participants')
        if pi.count() > 0:
            pi.fill('35')
            page.locator('button:has-text("Save")').first.click()
            page.wait_for_load_state("networkidle")

        shot(page, "19_manage_results_closed")

        # Show results on projector
        show_btn = page.locator('button:has-text("Show Results on Projector")')
        if show_btn.count() > 0:
            show_btn.click()
            page.wait_for_load_state("networkidle")
        shot(page, "20_manage_results_showing")

        # 14. Projector
        print("14. Projector display")
        disp = ctx.new_page()
        disp.goto(f"{BASE}/display")
        disp.set_viewport_size({"width": 1920, "height": 1080})
        time.sleep(3)
        disp.screenshot(path=f"{OUT}/21_projector_display.png", full_page=True)
        print("  -> 21_projector_display.png")
        disp.close()

        # 15. Dashboard
        print("15. Dashboard with election")
        page.goto(f"{BASE}/admin")
        page.wait_for_load_state("networkidle")
        shot(page, "22_dashboard_with_election")

        browser.close()
        print("\nAll screenshots captured!")


if __name__ == "__main__":
    main()
