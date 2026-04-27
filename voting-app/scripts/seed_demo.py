"""
Seed a demo election from the command line.

Usage:
    cd voting-app
    python scripts/seed_demo.py                # 20 codes (quick demo)
    python scripts/seed_demo.py --codes 100    # 100 codes (for load testing)

Environment variables:
    FRCA_DB_PATH          — override the database path
    FRCA_SKIP_PORT_CHECK  — set to "1" to skip port-in-use check
"""

import argparse
import logging
import os
import shutil
import socket
import sqlite3
import sys
from datetime import datetime

# Ensure the voting-app directory is on sys.path so we can import app modules.
_VOTING_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _VOTING_APP_DIR not in sys.path:
    sys.path.insert(0, _VOTING_APP_DIR)

import app as app_module
from app import app, _init_db_on, _migrate_db_on, generate_codes
from demo_names import (
    generate_demo_names,
    load_member_names_from_external,
)
from pdf_generators import generate_code_slips_pdf, generate_paper_ballot_pdf

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("FRCA_DB_PATH") or os.path.join(
    _VOTING_APP_DIR, "data", "frca_election.db"
)
SKIP_PORT_CHECK = os.environ.get("FRCA_SKIP_PORT_CHECK", "") == "1"

DEMO_SETTINGS = {
    "congregation_name": "Free Reformed Church of Darling Downs",
    "congregation_short": "FRC Darling Downs",
    "wifi_ssid": "ChurchVote",
    "wifi_password": "",
    "voting_base_url": "http://church.vote",
    "is_demo": "1",
    "setup_complete": "1",
    "admin_password": "admin",
}

ELECTION_DATA_TABLES = [
    "votes", "paper_votes", "postal_votes", "codes",
    "candidates", "offices", "elections", "round_counts",
]

LOG_DIR = os.path.join(_VOTING_APP_DIR, "logs")
BACKUP_DIR = os.path.join(_VOTING_APP_DIR, "backups")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("seed_demo")
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "seed_demo.log"))
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_sh)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_in_use(port=5000):
    """Return True if a process is already listening on *port*."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _backup_database(db_path):
    """Create a timestamped backup of the database file."""
    if not os.path.isfile(db_path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"db_backup_{stamp}.sqlite")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _wipe_election_tables(conn):
    """Delete all rows from election-data tables."""
    for table in ELECTION_DATA_TABLES:
        try:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608
        except sqlite3.OperationalError:
            pass  # table may not exist yet
    conn.commit()


def _set_demo_settings(conn):
    """Write the demo congregation settings into the database."""
    for key, value in DEMO_SETTINGS.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()


def _load_member_names(conn, data_dir):
    """Load member names with priority: app DB > external > empty list."""
    # 1. App database members table
    try:
        rows = conn.execute(
            "SELECT first_name, last_name FROM members"
        ).fetchall()
        names = [
            f"{r[0].strip()} {r[1].strip()}" for r in rows if r[0] and r[1]
        ]
        if names:
            return names
    except sqlite3.OperationalError:
        pass

    # 2. External sources
    names = load_member_names_from_external(data_dir)
    if names:
        return names

    # 3. Fallback (empty list — generate_demo_names handles it)
    return []


def _create_demo_election(conn, candidate_names):
    """Create the demo election with Elder and Deacon offices.

    Returns the election id.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.execute(
        "INSERT INTO elections (name, max_rounds, current_round, voting_open, "
        "show_results, election_date) VALUES (?, 2, 1, 0, 0, ?)",
        (f"DEMO Election {today}", today),
    )
    election_id = cursor.lastrowid

    # Elder office — 3 vacancies, 6 candidates, max_selections = 3
    cursor = conn.execute(
        "INSERT INTO offices (election_id, name, max_selections, vacancies, sort_order) "
        "VALUES (?, 'Elder', 3, 3, 1)",
        (election_id,),
    )
    elder_office_id = cursor.lastrowid
    for i, name in enumerate(candidate_names[:6]):
        conn.execute(
            "INSERT INTO candidates (office_id, name, sort_order) VALUES (?, ?, ?)",
            (elder_office_id, name, i + 1),
        )

    # Deacon office — 2 vacancies, 4 candidates, max_selections = 2
    cursor = conn.execute(
        "INSERT INTO offices (election_id, name, max_selections, vacancies, sort_order) "
        "VALUES (?, 'Deacon', 2, 2, 2)",
        (election_id,),
    )
    deacon_office_id = cursor.lastrowid
    for i, name in enumerate(candidate_names[6:10]):
        conn.execute(
            "INSERT INTO candidates (office_id, name, sort_order) VALUES (?, ?, ?)",
            (deacon_office_id, name, i + 1),
        )

    conn.commit()
    return election_id


def _open_round1_voting(conn, election_id):
    """Set voting_open = 1 for the election."""
    conn.execute(
        "UPDATE elections SET voting_open = 1 WHERE id = ?",
        (election_id,),
    )
    conn.commit()


