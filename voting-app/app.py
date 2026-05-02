"""
FRCA Election App
Self-contained offline voting app for office bearer elections
in Free Reformed Churches of Australia.

Run with: python app.py
"""

import csv
import io
import json
import math
import os
import shutil
import sqlite3
import secrets
import string
import hashlib
import time
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, g, jsonify, make_response, abort, send_file
)
from flask_wtf import CSRFProtect
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from pdf_generators import (
    generate_code_slips_pdf, generate_paper_ballot_pdf,
    generate_counter_sheet_pdf, generate_results_pdf,
    generate_dual_sided_ballots_pdf,
    generate_attendance_register_pdf, generate_printer_pack_zip,
    generate_minutes_docx,
    NAVY, GOLD, _generate_qr_image,
)
from demo_names import generate_demo_names, load_member_names_from_external
from election_rules import (
    calculate_thresholds, check_candidate_elected, resolve_elected_status,
)

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "frca_election.db")

# Force production mode — no dev server, no debug
os.environ.pop("FLASK_ENV", None)
os.environ.pop("FLASK_DEBUG", None)

app = Flask(__name__)
# Persist secret key to a file so CSRF tokens survive restarts
_secret_key_file = os.path.join(DATA_DIR, ".secret_key")
os.makedirs(DATA_DIR, exist_ok=True)
if os.path.exists(_secret_key_file):
    with open(_secret_key_file, "r") as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    with open(_secret_key_file, "w") as f:
        f.write(app.secret_key)
app.config["DEBUG"] = False
app.config["TESTING"] = False
app.config["WTF_CSRF_TIME_LIMIT"] = None  # No CSRF token expiry for slow voters

csrf = CSRFProtect(app)

# Default admin password — must be changed on first login
DEFAULT_ADMIN_PASSWORD = "admin"

# Code character set: uppercase + digits, excluding O/0/I/1/L
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _surname_sort_key(name):
    """Return a lowercase sort key based on the full surname.

    'Gary van Dijkstra' -> 'van dijkstra'
    'Neil ten Heuvel'   -> 'ten heuvel'
    'Henry Brouwerhof'  -> 'brouwerhof'
    """
    if not name:
        return ""
    parts = name.strip().split(None, 1)
    surname = parts[1] if len(parts) > 1 else parts[0]
    return surname.lower()


def get_db():
    """Get a database connection for the current request. Re-initializes if DB was wiped."""
    if "db" not in g:
        os.makedirs(DATA_DIR, exist_ok=True)
        is_new = not os.path.exists(DB_PATH)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.create_function("surname_sort_key", 1, _surname_sort_key)
        if is_new:
            # DB was wiped — re-create tables
            _init_db_on(g.db)
            _migrate_db_on(g.db)
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _init_db_on(db):
    """Create all tables on a given db connection."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS elections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            max_rounds INTEGER NOT NULL DEFAULT 2,
            current_round INTEGER NOT NULL DEFAULT 1,
            voting_open INTEGER NOT NULL DEFAULT 0,
            show_results INTEGER NOT NULL DEFAULT 0,
            election_date TEXT,
            is_interim INTEGER NOT NULL DEFAULT 0,
            interim_term_info TEXT,
            paper_ballot_count INTEGER NOT NULL DEFAULT 0,
            postal_voter_count INTEGER NOT NULL DEFAULT 0,
            display_phase INTEGER NOT NULL DEFAULT 1,
            paper_count_enabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS offices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            max_selections INTEGER NOT NULL DEFAULT 1,
            vacancies INTEGER,
            original_vacancies INTEGER,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (election_id) REFERENCES elections(id)
        );

        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            office_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            retiring_office_bearer INTEGER NOT NULL DEFAULT 0,
            elected INTEGER NOT NULL DEFAULT 0,
            elected_round INTEGER,
            relieved INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (office_id) REFERENCES offices(id)
        );

        CREATE TABLE IF NOT EXISTS codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL UNIQUE,
            plaintext TEXT NOT NULL DEFAULT '',
            used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (election_id) REFERENCES elections(id)
        );

        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'digital',
            cast_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (election_id) REFERENCES elections(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE TABLE IF NOT EXISTS paper_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            entered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (election_id) REFERENCES elections(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE TABLE IF NOT EXISTS postal_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (election_id) REFERENCES elections(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE TABLE IF NOT EXISTS round_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            participants INTEGER NOT NULL DEFAULT 0,
            paper_ballot_count INTEGER NOT NULL DEFAULT 0,
            digital_ballot_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(election_id, round_number),
            FOREIGN KEY (election_id) REFERENCES elections(id)
        );

        CREATE TABLE IF NOT EXISTS office_spoilt_ballots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            office_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(election_id, round_number, office_id),
            FOREIGN KEY (election_id) REFERENCES elections(id),
            FOREIGN KEY (office_id) REFERENCES offices(id)
        );

        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            age TEXT,
            address TEXT,
            email TEXT,
            mobile_phone TEXT,
            membership_status TEXT,
            imported_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS voter_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            election_id INTEGER,
            round_number INTEGER,
            ip TEXT,
            user_agent TEXT,
            path TEXT,
            code TEXT,
            result TEXT NOT NULL,
            detail TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_voter_audit_election ON voter_audit_log(election_id, ts);
        CREATE INDEX IF NOT EXISTS idx_voter_audit_code ON voter_audit_log(code);
    """)

    db.executescript("""
        CREATE TABLE IF NOT EXISTS count_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            round_no INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            started_at TEXT NOT NULL,
            persisted_at TEXT,
            persisted_by_admin_id INTEGER,
            cancelled_at TEXT,
            UNIQUE(election_id, round_no),
            FOREIGN KEY (election_id) REFERENCES elections(id)
        );
        CREATE TABLE IF NOT EXISTS count_session_helpers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            voter_code TEXT NOT NULL,
            short_id TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            marked_done_at TEXT,
            disregarded_at TEXT,
            UNIQUE(session_id, voter_code),
            FOREIGN KEY (session_id) REFERENCES count_sessions(id)
        );
        CREATE TABLE IF NOT EXISTS count_session_tallies (
            session_id INTEGER NOT NULL,
            helper_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (session_id, helper_id, candidate_id),
            FOREIGN KEY (session_id) REFERENCES count_sessions(id),
            FOREIGN KEY (helper_id) REFERENCES count_session_helpers(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );
        CREATE TABLE IF NOT EXISTS count_session_results (
            session_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            final_count INTEGER NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (session_id, candidate_id),
            FOREIGN KEY (session_id) REFERENCES count_sessions(id),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );
        CREATE INDEX IF NOT EXISTS idx_count_sessions_election ON count_sessions(election_id, round_no);
        CREATE INDEX IF NOT EXISTS idx_count_session_helpers_session ON count_session_helpers(session_id);
        CREATE INDEX IF NOT EXISTS idx_count_session_tallies_session ON count_session_tallies(session_id);
    """)
    db.commit()

    # Insert default settings if not present
    defaults = {
        "congregation_name": "Free Reformed Church",
        "congregation_short": "FRC",
        "wifi_ssid": "ChurchVote",
        "wifi_password": "",
        "voting_base_url": "http://church.vote",
        "admin_password": DEFAULT_ADMIN_PASSWORD,
        "setup_complete": "0",
    }
    for key, value in defaults.items():
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
    db.commit()


def init_db():
    """Create all tables if they don't exist."""
    _init_db_on(get_db())


def get_round_counts(election_id, round_number):
    """Get participants, paper_ballot_count, and digital_ballot_count for a round."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM round_counts WHERE election_id = ? AND round_number = ?",
        (election_id, round_number)
    ).fetchone()
    if row:
        try:
            digital = row["digital_ballot_count"] or 0
        except (IndexError, KeyError):
            digital = 0
        return row["participants"], row["paper_ballot_count"], digital
    return 0, 0, 0


# ---------------------------------------------------------------------------
# Wizard sidebar state
# ---------------------------------------------------------------------------

# Step ordering and slugs. Order matters; index in this list = step number.
WIZARD_STEPS = [
    # (slug, label, group)
    ("details",    "Election details",      "Setup"),
    ("members",    "Members",               "Setup"),
    ("offices",    "Offices & Candidates",  "Setup"),
    ("settings",   "Election settings",     "Setup"),
    ("codes",      "Codes & printing",      "Setup"),
    ("attendance", "Attendance & postal",   "Round"),
    ("welcome",    "Welcome & Rules",       "Round"),
    ("voting",     "Voting",                "Round"),
    ("count",      "Count & tally",         "Round"),
    ("decide",     "Decide",                "Round"),
    ("final",      "Final results",         "Finish"),
    ("minutes",    "Minutes & archive",     "Finish"),
]


def _step_done(db, election, slug, round_no):
    """Return True if the given step is Done in the spec sense.

    `round_no` is the round we are evaluating Done for: usually
    election.current_round, but used to render historical-round summaries.
    """
    eid = election["id"]
    if slug == "details":
        return True  # election row exists
    if slug == "members":
        # Members are app-global; the same imported list is reused across elections.
        return db.execute("SELECT COUNT(*) FROM members").fetchone()[0] > 0
    if slug == "offices":
        return db.execute(
            """
            SELECT 1 FROM offices o
            WHERE o.election_id = ?
              AND EXISTS (SELECT 1 FROM candidates c WHERE c.office_id = o.id)
            LIMIT 1
            """,
            (eid,),
        ).fetchone() is not None
    if slug == "settings":
        return True  # safe defaults; visiting is enough
    if slug == "codes":
        return db.execute(
            "SELECT COUNT(*) FROM codes WHERE election_id = ?", (eid,)
        ).fetchone()[0] > 0
    if slug == "attendance":
        in_person, _, _ = get_round_counts(eid, round_no)
        return in_person > 0
    if slug == "welcome":
        if (election["display_phase"] or 1) >= 2:
            return True
        if election["voting_open"]:
            return True
        v = db.execute(
            "SELECT 1 FROM votes WHERE election_id = ? AND round_number = ? LIMIT 1",
            (eid, round_no),
        ).fetchone()
        return v is not None
    if slug == "voting":
        v = db.execute(
            "SELECT 1 FROM votes WHERE election_id = ? AND round_number = ? LIMIT 1",
            (eid, round_no),
        ).fetchone()
        return v is not None
    if slug == "count":
        v = db.execute(
            "SELECT 1 FROM paper_votes WHERE election_id = ? AND round_number = ? LIMIT 1",
            (eid, round_no),
        ).fetchone()
        return v is not None
    if slug == "decide":
        if (election["current_round"] or 1) > round_no:
            return True
        return (election["display_phase"] or 1) >= 4
    if slug == "final":
        return (election["display_phase"] or 1) >= 4
    if slug == "minutes":
        return False
    return False


def _step_prerequisites_met(db, election, slug, round_no):
    """Return True if the step's prerequisites are satisfied (i.e. it is reachable)."""
    if slug in ("details", "members"):
        return True
    if slug == "offices":
        return _step_done(db, election, "details", round_no)
    if slug == "settings":
        return _step_done(db, election, "details", round_no)
    if slug == "codes":
        return _step_done(db, election, "offices", round_no)
    if slug == "attendance":
        return _step_done(db, election, "codes", round_no)
    if slug == "welcome":
        return _step_done(db, election, "attendance", round_no)
    if slug == "voting":
        return _step_done(db, election, "welcome", round_no)
    if slug == "count":
        if not _step_done(db, election, "voting", round_no):
            return False
        return not election["voting_open"] or (election["current_round"] or 1) != round_no
    if slug == "decide":
        return _step_prerequisites_met(db, election, "count", round_no)
    if slug == "final":
        # Reachable as soon as count is done and voting is closed, so the
        # chairman can preview the elected list on the admin Final step
        # before clicking Show Final Results on Projector (which advances
        # display_phase to 4 and is what makes "decide" Done).
        return _step_prerequisites_met(db, election, "decide", round_no)
    if slug == "minutes":
        return _step_done(db, election, "final", round_no)
    return False


def compute_sidebar_state(election_id):
    """Build the dict consumed by `_sidebar.html`."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        return None

    current_round = election["current_round"] or 1
    # Members are app-global, not per-election; the count is shared across all elections.
    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    # First pass: compute (done, reachable) for each step and stash item shells.
    status = {}  # slug -> (done, reachable)
    items_by_slug = {}
    for slug, label, _group in WIZARD_STEPS:
        done = _step_done(db, election, slug, current_round)
        reachable = _step_prerequisites_met(db, election, slug, current_round)
        status[slug] = (done, reachable)
        item_label = f"Members ({member_count})" if slug == "members" and member_count > 0 else label
        items_by_slug[slug] = {
            "slug": slug,
            "label": item_label,
            "url": url_for(f"admin_step_{slug}", election_id=election_id),
        }

    # Current step = lowest-numbered reachable, not-done step. If all done,
    # fall back to the last step in WIZARD_STEPS (currently "minutes").
    # Members is app-global; don't auto-land the user there. They can still
    # navigate to it from the sidebar; it just shouldn't be the default
    # landing step from /admin/election/<id>/manage redirects or
    # admin_election_open.
    current_step = next(
        (slug for slug, _label, _group in WIZARD_STEPS
         if slug != "members" and status[slug][1] and not status[slug][0]),
        WIZARD_STEPS[-1][0],
    )

    # Second pass: assign render state. Reachable but non-current/non-done
    # steps are "available" - clickable nav target (e.g. Final results when
    # count is done but the chairman has not yet flipped the projector).
    for slug, item in items_by_slug.items():
        done, reachable = status[slug]
        if slug == current_step:
            item["state"] = "current"
        elif done:
            item["state"] = "done"
        elif reachable:
            item["state"] = "available"
        else:
            item["state"] = "locked"

    groups = [
        {"label": "Setup", "entries": [items_by_slug[s] for s, _, g in WIZARD_STEPS if g == "Setup"]},
        {"label": f"Round {current_round}", "entries": [items_by_slug[s] for s, _, g in WIZARD_STEPS if g == "Round"]},
        {"label": "Finish", "entries": [items_by_slug[s] for s, _, g in WIZARD_STEPS if g == "Finish"]},
    ]

    if current_round > 1:
        for r in range(1, current_round):
            elected = db.execute(
                "SELECT COUNT(*) FROM candidates c "
                "JOIN offices o ON o.id = c.office_id "
                "WHERE o.election_id = ? AND c.elected = 1 AND c.elected_round = ?",
                (election_id, r),
            ).fetchone()[0]
            summary = f"Closed - {elected} elected" if elected else "Closed - 0 elected"
            groups.insert(
                1 + (r - 1),
                {"label": f"Round {r}", "collapsed": True, "summary": summary, "entries": []},
            )

    return {
        "election": {
            "id": election["id"],
            "name": election["name"],
            "date": election["election_date"] if "election_date" in election.keys() else "",
            "current_round": current_round,
            "max_rounds": election["max_rounds"],
            "voting_open": bool(election["voting_open"]),
        },
        "current_step": current_step,
        "groups": groups,
    }


def set_round_counts(election_id, round_number, participants, paper_ballot_count):
    """Set participants and paper_ballot_count for a specific round."""
    db = get_db()
    # Preserve existing digital_ballot_count
    existing = db.execute(
        "SELECT digital_ballot_count FROM round_counts WHERE election_id = ? AND round_number = ?",
        (election_id, round_number)
    ).fetchone()
    digital = existing["digital_ballot_count"] if existing else 0
    db.execute(
        """INSERT OR REPLACE INTO round_counts (election_id, round_number, participants, paper_ballot_count, digital_ballot_count)
           VALUES (?, ?, ?, ?, ?)""",
        (election_id, round_number, participants, paper_ballot_count, digital)
    )
    db.commit()


def increment_digital_ballot(election_id, round_number):
    """Increment the digital ballot counter for a round."""
    db = get_db()
    db.execute(
        """INSERT INTO round_counts (election_id, round_number, participants, paper_ballot_count, digital_ballot_count)
           VALUES (?, ?, 0, 0, 1)
           ON CONFLICT(election_id, round_number)
           DO UPDATE SET digital_ballot_count = digital_ballot_count + 1""",
        (election_id, round_number)
    )
    db.commit()


def get_setting(key, default=""):
    """Get a setting value from the database."""
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    """Set a setting value in the database."""
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    db.commit()


def _migrate_db_on(db):
    """Add columns for rules compliance on a given db connection."""
    migrations = [
        "ALTER TABLE elections ADD COLUMN election_date TEXT",
        "ALTER TABLE elections ADD COLUMN is_interim INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE elections ADD COLUMN interim_term_info TEXT",
        "ALTER TABLE elections ADD COLUMN paper_ballot_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE offices ADD COLUMN vacancies INTEGER",
        "ALTER TABLE candidates ADD COLUMN retiring_office_bearer INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE candidates ADD COLUMN elected INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE candidates ADD COLUMN relieved INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE elections ADD COLUMN postal_voter_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE round_counts ADD COLUMN digital_ballot_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE codes ADD COLUMN plaintext TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE elections ADD COLUMN display_phase INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE candidates ADD COLUMN elected_round INTEGER",
        "ALTER TABLE offices ADD COLUMN original_vacancies INTEGER",
        "ALTER TABLE elections DROP COLUMN participants",
        "ALTER TABLE elections ADD COLUMN paper_count_enabled INTEGER NOT NULL DEFAULT 0",
    ]
    for sql in migrations:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Add paper-count co-counting tables for existing databases. Idempotent
    # via CREATE TABLE IF NOT EXISTS; wrapped in try/except as a safety net.
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS count_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                election_id INTEGER NOT NULL,
                round_no INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                started_at TEXT NOT NULL,
                persisted_at TEXT,
                persisted_by_admin_id INTEGER,
                cancelled_at TEXT,
                UNIQUE(election_id, round_no),
                FOREIGN KEY (election_id) REFERENCES elections(id)
            );
            CREATE TABLE IF NOT EXISTS count_session_helpers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                voter_code TEXT NOT NULL,
                short_id TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                marked_done_at TEXT,
                disregarded_at TEXT,
                UNIQUE(session_id, voter_code),
                FOREIGN KEY (session_id) REFERENCES count_sessions(id)
            );
            CREATE TABLE IF NOT EXISTS count_session_tallies (
                session_id INTEGER NOT NULL,
                helper_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, helper_id, candidate_id),
                FOREIGN KEY (session_id) REFERENCES count_sessions(id),
                FOREIGN KEY (helper_id) REFERENCES count_session_helpers(id),
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            );
            CREATE TABLE IF NOT EXISTS count_session_results (
                session_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                final_count INTEGER NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (session_id, candidate_id),
                FOREIGN KEY (session_id) REFERENCES count_sessions(id),
                FOREIGN KEY (candidate_id) REFERENCES candidates(id)
            );
            CREATE INDEX IF NOT EXISTS idx_count_sessions_election ON count_sessions(election_id, round_no);
            CREATE INDEX IF NOT EXISTS idx_count_session_helpers_session ON count_session_helpers(session_id);
            CREATE INDEX IF NOT EXISTS idx_count_session_tallies_session ON count_session_tallies(session_id);
        """)
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Back-fill original_vacancies from vacancies for rows that never got it.
    # For elections already advanced past round 1, office.vacancies is already
    # decremented, so we fall back to max_selections where available — max_selections
    # decrements too, so this lower bound is no worse than current behaviour for
    # those rows. Row-level correction happens as new elections are created.
    db.execute(
        "UPDATE offices SET original_vacancies = COALESCE(vacancies, max_selections) "
        "WHERE original_vacancies IS NULL"
    )
    db.commit()


