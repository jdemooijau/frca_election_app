"""
Reset the election app to a clean state.

Usage:
    cd voting-app
    python scripts/reset_app.py

Environment variables:
    FRCA_DB_PATH          — override the database path
    FRCA_SKIP_PORT_CHECK  — set to "1" to skip port-in-use check
"""

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

from app import _init_db_on, _migrate_db_on

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("FRCA_DB_PATH") or os.path.join(
    _VOTING_APP_DIR, "data", "frca_election.db"
)
SKIP_PORT_CHECK = os.environ.get("FRCA_SKIP_PORT_CHECK", "") == "1"

ELECTION_DATA_TABLES = [
    "votes", "paper_votes", "postal_votes", "codes",
    "candidates", "offices", "elections", "round_counts",
]

DEMO_PDFS = [
    "demo_code_slips.pdf",
    "demo_paper_ballots.pdf",
    "demo_dual_ballot_handout.pdf",
]

LOG_DIR = os.path.join(_VOTING_APP_DIR, "logs")
BACKUP_DIR = os.path.join(_VOTING_APP_DIR, "backups")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("reset_app")
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "reset_app.log"))
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


def _reset_settings(conn):
    """Wipe all settings rows, then re-run _init_db_on to restore defaults."""
    conn.execute("DELETE FROM settings")
    conn.commit()
    _init_db_on(conn)


def _delete_demo_pdfs():
    """Remove demo PDF files from the voting-app root directory."""
    deleted = []
    for filename in DEMO_PDFS:
        pdf_path = os.path.join(_VOTING_APP_DIR, filename)
        if os.path.isfile(pdf_path):
            os.remove(pdf_path)
            deleted.append(pdf_path)
    return deleted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    db_path = DB_PATH
    abs_db_path = os.path.abspath(db_path)

    logger.info(f"Database: {abs_db_path}")

    # Confirmation prompt
    answer = input("This will wipe ALL election data and reset the app. Type YES to continue: ")
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

    # Reset settings to defaults
    _reset_settings(conn)
    logger.info("  Reset settings to defaults")

    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()

    # Delete demo PDFs
    deleted_pdfs = _delete_demo_pdfs()
    for pdf_path in deleted_pdfs:
        logger.info(f"  Deleted: {pdf_path}")

    # Delete plaintext code files
    import glob
    data_dir = os.path.dirname(abs_db_path)
    for f in glob.glob(os.path.join(data_dir, ".codes_*.json")):
        os.remove(f)
        logger.info(f"  Deleted: {f}")

    # Summary
    print()
    print("=== App Reset Complete ===")
    print(f"  \u2713 Database: {abs_db_path}")
    if backup_path:
        print(f"  \u2713 Backup: {backup_path}")
    print(f"  \u2713 Election data wiped")
    print(f"  \u2713 Settings reset to defaults (setup_complete=0)")
    if deleted_pdfs:
        for pdf_path in deleted_pdfs:
            print(f"  \u2713 Deleted: {os.path.basename(pdf_path)}")
    print()
    print("Run setup with: python app.py  (then visit /setup)")


if __name__ == "__main__":
    main()