def _export_pdfs(codes, election_name, conn, election_id, code_count=20):
    """Generate code-slips and paper-ballot PDFs into the data directory."""
    pdf_dir = _VOTING_APP_DIR

    short_name = DEMO_SETTINGS["congregation_short"]
    wifi_ssid = DEMO_SETTINGS["wifi_ssid"]
    wifi_password = DEMO_SETTINGS["wifi_password"]
    base_url = DEMO_SETTINGS["voting_base_url"]

    # Code slips
    code_buf = generate_code_slips_pdf(
        codes, election_name, short_name, wifi_ssid,
        wifi_password, base_url, is_demo=True,
    )
    code_slips_path = os.path.join(pdf_dir, "demo_code_slips.pdf")
    with open(code_slips_path, "wb") as f:
        f.write(code_buf.read())

    # Paper ballot — gather office/candidate data
    offices = conn.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,),
    ).fetchall()
    office_data = []
    for office in offices:
        candidates = conn.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY sort_order",
            (office["id"],),
        ).fetchall()
        office_data.append({
            "office": {"name": office["name"], "max_selections": office["max_selections"]},
            "candidates": [{"name": c["name"]} for c in candidates],
        })

    ballot_buf = generate_paper_ballot_pdf(
        election_name, 1, office_data, member_count=len(codes), is_demo=True,
    )
    ballot_path = os.path.join(pdf_dir, "demo_paper_ballots.pdf")
    with open(ballot_path, "wb") as f:
        f.write(ballot_buf.read())

    return code_slips_path, ballot_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Seed a demo election")
    parser.add_argument(
        "--codes", "-n", type=int, default=110,
        help="Number of voting codes to generate (default: 110). "
             "Attendance for round 1 is pre-set to this same number.",
    )
    args = parser.parse_args()
    code_count = args.codes

    db_path = DB_PATH
    abs_db_path = os.path.abspath(db_path)

    logger.info(f"Database: {abs_db_path}")

    # Confirmation prompt
    answer = input(
        f"This will wipe election data and seed a demo with {code_count} codes. "
        "Type YES to continue: "
    )
    if answer.strip() != "YES":
        logger.info("Aborted.")
        sys.exit(1)

    # Port check
    if not SKIP_PORT_CHECK and _port_in_use(5000):
        logger.error("Port 5000 is in use. Stop the running server first.")
        sys.exit(1)

    # Backup
    backup_path = _backup_database(db_path)
    if backup_path:
        logger.info(f"  Backup: {backup_path}")

    # Open/create database and ensure schema exists
    os.makedirs(os.path.dirname(abs_db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")  # OFF during wipe to avoid FK errors
    _init_db_on(conn)
    _migrate_db_on(conn)

    # Wipe election data
    _wipe_election_tables(conn)
    logger.info("  Wiped election data tables")

    # Re-enable foreign keys
    conn.execute("PRAGMA foreign_keys=ON")

    # Set demo settings
    _set_demo_settings(conn)
    logger.info("  Set congregation settings (Darling Downs)")

    # Generate candidate names
    member_names = _load_member_names(conn, _VOTING_APP_DIR)
    candidate_names = generate_demo_names(count=10, member_names=member_names)
    logger.info(f"  Generated {len(candidate_names)} candidate names")

    # Create demo election
    election_id = _create_demo_election(conn, candidate_names)
    election = conn.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    election_name = election["name"]
    logger.info(f"  Created election: {election_name}")

    # Generate voting codes (requires Flask app context)
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with app.app_context():
        codes = generate_codes(election_id, code_count)
    app_module.DB_PATH = original_db_path
    logger.info(f"  Generated {len(codes)} voting codes")

    # Pre-set round 1 attendance to match the code count, so the demo has a
    # sensible default and random_vote.py caps cleanly at this number.
    conn.execute(
        "INSERT OR REPLACE INTO round_counts "
        "(election_id, round_number, participants, paper_ballot_count, digital_ballot_count) "
        "VALUES (?, 1, ?, 0, 0)",
        (election_id, code_count),
    )
    conn.commit()
    logger.info(f"  Pre-set round 1 attendance: {code_count}")

    # Export PDFs
    code_slips_path, ballot_path = _export_pdfs(
        codes, election_name, conn, election_id,
    )
    logger.info(f"  Code slips PDF: {code_slips_path}")
    logger.info(f"  Paper ballot PDF: {ballot_path}")

    conn.close()

    # Summary
    print()
    print("=== Demo Election Seeded ===")
    print(f"  [OK] Database: {abs_db_path}")
    if backup_path:
        print(f"  [OK] Backup: {backup_path}")
    print(f"  [OK] Election: {election_name}")
    print(f"  [OK] Offices: Elder (3 vacancies, 6 candidates), Deacon (2 vacancies, 4 candidates)")
    print(f"  [OK] Admin password reset to: admin")
    print(f"  [OK] Voting codes: {len(codes)}")
    print(f"  [OK] Code slips: {code_slips_path}")
    print(f"  [OK] Paper ballot: {ballot_path}")
    print(f"  [--] Round 1 voting: PENDING  (load_test will open via admin flow)")
    print()
    print("Start the app with: python app.py")


if __name__ == "__main__":
    main()