def migrate_db():
    """Add columns for rules compliance. Safe to run repeatedly."""
    _migrate_db_on(get_db())


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def admin_required(f):
    """Decorator to require admin login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/election/<int:election_id>/step/details", methods=["GET"], endpoint="admin_step_details")
@admin_required
def _admin_step_details(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template(
        "admin/step_details.html",
        election=election,
        sidebar_state=sidebar_state,
    )


@app.route("/admin/election/<int:election_id>/step/details/save", methods=["POST"])
@admin_required
def admin_step_details_save(election_id):
    db = get_db()
    name = request.form.get("name", "").strip()
    election_date = request.form.get("election_date", "").strip()
    try:
        max_rounds = max(1, min(5, int(request.form.get("max_rounds", "2"))))
    except ValueError:
        max_rounds = 2
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin_step_details", election_id=election_id))
    db.execute(
        "UPDATE elections SET name = ?, election_date = ?, max_rounds = ? WHERE id = ?",
        (name, election_date, max_rounds, election_id),
    )
    db.commit()
    flash("Saved.", "success")
    return redirect(url_for("admin_step_details", election_id=election_id))


@app.route("/admin/election/<int:election_id>/step/members", methods=["GET"], endpoint="admin_step_members")
@admin_required
def admin_step_members(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    members = db.execute(
        "SELECT * FROM members ORDER BY surname_sort_key(last_name || ' ' || first_name)"
    ).fetchall()
    member_count = len(members)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template(
        "admin/members.html",
        members=members,
        member_count=member_count,
        sidebar_state=sidebar_state,
        parent_template="admin/_step_base.html",
    )


@app.route("/admin/election/<int:election_id>/step/offices", methods=["GET"], endpoint="admin_step_offices")
@admin_required
def admin_step_offices(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()
    candidates_by_office = {}
    for office in offices:
        candidates_by_office[office["id"]] = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
    sidebar_state = compute_sidebar_state(election_id)
    return render_template(
        "admin/step_offices.html",
        election=election,
        offices=offices,
        candidates_by_office=candidates_by_office,
        sidebar_state=sidebar_state,
    )


@app.route("/admin/election/<int:election_id>/step/settings", methods=["GET"], endpoint="admin_step_settings")
@admin_required
def admin_step_settings(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template("admin/step_settings.html",
                           election=election, sidebar_state=sidebar_state)


@app.route("/admin/election/<int:election_id>/step/codes", methods=["GET"], endpoint="admin_step_codes")
@admin_required
def admin_step_codes(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    # Smart default mirrors legacy admin_codes GET: (members + 10) * max_rounds.
    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    per_round = member_count + 10 if member_count > 0 else 100
    default_count = per_round * election["max_rounds"]

    total_codes = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ?", (election_id,)
    ).fetchone()[0]

    # Auto-generate on first visit once offices have been set up. Mirrors
    # the existing /admin/election/<id>/codes GET behavior.
    generated_codes = []
    if total_codes == 0:
        offices_exist = db.execute(
            "SELECT 1 FROM offices WHERE election_id = ? LIMIT 1",
            (election_id,)
        ).fetchone() is not None
        if offices_exist:
            generated_codes = generate_codes(election_id, default_count)
            flash(
                f"Auto-generated {len(generated_codes)} voting codes "
                f"({member_count} members × {election['max_rounds']} rounds + spares). "
                "Print the code slips next.",
                "success"
            )
            total_codes = len(generated_codes)

    used_codes = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1",
        (election_id,)
    ).fetchone()[0]
    postal_voter_count = election["postal_voter_count"] or 0

    sidebar_state = compute_sidebar_state(election_id)
    return render_template(
        "admin/step_codes.html",
        election=election,
        total_codes=total_codes,
        used_codes=used_codes,
        generated_codes=generated_codes,
        member_count=member_count,
        default_count=default_count,
        postal_voter_count=postal_voter_count,
        sidebar_state=sidebar_state,
    )


@app.route("/admin/election/<int:election_id>/step/attendance", methods=["GET"], endpoint="admin_step_attendance")
@admin_required
def admin_step_attendance(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    in_person, _, _ = get_round_counts(election_id, election["current_round"])
    sidebar_state = compute_sidebar_state(election_id)
    return render_template(
        "admin/step_attendance.html",
        election=election,
        in_person_participants=in_person,
        postal_voter_count=election["postal_voter_count"] or 0,
        sidebar_state=sidebar_state,
    )


@app.route("/admin/election/<int:election_id>/step/welcome", methods=["GET"], endpoint="admin_step_welcome")
@admin_required
def admin_step_welcome(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template(
        "admin/step_welcome.html",
        election=election,
        phase=election["display_phase"] or 1,
        sidebar_state=sidebar_state,
    )


@app.route("/admin/election/<int:election_id>/step/voting", methods=["GET"], endpoint="admin_step_voting")
@admin_required
def admin_step_voting(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_voting.html", **payload)


@app.route("/admin/election/<int:election_id>/step/count", methods=["GET"], endpoint="admin_step_count")
@admin_required
def admin_step_count(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_count.html", **payload)


@app.route("/admin/election/<int:election_id>/step/decide", methods=["GET"], endpoint="admin_step_decide")
@admin_required
def admin_step_decide(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_decide.html", **payload)


@app.route("/admin/election/<int:election_id>/step/final", methods=["GET"], endpoint="admin_step_final")
@admin_required
def admin_step_final(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_final.html", **payload)


@app.route("/admin/election/<int:election_id>/step/minutes", methods=["GET"], endpoint="admin_step_minutes")
@admin_required
def admin_step_minutes(election_id):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template("admin/step_minutes.html", election=election, sidebar_state=sidebar_state)


def hash_code(code):
    """Hash a voting code for fast lookup."""
    return hashlib.sha256(code.upper().encode()).hexdigest()


def log_voter_audit(election_id, code, result, detail=None, round_number=None):
    """Append a row to voter_audit_log. Safe to call from any voter route.

    code is the plaintext voting code (or None if not applicable). It is
    stored as-is for the chairman audit view — codes are short-lived and
    only the admin can read this table. Failures are swallowed because
    audit logging must not break a vote.
    """
    try:
        db = get_db()
        ip = request.remote_addr if request else None
        user_agent = (request.headers.get("User-Agent") or "")[:200] if request else None
        path = request.path if request else None
        db.execute(
            "INSERT INTO voter_audit_log "
            "(election_id, round_number, ip, user_agent, path, code, result, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (election_id, round_number, ip, user_agent, path, code, result, detail)
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def generate_codes(election_id, count):
    """Generate unique voting codes for an election. Returns list of plaintext codes."""
    db = get_db()
    codes = []
    attempts = 0
    max_attempts = count * 10

    while len(codes) < count and attempts < max_attempts:
        attempts += 1
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LENGTH))
        code_h = hash_code(code)

        existing = db.execute(
            "SELECT 1 FROM codes WHERE code_hash = ?", (code_h,)
        ).fetchone()
        if existing:
            continue

        db.execute(
            "INSERT INTO codes (election_id, code_hash, plaintext) VALUES (?, ?, ?)",
            (election_id, code_h, code)
        )
        codes.append(code)

    db.commit()
    return codes


def load_codes_from_db(election_id):
    """Load plaintext codes from the database. Returns list or None."""
    db = get_db()
    rows = db.execute(
        "SELECT plaintext FROM codes WHERE election_id = ? AND plaintext != '' ORDER BY id",
        (election_id,)
    ).fetchall()
    if not rows:
        return None
    return [row["plaintext"] for row in rows]


def no_cache(response):
    """Add no-cache headers to a response."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------

@app.after_request
def add_no_cache_headers(response):
    """Add no-cache headers to all responses."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.context_processor
def inject_globals():
    return {
        "now": datetime.now(),
        "congregation_name": get_setting("congregation_name", "Free Reformed Church"),
        "congregation_short": get_setting("congregation_short", "FRC"),
        "wifi_ssid": get_setting("wifi_ssid", "ChurchVote"),
        "wifi_password": get_setting("wifi_password", ""),
        "voting_base_url": get_setting("voting_base_url", "http://church.vote"),
    }


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = get_setting("admin_password", DEFAULT_ADMIN_PASSWORD)
        if request.form.get("password") == password:
            session["admin"] = True
            # Redirect to setup wizard if first login
            if get_setting("setup_complete") != "1":
                return redirect(url_for("admin_setup"))
            return redirect(url_for("admin_dashboard"))
        flash("Incorrect password.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/setup", methods=["GET", "POST"])
@admin_required
def admin_setup():
    """Settings — congregation config; doubles as the first-run wizard.

    On first run (setup_complete != "1") the admin password fields are
    required. Once setup is complete, the password fields become optional
    — leaving them blank keeps the existing password.
    """
    setup_complete = get_setting("setup_complete", "0") == "1"

    if request.method == "POST":
        congregation_name = request.form.get("congregation_name", "").strip()
        congregation_short = request.form.get("congregation_short", "").strip()
        wifi_ssid = request.form.get("wifi_ssid", "").strip()
        wifi_password = request.form.get("wifi_password", "").strip()
        voting_base_url = request.form.get("voting_base_url", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not congregation_name:
            flash("Congregation name is required.", "error")
            return _render_setup_form()

        # Password handling:
        #   first-run: required and >= 6 chars
        #   later edits: only validate / update if a new password was typed
        if setup_complete and not new_password and not confirm_password:
            password_to_save = None
        else:
            if not new_password or len(new_password) < 6:
                flash(
                    "Please set a new admin password (at least 6 characters)."
                    if not setup_complete
                    else "New password must be at least 6 characters, or leave both fields blank to keep the existing password.",
                    "error"
                )
                return _render_setup_form()
            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
                return _render_setup_form()
            password_to_save = new_password

        set_setting("congregation_name", congregation_name)
        set_setting("congregation_short", congregation_short or congregation_name)
        set_setting("wifi_ssid", wifi_ssid or "ChurchVote")
        set_setting("wifi_password", wifi_password)
        set_setting("voting_base_url", voting_base_url or "http://church.vote")
        if password_to_save is not None:
            set_setting("admin_password", password_to_save)
        set_setting("setup_complete", "1")

        flash(
            "Settings saved." if setup_complete else "Setup complete. Welcome.",
            "success"
        )
        return redirect(url_for("admin_dashboard"))

    return _render_setup_form()


def _render_setup_form():
    """Render setup.html with current settings pre-filled."""
    return render_template(
        "admin/setup.html",
        setup_complete=get_setting("setup_complete", "0") == "1",
        congregation_name=get_setting("congregation_name", ""),
        congregation_short=get_setting("congregation_short", ""),
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        voting_base_url=get_setting("voting_base_url", "http://church.vote"),
    )


@app.route("/admin")
@admin_required
def admin_dashboard():
    # Redirect to setup if not yet configured
    if get_setting("setup_complete") != "1":
        return redirect(url_for("admin_setup"))

    db = get_db()
    elections = db.execute(
        "SELECT * FROM elections ORDER BY created_at DESC"
    ).fetchall()
    return render_template("admin/dashboard.html", elections=elections)


@app.route("/admin/election/new", methods=["GET", "POST"])
@admin_required
def admin_election_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        max_rounds = int(request.form.get("max_rounds", 2))
        election_date = request.form.get("election_date", "").strip()
        if not name:
            flash("Election name is required.", "error")
            return render_template("admin/election_new.html")

        if max_rounds < 1 or max_rounds > 5:
            flash("Max rounds must be between 1 and 5.", "error")
            return render_template("admin/election_new.html")

        db = get_db()
        cursor = db.execute(
            """INSERT INTO elections (name, max_rounds, election_date)
               VALUES (?, ?, ?)""",
            (name, max_rounds, election_date or None)
        )
        election_id = cursor.lastrowid
        db.commit()

        flash("Election created. Now add offices and candidates.", "success")
        return redirect(url_for("admin_step_offices", election_id=election_id))

    return render_template("admin/election_new.html")


@app.route("/admin/election/<int:election_id>/setup", methods=["GET"])
@admin_required
def admin_election_setup_legacy_get(election_id):
    """Legacy URL. Redirect to the wizard step."""
    return redirect(url_for("admin_step_offices", election_id=election_id), code=301)


@app.route("/admin/election/<int:election_id>/setup", methods=["POST"])
@admin_required
def admin_election_setup(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    office_name = request.form.get("office_name", "").strip()
    vacancies = int(request.form.get("vacancies", 1))
    max_selections = int(request.form.get("max_selections", 0)) or vacancies
    candidate_names = request.form.get("candidate_names", "").strip()
    confirm_slate = request.form.get("confirm_slate_override")

    if not office_name:
        flash("Office name is required.", "error")
    elif not candidate_names:
        flash("At least one candidate is required.", "error")
    elif vacancies < 1:
        flash("Vacancies must be at least 1.", "error")
    else:
        # Count candidates
        cand_list = [n.strip() for n in candidate_names.split("\n") if n.strip()]
        expected_slate = 2 * vacancies

        # Article 2 slate validation
        if len(cand_list) != expected_slate and not confirm_slate:
            flash(
                f"Article 2 requires a slate of {expected_slate} candidates for {vacancies} "
                f"{'vacancy' if vacancies == 1 else 'vacancies'} (twice the number of vacancies). "
                f"You have {len(cand_list)} candidates. "
                f"Article 13 permits deviation — confirm below to proceed.",
                "error"
            )
            return render_template(
                "admin/step_offices.html",
                election=election,
                offices=db.execute(
                    "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
                    (election_id,)
                ).fetchall(),
                candidates_by_office={
                    o["id"]: db.execute(
                        "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
                        (o["id"],)
                    ).fetchall()
                    for o in db.execute(
                        "SELECT * FROM offices WHERE election_id = ?", (election_id,)
                    ).fetchall()
                },
                slate_warning=True,
                prefill_office=office_name,
                prefill_vacancies=vacancies,
                prefill_max_selections=max_selections,
                prefill_candidates=candidate_names,
                sidebar_state=compute_sidebar_state(election_id),
            )

        # Get next sort order
        max_sort = db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM offices WHERE election_id = ?",
            (election_id,)
        ).fetchone()[0]

        cursor = db.execute(
            "INSERT INTO offices (election_id, name, max_selections, vacancies, original_vacancies, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (election_id, office_name, max_selections, vacancies, vacancies, max_sort + 1)
        )
        office_id = cursor.lastrowid

        # Parse candidate names (one per line)
        for i, cand_name in enumerate(cand_list):
            db.execute(
                "INSERT INTO candidates (office_id, name, sort_order) VALUES (?, ?, ?)",
                (office_id, cand_name, i)
            )

        db.commit()

        if len(cand_list) != expected_slate:
            flash(f"Office '{office_name}' added (Article 13 deviation: {len(cand_list)} candidates for {vacancies} vacancies).", "success")
        else:
            flash(f"Office '{office_name}' added with {len(cand_list)} candidates.", "success")

    return redirect(url_for("admin_step_offices", election_id=election_id))


@app.route("/admin/election/<int:election_id>/settings", methods=["POST"])
@admin_required
def admin_election_settings(election_id):
    """Update election-level toggles (paper_count_enabled, etc.).

    Allowed only before voting opens for the election.
    """
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    if election["voting_open"]:
        flash("Cannot change settings while voting is open.", "error")
        return redirect(url_for("admin_step_settings", election_id=election_id))

    paper_count_enabled = 1 if request.form.get("paper_count_enabled") == "1" else 0
    db.execute(
        "UPDATE elections SET paper_count_enabled = ? WHERE id = ?",
        (paper_count_enabled, election_id)
    )
    db.commit()
    flash("Settings updated.", "success")
    return redirect(url_for("admin_step_settings", election_id=election_id))


@app.route("/admin/election/<int:election_id>/office/<int:office_id>/delete", methods=["POST"])
@admin_required
def admin_office_delete(election_id, office_id):
    db = get_db()
    db.execute("DELETE FROM candidates WHERE office_id = ?", (office_id,))
    db.execute("DELETE FROM offices WHERE id = ? AND election_id = ?", (office_id, election_id))
    db.commit()
    flash("Office removed.", "success")
    return redirect(url_for("admin_step_offices", election_id=election_id))


@app.route("/admin/election/<int:election_id>/codes", methods=["GET"])
@admin_required
def admin_codes_legacy_get(election_id):
    """Legacy URL. Redirect to the wizard step."""
    return redirect(url_for("admin_step_codes", election_id=election_id), code=301)


@app.route("/admin/election/<int:election_id>/codes", methods=["POST"])
@admin_required
def admin_codes(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    # Smart default for the count field if the user submitted no explicit value:
    # (member count + 10) * max_rounds.
    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    per_round = member_count + 10 if member_count > 0 else 100
    default_count = per_round * election["max_rounds"]

    existing_codes_count = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ?",
        (election_id,)
    ).fetchone()[0]

    count = int(request.form.get("count", default_count))
    if count < 1 or count > 999:
        flash("Code count must be between 1 and 999.", "error")
    elif existing_codes_count > 0:
        flash(
            f"Codes already exist ({existing_codes_count} codes). "
            "Delete them first to regenerate.",
            "error"
        )
    else:
        generated_codes = generate_codes(election_id, count)
        flash(f"Generated {len(generated_codes)} voting codes.", "success")

    return redirect(url_for("admin_step_codes", election_id=election_id))


@app.route("/admin/election/<int:election_id>/codes/delete", methods=["POST"])
@admin_required
def admin_codes_delete(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    # Hard guard 1: never delete once any code has been used
    used_count = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1",
        (election_id,)
    ).fetchone()[0]
    if used_count > 0:
        flash(
            f"Cannot delete codes — {used_count} code(s) have already been "
            "used. Regenerating would invalidate any votes already cast.",
            "error"
        )
        return redirect(url_for("admin_step_codes", election_id=election_id))

    # Hard guard 2: require typed election name AND admin password.
    # Codes may already be printed — regenerating without the chairman
    # knowing would fail the election.
    typed_name = (request.form.get("confirm_name") or "").strip()
    typed_password = request.form.get("password") or ""
    if typed_name != (election["name"] or ""):
        flash(
            "Codes not deleted — typed election name did not match. "
            "Codes may already be on printed slips; regenerating without "
            "reprinting would fail the election.",
            "error"
        )
        return redirect(url_for("admin_step_codes", election_id=election_id))
    if typed_password != get_setting("admin_password"):
        flash("Codes not deleted — admin password incorrect.", "error")
        return redirect(url_for("admin_step_codes", election_id=election_id))

    db.execute("DELETE FROM codes WHERE election_id = ?", (election_id,))
    db.commit()
    flash(
        "All codes deleted. Generate fresh codes and reprint the slips "
        "before voting opens.",
        "success"
    )
    return redirect(url_for("admin_step_codes", election_id=election_id))


@app.route("/admin/election/<int:election_id>/voting", methods=["POST"])
@admin_required
def admin_toggle_voting(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    new_state = 0 if election["voting_open"] else 1

    # Don't open voting if no unused codes exist
    if new_state == 1:
        code_count = db.execute(
            "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 0",
            (election_id,)
        ).fetchone()[0]
        if code_count == 0:
            flash("Cannot open voting — no unused codes available.", "error")
            return redirect(url_for("admin_step_voting", election_id=election_id))

        # Don't open voting until attendance is set. Without it, the Article 6b
        # threshold cannot be calculated and no candidate can be declared elected.
        in_person, _, _ = get_round_counts(election_id, election["current_round"])
        if in_person <= 0:
            flash(
                "Cannot open voting — set the attendance count from the register first "
                "(Phase 2, Step 1).",
                "error",
            )
            return redirect(url_for("admin_step_voting", election_id=election_id))

    # Closing voting only sets voting_open = 0. The chairman explicitly
    # decides when to reveal tallies on the projector via the
    # "Show Results on Projector" button (admin_toggle_results), or by
    # advancing display_phase to 4 for the final summary view.
    if new_state == 0:
        db.execute(
            "UPDATE elections SET voting_open = 0 WHERE id = ?",
            (election_id,)
        )
    else:
        # Opening voting must also bring the projector to phase 3.
        # Voters key off (voting_open AND display_phase >= 3); leaving phase
        # at 1 or 2 would set voting_open without voters seeing the code form.
        db.execute(
            "UPDATE elections SET voting_open = 1, display_phase = 3 WHERE id = ?",
            (election_id,)
        )
    db.commit()

    status = "opened" if new_state else "closed"
    flash(f"Voting {status} for round {election['current_round']}.", "success")
    return redirect(url_for("admin_step_voting", election_id=election_id))


@app.route("/admin/election/<int:election_id>/toggle-results", methods=["POST"])
@admin_required
def admin_toggle_results(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    new_state = 0 if election["show_results"] else 1
    db.execute(
        "UPDATE elections SET show_results = ? WHERE id = ?",
        (new_state, election_id)
    )
    db.commit()

    status = "visible" if new_state else "hidden"
    flash(f"Vote counts are now {status} on the projector display.", "success")
    return redirect(url_for("admin_step_voting", election_id=election_id))


@app.route("/admin/election/<int:election_id>/display-phase", methods=["POST"])
@admin_required
def admin_set_display_phase(election_id):
    """Advance or go back in the projector display phase flow.

    Phase 1 = Welcome (congregation + election details)
    Phase 2 = Election Rules (candidates list + articles 4, 6, 12)
    Phase 3 = Voting (opens voting automatically on first entry)
    Phase 4 = Final Results (chairman-triggered end-of-election summary)
    """
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    direction = request.form.get("direction", "next")
    current_phase = election["display_phase"] or 1
    target = request.form.get("target")

    if target is not None:
        try:
            new_phase = int(target)
        except ValueError:
            return redirect(url_for("admin_election_open", election_id=election_id))
        if new_phase not in (1, 2, 3, 4):
            return redirect(url_for("admin_election_open", election_id=election_id))
    elif direction == "next" and current_phase < 3:
        new_phase = current_phase + 1
    elif direction == "prev" and current_phase > 1:
        new_phase = current_phase - 1
    else:
        return redirect(url_for("admin_election_open", election_id=election_id))

    # Advancing to phase 3 opens voting automatically
    if new_phase == 3 and not election["voting_open"]:
        code_count = db.execute(
            "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 0",
            (election_id,)
        ).fetchone()[0]
        if code_count == 0:
            flash("Cannot proceed to voting — no unused codes available.", "error")
            return redirect(url_for("admin_election_open", election_id=election_id))

        # Attendance must be set before voting can open. Without it the
        # Article 6b threshold cannot be calculated and no candidate can be
        # declared elected.
        in_person, _, _ = get_round_counts(election_id, election["current_round"])
        if in_person <= 0:
            flash(
                "Cannot proceed to voting — set the attendance count from the register first "
                "(Step 1 above).",
                "error",
            )
            return redirect(url_for("admin_election_open", election_id=election_id))

        db.execute(
            "UPDATE elections SET display_phase = ?, voting_open = 1 WHERE id = ?",
            (new_phase, election_id)
        )
        db.commit()
        flash(f"Voting opened for round {election['current_round']}. Projector now showing voting display.", "success")
    else:
        # Going back from phase 3 does NOT close voting — that's a separate action
        if new_phase == 4:
            # Always start Final Results on the clean summary view
            db.execute(
                "UPDATE elections SET display_phase = 4, show_results = 0 WHERE id = ?",
                (election_id,)
            )
        else:
            db.execute(
                "UPDATE elections SET display_phase = ? WHERE id = ?",
                (new_phase, election_id)
            )
        db.commit()
        phase_names = {1: "Welcome", 2: "Election Rules", 3: "Voting", 4: "Final Results"}
        flash(f"Projector display: {phase_names[new_phase]}", "success")

    referrer = request.referrer or ""
    if "/step/welcome" in referrer:
        return redirect(url_for("admin_step_welcome", election_id=election_id))
    if "/step/decide" in referrer:
        return redirect(url_for("admin_step_decide", election_id=election_id))
    if "/step/final" in referrer:
        return redirect(url_for("admin_step_final", election_id=election_id))
    return redirect(url_for("admin_election_open", election_id=election_id))


def _build_manage_view_payload(election_id):
    """Build the context dict used by manage.html and the wizard step 8-11 views."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    current_round = election["current_round"]

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    results = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()

        candidate_results = []
        for cand in candidates:
            digital = db.execute(
                "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                (cand["id"], current_round, election_id)
            ).fetchone()[0]

            paper = db.execute(
                "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                (cand["id"], current_round, election_id)
            ).fetchone()[0]

            # Postal votes only count in round 1
            postal = 0
            if current_round == 1:
                postal = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                    (cand["id"], election_id)
                ).fetchone()[0]

            candidate_results.append({
                "id": cand["id"],
                "name": cand["name"],
                "active": cand["active"],
                "elected": cand["elected"],
                "relieved": cand["relieved"],
                "retiring_office_bearer": cand["retiring_office_bearer"],
                "digital": digital,
                "paper": paper,
                "postal": postal,
                "total": digital + paper + postal
            })

        results.append({
            "office": office,
            "candidates": candidate_results
        })

    # Vote counts
    total_codes = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ?",
        (election_id,)
    ).fetchone()[0]

    # Article 6 threshold calculations: per-round counts
    in_person_participants, paper_ballot_count, digital_ballot_count = get_round_counts(election_id, current_round)
    postal_voter_count = (election["postal_voter_count"] or 0) if current_round == 1 else 0

    # used_codes on the manage view = digital votes this round (not cumulative
    # code burns, which would mix rounds and inflate totals)
    used_codes = digital_ballot_count

    # Postal voters count as participants in round 1 only
    participants = in_person_participants + postal_voter_count

    # Article 6a interpretation: "valid votes cast" is the sum of ticks
    # recorded for candidates IN THIS OFFICE (Reading A, per council
    # decision). Blank ballots/slots and spoilt ballots do not count
    # toward the denominator. See docs/ELECTION_RULES.md for provenance.
    valid_votes_cast = digital_ballot_count + paper_ballot_count + postal_voter_count

    thresholds = {}
    for item in results:
        office = item["office"]
        vacancies = office["vacancies"] or office["max_selections"]
        office_valid_votes = sum(c["total"] for c in item["candidates"])
        item["valid_votes_cast"] = office_valid_votes
        if participants > 0 and vacancies > 0:
            t6a, t6b = calculate_thresholds(vacancies, office_valid_votes, participants)
            for cand in item["candidates"]:
                _, p6a, p6b = check_candidate_elected(cand["total"], t6a, t6b)
                cand["passes_6a"] = p6a
                cand["passes_6b"] = p6b
            resolve_elected_status(item["candidates"], vacancies)
            for cand in item["candidates"]:
                cand["meets_threshold"] = cand["elected"]
            thresholds[office["id"]] = {
                "vacancies": vacancies,
                "valid_votes_cast": office_valid_votes,
                "participants": participants,
                "threshold_6a": t6a,
                "threshold_6b": t6b,
            }

    # Phase-driven flow detection for the manage page (see
    # docs/superpowers/specs/2026-04-21-manage-page-phase-flow-design.md).
    total_ballots = used_codes + paper_ballot_count + postal_voter_count
    display_phase = election["display_phase"] or 1

    # Aggregate elected brothers across rounds (DB-persisted plus live
    # this-round) to decide whether the election is complete.
    offices_for_complete = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()
    election_complete = bool(offices_for_complete)
    elected_summary_by_office = []
    for off in offices_for_complete:
        persisted_names = [
            r["name"] for r in db.execute(
                "SELECT name FROM candidates WHERE office_id = ? "
                "AND elected = 1 AND elected_round IS NOT NULL",
                (off["id"],)
            ).fetchall()
        ]
        names = list(persisted_names)
        # Always merge live-elected names so the per-office summary stays
        # consistent with the row-level ELECTED badges. Phase 5 workflow
        # advancement is gated separately below via voting closure.
        for item in results:
            if item["office"]["id"] == off["id"]:
                for c in item["candidates"]:
                    if c.get("elected") and c["name"] not in names:
                        names.append(c["name"])
                break
        names.sort(key=_surname_sort_key)
        original = (
            off["original_vacancies"]
            if off["original_vacancies"] is not None
            else (off["vacancies"] or off["max_selections"])
        )
        if len(names) < original:
            election_complete = False
        elected_summary_by_office.append({
            "office_name": off["name"],
            "original_vacancies": original,
            "names": names,
            "filled": len(names) >= original,
        })

    # Phase 5 should not auto-activate while ballots are still being cast,
    # even if live thresholds say every vacancy is filled.
    if election["voting_open"] and display_phase != 4:
        election_complete = False

    voting_ever_opened = (
        current_round > 1 or display_phase >= 3 or total_ballots > 0
    )
    # Per-round signal: has THIS round ever been opened? Distinguishes a
    # fresh round (e.g. just-advanced R2 with no ballots yet) from a round
    # that has been opened at least once. Used for the Open vs Re-open
    # button label and the phase-3 "walk projector through" prompt.
    this_round_opened = (
        bool(election["voting_open"])
        or display_phase >= 3
        or total_ballots > 0
    )

    if election_complete or display_phase == 4:
        active_phase = 5
    elif election["voting_open"]:
        active_phase = 3
    elif total_ballots > 0 or election["show_results"]:
        active_phase = 4
    elif (
        in_person_participants > 0
        and display_phase >= 2
        and not voting_ever_opened
    ):
        # Attendance set + projector reached Rules: ready to Open Round.
        active_phase = 3
    elif display_phase in (1, 2):
        active_phase = 2
    else:
        active_phase = 1

    phase_done = {
        1: total_codes > 0,
        2: voting_ever_opened,
        3: not election["voting_open"] and total_ballots > 0,
        4: election_complete,
        5: False,
    }

    phase_summary = {
        1: f"{total_codes} codes generated"
            + (f", {postal_voter_count} postal vote(s) entered" if postal_voter_count > 0 else "")
            if total_codes > 0
            else "Print materials, enter postal votes",
        2: (
            f"{in_person_participants} brothers present"
            if voting_ever_opened
            else "Welcome → Rules → Voting"
        ),
        3: (
            f"Round {current_round} closed - {total_ballots} ballots received"
            if not election["voting_open"] and total_ballots > 0
            else (
                f"Round {current_round} voting open"
                if election["voting_open"]
                else (
                    f"Ready to open round {current_round}"
                    if active_phase == 3
                    else "Voting not yet opened"
                )
            )
        ),
        4: (
            "Counting and decision"
            if active_phase == 4
            else "Activates after voting closes"
        ),
        5: (
            "Election complete"
            if election_complete
            else "Activates when all vacancies are filled"
        ),
    }

    return {
        "election": election,
        "results": results,
        "total_codes": total_codes,
        "used_codes": used_codes,
        "in_person_participants": in_person_participants,
        "participants": participants,
        "paper_ballot_count": paper_ballot_count,
        "postal_voter_count": postal_voter_count,
        "valid_votes_cast": valid_votes_cast,
        "total_ballots": total_ballots,
        "thresholds": thresholds,
        "current_round": current_round,
        "active_phase": active_phase,
        "phase_done": phase_done,
        "phase_summary": phase_summary,
        "election_complete": election_complete,
        "elected_summary_by_office": elected_summary_by_office,
        "voting_ever_opened": voting_ever_opened,
        "this_round_opened": this_round_opened,
        "sidebar_state": compute_sidebar_state(election_id),
    }


@app.route("/admin/election/<int:election_id>")
@admin_required
def admin_election_open(election_id):
    """Dashboard 'Open' click target. Lands on the current default step."""
    state = compute_sidebar_state(election_id)
    if not state:
        abort(404)
    return redirect(url_for(f"admin_step_{state['current_step']}", election_id=election_id))


@app.route("/admin/election/<int:election_id>/manage")
@admin_required
def admin_election_manage(election_id):
    """Legacy URL. Redirect to the wizard step shell."""
    state = compute_sidebar_state(election_id)
    if not state:
        abort(404)
    return redirect(
        url_for(f"admin_step_{state['current_step']}", election_id=election_id),
        code=301,
    )


@app.route("/admin/election/<int:election_id>/participants", methods=["POST"])
@admin_required
def admin_set_participants(election_id):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    current_round = election["current_round"]

    # Each phase of the manage page posts only the field it owns.
    # Phase 2 (Opening) sends 'participants' — paper_ballot_count is unknown
    # until counting time. Phase 4 (Counting) sends 'paper_ballot_count'.
    # Fall back to the existing value when a field isn't in the form.
    existing_participants, existing_paper, _ = get_round_counts(election_id, current_round)

    if "participants" in request.form:
        participants = max(0, int(request.form.get("participants", 0)))
    else:
        participants = existing_participants

    if "paper_ballot_count" in request.form:
        paper_ballot_count = max(0, int(request.form.get("paper_ballot_count", 0)))
    else:
        paper_ballot_count = existing_paper

    set_round_counts(election_id, current_round, participants, paper_ballot_count)
    flash(f"Round {current_round} — Participants: {participants}, Paper ballots: {paper_ballot_count}.", "success")
    # Route wizard callers back to whichever step they posted from; legacy
    # callers (the old manage page) fall through to admin_election_manage.
    referrer = request.referrer or ""
    if "/step/count" in referrer:
        return redirect(url_for("admin_step_count", election_id=election_id))
    elif "/step/attendance" in referrer:
        return redirect(url_for("admin_step_attendance", election_id=election_id))
    else:
        return redirect(url_for("admin_election_open", election_id=election_id))


@app.route("/admin/election/<int:election_id>/postal-votes", methods=["GET", "POST"])
@admin_required
def admin_postal_votes(election_id):
    """Enter aggregate postal vote totals (round 1 only, before voting opens)."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    if request.method == "POST":
        postal_voter_count = int(request.form.get("postal_voter_count", 0))
        if postal_voter_count < 0:
            postal_voter_count = 0

        db.execute(
            "UPDATE elections SET postal_voter_count = ? WHERE id = ?",
            (postal_voter_count, election_id)
        )

        # Save per-candidate postal votes
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = ?", (election_id,)
        ).fetchall()

        for office in offices:
            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ?", (office["id"],)
            ).fetchall()
            for cand in candidates:
                field_name = f"postal_{cand['id']}"
                count = int(request.form.get(field_name, 0))
                if count < 0:
                    count = 0
                db.execute(
                    "DELETE FROM postal_votes WHERE election_id = ? AND candidate_id = ?",
                    (election_id, cand["id"])
                )
                if count > 0:
                    db.execute(
                        "INSERT INTO postal_votes (election_id, candidate_id, count) VALUES (?, ?, ?)",
                        (election_id, cand["id"], count)
                    )

        db.commit()

        # Validation: postal votes per candidate can't exceed postal_voter_count × max_selections
        for office in offices:
            max_sel = office["max_selections"]
            total_postal = sum(
                int(request.form.get(f"postal_{c['id']}", 0))
                for c in db.execute("SELECT * FROM candidates WHERE office_id = ?", (office["id"],)).fetchall()
            )
            if total_postal > postal_voter_count * max_sel:
                flash(
                    f"Warning: {office['name']} has {total_postal} postal votes but only "
                    f"{postal_voter_count} postal voters × {max_sel} selections = {postal_voter_count * max_sel} maximum.",
                    "error"
                )

        flash("Postal vote totals saved.", "success")
        return redirect(url_for("admin_postal_votes", election_id=election_id))

    # GET: show form
    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    office_candidates = []
    for office in offices:
        candidates = db.execute(
            """SELECT c.*, COALESCE(pv.count, 0) as postal_count FROM candidates c
               LEFT JOIN postal_votes pv ON pv.candidate_id = c.id AND pv.election_id = ?
               WHERE c.office_id = ? ORDER BY surname_sort_key(c.name)""",
            (election_id, office["id"])
        ).fetchall()
        office_candidates.append({"office": office, "candidates": candidates})

    return render_template(
        "admin/postal_votes.html",
        election=election,
        office_candidates=office_candidates,
        locked=False
    )


@app.route("/admin/election/<int:election_id>/postal-tally")
@admin_required
def admin_postal_tally(election_id):
    """Client-side tally helper for counting postal vote letters one by one."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    office_candidates = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates c WHERE c.office_id = ? AND c.active = 1 ORDER BY surname_sort_key(c.name)",
            (office["id"],)
        ).fetchall()
        office_candidates.append({"office": office, "candidates": candidates})

    return render_template(
        "admin/postal_tally.html",
        election=election,
        office_candidates=office_candidates,
    )


@app.route("/admin/election/<int:election_id>/paper-votes", methods=["GET", "POST"])
@admin_required
def admin_paper_votes(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    current_round = election["current_round"]

    def _safe_int(s):
        s = (s or "").strip()
        return int(s) if s.isdigit() else 0

    posted_paper = {}   # cand_id -> count (used to repopulate form on error)
    posted_spoilt = {}  # office_id -> spoilt count

    if request.method == "POST":
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = ?", (election_id,)
        ).fetchall()

        # 1. Parse all form values without touching the DB yet.
        per_office_candidates = {}
        for office in offices:
            cands = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? AND active = 1",
                (office["id"],)
            ).fetchall()
            per_office_candidates[office["id"]] = cands
            for cand in cands:
                posted_paper[cand["id"]] = _safe_int(request.form.get(f"paper_{cand['id']}"))
            posted_spoilt[office["id"]] = _safe_int(request.form.get(f"spoilt_{office['id']}"))

        # 2. Validate per-office. Allow under-voting (blanks) but reject
        #    totals that exceed mathematically possible valid votes.
        #    valid_ballots = paper_ballot_count - spoilt_count
        #    max_valid_votes = valid_ballots * max_selections
        _, paper_ballot_count, _ = get_round_counts(election_id, current_round)
        errors = []
        if paper_ballot_count > 0:
            for office in offices:
                cands = per_office_candidates[office["id"]]
                office_total = sum(posted_paper[c["id"]] for c in cands)
                spoilt = posted_spoilt[office["id"]]
                valid_ballots = max(0, paper_ballot_count - spoilt)
                max_valid = valid_ballots * office["max_selections"]
                if office_total > max_valid:
                    errors.append(
                        f"{office['name']}: {office_total} votes entered but max is "
                        f"{max_valid} ({valid_ballots} valid ballots × {office['max_selections']} selections). "
                        f"Recount the paper ballots and try again."
                    )

        if errors:
            for msg in errors:
                flash(msg, "error")
            # Fall through to GET render path; posted_paper / posted_spoilt
            # repopulate the form with the user's entries so they can see
            # exactly what was wrong rather than starting from scratch.
        else:
            # 3. Save - all offices passed validation.
            for office in offices:
                cands = per_office_candidates[office["id"]]
                for cand in cands:
                    db.execute(
                        "DELETE FROM paper_votes WHERE election_id = ? AND round_number = ? AND candidate_id = ?",
                        (election_id, current_round, cand["id"])
                    )
                    count = posted_paper[cand["id"]]
                    if count > 0:
                        db.execute(
                            "INSERT INTO paper_votes (election_id, round_number, candidate_id, count) VALUES (?, ?, ?, ?)",
                            (election_id, current_round, cand["id"], count)
                        )
                # Spoilt is distinct from blank: a spoilt ballot is wrongly
                # filled (Article 7), excluded from valid votes; a blank ballot
                # is a deliberate abstention. Tracking spoilt per-office gives
                # a clearer audit record.
                db.execute(
                    "INSERT INTO office_spoilt_ballots "
                    "(election_id, round_number, office_id, count) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(election_id, round_number, office_id) "
                    "DO UPDATE SET count = excluded.count",
                    (election_id, current_round, office["id"], posted_spoilt[office["id"]]),
                )
            db.commit()
            flash("Paper vote totals saved.", "success")
            return redirect(url_for("admin_step_count", election_id=election_id))

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    office_candidates = []
    for office in offices:
        candidates = db.execute(
            "SELECT c.*, COALESCE(pv.count, 0) as paper_count FROM candidates c "
            "LEFT JOIN paper_votes pv ON pv.candidate_id = c.id AND pv.round_number = ? AND pv.election_id = ? "
            "WHERE c.office_id = ? AND c.active = 1 ORDER BY surname_sort_key(c.name)",
            (current_round, election_id, office["id"])
        ).fetchall()
        # Convert to mutable dicts so we can override paper_count with the
        # user's posted values when re-rendering after a validation failure.
        candidates = [dict(c) for c in candidates]
        if posted_paper:
            for c in candidates:
                if c["id"] in posted_paper:
                    c["paper_count"] = posted_paper[c["id"]]
        spoilt_row = db.execute(
            "SELECT count FROM office_spoilt_ballots "
            "WHERE election_id = ? AND round_number = ? AND office_id = ?",
            (election_id, current_round, office["id"]),
        ).fetchone()
        spoilt_count = spoilt_row["count"] if spoilt_row else 0
        if posted_spoilt and office["id"] in posted_spoilt:
            spoilt_count = posted_spoilt[office["id"]]
        office_candidates.append({
            "office": office,
            "candidates": candidates,
            "spoilt_count": spoilt_count,
        })

    return render_template(
        "admin/paper_votes.html",
        election=election,
        office_candidates=office_candidates
    )


@app.route("/admin/election/<int:election_id>/next-round", methods=["POST"])
@admin_required
def admin_next_round(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    if election["voting_open"]:
        flash("Close voting before starting a new round.", "error")
        return redirect(url_for("admin_step_decide", election_id=election_id))

    current_round = election["current_round"]

    # Get selected candidate IDs to carry forward
    carry_forward_ids = request.form.getlist("carry_forward")
    if not carry_forward_ids:
        flash("Select at least one candidate to carry forward.", "error")
        return redirect(url_for("admin_step_decide", election_id=election_id))

    # Deactivate all candidates, then reactivate only the carried-forward ones
    carry_set = set(int(c) for c in carry_forward_ids)

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ?", (election_id,)
    ).fetchall()

    # Participants/votes for the round being closed — needed to compute
    # how many candidates were elected per office, so we can reduce vacancies.
    in_person_prev, paper_prev, digital_prev = get_round_counts(election_id, current_round)
    postal_prev = (election["postal_voter_count"] or 0) if current_round == 1 else 0
    participants_prev = in_person_prev + postal_prev
    valid_votes_prev = digital_prev + paper_prev + postal_prev

    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1",
            (office["id"],)
        ).fetchall()

        current_vacancies = office["vacancies"] or office["max_selections"]

        # Identify candidates elected in the round being closed.
        # Reading A: valid_votes_cast for the threshold is the per-office
        # sum of candidate ticks (digital + paper + postal). Compute
        # candidate totals first, then derive the threshold from them.
        elected_ids = []
        if participants_prev > 0 and current_vacancies > 0:
            cand_totals = []
            for cand in candidates:
                digital = db.execute(
                    "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], current_round, election_id)
                ).fetchone()[0]
                paper = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], current_round, election_id)
                ).fetchone()[0]
                postal = 0
                if current_round == 1:
                    postal = db.execute(
                        "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                        (cand["id"], election_id)
                    ).fetchone()[0]
                total = digital + paper + postal
                cand_totals.append({"id": cand["id"], "total": total})

            office_valid_votes = sum(c["total"] for c in cand_totals)
            t6a, t6b = calculate_thresholds(current_vacancies, office_valid_votes, participants_prev)

            cand_summary = []
            for ct in cand_totals:
                _, p6a, p6b = check_candidate_elected(ct["total"], t6a, t6b)
                cand_summary.append({
                    "id": ct["id"], "total": ct["total"],
                    "passes_6a": p6a, "passes_6b": p6b, "elected": False,
                })
            resolve_elected_status(cand_summary, current_vacancies)
            elected_ids = [c["id"] for c in cand_summary if c["elected"]]

        elected_this_round = len(elected_ids)

        # Persist the elected brothers so the minutes summary and the final
        # display can see the full cross-round picture even after candidates
        # are deactivated for the next round.
        for cand_id in elected_ids:
            db.execute(
                "UPDATE candidates SET elected = 1, elected_round = ? WHERE id = ?",
                (current_round, cand_id)
            )

        carried_forward_count = sum(1 for c in candidates if c["id"] in carry_set)

        # Deactivate all
        db.execute(
            "UPDATE candidates SET active = 0 WHERE office_id = ?",
            (office["id"],)
        )

        # Remaining vacancies = current vacancies minus those filled this round.
        # max_selections is capped by the number of candidates actually on the next ballot.
        remaining_vacancies = max(current_vacancies - elected_this_round, 0)
        new_max_selections = min(remaining_vacancies, carried_forward_count) if carried_forward_count > 0 else 0

        db.execute(
            "UPDATE offices SET vacancies = ?, max_selections = ? WHERE id = ?",
            (remaining_vacancies, new_max_selections, office["id"])
        )

    # Reactivate carried-forward candidates
    for cand_id in carry_forward_ids:
        db.execute(
            "UPDATE candidates SET active = 1 WHERE id = ?",
            (int(cand_id),)
        )

    # Advance the round
    new_round = current_round + 1
    db.execute(
        "UPDATE elections SET current_round = ?, voting_open = 0, show_results = 0, display_phase = 1 WHERE id = ?",
        (new_round, election_id)
    )

    # Carry over brothers present to the new round (paper ballots reset to 0)
    prev_participants, _, _ = get_round_counts(election_id, current_round)
    set_round_counts(election_id, new_round, prev_participants, 0)

    db.commit()

    flash(f"Round {new_round} started. Vacancies updated based on elected candidates.", "success")
    return redirect(url_for("admin_step_attendance", election_id=election_id))


@app.route("/admin/election/<int:election_id>/voter-log")
@admin_required
def admin_voter_log(election_id):
    """Audit log of every voter-route interaction for diagnostic review.

    Filters on the query string:
      ?result=rejected_already_used  → only rows with that result
      ?code=ABC123                   → only rows for this code (case-insensitive)
      ?limit=200                     → row cap (default 500, max 5000)
    """
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    result_filter = request.args.get("result", "").strip()
    code_filter = request.args.get("code", "").strip().upper()
    try:
        limit = max(1, min(int(request.args.get("limit", 500)), 5000))
    except ValueError:
        limit = 500

    where = ["election_id = ?"]
    params = [election_id]
    if result_filter:
        where.append("result = ?")
        params.append(result_filter)
    if code_filter:
        where.append("UPPER(code) = ?")
        params.append(code_filter)
    sql = (
        "SELECT id, ts, round_number, ip, user_agent, path, code, result, detail "
        "FROM voter_audit_log WHERE " + " AND ".join(where)
        + " ORDER BY id DESC LIMIT ?"
    )
    params.append(limit)
    rows = db.execute(sql, params).fetchall()

    # Distinct result values for the filter dropdown
    distinct_results = [r["result"] for r in db.execute(
        "SELECT DISTINCT result FROM voter_audit_log "
        "WHERE election_id = ? ORDER BY result",
        (election_id,)
    ).fetchall()]

    # Same-code repeats — flag any code that produced more than one
    # 'code_accepted' or 'vote_submitted'
    repeat_offenders = db.execute(
        "SELECT code, COUNT(*) AS n FROM voter_audit_log "
        "WHERE election_id = ? AND code IS NOT NULL "
        "AND result IN ('code_accepted', 'vote_submitted') "
        "GROUP BY code HAVING n > 1 ORDER BY n DESC",
        (election_id,)
    ).fetchall()

    return render_template(
        "admin/voter_log.html",
        election=election,
        rows=rows,
        result_filter=result_filter,
        code_filter=code_filter,
        limit=limit,
        distinct_results=distinct_results,
        repeat_offenders=repeat_offenders,
    )


@app.route("/admin/election/<int:election_id>/soft-reset", methods=["POST"])
@admin_required
def admin_soft_reset(election_id):
    """Soft reset: clear votes and un-burn codes, keep postal votes and setup."""
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    # Validate confirmation
    if request.form.get("confirm_text", "").strip() != "RESET":
        flash("Soft reset cancelled — type RESET to confirm.", "error")
        return redirect(url_for("admin_election_open", election_id=election_id))

    if request.form.get("password") != get_setting("admin_password"):
        flash("Soft reset cancelled — incorrect password.", "error")
        return redirect(url_for("admin_election_open", election_id=election_id))

    current_round = election["current_round"]

    # Clear digital votes for current round
    db.execute("DELETE FROM votes WHERE election_id = ? AND round_number = ?",
               (election_id, current_round))

    # Clear paper votes for current round
    db.execute("DELETE FROM paper_votes WHERE election_id = ? AND round_number = ?",
               (election_id, current_round))

    # Un-burn all codes (so they can be reused)
    db.execute("UPDATE codes SET used = 0 WHERE election_id = ?", (election_id,))

    # Clear round counts (participants, paper ballot count)
    db.execute("DELETE FROM round_counts WHERE election_id = ? AND round_number = ?",
               (election_id, current_round))

    # Close voting, hide results, reset display phase
    db.execute("UPDATE elections SET voting_open = 0, show_results = 0, display_phase = 1 WHERE id = ?",
               (election_id,))

    # Cancel any active count session for the current round
    db.execute(
        "UPDATE count_sessions SET status = 'cancelled', cancelled_at = ? "
        "WHERE election_id = ? AND round_no = ? AND status = 'active'",
        (_now_iso(), election_id, current_round)
    )

    db.commit()
    flash(f"Soft reset complete. Round {current_round} votes cleared, codes restored. Postal votes and setup unchanged.", "success")
    return redirect(url_for("admin_step_attendance", election_id=election_id))


@app.route("/admin/election/<int:election_id>/hard-reset", methods=["POST"])
@admin_required
def admin_hard_reset(election_id):
    """Hard reset: clear everything and return to election setup."""
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    # Validate confirmation
    if request.form.get("confirm_text", "").strip() != "HARD RESET":
        flash("Hard reset cancelled — type HARD RESET to confirm.", "error")
        return redirect(url_for("admin_election_open", election_id=election_id))

    if request.form.get("password") != get_setting("admin_password"):
        flash("Hard reset cancelled — incorrect password.", "error")
        return redirect(url_for("admin_election_open", election_id=election_id))

    # Clear all votes across all rounds
    db.execute("DELETE FROM votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM paper_votes WHERE election_id = ?", (election_id,))

    # Clear postal votes
    db.execute("DELETE FROM postal_votes WHERE election_id = ?", (election_id,))

    # Delete all codes
    db.execute("DELETE FROM codes WHERE election_id = ?", (election_id,))

    # Clear all round counts
    db.execute("DELETE FROM round_counts WHERE election_id = ?", (election_id,))

    # Reset election to round 1
    db.execute(
        "UPDATE elections SET current_round = 1, voting_open = 0, show_results = 0, postal_voter_count = 0, display_phase = 1 WHERE id = ?",
        (election_id,)
    )

    # Reactivate all candidates
    offices = db.execute("SELECT id FROM offices WHERE election_id = ?", (election_id,)).fetchall()
    for office in offices:
        db.execute(
            "UPDATE candidates SET active = 1, elected = 0, elected_round = NULL, relieved = 0 WHERE office_id = ?",
            (office["id"],)
        )

    # Wipe all count session data for this election
    db.execute(
        "DELETE FROM count_session_results WHERE session_id IN "
        "(SELECT id FROM count_sessions WHERE election_id = ?)",
        (election_id,)
    )
    db.execute(
        "DELETE FROM count_session_tallies WHERE session_id IN "
        "(SELECT id FROM count_sessions WHERE election_id = ?)",
        (election_id,)
    )
    db.execute(
        "DELETE FROM count_session_helpers WHERE session_id IN "
        "(SELECT id FROM count_sessions WHERE election_id = ?)",
        (election_id,)
    )
    db.execute(
        "DELETE FROM count_sessions WHERE election_id = ?",
        (election_id,)
    )

    db.commit()
    flash("Hard reset complete. All votes, codes, and postal votes cleared. Candidates reactivated. Generate new codes before voting.", "success")
    return redirect(url_for("admin_step_offices", election_id=election_id))


@app.route("/admin/election/<int:election_id>/delete", methods=["POST"])
@admin_required
def admin_election_delete(election_id):
    """Delete an election and all its dependent data."""
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    confirm_name = request.form.get("confirm_name", "").strip()
    if confirm_name != election["name"]:
        flash("Deletion cancelled — election name does not match.", "error")
        return redirect(url_for("admin_dashboard"))

    # Cascade delete in FK-safe order
    db.execute("DELETE FROM votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM paper_votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM postal_votes WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM codes WHERE election_id = ?", (election_id,))
    db.execute(
        "DELETE FROM count_session_results WHERE session_id IN "
        "(SELECT id FROM count_sessions WHERE election_id = ?)",
        (election_id,)
    )
    db.execute(
        "DELETE FROM count_session_tallies WHERE session_id IN "
        "(SELECT id FROM count_sessions WHERE election_id = ?)",
        (election_id,)
    )
    db.execute(
        "DELETE FROM count_session_helpers WHERE session_id IN "
        "(SELECT id FROM count_sessions WHERE election_id = ?)",
        (election_id,)
    )
    db.execute("DELETE FROM count_sessions WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM office_spoilt_ballots WHERE election_id = ?", (election_id,))
    db.execute(
        "DELETE FROM candidates WHERE office_id IN (SELECT id FROM offices WHERE election_id = ?)",
        (election_id,)
    )
    db.execute("DELETE FROM offices WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM round_counts WHERE election_id = ?", (election_id,))
    db.execute("DELETE FROM elections WHERE id = ?", (election_id,))
    db.commit()

    flash(f"Election \"{election['name']}\" deleted.", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Member import routes
# ---------------------------------------------------------------------------

MEMBER_CSV_HEADERS = {"Last name", "First name"}  # Minimum required headers


@app.route("/admin/wipe-database", methods=["POST"])
@admin_required
def admin_wipe_database():
    """Delete the entire database and restart fresh."""
    if request.form.get("confirm_text", "").strip() != "DELETE EVERYTHING":
        flash("Wipe cancelled — type DELETE EVERYTHING to confirm.", "error")
        return redirect(url_for("admin_dashboard"))

    if request.form.get("password") != get_setting("admin_password"):
        flash("Wipe cancelled — incorrect password.", "error")
        return redirect(url_for("admin_dashboard"))

    # Close the DB connection, delete the file, and redirect to trigger fresh init
    db = get_db()
    db.close()
    g.pop("db", None)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    # Also remove the secret key so a new one is generated
    secret_key_file = os.path.join(DATA_DIR, ".secret_key")
    if os.path.exists(secret_key_file):
        os.remove(secret_key_file)

    flash("Database wiped. Please restart the app.", "success")
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# Sample-data helpers (used by the "Load sample candidates" button)
# ---------------------------------------------------------------------------


def _load_member_names(db):
    """Load member names with priority: app DB > external > empty list."""
    try:
        rows = db.execute("SELECT first_name, last_name FROM members").fetchall()
        names = [
            f"{r['first_name'].strip()} {r['last_name'].strip()}"
            for r in rows if r["first_name"] and r["last_name"]
        ]
        if names:
            return names
    except Exception:
        pass
    names = load_member_names_from_external(BASE_DIR)
    if names:
        return names
    return []


@app.route("/admin/election/<int:election_id>/load-sample-offices", methods=["POST"])
@admin_required
def admin_load_sample_offices(election_id):
    """One-click setup helper: add a typical FRC slate (Elder + Deacon offices
    with sample candidate names drawn from the demo names pool).

    Refuses if offices already exist for this election, to avoid duplicating
    or conflicting with what the chairman has already entered.
    """
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    existing = db.execute(
        "SELECT COUNT(*) FROM offices WHERE election_id = ?", (election_id,)
    ).fetchone()[0]
    if existing > 0:
        flash(
            "Sample candidates not loaded — this election already has offices. "
            "Remove them first if you want to start over.",
            "error",
        )
        return redirect(url_for("admin_step_offices", election_id=election_id))

    member_names = _load_member_names(db)
    candidate_names = generate_demo_names(count=10, member_names=member_names)

    # Elder office — 3 vacancies, 6 candidates, max_selections = 3
    cursor = db.execute(
        "INSERT INTO offices (election_id, name, max_selections, vacancies, original_vacancies, sort_order) "
        "VALUES (?, 'Elder', 3, 3, 3, 1)",
        (election_id,),
    )
    elder_office_id = cursor.lastrowid
    for i, name in enumerate(candidate_names[:6]):
        db.execute(
            "INSERT INTO candidates (office_id, name, sort_order) VALUES (?, ?, ?)",
            (elder_office_id, name, i + 1),
        )

    # Deacon office — 2 vacancies, 4 candidates, max_selections = 2
    cursor = db.execute(
        "INSERT INTO offices (election_id, name, max_selections, vacancies, original_vacancies, sort_order) "
        "VALUES (?, 'Deacon', 2, 2, 2, 2)",
        (election_id,),
    )
    deacon_office_id = cursor.lastrowid
    for i, name in enumerate(candidate_names[6:10]):
        db.execute(
            "INSERT INTO candidates (office_id, name, sort_order) VALUES (?, ?, ?)",
            (deacon_office_id, name, i + 1),
        )

    db.commit()

    flash(
        "Sample offices loaded: Elder (3 vacancies, 6 candidates) and Deacon (2 vacancies, 4 candidates).",
        "success",
    )
    return redirect(url_for("admin_step_offices", election_id=election_id))


@app.route("/admin/members", methods=["GET", "POST"])
@admin_required
def admin_members():
    db = get_db()

    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Please select a CSV file.", "error")
            return redirect(url_for("admin_members"))

        try:
            # Read with utf-8-sig to handle BOM
            stream = io.TextIOWrapper(file.stream, encoding="utf-8-sig")
            reader = csv.DictReader(stream)

            # Validate headers
            if not reader.fieldnames or not MEMBER_CSV_HEADERS.issubset(set(reader.fieldnames)):
                flash("Invalid CSV format. File must contain at least 'Last name' and 'First name' columns.", "error")
                return redirect(url_for("admin_members"))

            rows = list(reader)
            if not rows:
                flash("CSV file contains no data rows.", "error")
                return redirect(url_for("admin_members"))

            # Full re-import: delete all existing, insert new
            db.execute("DELETE FROM members")
            for row in rows:
                db.execute(
                    """INSERT INTO members (last_name, first_name, age, address, email, mobile_phone, membership_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("Last name", "").strip(),
                        row.get("First name", "").strip(),
                        row.get("Age", "").strip(),
                        row.get("Full address", "").strip(),
                        row.get("Email", "").strip(),
                        row.get("Mobile phone", "").strip(),
                        row.get("Membership status", "").strip(),
                    )
                )
            db.commit()
            flash(f"Imported {len(rows)} members.", "success")

        except Exception as e:
            flash(f"Error reading CSV: {e}", "error")

        return redirect(url_for("admin_members"))

    # GET: show current members
    members = db.execute(
        "SELECT * FROM members ORDER BY surname_sort_key(last_name || ' ' || first_name)"
    ).fetchall()
    member_count = len(members)

    return render_template("admin/members.html", members=members, member_count=member_count)


@app.route("/admin/members/attendance-pdf")
@admin_required
def admin_attendance_pdf():
    """Generate a printable attendance register PDF from the member list."""
    db = get_db()
    members = db.execute(
        "SELECT * FROM members ORDER BY last_name, first_name"
    ).fetchall()

    if not members:
        flash("No members imported. Upload a CSV first.", "error")
        return redirect(url_for("admin_members"))

    cong_name = get_setting("congregation_name", "Free Reformed Church")

    # Find the most recent election for date/name context
    election = db.execute(
        "SELECT * FROM elections ORDER BY id DESC LIMIT 1"
    ).fetchone()
    election_name = election["name"] if election else None
    election_date = election["election_date"] if election else None

    buf = generate_attendance_register_pdf(
        members=[dict(m) for m in members],
        congregation_name=cong_name,
        election_name=election_name,
        election_date=election_date,
    )

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="attendance_register.pdf"
    )


@app.route("/admin/members/clear", methods=["POST"])
@admin_required
def admin_members_clear():
    db = get_db()
    db.execute("DELETE FROM members")
    db.commit()
    flash("All members cleared.", "success")
    return redirect(url_for("admin_members"))


@app.route("/api/members/search")
@admin_required
def api_members_search():
    """Search members by name for the autocomplete widget."""
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])

    db = get_db()
    results = db.execute(
        """SELECT id, first_name, last_name FROM members
           WHERE lower(first_name || ' ' || last_name) LIKE ?
              OR lower(last_name || ', ' || first_name) LIKE ?
              OR lower(last_name || ' ' || first_name) LIKE ?
           ORDER BY last_name, first_name
           LIMIT 10""",
        (f"%{q}%", f"%{q}%", f"%{q}%")
    ).fetchall()

    return jsonify([
        {"id": row["id"], "name": f"{row['first_name']} {row['last_name']}"}
        for row in results
    ])


# ---------------------------------------------------------------------------
# Voter routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
@app.route("/v/<prefill_code>", methods=["GET"])
def voter_enter_code(prefill_code=None):
    db = get_db()
    # Gate on both voting_open and display_phase: the chairman drives the
    # projector through phases 1 (Welcome), 2 (Rules), 3 (Voting). Even if
    # voting_open is set, voters should only see the form when the projector
    # is actually on the voting phase.
    election = db.execute(
        "SELECT * FROM elections "
        "WHERE voting_open = 1 AND display_phase >= 3 "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # QR scan with code: validate immediately and skip to ballot
    if prefill_code:
        code = prefill_code.strip().upper()
        eid = election["id"] if election else None
        rnd = election["current_round"] if election else None
        if not election:
            flash("Voting is not currently open.", "error")
            log_voter_audit(eid, code, "rejected_voting_closed",
                            "QR scan while voting closed", round_number=rnd)
        elif len(code) != CODE_LENGTH:
            flash("Invalid code.", "error")
            log_voter_audit(eid, code, "rejected_invalid_format",
                            f"QR code length {len(code)}", round_number=rnd)
        else:
            code_h = hash_code(code)
            code_row = db.execute(
                "SELECT * FROM codes WHERE code_hash = ? AND election_id = ?",
                (code_h, election["id"])
            ).fetchone()

            if not code_row:
                flash("Invalid code. Please check and try again.", "error")
                log_voter_audit(eid, code, "rejected_unknown_code",
                                "QR scan code not in DB", round_number=rnd)
            elif code_row["used"]:
                flash("This code has already been used.", "error")
                log_voter_audit(eid, code, "rejected_already_used",
                                "QR scan code already burned", round_number=rnd)
            else:
                session["code_hash"] = code_h
                session["election_id"] = election["id"]
                session["used_code"] = code
                session["_clear_stale_flashes"] = True
                log_voter_audit(eid, code, "code_accepted",
                                "QR scan accepted", round_number=rnd)
                return redirect(url_for("voter_ballot"))

        # Validation failed — fall through to enter_code page (no prefill)
        prefill_code = None

    resp = make_response(render_template(
        "voter/enter_code.html",
        election=election,
        prefill_code=prefill_code,
        wifi_ssid=get_setting("wifi_ssid", ""),
    ))
    return no_cache(resp)


@app.route("/vote", methods=["GET", "POST"])
def voter_validate_code():
    if request.method == "GET":
        return redirect(url_for("voter_enter_code"))

    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE voting_open = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()

    code_raw = request.form.get("code", "")
    code = code_raw.strip().upper()
    eid = election["id"] if election else None
    rnd = election["current_round"] if election else None

    if not election:
        flash("Voting is not currently open.", "error")
        log_voter_audit(None, code or None, "rejected_voting_closed",
                        "Form submit while voting closed")
        return redirect(url_for("voter_enter_code"))

    if not code or len(code) != CODE_LENGTH:
        flash("Please enter a valid 6-character code.", "error")
        log_voter_audit(eid, code or None, "rejected_invalid_format",
                        f"Form submit length {len(code)}", round_number=rnd)
        return redirect(url_for("voter_enter_code"))

    code_h = hash_code(code)
    code_row = db.execute(
        "SELECT * FROM codes WHERE code_hash = ? AND election_id = ?",
        (code_h, election["id"])
    ).fetchone()

    if not code_row:
        flash("Invalid code. Please check and try again.", "error")
        log_voter_audit(eid, code, "rejected_unknown_code",
                        "Form submit code not in DB", round_number=rnd)
        return redirect(url_for("voter_enter_code"))

    if code_row["used"]:
        flash("This code has already been used.", "error")
        log_voter_audit(eid, code, "rejected_already_used",
                        "Form submit code already burned", round_number=rnd)
        return redirect(url_for("voter_enter_code"))

    session["code_hash"] = code_h
    session["election_id"] = election["id"]
    session["used_code"] = code
    log_voter_audit(eid, code, "code_accepted", "Form submit accepted",
                    round_number=rnd)
    return redirect(url_for("voter_ballot"))


@app.route("/ballot", methods=["GET"])
def voter_ballot():
    # Clear stale flash messages from earlier QR scans (e.g. "voting not open").
    # The flag is set when code validation succeeds, signalling a fresh ballot load.
    if session.pop("_clear_stale_flashes", False):
        session.pop("_flashes", None)

    code_h = session.get("code_hash")
    election_id = session.get("election_id")

    if not code_h or not election_id:
        return redirect(url_for("voter_enter_code"))

    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ? AND voting_open = 1",
        (election_id,)
    ).fetchone()

    if not election:
        session.pop("code_hash", None)
        session.pop("election_id", None)
        flash("Voting is no longer open.", "error")
        return redirect(url_for("voter_enter_code"))

    # Double check code is still valid.
    # Demo pre-burned codes are already used=1, so skip that constraint.
    if session.get("demo_pre_burned"):
        code_row = db.execute(
            "SELECT * FROM codes WHERE code_hash = ?",
            (code_h,)
        ).fetchone()
    else:
        code_row = db.execute(
            "SELECT * FROM codes WHERE code_hash = ? AND used = 0",
            (code_h,)
        ).fetchone()
    if not code_row:
        session.pop("code_hash", None)
        session.pop("election_id", None)
        flash("This code is no longer valid.", "error")
        return redirect(url_for("voter_enter_code"))

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    office_candidates = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        office_candidates.append({
            "office": office,
            "candidates": candidates
        })

    resp = make_response(render_template(
        "voter/ballot.html",
        election=election,
        office_candidates=office_candidates,
        voter_code=code_row["plaintext"] if code_row["plaintext"] else None,
    ))
    return no_cache(resp)


@app.route("/submit", methods=["POST"])
def voter_submit():
    code_h = session.get("code_hash")
    election_id = session.get("election_id")

    if not code_h or not election_id:
        return redirect(url_for("voter_enter_code"))

    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ? AND voting_open = 1",
        (election_id,)
    ).fetchone()

    if not election:
        session.pop("code_hash", None)
        session.pop("election_id", None)
        flash("Voting is no longer open.", "error")
        return redirect(url_for("voter_enter_code"))

    # Server-side validation: max selections per office
    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    selected_candidates = []
    confirm_partial = request.form.get("confirm_partial")
    under_selected = []

    for office in offices:
        field_name = f"office_{office['id']}"
        selections = request.form.getlist(field_name)
        if len(selections) > office["max_selections"]:
            flash(f"Too many selections for {office['name']}. Maximum is {office['max_selections']}.", "error")
            return redirect(url_for("voter_ballot"))

        # Only warn about under-selection if there are more candidates than selected
        active_count = db.execute(
            "SELECT COUNT(*) FROM candidates WHERE office_id = ? AND active = 1",
            (office["id"],)
        ).fetchone()[0]
        if active_count > 0 and len(selections) < office["max_selections"] and len(selections) < active_count:
            under_selected.append(
                f"{office['name']}: you selected {len(selections)} of {office['max_selections']}"
            )

        # Validate that selected candidates exist, are active, and belong to this office
        for cand_id_str in selections:
            cand = db.execute(
                "SELECT * FROM candidates WHERE id = ? AND office_id = ? AND active = 1",
                (int(cand_id_str), office["id"])
            ).fetchone()
            if not cand:
                flash("Invalid selection.", "error")
                return redirect(url_for("voter_ballot"))
            selected_candidates.append(int(cand_id_str))

    # Warn if fewer than max selected — re-render ballot with selections preserved
    if under_selected and not confirm_partial:
        # Rebuild the ballot data for re-rendering
        office_candidates = []
        selected_set = set(str(c) for c in selected_candidates)
        for office in offices:
            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()
            office_candidates.append({
                "office": office,
                "candidates": candidates
            })

        warning_msg = "You have not used all your votes. " + ". ".join(under_selected) + ". Press 'Confirm and Cast Vote' if this is intentional."
        resp = make_response(render_template(
            "voter/ballot.html",
            election=election,
            office_candidates=office_candidates,
            partial_warning=True,
            warning_message=warning_msg,
            selected_ids=selected_set
        ))
        return no_cache(resp)

    code_for_log = session.get("used_code")

    # Atomic transaction: burn code + record votes
    try:
        result = db.execute(
            "UPDATE codes SET used = 1 WHERE code_hash = ? AND used = 0",
            (code_h,)
        )
        if result.rowcount == 0:
            # Code was already used (race condition)
            db.rollback()
            session.pop("code_hash", None)
            session.pop("election_id", None)
            session.pop("used_code", None)
            flash("This code has already been used.", "error")
            log_voter_audit(
                election_id, code_for_log, "rejected_already_used_at_submit",
                "Submit reached burn step but code was already used (race)",
                round_number=election["current_round"]
            )
            return redirect(url_for("voter_enter_code"))

        # Record votes — NO link to the code
        for cand_id in selected_candidates:
            db.execute(
                "INSERT INTO votes (election_id, round_number, candidate_id, source) VALUES (?, ?, ?, 'digital')",
                (election_id, election["current_round"], cand_id)
            )

        # Increment digital ballot counter
        increment_digital_ballot(election_id, election["current_round"])

        db.commit()
        log_voter_audit(
            election_id, code_for_log, "vote_submitted",
            f"Recorded {len(selected_candidates)} candidate selection(s)",
            round_number=election["current_round"]
        )
    except Exception as ex:
        db.rollback()
        flash("An error occurred. Please try again.", "error")
        log_voter_audit(
            election_id, code_for_log, "submit_error",
            f"Exception during burn/insert: {type(ex).__name__}",
            round_number=election["current_round"]
        )
        return redirect(url_for("voter_enter_code"))

    # Clear code_hash, but keep election_id and used_code in session so
    # /confirmation and /count/join can render the paper-count assist button.
    # The code is already burned, so used_code is no longer sensitive.
    session.pop("code_hash", None)

    return redirect(url_for("voter_confirmation"))


@app.route("/confirmation")
def voter_confirmation():
    # Keep used_code in session so the paper-count assist button can read it.
    # The code is already burned, so this is not sensitive.
    used_code = session.get("used_code")
    election_id = session.get("election_id")
    show_assist = False
    if used_code and election_id:
        db = get_db()
        election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
        if election and _paper_count_active_for_round(db, election):
            show_assist = True
    resp = make_response(render_template(
        "voter/confirmation.html",
        used_code=used_code,
        show_assist=show_assist,
    ))
    return no_cache(resp)


# ---------------------------------------------------------------------------
# Paper ballot co-counting
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _short_id_from_code(code):
    return (code or "")[-6:].upper()


def _compute_consensus_for_candidate(active_counts):
    """Return a dict describing per-candidate consensus state."""
    if not active_counts:
        return {"status": "no_data"}
    if len(active_counts) < 3:
        return {"status": "insufficient", "values": active_counts}
    if all(c == active_counts[0] for c in active_counts):
        return {"status": "ok", "value": active_counts[0]}
    return {"status": "mismatch", "values": active_counts}


def _helper_is_active(db, helper_id):
    """Active = has at least one tally row (any +1 or -1 was registered)."""
    row = db.execute(
        "SELECT 1 FROM count_session_tallies WHERE helper_id = ? LIMIT 1",
        (helper_id,)
    ).fetchone()
    return row is not None


def _flag_out_of_sync(per_helper_counts, candidate_modes):
    """Return short_ids whose counts differ from the per-candidate mode on
    >30% of candidates with a defined mode.
    """
    flagged = set()
    candidates_with_mode = [c for c, m in candidate_modes.items() if m is not None]
    if not candidates_with_mode:
        return flagged
    for sid, counts in per_helper_counts.items():
        diffs = sum(
            1 for c in candidates_with_mode if counts.get(c, 0) != candidate_modes[c]
        )
        if diffs / len(candidates_with_mode) > 0.30:
            flagged.add(sid)
    return flagged


def _get_or_create_count_session(db, election_id, round_no):
    """Find or create the count_sessions row for this (election, round).

    Returns the row.
    """
    row = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if row:
        return row
    db.execute(
        "INSERT OR IGNORE INTO count_sessions "
        "(election_id, round_no, status, started_at) "
        "VALUES (?, ?, 'active', ?)",
        (election_id, round_no, _now_iso())
    )
    db.commit()
    return db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()


PAPER_COUNT_MAX_HELPERS = 20


def _paper_count_active_for_round(db, election):
    """True if paper count is enabled, the current round's session has not
    been persisted or cancelled, and the helper cap has not been hit.
    The button is shown regardless of voting state so voters who finish early
    can opt in immediately.
    """
    if not election["paper_count_enabled"]:
        return False
    sess = db.execute(
        "SELECT id, status FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election["id"], election["current_round"])
    ).fetchone()
    if sess and sess["status"] in ("persisted", "cancelled"):
        return False
    if sess:
        helper_count = db.execute(
            "SELECT COUNT(*) AS cnt FROM count_session_helpers "
            "WHERE session_id = ? AND disregarded_at IS NULL",
            (sess["id"],)
        ).fetchone()["cnt"]
        if helper_count >= PAPER_COUNT_MAX_HELPERS:
            return False
    return True


@app.route("/count/join", methods=["POST"])
def count_join():
    code = session.get("used_code")
    election_id = session.get("election_id")
    if not code or not election_id:
        return ("Not eligible", 403)
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        return ("Election not found", 404)
    if not election["paper_count_enabled"]:
        return ("Paper count not enabled", 400)

    sess = _get_or_create_count_session(db, election_id, election["current_round"])
    if sess["status"] != "active":
        return ("Session is not active", 400)

    # Helper row is created lazily on first tap (see count_tap).
    return redirect(url_for("count_helper_page", session_id=sess["id"]))


@app.route("/count/<int:session_id>")
def count_helper_page(session_id):
    code = session.get("used_code")
    if not code:
        return redirect(url_for("voter_enter_code"))
    db = get_db()
    sess = db.execute("SELECT * FROM count_sessions WHERE id = ?", (session_id,)).fetchone()
    if not sess:
        abort(404)
    helper = db.execute(
        "SELECT * FROM count_session_helpers WHERE session_id = ? AND voter_code = ?",
        (session_id, code)
    ).fetchone()
    # If they haven't tapped yet, render a preview helper - the row is created
    # lazily on first tap (see count_tap). But first check the cap so a 31st
    # arriver gets a clear "team is full" page instead of a silently broken
    # grid (the visibility gate hides the button, but there's a small race).
    if helper is None:
        helper_count = db.execute(
            "SELECT COUNT(*) AS cnt FROM count_session_helpers "
            "WHERE session_id = ? AND disregarded_at IS NULL",
            (session_id,)
        ).fetchone()["cnt"]
        if helper_count >= PAPER_COUNT_MAX_HELPERS:
            return render_template("voter/count_helper.html", state="full",
                                   helper={"short_id": ""}, sess=sess)
        helper = {"short_id": _short_id_from_code(code), "marked_done_at": None}

    # Determine end-state to render
    if sess["status"] == "persisted":
        return render_template("voter/count_helper.html",
                               state="thanks", helper=helper, sess=sess)
    if sess["status"] == "cancelled":
        return render_template("voter/count_helper.html",
                               state="cancelled", helper=helper, sess=sess)
    if helper["marked_done_at"]:
        return render_template("voter/count_helper.html",
                               state="thanks", helper=helper, sess=sess)

    # Active state: build candidate list grouped by office
    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (sess["election_id"],)
    ).fetchall()
    candidates_by_office = {}
    for office in offices:
        candidates_by_office[office["id"]] = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
    return render_template(
        "voter/count_helper.html",
        state="active",
        helper=helper,
        sess=sess,
        offices=offices,
        candidates_by_office=candidates_by_office
    )


def _resolve_helper(db, session_id, voter_code):
    """Return (sess_row, helper_row) or (None, None) if not a member."""
    sess = db.execute(
        "SELECT * FROM count_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not sess:
        return None, None
    helper = db.execute(
        "SELECT * FROM count_session_helpers WHERE session_id = ? AND voter_code = ?",
        (session_id, voter_code)
    ).fetchone()
    return sess, helper


@app.route("/count/<int:session_id>/tap", methods=["POST"])
@csrf.exempt
def count_tap(session_id):
    code = session.get("used_code")
    if not code:
        return ("Not eligible", 403)
    db = get_db()
    sess, helper = _resolve_helper(db, session_id, code)
    if sess is None:
        return ("Session not found", 404)
    if sess["status"] != "active":
        return ("Session not active", 403)
    if helper is None:
        # Lazy creation on first tap; the cap is enforced here.
        helper_count = db.execute(
            "SELECT COUNT(*) AS cnt FROM count_session_helpers "
            "WHERE session_id = ? AND disregarded_at IS NULL",
            (session_id,)
        ).fetchone()["cnt"]
        if helper_count >= PAPER_COUNT_MAX_HELPERS:
            return ("Counting team is full", 403)
        now = _now_iso()
        db.execute(
            "INSERT INTO count_session_helpers "
            "(session_id, voter_code, short_id, joined_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, code, _short_id_from_code(code), now, now)
        )
        db.commit()
        log_voter_audit(
            sess["election_id"], code, "paper_count_helper_joined",
            detail=_short_id_from_code(code),
            round_number=sess["round_no"]
        )
        helper = db.execute(
            "SELECT * FROM count_session_helpers WHERE session_id = ? AND voter_code = ?",
            (session_id, code)
        ).fetchone()
    if helper["marked_done_at"]:
        return ("Helper already marked done", 403)

    body = request.get_json(silent=True) or {}
    try:
        candidate_id = int(body.get("candidate_id"))
        delta = int(body.get("delta"))
    except (TypeError, ValueError):
        return ("Bad payload", 400)
    if delta not in (1, -1):
        return ("Bad delta", 400)

    cand = db.execute(
        "SELECT c.id FROM candidates c JOIN offices o ON c.office_id = o.id "
        "WHERE c.id = ? AND o.election_id = ?",
        (candidate_id, sess["election_id"])
    ).fetchone()
    if not cand:
        return ("Bad candidate", 400)

    db.execute(
        "INSERT OR IGNORE INTO count_session_tallies (session_id, helper_id, candidate_id, count) "
        "VALUES (?, ?, ?, 0)",
        (session_id, helper["id"], candidate_id)
    )
    if delta == 1:
        db.execute(
            "UPDATE count_session_tallies SET count = count + 1 "
            "WHERE session_id = ? AND helper_id = ? AND candidate_id = ?",
            (session_id, helper["id"], candidate_id)
        )
    else:
        db.execute(
            "UPDATE count_session_tallies SET count = MAX(count - 1, 0) "
            "WHERE session_id = ? AND helper_id = ? AND candidate_id = ?",
            (session_id, helper["id"], candidate_id)
        )
    new_count = db.execute(
        "SELECT count FROM count_session_tallies "
        "WHERE session_id = ? AND helper_id = ? AND candidate_id = ?",
        (session_id, helper["id"], candidate_id)
    ).fetchone()["count"]
    db.execute(
        "UPDATE count_session_helpers SET last_seen_at = ? WHERE id = ?",
        (_now_iso(), helper["id"])
    )
    db.commit()
    return jsonify({"count": new_count})


@app.route("/count/<int:session_id>/done", methods=["POST"])
@csrf.exempt
def count_done(session_id):
    code = session.get("used_code")
    if not code:
        return ("Not eligible", 403)
    db = get_db()
    sess, helper = _resolve_helper(db, session_id, code)
    if sess is None:
        return ("Session not found", 404)
    if helper is None:
        # They never tapped; nothing to mark done.
        return ("", 200)
    if sess["status"] != "active":
        return ("Session not active", 403)
    if helper["marked_done_at"]:
        return ("Already done", 200)
    now = _now_iso()
    db.execute(
        "UPDATE count_session_helpers SET marked_done_at = ?, last_seen_at = ? WHERE id = ?",
        (now, now, helper["id"])
    )
    db.commit()
    return ("", 200)


@app.route("/count/<int:session_id>/heartbeat", methods=["GET"])
@csrf.exempt
def count_heartbeat(session_id):
    code = session.get("used_code")
    if not code:
        return jsonify({"error": "not eligible"}), 403
    db = get_db()
    sess, helper = _resolve_helper(db, session_id, code)
    if sess is None:
        return jsonify({"error": "session not found"}), 404
    if helper is None:
        # Voter is on the page but hasn't tapped yet; nothing to update.
        return jsonify({
            "session_status": sess["status"],
            "helper_done": False,
        })
    db.execute(
        "UPDATE count_session_helpers SET last_seen_at = ? WHERE id = ?",
        (_now_iso(), helper["id"])
    )
    db.commit()
    return jsonify({
        "session_status": sess["status"],
        "helper_done": bool(helper["marked_done_at"]),
    })


# ---------------------------------------------------------------------------
# Admin paper count dashboard (Task 8 skeleton; endpoints stubbed)
# ---------------------------------------------------------------------------

@app.route("/admin/election/<int:election_id>/count/<int:round_no>")
@admin_required
def admin_count_dashboard(election_id, round_no):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    if not election["paper_count_enabled"]:
        abort(404)
    sess = _get_or_create_count_session(db, election_id, round_no)
    return render_template(
        "admin/count.html",
        election=election,
        sess=sess,
        round_no=round_no
    )


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/state")
@admin_required
def admin_count_state(election_id, round_no):
    db = get_db()
    sess = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if sess is None:
        return jsonify({
            "helpers": [],
            "candidates": [],
            "helper_count": 0,
            "done_count": 0,
            "session_status": "none",
        })

    helpers = db.execute(
        "SELECT * FROM count_session_helpers WHERE session_id = ? ORDER BY joined_at",
        (sess["id"],)
    ).fetchall()
    helper_rows = []
    active_helper_ids = []
    for h in helpers:
        is_active = _helper_is_active(db, h["id"])
        helper_rows.append({
            "id": h["id"],
            "short_id": h["short_id"],
            "active": is_active,
            "disregarded": h["disregarded_at"] is not None,
            "done": h["marked_done_at"] is not None,
            "last_seen_at": h["last_seen_at"],
        })
        if is_active and h["disregarded_at"] is None:
            active_helper_ids.append(h["id"])

    counts_rows = db.execute(
        "SELECT helper_id, candidate_id, count FROM count_session_tallies WHERE session_id = ?",
        (sess["id"],)
    ).fetchall()
    counts_by_hc = {}
    for r in counts_rows:
        counts_by_hc.setdefault(r["helper_id"], {})[r["candidate_id"]] = r["count"]

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()
    candidate_states = []
    candidate_modes = {}
    from collections import Counter
    for office in offices:
        cands = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        for c in cands:
            active_counts = [
                counts_by_hc.get(hid, {}).get(c["id"], 0)
                for hid in active_helper_ids
                if c["id"] in counts_by_hc.get(hid, {})
            ]
            consensus = _compute_consensus_for_candidate(active_counts)
            per_helper = {
                h["short_id"]: counts_by_hc.get(h["id"], {}).get(c["id"])
                for h in helpers
            }
            mode_val = None
            if active_counts:
                cnt = Counter(active_counts)
                top, freq = cnt.most_common(1)[0]
                if freq * 2 > len(active_counts):
                    mode_val = top
            candidate_modes[c["id"]] = mode_val
            candidate_states.append({
                "id": c["id"],
                "name": c["name"],
                "office_id": office["id"],
                "office_name": office["name"],
                "per_helper": per_helper,
                "consensus": consensus,
            })

    per_helper_counts = {
        h["short_id"]: counts_by_hc.get(h["id"], {})
        for h in helpers
        if _helper_is_active(db, h["id"]) and h["disregarded_at"] is None
    }
    flagged = _flag_out_of_sync(per_helper_counts, candidate_modes)
    for h in helper_rows:
        h["out_of_sync"] = h["short_id"] in flagged

    active_count = sum(
        1 for h in helper_rows if h["active"] and not h["disregarded"]
    )
    done_count = sum(
        1 for h in helper_rows if h["done"] and h["active"] and not h["disregarded"]
    )

    if active_count == 0:
        banner = "grey"
    elif any(c["consensus"]["status"] == "mismatch" for c in candidate_states):
        banner = "red"
    elif (
        active_count >= 3
        and done_count == active_count
        and all(c["consensus"]["status"] in ("ok", "no_data") for c in candidate_states)
    ):
        banner = "green"
    else:
        banner = "amber"

    return jsonify({
        "session_status": sess["status"],
        "helpers": helper_rows,
        "candidates": candidate_states,
        "helper_count": active_count,
        "done_count": done_count,
        "banner": banner,
    })


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/disregard", methods=["POST"])
@admin_required
@csrf.exempt
def admin_count_disregard(election_id, round_no):
    db = get_db()
    sess = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if sess is None:
        return ("No session", 404)
    if sess["status"] != "active":
        return ("Session not active", 400)
    body = request.get_json(silent=True) or {}
    try:
        helper_id = int(body.get("helper_id"))
    except (TypeError, ValueError):
        return ("Bad payload", 400)
    disregard = bool(body.get("disregard"))
    helper = db.execute(
        "SELECT * FROM count_session_helpers WHERE id = ? AND session_id = ?",
        (helper_id, sess["id"])
    ).fetchone()
    if helper is None:
        return ("No such helper", 404)
    if disregard:
        db.execute(
            "UPDATE count_session_helpers SET disregarded_at = ? WHERE id = ?",
            (_now_iso(), helper_id)
        )
        action = "set"
    else:
        db.execute(
            "UPDATE count_session_helpers SET disregarded_at = NULL WHERE id = ?",
            (helper_id,)
        )
        action = "cleared"
    db.commit()
    log_voter_audit(
        election_id, None, "paper_count_helper_disregarded",
        detail=f"{helper['short_id']} {action}",
        round_number=round_no
    )
    return ("", 200)


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/persist", methods=["POST"])
@admin_required
@csrf.exempt
def admin_count_persist(election_id, round_no):
    db = get_db()
    sess = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if sess is None:
        return ("No session", 404)
    if sess["status"] != "active":
        return ("Session not active", 400)

    body = request.get_json(silent=True) or {}
    totals = body.get("totals") or {}
    if not isinstance(totals, dict):
        return ("Bad payload", 400)

    helpers = db.execute(
        "SELECT * FROM count_session_helpers WHERE session_id = ? "
        "AND disregarded_at IS NULL",
        (sess["id"],)
    ).fetchall()
    active_helper_ids = [h["id"] for h in helpers if _helper_is_active(db, h["id"])]
    counts_rows = db.execute(
        "SELECT helper_id, candidate_id, count FROM count_session_tallies WHERE session_id = ?",
        (sess["id"],)
    ).fetchall()
    counts_by_hc = {}
    for r in counts_rows:
        counts_by_hc.setdefault(r["helper_id"], {})[r["candidate_id"]] = r["count"]

    all_cands = db.execute(
        "SELECT c.id FROM candidates c JOIN offices o ON c.office_id = o.id "
        "WHERE o.election_id = ?",
        (election_id,)
    ).fetchall()

    persisted_log = {}
    for c in all_cands:
        cid = c["id"]
        active_counts = [counts_by_hc.get(hid, {}).get(cid, 0) for hid in active_helper_ids
                         if cid in counts_by_hc.get(hid, {})]
        consensus = _compute_consensus_for_candidate(active_counts)
        admin_value = totals.get(str(cid))
        if consensus["status"] == "ok" and (admin_value is None or int(admin_value) == consensus["value"]):
            final_count = consensus["value"]
            source = "consensus"
        else:
            if admin_value is None:
                final_count = 0
            else:
                try:
                    final_count = int(admin_value)
                except (TypeError, ValueError):
                    return (f"Bad total for candidate {cid}", 400)
            source = "admin_override"
        db.execute(
            "INSERT INTO count_session_results (session_id, candidate_id, final_count, source) "
            "VALUES (?, ?, ?, ?)",
            (sess["id"], cid, final_count, source)
        )
        persisted_log[cid] = {"final": final_count, "source": source}

    # Auto-populate paper_votes if none have been entered yet for this round
    existing_paper_votes = db.execute(
        "SELECT COUNT(*) as cnt FROM paper_votes WHERE election_id = ? AND round_number = ?",
        (election_id, round_no)
    ).fetchone()["cnt"]
    if existing_paper_votes == 0:
        for cid, info in persisted_log.items():
            if info["final"] > 0:
                db.execute(
                    "INSERT INTO paper_votes (election_id, round_number, candidate_id, count) "
                    "VALUES (?, ?, ?, ?)",
                    (election_id, round_no, cid, info["final"])
                )

    admin_id = session.get("admin_id")
    db.execute(
        "UPDATE count_sessions SET status = 'persisted', persisted_at = ?, "
        "persisted_by_admin_id = ? WHERE id = ?",
        (_now_iso(), admin_id, sess["id"])
    )
    db.commit()

    disregarded = [h["short_id"] for h in db.execute(
        "SELECT short_id FROM count_session_helpers "
        "WHERE session_id = ? AND disregarded_at IS NOT NULL",
        (sess["id"],)
    ).fetchall()]
    log_voter_audit(
        election_id, None, "paper_count_persisted",
        detail=f"persisted={persisted_log}, disregarded={disregarded}",
        round_number=round_no
    )
    return ("", 200)


@app.route("/admin/elections/<int:election_id>/scan-ballot-result", methods=["POST"])
@admin_required
@csrf.exempt
def admin_scan_ballot_result(election_id):
    """Process one scanned QR. JSON body: {"code": "KR4T7N"}.

    Response classes:
        match       - code is currently used in this election; decrement
                      paper_ballot_count and log an audit row
        paper_only  - code exists but is not used; no-op
        unknown     - code does not exist in this election
    """
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    payload = request.get_json(silent=True) or {}
    raw_code = (payload.get("code") or "").strip().upper()
    if not raw_code:
        return jsonify({"result": "unknown"}), 200

    code_h = hash_code(raw_code)
    row = db.execute(
        "SELECT used FROM codes WHERE election_id = ? AND code_hash = ?",
        (election_id, code_h)
    ).fetchone()

    if row is None:
        return jsonify({"result": "unknown"}), 200
    if row["used"] == 0:
        return jsonify({"result": "paper_only"}), 200

    # Match: decrement paper_ballot_count for the current round and audit.
    current_round = election["current_round"] or 1
    cur = db.execute(
        "UPDATE round_counts SET paper_ballot_count = paper_ballot_count - 1 "
        "WHERE election_id = ? AND round_number = ? AND paper_ballot_count > 0",
        (election_id, current_round)
    )
    if cur.rowcount == 0:
        db.commit()
        log_voter_audit(election_id, raw_code, "paper_set_aside_at_count",
                        "Paper ballot scanned but paper_ballot_count was already 0",
                        round_number=current_round)
        return jsonify({"result": "match",
                        "warning": "paper_ballot_count is already 0"}), 200

    log_voter_audit(election_id, raw_code, "paper_set_aside_at_count",
                    "Paper ballot scanned during count, code already burned online",
                    round_number=current_round)
    db.commit()
    return jsonify({"result": "match"}), 200


# ---------------------------------------------------------------------------
# Projector display
# ---------------------------------------------------------------------------

def _build_display_data():
    """Shared data computation for projector and phone display pages."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if not election:
        return None, {}

    current_round = election["current_round"]

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election["id"],)
    ).fetchall()

    in_person, paper_ballot_count_r, used_codes = get_round_counts(election["id"], current_round)
    postal_voter_count_r = (election["postal_voter_count"] or 0) if current_round == 1 else 0
    participants_r = in_person + postal_voter_count_r
    valid_votes_r = used_codes + paper_ballot_count_r + postal_voter_count_r

    results = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()

        # Inactive candidates for round > 1 — names printed on paper ballots
        # but no longer in contention. Voters must not mark these.
        inactive_names = []
        if current_round > 1:
            inactive_rows = db.execute(
                "SELECT name FROM candidates WHERE office_id = ? AND active = 0 ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()
            inactive_names = [r["name"] for r in inactive_rows]

        vacancies = office["vacancies"] or office["max_selections"]

        # First pass: compute per-candidate totals.
        candidate_results = []
        for cand in candidates:
            digital = db.execute(
                "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                (cand["id"], current_round, election["id"])
            ).fetchone()[0]

            paper = db.execute(
                "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                (cand["id"], current_round, election["id"])
            ).fetchone()[0]

            postal = 0
            if current_round == 1:
                postal = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                    (cand["id"], election["id"])
                ).fetchone()[0]

            candidate_results.append({
                "name": cand["name"],
                "total": digital + paper + postal,
                "elected": False,
                "passes_6a": False,
                "passes_6b": False,
                "elected_round": None,
            })

        # Reading A: valid_votes_cast for the threshold is the per-office sum
        # of candidate ticks. Compute it before deriving thresholds.
        votes_cast_for_office = sum(c["total"] for c in candidate_results)
        if participants_r > 0 and vacancies > 0:
            t6a, t6b = calculate_thresholds(vacancies, votes_cast_for_office, participants_r)
        else:
            t6a, t6b = 0, 0

        if participants_r > 0 and vacancies > 0:
            for cand in candidate_results:
                _, p6a, p6b = check_candidate_elected(cand["total"], t6a, t6b)
                cand["passes_6a"] = p6a
                cand["passes_6b"] = p6b

        resolve_elected_status(candidate_results, vacancies)

        # Tag current-round winners with the round they won in. (Prior-round
        # winners get tagged below with their own elected_round.)
        for c in candidate_results:
            if c["elected"]:
                c["elected_round"] = current_round

        count_pass_6a = sum(1 for c in candidate_results if c["passes_6a"])
        count_pass_6b = sum(1 for c in candidate_results if c["passes_6b"])

        # When the chairman has advanced to phase 4 (Final Results), the
        # projector should also surface brothers elected in PRIOR rounds for
        # this office, with their winning-round vote totals. Threshold and
        # 6a/6b counts above stay current-round-only because the rules apply
        # per round.
        phase_for_aggregation = election["display_phase"] or 1
        if phase_for_aggregation == 4 and current_round > 1:
            prior_elected = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? "
                "AND elected = 1 AND elected_round IS NOT NULL "
                "AND elected_round < ? "
                "ORDER BY surname_sort_key(name)",
                (office["id"], current_round)
            ).fetchall()
            for cand in prior_elected:
                r = cand["elected_round"]
                digital_p = db.execute(
                    "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], r, election["id"])
                ).fetchone()[0]
                paper_p = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], r, election["id"])
                ).fetchone()[0]
                postal_p = 0
                if r == 1:
                    postal_p = db.execute(
                        "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                        (cand["id"], election["id"])
                    ).fetchone()[0]
                candidate_results.append({
                    "name": cand["name"],
                    "total": digital_p + paper_p + postal_p,
                    "elected": True,
                    "passes_6a": False,
                    "passes_6b": False,
                    "elected_round": r,
                })
            candidate_results.sort(key=lambda c: _surname_sort_key(c["name"]))

        elected_count = sum(1 for c in candidate_results if c["elected"])
        remaining_vacancies = max(vacancies - elected_count, 0)
        runoff_needed = remaining_vacancies > 0 and elected_count < len(candidate_results)

        spoilt_row = db.execute(
            "SELECT count FROM office_spoilt_ballots "
            "WHERE election_id = ? AND round_number = ? AND office_id = ?",
            (election["id"], current_round, office["id"]),
        ).fetchone()
        spoilt_count = spoilt_row["count"] if spoilt_row else 0

        results.append({
            "office_name": office["name"],
            "office_id": office["id"],
            "vacancies": vacancies,
            "candidates": candidate_results,
            "max_selections": office["max_selections"],
            "votes_cast": votes_cast_for_office,
            # valid_votes_cast for the Article 6a denominator (Reading A).
            # Same value as votes_cast in this app: sum of candidate ticks
            # for this office. Kept as a separate field so the rule's
            # vocabulary is explicit in templates/API.
            "valid_votes_cast": votes_cast_for_office,
            "spoilt_count": spoilt_count,
            "threshold_6a": t6a,
            "threshold_6b": t6b,
            "count_pass_6a": count_pass_6a,
            "count_pass_6b": count_pass_6b,
            "elected_count": elected_count,
            "remaining_vacancies": remaining_vacancies,
            "runoff_needed": runoff_needed,
            "inactive_names": inactive_names,
        })

    in_person, paper_ballot_count, used_codes = get_round_counts(election["id"], current_round)
    postal_voter_count = (election["postal_voter_count"] or 0) if current_round == 1 else 0
    total_ballots = used_codes + paper_ballot_count + postal_voter_count

    wifi_ssid = get_setting("wifi_ssid", "")
    wifi_password = get_setting("wifi_password", "")
    vote_url = get_setting("voting_base_url", "http://church.vote")

    paper_guide = [
        {
            "office_name": r["office_name"],
            "names": [c["name"] for c in r["candidates"]],
        }
        for r in results if r["inactive_names"]
    ]

    # Election-complete summary: elected brothers per office aggregated from
    # the DB (candidates.elected set at each round close) plus any live
    # elected from the current round (not yet persisted if admin_next_round
    # hasn't fired). Election is complete when every office has filled its
    # original_vacancies.
    elected_by_office = []
    election_complete = True
    for office in offices:
        persisted = db.execute(
            "SELECT name FROM candidates "
            "WHERE office_id = ? AND elected = 1 AND elected_round IS NOT NULL",
            (office["id"],)
        ).fetchall()
        names = [r["name"] for r in persisted]
        # Merge any live-elected names from this round's results. We do this
        # whenever voting is closed OR the chairman has explicitly switched
        # to phase 4 (final results) — the live count is the truth in both
        # cases. Skip while voting is open and phase < 4 to avoid "elected"
        # flickering in mid-vote.
        phase_now = election["display_phase"] or 1
        if (not election["voting_open"]) or phase_now == 4:
            for res in results:
                if res["office_id"] == office["id"]:
                    for c in res["candidates"]:
                        if c["elected"] and c["name"] not in names:
                            names.append(c["name"])
        # Alphabetical order by surname for the final display summary
        names.sort(key=_surname_sort_key)
        original = (
            office["original_vacancies"]
            if office["original_vacancies"] is not None
            else (office["vacancies"] or office["max_selections"])
        )
        elected_by_office.append({
            "office_name": office["name"],
            "original_vacancies": original,
            "names": names,
            "filled": len(names) >= original,
        })
        if len(names) < original:
            election_complete = False
    # An election with no offices isn't "complete" — avoid false positives.
    if not elected_by_office:
        election_complete = False

    ctx = dict(
        election=election,
        used_codes=used_codes,
        total_ballots=total_ballots,
        participants=in_person + postal_voter_count,
        in_person_participants=in_person,
        paper_ballot_count=paper_ballot_count,
        postal_voter_count=postal_voter_count,
        valid_votes_cast=used_codes + paper_ballot_count + postal_voter_count,
        results=results,
        paper_guide=paper_guide,
        elected_by_office=elected_by_office,
        election_complete=election_complete,
        wifi_ssid=wifi_ssid,
        wifi_password=wifi_password,
        vote_url=vote_url,
    )
    return election, ctx


@app.route("/display")
def display():
    election, ctx = _build_display_data()
    if not election:
        return render_template("display/waiting.html")

    phase = election["display_phase"] or 1
    if phase == 1:
        # Welcome page — also pass offices for the vacancy cards
        db = get_db()
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
            (election["id"],)
        ).fetchall()
        ctx["offices"] = offices
        return render_template("display/welcome.html", **ctx)
    elif phase == 2:
        return render_template("display/rules.html", **ctx)
    elif phase == 4:
        if election["show_results"]:
            return render_template("display/projector.html", **ctx)
        return render_template("display/final.html", **ctx)
    else:
        # Closing voting reveals vote counts on the projector view; the clean
        # Final Summary (final.html) is only shown when the chairman explicitly
        # advances to phase 4.
        return render_template("display/projector.html", **ctx)


@app.route("/displayphone")
def display_phone():
    election, ctx = _build_display_data()
    if not election:
        return render_template("display/waiting.html")

    # Surface the "Assist with Paper Counting" button on the live results page
    # for any voter whose burned-code session is still around. Voters typically
    # navigate here after submitting their vote, so this is where they can
    # opt in once the chairman closes voting for the round.
    show_assist = False
    used_code = session.get("used_code")
    sess_election_id = session.get("election_id")
    if used_code and sess_election_id == election["id"]:
        db = get_db()
        if _paper_count_active_for_round(db, election):
            show_assist = True
    ctx["show_assist"] = show_assist

    phase = election["display_phase"] or 1
    if phase == 4:
        if election["show_results"]:
            return render_template("display/phone.html", **ctx)
        return render_template("display/final.html", **ctx)
    # Closing voting keeps the phone display on the live view (now revealing
    # counts); final.html only renders once the chairman advances to phase 4.
    return render_template("display/phone.html", **ctx)


@app.route("/api/display-data")
@csrf.exempt
def api_display_data():
    """JSON endpoint for live display refresh."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if not election:
        return jsonify({"active": False})

    current_round = election["current_round"]

    # Digital ballots for current round
    used_codes = db.execute(
        "SELECT COUNT(DISTINCT cast_at) FROM votes WHERE election_id = ? AND round_number = ? AND source = 'digital'",
        (election["id"], current_round)
    ).fetchone()[0]

    in_person, paper_ballot_count, used_codes = get_round_counts(election["id"], current_round)
    postal_voter_count = (election["postal_voter_count"] or 0) if current_round == 1 else 0
    total_ballots = used_codes + paper_ballot_count + postal_voter_count
    participants = in_person + postal_voter_count

    data = {
        "active": True,
        "election_name": election["name"],
        "current_round": current_round,
        "max_rounds": election["max_rounds"],
        "voting_open": bool(election["voting_open"]),
        "show_results": bool(election["show_results"]),
        "display_phase": election["display_phase"] or 1,
        "used_codes": used_codes,
        "total_ballots": total_ballots,
        "participants": participants,
        "paper_ballot_count": paper_ballot_count,
        "postal_voter_count": postal_voter_count
    }

    # Paper-ballot guide shown on the Vote-on-Paper card in round > 1.
    # Lists the only names voters should mark per office; empty names list
    # means "no candidates this round — do not mark any {office}".
    paper_guide = []
    if current_round > 1:
        offices_for_meta = db.execute(
            "SELECT id, name FROM offices WHERE election_id = ? ORDER BY sort_order",
            (election["id"],)
        ).fetchall()
        for office in offices_for_meta:
            any_inactive = db.execute(
                "SELECT 1 FROM candidates WHERE office_id = ? AND active = 0 LIMIT 1",
                (office["id"],)
            ).fetchone()
            if not any_inactive:
                continue
            active_rows = db.execute(
                "SELECT name FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()
            paper_guide.append({
                "office_name": office["name"],
                "names": [r["name"] for r in active_rows],
            })
    data["paper_guide"] = paper_guide

    # Always compute results for elected status
    if election["show_results"] or not election["voting_open"]:
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
            (election["id"],)
        ).fetchall()

        in_person_api, paper_bc_api, _ = get_round_counts(election["id"], current_round)
        postal_vc_api = postal_voter_count
        participants_api = in_person_api + postal_vc_api
        valid_votes_api = used_codes + paper_bc_api + postal_vc_api

        results = []
        for office in offices:
            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()

            vacancies = office["vacancies"] or office["max_selections"]

            # First pass: per-candidate totals.
            candidate_results = []
            for cand in candidates:
                digital = db.execute(
                    "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], current_round, election["id"])
                ).fetchone()[0]

                paper = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], current_round, election["id"])
                ).fetchone()[0]

                postal = 0
                if current_round == 1:
                    postal = db.execute(
                        "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                        (cand["id"], election["id"])
                    ).fetchone()[0]

                candidate_results.append({
                    "name": cand["name"],
                    "total": digital + paper + postal,
                    "elected": False,
                    "passes_6a": False,
                    "passes_6b": False,
                    "elected_round": None,
                })

            # Reading A: valid_votes_cast = per-office sum of candidate ticks.
            votes_cast_for_office = sum(c["total"] for c in candidate_results)
            if participants_api > 0 and vacancies > 0:
                t6a, t6b = calculate_thresholds(vacancies, votes_cast_for_office, participants_api)
            else:
                t6a, t6b = 0, 0

            if participants_api > 0 and vacancies > 0:
                for cand in candidate_results:
                    _, p6a, p6b = check_candidate_elected(cand["total"], t6a, t6b)
                    cand["passes_6a"] = p6a
                    cand["passes_6b"] = p6b

            resolve_elected_status(candidate_results, vacancies)

            for c in candidate_results:
                if c["elected"]:
                    c["elected_round"] = current_round

            count_pass_6a = sum(1 for c in candidate_results if c["passes_6a"])
            count_pass_6b = sum(1 for c in candidate_results if c["passes_6b"])

            # Phase 4: surface prior-round winners for this office with their
            # winning-round vote totals, mirroring _build_display_data.
            phase_for_aggregation = election["display_phase"] or 1
            if phase_for_aggregation == 4 and current_round > 1:
                prior_elected = db.execute(
                    "SELECT * FROM candidates WHERE office_id = ? "
                    "AND elected = 1 AND elected_round IS NOT NULL "
                    "AND elected_round < ? "
                    "ORDER BY surname_sort_key(name)",
                    (office["id"], current_round)
                ).fetchall()
                for cand in prior_elected:
                    r = cand["elected_round"]
                    digital_p = db.execute(
                        "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                        (cand["id"], r, election["id"])
                    ).fetchone()[0]
                    paper_p = db.execute(
                        "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                        (cand["id"], r, election["id"])
                    ).fetchone()[0]
                    postal_p = 0
                    if r == 1:
                        postal_p = db.execute(
                            "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                            (cand["id"], election["id"])
                        ).fetchone()[0]
                    candidate_results.append({
                        "name": cand["name"],
                        "total": digital_p + paper_p + postal_p,
                        "elected": True,
                        "passes_6a": False,
                        "passes_6b": False,
                        "elected_round": r,
                    })
                candidate_results.sort(key=lambda c: _surname_sort_key(c["name"]))

            elected_count = sum(1 for c in candidate_results if c["elected"])
            remaining_vacancies = max(vacancies - elected_count, 0)
            runoff_needed = remaining_vacancies > 0 and elected_count < len(candidate_results)

            spoilt_row = db.execute(
                "SELECT count FROM office_spoilt_ballots "
                "WHERE election_id = ? AND round_number = ? AND office_id = ?",
                (election["id"], current_round, office["id"]),
            ).fetchone()
            spoilt_count = spoilt_row["count"] if spoilt_row else 0

            results.append({
                "office_name": office["name"],
                "candidates": candidate_results,
                "max_selections": office["max_selections"],
                "votes_cast": votes_cast_for_office,
                "valid_votes_cast": votes_cast_for_office,
                "spoilt_count": spoilt_count,
                "vacancies": vacancies,
                "threshold_6a": t6a,
                "threshold_6b": t6b,
                "count_pass_6a": count_pass_6a,
                "count_pass_6b": count_pass_6b,
                "elected_count": elected_count,
                "remaining_vacancies": remaining_vacancies,
                "runoff_needed": runoff_needed,
            })

        data["results"] = results
        # Per Reading A, the threshold denominator is per-office (above).
        # Keep the global field present but report it as the round's total
        # candidate ticks across all offices for any consumer that may
        # reference it; templates and JS now use per-office values.
        data["valid_votes_cast"] = sum(r["valid_votes_cast"] for r in results)

    # Election-complete flag (used by the display to auto-switch to final.html)
    offices_all = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election["id"],)
    ).fetchall()
    complete = bool(offices_all)
    for office in offices_all:
        persisted_count = db.execute(
            "SELECT COUNT(*) FROM candidates WHERE office_id = ? AND elected = 1",
            (office["id"],)
        ).fetchone()[0]
        live_count = 0
        phase_now = election["display_phase"] or 1
        if ((not election["voting_open"]) or phase_now == 4) and "results" in data:
            for r in data["results"]:
                if r["office_name"] == office["name"]:
                    for c in r["candidates"]:
                        if c["elected"]:
                            # Only count live ones not already persisted
                            already_persisted = db.execute(
                                "SELECT 1 FROM candidates WHERE office_id = ? AND name = ? AND elected = 1",
                                (office["id"], c["name"])
                            ).fetchone()
                            if not already_persisted:
                                live_count += 1
        original = (
            office["original_vacancies"]
            if office["original_vacancies"] is not None
            else (office["vacancies"] or office["max_selections"])
        )
        if persisted_count + live_count < original:
            complete = False
    data["election_complete"] = complete

    return jsonify(data)


# ---------------------------------------------------------------------------
# PDF generation (thin wrappers — logic lives in pdf_generators.py)
# ---------------------------------------------------------------------------


@app.route("/admin/election/<int:election_id>/codes/pdf")
@admin_required
def admin_codes_pdf(election_id):
    """Generate printable code slips with QR codes."""
    codes = load_codes_from_db(election_id)

    if not codes:
        flash("Code slips can only be exported after code generation. Delete and regenerate codes to get a new PDF.", "error")
        return redirect(url_for("admin_step_codes", election_id=election_id))

    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()

    buf = generate_code_slips_pdf(
        codes=codes,
        election_name=election["name"],
        short_name=get_setting("congregation_short", "FRC"),
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://church.vote"),
    )
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name="voting_codes.pdf")


@app.route("/admin/election/<int:election_id>/counter-sheet-pdf")
@admin_required
def admin_counter_sheet_pdf(election_id):
    """Generate a counter sheet PDF for paper ballot counting."""
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order", (election_id,)
    ).fetchall()

    offices_data = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        offices_data.append({
            "office": dict(office),
            "candidates": [dict(c) for c in candidates],
        })

    cong_name = get_setting("congregation_name", "Free Reformed Church")
    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    buf = generate_counter_sheet_pdf(
        election_name=election["name"],
        congregation_name=cong_name,
        offices_data=offices_data,
        member_count=member_count,
    )
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name="counter_sheet.pdf")


@app.route("/admin/election/<int:election_id>/paper-ballot-pdf/<int:round_number>")
@admin_required
def admin_paper_ballot_pdf(election_id, round_number):
    """Generate printable paper ballot forms."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    office_data = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        office_data.append({
            "office": dict(office),
            "candidates": [dict(c) for c in candidates],
        })

    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    buf = generate_paper_ballot_pdf(
        election_name=election["name"],
        round_number=round_number,
        office_data=office_data,
        member_count=member_count,
    )
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"paper_ballot_round_{round_number}.pdf")


@app.route("/admin/election/<int:election_id>/dual-sided-ballots-pdf")
@admin_required
def admin_dual_sided_ballots_pdf(election_id):
    """Generate dual-sided ballots PDF for duplex printing."""
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

    # Require plaintext codes on file (same safety rule as admin_codes_pdf)
    codes = load_codes_from_db(election_id)
    if not codes:
        flash("Codes are not available. Delete and regenerate codes to get a new PDF.", "error")
        return redirect(url_for("admin_step_codes", election_id=election_id))

    # Filter to only unused codes
    used_hashes = set()
    for row in db.execute("SELECT code_hash FROM codes WHERE election_id = ? AND used = 1", (election_id,)):
        used_hashes.add(row["code_hash"])

    unused_codes = [c for c in codes if hash_code(c) not in used_hashes]

    if not unused_codes:
        flash("All codes have been used. Generate new codes first.", "error")
        return redirect(url_for("admin_step_codes", election_id=election_id))

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order", (election_id,)
    ).fetchall()

    office_data = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        office_data.append({"office": dict(office), "candidates": [dict(c) for c in candidates]})

    filename = "dual_sided_ballots.pdf"

    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    buf = generate_dual_sided_ballots_pdf(
        election_name=election["name"],
        short_name=get_setting("congregation_short", "FRC"),
        round_number=election["current_round"],
        office_data=office_data,
        codes=unused_codes,
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://church.vote"),
        member_count=member_count,
    )

    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=filename)


@app.route("/admin/election/<int:election_id>/printer-pack-zip")
@admin_required
def admin_printer_pack_zip(election_id):
    """Generate a ZIP with all PDFs needed for professional printing."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    codes = db.execute(
        "SELECT plaintext FROM codes WHERE election_id = ? ORDER BY id",
        (election_id,)
    ).fetchall()
    codes = [row["plaintext"] for row in codes]

    used_hashes = {
        row["code_hash"] for row in db.execute(
            "SELECT code_hash FROM codes WHERE election_id = ? AND used = 1",
            (election_id,)
        ).fetchall()
    }
    unused_codes = [c for c in codes if hash_code(c) not in used_hashes]

    if not unused_codes:
        flash("All codes have been used. Generate new codes first.", "error")
        return redirect(url_for("admin_step_codes", election_id=election_id))

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    office_data = []
    for office in offices:
        candidates = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? AND active = 1 ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        office_data.append({"office": dict(office), "candidates": [dict(c) for c in candidates]})

    members = db.execute(
        "SELECT * FROM members ORDER BY last_name, first_name"
    ).fetchall()

    cong_name = get_setting("congregation_name", "Free Reformed Church")

    buf = generate_printer_pack_zip(
        election_name=election["name"],
        short_name=get_setting("congregation_short", "FRC"),
        round_number=election["current_round"],
        office_data=office_data,
        codes=unused_codes,
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://church.vote"),
        congregation_name=cong_name,
        members=[dict(m) for m in members],
        election_date=election["election_date"],
        member_count=len(members),
    )

    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="printer_pack.zip")


@app.route("/admin/election/<int:election_id>/results-pdf")
@admin_required
def admin_results_pdf(election_id):
    """Export election results as a PDF."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    # Build rounds_data structure for the shared PDF generator
    rounds_data = []
    for round_num in range(1, election["current_round"] + 1):
        used_codes = db.execute(
            "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1",
            (election_id,)
        ).fetchone()[0]

        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
            (election_id,)
        ).fetchall()

        offices_list = []
        for office in offices:
            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()

            cand_list = []
            for cand in candidates:
                digital = db.execute(
                    "SELECT COUNT(*) FROM votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], round_num, election_id)
                ).fetchone()[0]

                paper = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], round_num, election_id)
                ).fetchone()[0]

                postal = 0
                if round_num == 1:
                    postal = db.execute(
                        "SELECT COALESCE(SUM(count), 0) FROM postal_votes WHERE candidate_id = ? AND election_id = ?",
                        (cand["id"], election_id)
                    ).fetchone()[0]

                # Skip candidates who were already elected before this round
                # or who weren't on this round's ballot. See the matching
                # block in admin_minutes_docx for the heuristic's rationale.
                already_elected_before = (
                    cand["elected_round"] is not None
                    and cand["elected_round"] < round_num
                )
                if already_elected_before:
                    continue
                on_ballot = (
                    cand["active"] == 1
                    or cand["elected_round"] == round_num
                    or (digital + paper + postal) > 0
                )
                if not on_ballot:
                    continue

                cand_list.append({
                    "name": cand["name"],
                    "digital": digital,
                    "paper": paper,
                    "postal": postal,
                    "total": digital + paper + postal,
                })

            offices_list.append({
                "name": office["name"],
                "candidates": cand_list,
            })

        postal_voter_count = (election["postal_voter_count"] or 0) if round_num == 1 else 0

        rounds_data.append({
            "round_number": round_num,
            "used_codes": used_codes,
            "postal_voter_count": postal_voter_count,
            "offices": offices_list,
        })

    buf = generate_results_pdf(
        election_name=election["name"],
        rounds_data=rounds_data,
    )
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"election_results_{election['name'].replace(' ', '_')}.pdf"
    )


@app.route("/admin/election/<int:election_id>/secretary-report-pdf")
@admin_required
def admin_secretary_report_pdf(election_id):
    """Removed — redirects to raw results export."""
    return redirect(url_for("admin_results_pdf", election_id=election_id))


@app.route("/admin/election/<int:election_id>/minutes-docx")
@admin_required
def admin_minutes_docx(election_id):
    """Export election minutes as a DOCX for the secretary."""
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    congregation_name = get_setting("congregation_name", "Free Reformed Church")

    offices = db.execute(
        "SELECT * FROM offices WHERE election_id = ? ORDER BY sort_order",
        (election_id,)
    ).fetchall()

    # Track vacancies remaining per office at the start of each round,
    # starting from the preserved original_vacancies and decrementing by the
    # number of brothers whose elected_round matches earlier rounds.
    office_vacancies_at_round = {
        office["id"]: (
            office["original_vacancies"]
            if office["original_vacancies"] is not None
            else (office["vacancies"] or office["max_selections"])
        )
        for office in offices
    }

    # Build rounds_data with full detail for each round
    rounds_data = []
    for round_num in range(1, election["current_round"] + 1):
        in_person, paper_ballot_count, digital_count = get_round_counts(
            election_id, round_num
        )
        postal_voter_count = (
            (election["postal_voter_count"] or 0) if round_num == 1 else 0
        )
        participants = in_person + postal_voter_count
        total_ballots = digital_count + paper_ballot_count + postal_voter_count

        offices_list = []
        for office in offices:
            vacancies = office_vacancies_at_round[office["id"]]

            # If this office was already fully decided before this round,
            # skip it — nothing to report for this round under this office.
            if vacancies <= 0:
                continue

            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? "
                "ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()

            # First pass: candidate totals (filter out already-elected).
            cand_list = []
            for cand in candidates:
                digital = db.execute(
                    "SELECT COUNT(*) FROM votes "
                    "WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], round_num, election_id)
                ).fetchone()[0]

                paper = db.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM paper_votes "
                    "WHERE candidate_id = ? AND round_number = ? AND election_id = ?",
                    (cand["id"], round_num, election_id)
                ).fetchone()[0]

                postal = 0
                if round_num == 1:
                    postal = db.execute(
                        "SELECT COALESCE(SUM(count), 0) FROM postal_votes "
                        "WHERE candidate_id = ? AND election_id = ?",
                        (cand["id"], election_id)
                    ).fetchone()[0]

                # Candidates already elected in a prior round shouldn't appear
                # on this round's ballot table.
                already_elected_before = (
                    cand["elected_round"] is not None
                    and cand["elected_round"] < round_num
                )
                if already_elected_before:
                    continue

                # Per-round ballot membership isn't persisted in the schema,
                # so reconstruct it heuristically: a candidate was on this
                # round's ballot if they're still active, were elected this
                # round, or received any vote this round. Risk: a candidate
                # who genuinely got 0 votes drops from historical minutes,
                # which is vanishingly unlikely in a real congregational
                # ballot.
                on_ballot = (
                    cand["active"] == 1
                    or cand["elected_round"] == round_num
                    or (digital + paper + postal) > 0
                )
                if not on_ballot:
                    continue

                cand_list.append({
                    "id": cand["id"],
                    "name": cand["name"],
                    "digital": digital,
                    "paper": paper,
                    "postal": postal,
                    "total": digital + paper + postal,
                    "elected": False,
                    "passes_6a": False,
                    "passes_6b": False,
                })

            # Reading A: valid_votes_cast = sum of candidate ticks for this office.
            office_valid_votes = sum(c["total"] for c in cand_list)
            t6a, t6b = (0, 0)
            if participants > 0 and vacancies > 0:
                t6a, t6b = calculate_thresholds(
                    vacancies, office_valid_votes, participants
                )
                for c in cand_list:
                    _, p6a, p6b = check_candidate_elected(c["total"], t6a, t6b)
                    c["passes_6a"] = p6a
                    c["passes_6b"] = p6b

            resolve_elected_status(cand_list, vacancies)

            # Update the running vacancy count for subsequent rounds.
            elected_this_round = sum(1 for c in cand_list if c["elected"])
            office_vacancies_at_round[office["id"]] = max(
                vacancies - elected_this_round, 0
            )

            offices_list.append({
                "name": office["name"],
                "vacancies": vacancies,
                # max_selections for the round = vacancies remaining at the
                # start of the round; historic carry-forward sizes are not
                # preserved, so this is the best post-hoc reconstruction.
                "max_selections": vacancies,
                "threshold_6a": t6a if participants > 0 else None,
                "threshold_6b": t6b if participants > 0 else None,
                "candidates": cand_list,
            })

        rounds_data.append({
            "round_number": round_num,
            "participants": participants,
            "in_person": in_person,
            "postal_voter_count": postal_voter_count,
            "used_codes": digital_count,
            "paper_ballot_count": paper_ballot_count,
            "total_ballots": total_ballots,
            "offices": offices_list,
        })

    # Build elected summary across ALL rounds. Previously-elected brothers
    # are persisted to candidates.elected / elected_round at each round
    # close (admin_next_round). The current round is still open, so compute
    # live for the final round using the current office.vacancies which
    # represents the remaining seats at the start of this round.
    elected_summary = []
    final_round_elected_by_office = {}
    if rounds_data:
        last_round = rounds_data[-1]
        for office_result in last_round["offices"]:
            names = [c["name"] for c in office_result["candidates"] if c["elected"]]
            final_round_elected_by_office[office_result["name"]] = names

    for office in offices:
        persisted = db.execute(
            "SELECT name FROM candidates "
            "WHERE office_id = ? AND elected = 1 AND elected_round IS NOT NULL",
            (office["id"],)
        ).fetchall()
        names_in_order = [r["name"] for r in persisted]
        # Merge in anyone elected in the current round but not yet persisted
        for name in final_round_elected_by_office.get(office["name"], []):
            if name not in names_in_order:
                names_in_order.append(name)
        # Alphabetical by surname for the final summary
        names_in_order.sort(key=_surname_sort_key)
        elected_summary.append({
            "office": office["name"],
            "names": names_in_order,
        })

    buf = generate_minutes_docx(
        congregation_name=congregation_name,
        election_name=election["name"],
        election_date=election["election_date"] or "",
        rounds_data=rounds_data,
        elected_summary=elected_summary,
    )

    safe_name = election["name"].replace(" ", "_")
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"election_minutes_{safe_name}.docx",
    )


@app.route("/admin/council-proposal")
@admin_required
def admin_council_proposal():
    """Render the council proposal markdown as HTML."""
    proposal_path = os.path.join(BASE_DIR, "docs", "COUNCIL_PROPOSAL.md")
    if not os.path.exists(proposal_path):
        abort(404)

    with open(proposal_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    try:
        import markdown
        html_content = markdown.markdown(md_content)
    except ImportError:
        html_content = f"<pre>{md_content}</pre>"

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Council Proposal</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #1A3353; }}
    h1 {{ border-bottom: 2px solid #D4A843; padding-bottom: 8px; }}
    h2 {{ color: #1A3353; margin-top: 24px; }}
    em {{ color: #666; }}
    hr {{ border: none; border-top: 1px solid #D4A843; margin: 24px 0; }}
    a {{ color: #1A3353; }}
    @media print {{ body {{ max-width: 100%; margin: 0; }} }}
</style>
</head><body>{html_content}
<p style="margin-top: 24px;"><a href="/admin">&larr; Back to Admin Dashboard</a></p>
</body></html>"""


# ---------------------------------------------------------------------------
# Captive portal detection (CPD) routes
# ---------------------------------------------------------------------------

# Paths whose response must not be host-redirected. Phone OSes probe these to
# decide whether the network is captive, and the portal API itself is hit
# directly on the literal IP advertised in DHCP option 114, so they must
# answer with their own response regardless of the Host header.
_CPD_PROBE_PATHS = frozenset({
    "/api/captive-portal",
    "/.well-known/captive-portal",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/generate_204",
    "/gen_204",
    "/connecttest.txt",
    "/ncsi.txt",
    "/success.txt",
    "/canonical.html",
    "/redirect",
    "/mobile/status.php",
    "/favicon.ico",
})


@app.before_request
def force_canonical_host():
    """Bounce phones that hit the server via DNS hijack to the canonical URL.

    A phone joined to ChurchVote that opens, say, bbc.com will resolve that
    hostname to the laptop and arrive here with Host=bbc.com. We 302 it to
    voting_base_url so the URL bar reads church.vote. Admin access via the
    raw IP, plus localhost/127.0.0.1 for local testing, is left alone.
    """
    path = request.path
    if path in _CPD_PROBE_PATHS or path.startswith("/static/"):
        return None

    canonical_url = get_setting("voting_base_url", "http://church.vote")
    canonical_host = (urlparse(canonical_url).hostname or "").lower()
    if not canonical_host:
        return None

    request_host = request.host.split(":", 1)[0].lower()
    if request_host == canonical_host:
        return None
    if request_host in ("localhost", "127.0.0.1"):
        return None
    parts = request_host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return None

    target = canonical_url.rstrip("/") + path
    qs = request.query_string.decode("utf-8")
    if qs:
        target += "?" + qs
    return redirect(target, code=302)


@app.route("/api/captive-portal")
@app.route("/.well-known/captive-portal")
def captive_portal_api():
    """RFC 8908 Captive Portal API. Advertises the voting page so the OS
    popup (triggered by DHCP option 114) opens church.vote directly."""
    from flask import Response, json as flask_json
    portal_url = get_setting("voting_base_url", "http://church.vote")
    data = flask_json.dumps({"captive": True, "user-portal-url": portal_url})
    return Response(data, status=200, content_type="application/captive+json")


# CPD probe routes — return the expected "success" responses so phones
# think the network is normal and stay connected.  The DNS wildcard still
# redirects all other browser traffic to the voting page.

@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
def cpd_apple():
    """iOS/macOS probe — expects 200 with 'Success' in the title."""
    return "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"


@app.route("/generate_204")
@app.route("/gen_204")
def cpd_android():
    """Android probe — expects HTTP 204 with empty body."""
    return "", 204


@app.route("/connecttest.txt")
def cpd_windows():
    """Windows probe — expects 200 with 'Microsoft Connect Test'."""
    return "Microsoft Connect Test"


@app.route("/ncsi.txt")
def cpd_windows_ncsi():
    """Windows NCSI probe — expects 200 with 'Microsoft NCSI'."""
    return "Microsoft NCSI"


@app.route("/success.txt")
@app.route("/canonical.html")
def cpd_firefox():
    """Firefox probe — expects 200 with 'success'."""
    return "success\n"


@app.route("/redirect")
@app.route("/mobile/status.php")
def cpd_other():
    """Other probes — return 200 OK."""
    return "OK"


@app.route("/favicon.ico")
def favicon():
    """Return empty 204 so browsers stop falling through to catch_all."""
    return "", 204


@app.route("/<path:path>")
def catch_all(path):
    """Redirect unknown paths to the canonical voting URL so the URL bar
    shows church.vote rather than whatever foreign host the phone tried."""
    canonical_url = get_setting("voting_base_url", "http://church.vote")
    return redirect(canonical_url.rstrip("/") + "/", code=302)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()
    migrate_db()

if __name__ == "__main__":
    print("Do not run this file directly. Use start.bat (Windows) or run.sh (Linux/Mac).")
    print("See docs/SETUP.md for instructions.")
