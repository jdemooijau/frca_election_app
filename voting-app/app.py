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
from datetime import datetime
from functools import wraps

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
    generate_dual_ballot_handout_pdf, generate_dual_sided_ballots_pdf,
    generate_attendance_register_pdf, generate_printer_pack_zip,
    generate_minutes_docx,
    draw_demo_watermark, draw_demo_header, NAVY, GOLD, _generate_qr_image,
)
from demo_names import generate_demo_names, load_member_names_from_external

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
            participants INTEGER,
            paper_ballot_count INTEGER NOT NULL DEFAULT 0,
            postal_voter_count INTEGER NOT NULL DEFAULT 0,
            display_phase INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS offices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            max_selections INTEGER NOT NULL DEFAULT 1,
            vacancies INTEGER,
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
    """)

    # Insert default settings if not present
    defaults = {
        "congregation_name": "Free Reformed Church",
        "congregation_short": "FRC",
        "wifi_ssid": "ChurchVote",
        "wifi_password": "",
        "voting_base_url": "http://192.168.8.100:5000",
        "admin_password": DEFAULT_ADMIN_PASSWORD,
        "setup_complete": "0",
        "is_demo": "0",
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
        "ALTER TABLE elections ADD COLUMN participants INTEGER",
        "ALTER TABLE elections ADD COLUMN paper_ballot_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE offices ADD COLUMN vacancies INTEGER",
        "ALTER TABLE candidates ADD COLUMN retiring_office_bearer INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE candidates ADD COLUMN elected INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE candidates ADD COLUMN relieved INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE elections ADD COLUMN postal_voter_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE round_counts ADD COLUMN digital_ballot_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE codes ADD COLUMN plaintext TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE elections ADD COLUMN display_phase INTEGER NOT NULL DEFAULT 1",
    ]
    for sql in migrations:
        try:
            db.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already exists
    db.commit()


def migrate_db():
    """Add columns for rules compliance. Safe to run repeatedly."""
    _migrate_db_on(get_db())


# ---------------------------------------------------------------------------
# Threshold calculations (Article 6)
# ---------------------------------------------------------------------------

def calculate_thresholds(vacancies, valid_votes_cast, participants):
    """
    Article 6 threshold calculations.

    6a: candidate must receive STRICTLY MORE THAN
        (valid_votes_cast / vacancies / 2)
    6b: candidate must receive AT LEAST
        ceil(participants * 2 / 5)  (fractions rounded up per Article 7)
    """
    if vacancies <= 0:
        return 0, 0
    threshold_6a = valid_votes_cast / (2 * vacancies)
    threshold_6b = math.ceil(participants * 2 / 5)
    return threshold_6a, threshold_6b


def check_candidate_elected(votes, threshold_6a, threshold_6b):
    """
    Check if a candidate meets BOTH Article 6 thresholds.
    Returns (meets_thresholds, passes_6a, passes_6b).

    NOTE: meets_thresholds alone is NOT sufficient to declare a candidate elected.
    Per Article 6 ("candidates who receive the MOST votes... provided that ..."),
    only the top-N candidates by vote count (N = vacancies) among those who pass
    both thresholds are elected. Use resolve_elected_status() to apply that rule.
    """
    passes_6a = votes > threshold_6a   # strict greater than
    passes_6b = votes >= threshold_6b  # greater than or equal
    return (passes_6a and passes_6b), passes_6a, passes_6b


def resolve_elected_status(candidates, vacancies):
    """
    Apply Article 6 + 7 to decide which candidates are elected this round.

    Preconditions: each candidate dict has "total", "passes_6a", "passes_6b".
    Sets "elected" to True only for the top `vacancies` threshold-passers by
    vote count. Candidates tied on votes at the cutoff are NOT elected (they
    must face a runoff per Article 7).
    """
    for c in candidates:
        c["elected"] = False

    if vacancies <= 0:
        return

    passing = [c for c in candidates if c.get("passes_6a") and c.get("passes_6b")]
    if not passing:
        return

    passing.sort(key=lambda c: c["total"], reverse=True)

    if len(passing) <= vacancies:
        for c in passing:
            c["elected"] = True
        return

    cutoff_votes = passing[vacancies - 1]["total"]
    next_votes = passing[vacancies]["total"]

    if cutoff_votes == next_votes:
        # Tie at the boundary — only elect candidates strictly above the tie
        for c in passing:
            if c["total"] > cutoff_votes:
                c["elected"] = True
    else:
        for c in passing[:vacancies]:
            c["elected"] = True


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


def hash_code(code):
    """Hash a voting code for fast lookup."""
    return hashlib.sha256(code.upper().encode()).hexdigest()


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
        "voting_base_url": get_setting("voting_base_url", "http://192.168.8.100:5000"),
        "is_demo": get_setting("is_demo", "0") == "1",
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
    """First-run setup wizard — congregation config and password change."""
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
            return render_template("admin/setup.html")

        if not new_password or len(new_password) < 6:
            flash("Please set a new admin password (at least 6 characters).", "error")
            return render_template("admin/setup.html")

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("admin/setup.html")

        set_setting("congregation_name", congregation_name)
        set_setting("congregation_short", congregation_short or congregation_name)
        set_setting("wifi_ssid", wifi_ssid or "ChurchVote")
        set_setting("wifi_password", wifi_password)
        set_setting("voting_base_url", voting_base_url or "http://192.168.8.100:5000")
        set_setting("admin_password", new_password)
        set_setting("setup_complete", "1")

        flash("Setup complete. Welcome.", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin/setup.html")


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
        return redirect(url_for("admin_election_setup", election_id=election_id))

    return render_template("admin/election_new.html")


@app.route("/admin/election/<int:election_id>/setup", methods=["GET", "POST"])
@admin_required
def admin_election_setup(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    if request.method == "POST":
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
                    "admin/election_setup.html",
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
                    prefill_candidates=candidate_names
                )

            # Get next sort order
            max_sort = db.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM offices WHERE election_id = ?",
                (election_id,)
            ).fetchone()[0]

            cursor = db.execute(
                "INSERT INTO offices (election_id, name, max_selections, vacancies, sort_order) VALUES (?, ?, ?, ?, ?)",
                (election_id, office_name, max_selections, vacancies, max_sort + 1)
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

        return redirect(url_for("admin_election_setup", election_id=election_id))

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

    return render_template(
        "admin/election_setup.html",
        election=election,
        offices=offices,
        candidates_by_office=candidates_by_office
    )


@app.route("/admin/election/<int:election_id>/office/<int:office_id>/delete", methods=["POST"])
@admin_required
def admin_office_delete(election_id, office_id):
    db = get_db()
    db.execute("DELETE FROM candidates WHERE office_id = ?", (office_id,))
    db.execute("DELETE FROM offices WHERE id = ? AND election_id = ?", (office_id, election_id))
    db.commit()
    flash("Office removed.", "success")
    return redirect(url_for("admin_election_setup", election_id=election_id))


@app.route("/admin/election/<int:election_id>/codes", methods=["GET", "POST"])
@admin_required
def admin_codes(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    generated_codes = None

    if request.method == "POST":
        count = int(request.form.get("count", 100))

        if count < 1 or count > 999:
            flash("Code count must be between 1 and 999.", "error")
        else:
            existing = db.execute(
                "SELECT COUNT(*) FROM codes WHERE election_id = ?",
                (election_id,)
            ).fetchone()[0]
            if existing > 0:
                flash(f"Codes already generated ({existing} codes). Delete them first to regenerate.", "error")
            else:
                codes = generate_codes(election_id, count)
                generated_codes = codes
                flash(f"Generated {len(codes)} voting codes.", "success")

    # Code stats
    stats = db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN used = 1 THEN 1 ELSE 0 END) as used
           FROM codes WHERE election_id = ?""",
        (election_id,)
    ).fetchone()
    total_codes = stats["total"]
    used_codes = stats["used"] or 0

    # Smart default: (member count + 10) * max_rounds
    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    per_round = member_count + 10 if member_count > 0 else 100
    default_count = per_round * election["max_rounds"]

    return render_template(
        "admin/codes.html",
        election=election,
        total_codes=total_codes,
        used_codes=used_codes,
        generated_codes=generated_codes,
        default_count=default_count,
        member_count=member_count
    )


@app.route("/admin/election/<int:election_id>/codes/delete", methods=["POST"])
@admin_required
def admin_codes_delete(election_id):
    db = get_db()
    # Only allow deleting if no codes have been used
    used_count = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1",
        (election_id,)
    ).fetchone()[0]
    if used_count > 0:
        flash(f"Cannot delete codes — {used_count} codes have already been used.", "error")
    else:
        db.execute(
            "DELETE FROM codes WHERE election_id = ?",
            (election_id,)
        )
        db.commit()
        flash("All codes deleted.", "success")
    return redirect(url_for("admin_codes", election_id=election_id))


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
            return redirect(url_for("admin_election_manage", election_id=election_id))

    db.execute(
        "UPDATE elections SET voting_open = ? WHERE id = ?",
        (new_state, election_id)
    )
    db.commit()

    status = "opened" if new_state else "closed"
    flash(f"Voting {status} for round {election['current_round']}.", "success")
    return redirect(url_for("admin_election_manage", election_id=election_id))


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
    return redirect(url_for("admin_election_manage", election_id=election_id))


@app.route("/admin/election/<int:election_id>/display-phase", methods=["POST"])
@admin_required
def admin_set_display_phase(election_id):
    """Advance or go back in the projector display phase flow.

    Phase 1 = Welcome (congregation + election details)
    Phase 2 = Election Rules (candidates list + articles 4, 6, 12)
    Phase 3 = Voting (opens voting automatically on first entry)
    """
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    direction = request.form.get("direction", "next")
    current_phase = election["display_phase"] or 1

    if direction == "next" and current_phase < 3:
        new_phase = current_phase + 1
    elif direction == "prev" and current_phase > 1:
        new_phase = current_phase - 1
    else:
        return redirect(url_for("admin_election_manage", election_id=election_id))

    # Advancing to phase 3 opens voting automatically
    if new_phase == 3 and not election["voting_open"]:
        code_count = db.execute(
            "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 0",
            (election_id,)
        ).fetchone()[0]
        if code_count == 0:
            flash("Cannot proceed to voting — no unused codes available.", "error")
            return redirect(url_for("admin_election_manage", election_id=election_id))
        db.execute(
            "UPDATE elections SET display_phase = ?, voting_open = 1 WHERE id = ?",
            (new_phase, election_id)
        )
        db.commit()
        flash(f"Voting opened for round {election['current_round']}. Projector now showing voting display.", "success")
    else:
        # Going back from phase 3 does NOT close voting — that's a separate action
        db.execute(
            "UPDATE elections SET display_phase = ? WHERE id = ?",
            (new_phase, election_id)
        )
        db.commit()
        phase_names = {1: "Welcome", 2: "Election Rules", 3: "Voting"}
        flash(f"Projector display: {phase_names[new_phase]}", "success")

    return redirect(url_for("admin_election_manage", election_id=election_id))


@app.route("/admin/election/<int:election_id>/manage")
@admin_required
def admin_election_manage(election_id):
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

    used_codes = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1",
        (election_id,)
    ).fetchone()[0]

    # Article 6 threshold calculations — per-round counts
    in_person_participants, paper_ballot_count, digital_ballot_count = get_round_counts(election_id, current_round)
    postal_voter_count = (election["postal_voter_count"] or 0) if current_round == 1 else 0

    # Postal voters count as participants in round 1 only
    participants = in_person_participants + postal_voter_count

    valid_votes_cast = digital_ballot_count + paper_ballot_count + postal_voter_count

    thresholds = {}
    for item in results:
        office = item["office"]
        vacancies = office["vacancies"] or office["max_selections"]
        if participants > 0 and vacancies > 0:
            t6a, t6b = calculate_thresholds(vacancies, valid_votes_cast, participants)
            for cand in item["candidates"]:
                _, p6a, p6b = check_candidate_elected(cand["total"], t6a, t6b)
                cand["passes_6a"] = p6a
                cand["passes_6b"] = p6b
            resolve_elected_status(item["candidates"], vacancies)
            for cand in item["candidates"]:
                cand["meets_threshold"] = cand["elected"]
            thresholds[office["id"]] = {
                "vacancies": vacancies,
                "valid_votes_cast": valid_votes_cast,
                "participants": participants,
                "threshold_6a": t6a,
                "threshold_6b": t6b,
            }

    return render_template(
        "admin/manage.html",
        election=election,
        results=results,
        total_codes=total_codes,
        used_codes=used_codes,
        in_person_participants=in_person_participants,
        participants=participants,
        paper_ballot_count=paper_ballot_count,
        postal_voter_count=postal_voter_count,
        valid_votes_cast=valid_votes_cast,
        thresholds=thresholds,
        current_round=current_round
    )


@app.route("/admin/election/<int:election_id>/participants", methods=["POST"])
@admin_required
def admin_set_participants(election_id):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    current_round = election["current_round"]
    participants = max(0, int(request.form.get("participants", 0)))
    paper_ballot_count = max(0, int(request.form.get("paper_ballot_count", 0)))
    set_round_counts(election_id, current_round, participants, paper_ballot_count)
    flash(f"Round {current_round} — Participants: {participants}, Paper ballots: {paper_ballot_count}.", "success")
    return redirect(url_for("admin_election_manage", election_id=election_id))


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

    if request.method == "POST":
        # Process paper vote entries
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = ?", (election_id,)
        ).fetchall()

        for office in offices:
            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? AND active = 1",
                (office["id"],)
            ).fetchall()

            for cand in candidates:
                field_name = f"paper_{cand['id']}"
                count_str = request.form.get(field_name, "0").strip()
                count = int(count_str) if count_str.isdigit() else 0

                # Delete any existing paper votes for this candidate/round
                db.execute(
                    "DELETE FROM paper_votes WHERE election_id = ? AND round_number = ? AND candidate_id = ?",
                    (election_id, current_round, cand["id"])
                )
                if count > 0:
                    db.execute(
                        "INSERT INTO paper_votes (election_id, round_number, candidate_id, count) VALUES (?, ?, ?, ?)",
                        (election_id, current_round, cand["id"], count)
                    )

        db.commit()

        # Validate totals against paper ballot count
        _, paper_ballot_count, _ = get_round_counts(election_id, current_round)
        if paper_ballot_count > 0:
            for office in offices:
                total_votes = sum(
                    int(request.form.get(f"paper_{c['id']}", 0))
                    for c in db.execute(
                        "SELECT * FROM candidates WHERE office_id = ? AND active = 1", (office["id"],)
                    ).fetchall()
                )
                max_possible = paper_ballot_count * office["max_selections"]
                if total_votes > max_possible:
                    flash(
                        f"Warning: {office['name']} has {total_votes} paper votes but only "
                        f"{paper_ballot_count} ballots × {office['max_selections']} selections = {max_possible} maximum. "
                        f"Please check your counts.",
                        "error"
                    )

        flash("Paper vote totals saved.", "success")
        return redirect(url_for("admin_election_manage", election_id=election_id))

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
        office_candidates.append({
            "office": office,
            "candidates": candidates
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
        return redirect(url_for("admin_election_manage", election_id=election_id))

    current_round = election["current_round"]
    if current_round >= election["max_rounds"]:
        flash(f"Maximum rounds ({election['max_rounds']}) reached.", "error")
        return redirect(url_for("admin_election_manage", election_id=election_id))

    # Get selected candidate IDs to carry forward
    carry_forward_ids = request.form.getlist("carry_forward")
    if not carry_forward_ids:
        flash("Select at least one candidate to carry forward.", "error")
        return redirect(url_for("admin_election_manage", election_id=election_id))

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

        # Count candidates elected in the round being closed
        elected_this_round = 0
        if participants_prev > 0 and current_vacancies > 0:
            t6a, t6b = calculate_thresholds(current_vacancies, valid_votes_prev, participants_prev)
            cand_summary = []
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
                _, p6a, p6b = check_candidate_elected(total, t6a, t6b)
                cand_summary.append({"total": total, "passes_6a": p6a, "passes_6b": p6b, "elected": False})
            resolve_elected_status(cand_summary, current_vacancies)
            elected_this_round = sum(1 for c in cand_summary if c["elected"])

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
    return redirect(url_for("admin_election_manage", election_id=election_id))


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
        return redirect(url_for("admin_election_manage", election_id=election_id))

    if request.form.get("password") != get_setting("admin_password"):
        flash("Soft reset cancelled — incorrect password.", "error")
        return redirect(url_for("admin_election_manage", election_id=election_id))

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

    db.commit()
    flash(f"Soft reset complete. Round {current_round} votes cleared, codes restored. Postal votes and setup unchanged.", "success")
    return redirect(url_for("admin_election_manage", election_id=election_id))


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
        return redirect(url_for("admin_election_manage", election_id=election_id))

    if request.form.get("password") != get_setting("admin_password"):
        flash("Hard reset cancelled — incorrect password.", "error")
        return redirect(url_for("admin_election_manage", election_id=election_id))

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
        db.execute("UPDATE candidates SET active = 1, elected = 0, relieved = 0 WHERE office_id = ?",
                   (office["id"],))

    db.commit()
    flash("Hard reset complete. All votes, codes, and postal votes cleared. Candidates reactivated. Generate new codes before voting.", "success")
    return redirect(url_for("admin_election_setup", election_id=election_id))


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
# Demo mode routes
# ---------------------------------------------------------------------------

DEMO_SETTINGS = {
    "congregation_name": "Free Reformed Church of Darling Downs",
    "congregation_short": "FRC Darling Downs",
    "wifi_ssid": "ChurchVote",
    "wifi_password": "",
    "voting_base_url": "http://192.168.8.100:5000",
    "is_demo": "1",
    "setup_complete": "1",
}

ELECTION_DATA_TABLES = [
    "votes", "paper_votes", "postal_votes", "codes",
    "candidates", "offices", "elections", "round_counts",
]


def _backup_database():
    """Create a timestamped backup of the database file. Returns backup path or None."""
    if not os.path.isfile(DB_PATH):
        return None
    backup_dir = os.path.join(BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"db_backup_{stamp}.sqlite")
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def _wipe_election_tables(db):
    """Delete all rows from election-data tables."""
    for table in ELECTION_DATA_TABLES:
        try:
            db.execute(f"DELETE FROM {table}")  # noqa: S608
        except Exception:
            pass
    db.commit()


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


def _create_demo_election(db, candidate_names):
    """Create the demo election with Elder and Deacon offices. Returns election id."""
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = db.execute(
        "INSERT INTO elections (name, max_rounds, current_round, voting_open, "
        "show_results, election_date) VALUES (?, 2, 1, 0, 0, ?)",
        (f"DEMO Election {today}", today),
    )
    election_id = cursor.lastrowid

    # Elder office — 3 vacancies, 6 candidates, max_selections = 3
    cursor = db.execute(
        "INSERT INTO offices (election_id, name, max_selections, vacancies, sort_order) "
        "VALUES (?, 'Elder', 3, 3, 1)",
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
        "INSERT INTO offices (election_id, name, max_selections, vacancies, sort_order) "
        "VALUES (?, 'Deacon', 2, 2, 2)",
        (election_id,),
    )
    deacon_office_id = cursor.lastrowid
    for i, name in enumerate(candidate_names[6:10]):
        db.execute(
            "INSERT INTO candidates (office_id, name, sort_order) VALUES (?, ?, ?)",
            (deacon_office_id, name, i + 1),
        )

    db.commit()
    return election_id


@app.route("/admin/load-demo", methods=["POST"])
@admin_required
def admin_load_demo():
    """Wipe election data and seed a demo election."""
    if request.form.get("confirm_text", "").strip() != "LOAD DEMO":
        flash("Load demo cancelled — type LOAD DEMO to confirm.", "error")
        return redirect(url_for("admin_dashboard"))

    if request.form.get("password") != get_setting("admin_password", DEFAULT_ADMIN_PASSWORD):
        flash("Load demo cancelled — incorrect password.", "error")
        return redirect(url_for("admin_dashboard"))

    # Backup
    _backup_database()

    db = get_db()

    # Wipe election data
    _wipe_election_tables(db)

    # Set demo congregation settings
    for key, value in DEMO_SETTINGS.items():
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    db.commit()

    # Generate candidate names
    member_names = _load_member_names(db)
    candidate_names = generate_demo_names(count=10, member_names=member_names)

    # Create demo election
    election_id = _create_demo_election(db, candidate_names)

    # Generate 20 voting codes
    codes = generate_codes(election_id, 20)

    # Open round 1 voting
    db.execute("UPDATE elections SET voting_open = 1 WHERE id = ?", (election_id,))
    db.commit()

    flash("Demo election loaded with Elder and Deacon offices, 20 voting codes, and round 1 open.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/exit-demo", methods=["POST"])
@admin_required
def admin_exit_demo():
    """Wipe the demo election and reset the app to initial state."""
    if request.form.get("confirm_text", "").strip() != "RESET":
        flash("Exit demo cancelled — type RESET to confirm.", "error")
        return redirect(url_for("admin_dashboard"))

    if request.form.get("password") != get_setting("admin_password", DEFAULT_ADMIN_PASSWORD):
        flash("Exit demo cancelled — incorrect password.", "error")
        return redirect(url_for("admin_dashboard"))

    # Backup
    _backup_database()

    db = get_db()

    # Wipe election data
    _wipe_election_tables(db)

    # Reset settings to defaults (setup_complete=0, is_demo=0)
    db.execute("DELETE FROM settings")
    db.commit()
    _init_db_on(db)

    # Delete demo PDFs if they exist
    for pdf_name in ("demo_code_slips.pdf", "demo_paper_ballots.pdf", "demo_dual_ballot_handout.pdf"):
        pdf_path = os.path.join(BASE_DIR, pdf_name)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

    flash("Demo exited and app reset. The setup wizard will run on next launch.", "success")
    return redirect(url_for("admin_setup"))


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
        "SELECT * FROM members ORDER BY last_name, first_name"
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
    election = db.execute(
        "SELECT * FROM elections WHERE voting_open = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # QR scan with code: validate immediately and skip to ballot
    if prefill_code:
        if not election:
            flash("Voting is not currently open.", "error")
        else:
            code = prefill_code.strip().upper()

            if len(code) != CODE_LENGTH:
                flash("Invalid code.", "error")
            else:
                code_h = hash_code(code)
                code_row = db.execute(
                    "SELECT * FROM codes WHERE code_hash = ? AND election_id = ?",
                    (code_h, election["id"])
                ).fetchone()

                if not code_row:
                    flash("Invalid code. Please check and try again.", "error")
                elif code_row["used"]:
                    flash("This code has already been used.", "error")
                else:
                    session["code_hash"] = code_h
                    session["election_id"] = election["id"]
                    session["used_code"] = code
                    session["_clear_stale_flashes"] = True
                    return redirect(url_for("voter_ballot"))

        # Validation failed — fall through to enter_code page (no prefill)
        prefill_code = None

    resp = make_response(render_template(
        "voter/enter_code.html", election=election, prefill_code=prefill_code
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

    if not election:
        flash("Voting is not currently open.", "error")
        return redirect(url_for("voter_enter_code"))

    code = request.form.get("code", "").strip().upper()

    if not code or len(code) != CODE_LENGTH:
        flash("Please enter a valid 6-character code.", "error")
        return redirect(url_for("voter_enter_code"))

    code_h = hash_code(code)
    code_row = db.execute(
        "SELECT * FROM codes WHERE code_hash = ? AND election_id = ?",
        (code_h, election["id"])
    ).fetchone()

    if not code_row:
        flash("Invalid code. Please check and try again.", "error")
        return redirect(url_for("voter_enter_code"))

    if code_row["used"]:
        flash("This code has already been used.", "error")
        return redirect(url_for("voter_enter_code"))

    session["code_hash"] = code_h
    session["election_id"] = election["id"]
    session["used_code"] = code
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

    # Double check code is still valid
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

    # Atomic transaction: burn code + record votes
    try:
        # Burn the code
        result = db.execute(
            "UPDATE codes SET used = 1 WHERE code_hash = ? AND used = 0",
            (code_h,)
        )
        if result.rowcount == 0:
            # Code was already used (race condition)
            db.rollback()
            session.pop("code_hash", None)
            session.pop("election_id", None)
            flash("This code has already been used.", "error")
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
    except Exception:
        db.rollback()
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("voter_enter_code"))

    # Clear session — no trace of the code
    session.pop("code_hash", None)
    session.pop("election_id", None)

    return redirect(url_for("voter_confirmation"))


@app.route("/confirmation")
def voter_confirmation():
    used_code = session.pop("used_code", None)
    resp = make_response(render_template("voter/confirmation.html", used_code=used_code))
    return no_cache(resp)


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
        if participants_r > 0 and vacancies > 0:
            t6a, t6b = calculate_thresholds(vacancies, valid_votes_r, participants_r)
        else:
            t6a, t6b = 0, 0

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

            total = digital + paper + postal
            passes_6a = False
            passes_6b = False
            if participants_r > 0 and vacancies > 0:
                _, passes_6a, passes_6b = check_candidate_elected(total, t6a, t6b)

            candidate_results.append({
                "name": cand["name"],
                "total": total,
                "elected": False,
                "passes_6a": passes_6a,
                "passes_6b": passes_6b,
            })

        resolve_elected_status(candidate_results, vacancies)

        votes_cast_for_office = sum(c["total"] for c in candidate_results)
        count_pass_6a = sum(1 for c in candidate_results if c["passes_6a"])
        count_pass_6b = sum(1 for c in candidate_results if c["passes_6b"])
        elected_count = sum(1 for c in candidate_results if c["elected"])
        remaining_vacancies = max(vacancies - elected_count, 0)
        runoff_needed = remaining_vacancies > 0 and elected_count < len(candidate_results)

        results.append({
            "office_name": office["name"],
            "office_id": office["id"],
            "vacancies": vacancies,
            "candidates": candidate_results,
            "max_selections": office["max_selections"],
            "votes_cast": votes_cast_for_office,
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
    vote_url = get_setting("voting_base_url", "http://192.168.8.100:5000")

    paper_guide = [
        {
            "office_name": r["office_name"],
            "names": [c["name"] for c in r["candidates"]],
        }
        for r in results if r["inactive_names"]
    ]

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
    else:
        return render_template("display/projector.html", **ctx)


@app.route("/displayphone")
def display_phone():
    election, ctx = _build_display_data()
    if not election:
        return render_template("display/waiting.html")
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
            if participants_api > 0 and vacancies > 0:
                t6a, t6b = calculate_thresholds(vacancies, valid_votes_api, participants_api)
            else:
                t6a, t6b = 0, 0

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

                total = digital + paper + postal
                passes_6a = False
                passes_6b = False
                if participants_api > 0 and vacancies > 0:
                    _, passes_6a, passes_6b = check_candidate_elected(total, t6a, t6b)

                candidate_results.append({
                    "name": cand["name"],
                    "total": total,
                    "elected": False,
                    "passes_6a": passes_6a,
                    "passes_6b": passes_6b,
                })

            resolve_elected_status(candidate_results, vacancies)

            votes_cast_for_office = sum(c["total"] for c in candidate_results)
            count_pass_6a = sum(1 for c in candidate_results if c["passes_6a"])
            count_pass_6b = sum(1 for c in candidate_results if c["passes_6b"])
            elected_count = sum(1 for c in candidate_results if c["elected"])
            remaining_vacancies = max(vacancies - elected_count, 0)
            runoff_needed = remaining_vacancies > 0 and elected_count < len(candidate_results)

            results.append({
                "office_name": office["name"],
                "candidates": candidate_results,
                "max_selections": office["max_selections"],
                "votes_cast": votes_cast_for_office,
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
        data["valid_votes_cast"] = valid_votes_api

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
        return redirect(url_for("admin_codes", election_id=election_id))

    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    is_demo = get_setting("is_demo", "0") == "1"

    buf = generate_code_slips_pdf(
        codes=codes,
        election_name=election["name"],
        short_name=get_setting("congregation_short", "FRC"),
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://192.168.8.100:5000"),
        is_demo=is_demo,
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
    is_demo = get_setting("is_demo", "0") == "1"

    buf = generate_counter_sheet_pdf(
        election_name=election["name"],
        congregation_name=cong_name,
        offices_data=offices_data,
        member_count=member_count,
        is_demo=is_demo,
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
    is_demo = get_setting("is_demo", "0") == "1"

    buf = generate_paper_ballot_pdf(
        election_name=election["name"],
        round_number=round_number,
        office_data=office_data,
        member_count=member_count,
        is_demo=is_demo,
    )
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"paper_ballot_round_{round_number}.pdf")


@app.route("/admin/election/<int:election_id>/dual-ballot-pdf")
@admin_required
def admin_dual_ballot_pdf(election_id):
    """Generate dual ballot handout PDF (demo mode only)."""
    if get_setting("is_demo", "0") != "1":
        abort(403)

    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)

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

    codes = load_codes_from_db(election_id)
    if not codes:
        flash("Codes are not available. Delete and regenerate codes to get a new PDF.", "error")
        return redirect(url_for("admin_codes", election_id=election_id))

    buf = generate_dual_ballot_handout_pdf(
        election_name=election["name"],
        congregation_name=get_setting("congregation_name", "Free Reformed Church"),
        office_data=office_data,
        codes=codes[:20],
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://192.168.8.100:5000"),
    )

    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name="demo_dual_ballot_handout.pdf")


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
        return redirect(url_for("admin_codes", election_id=election_id))

    # Filter to only unused codes
    used_hashes = set()
    for row in db.execute("SELECT code_hash FROM codes WHERE election_id = ? AND used = 1", (election_id,)):
        used_hashes.add(row["code_hash"])

    unused_codes = [c for c in codes if hash_code(c) not in used_hashes]

    if not unused_codes:
        flash("All codes have been used. Generate new codes first.", "error")
        return redirect(url_for("admin_codes", election_id=election_id))

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

    is_demo = get_setting("is_demo", "0") == "1"
    filename = "demo_dual_sided_ballots.pdf" if is_demo else "dual_sided_ballots.pdf"

    buf = generate_dual_sided_ballots_pdf(
        election_name=election["name"],
        short_name=get_setting("congregation_short", "FRC"),
        round_number=election["current_round"],
        office_data=office_data,
        codes=unused_codes,
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://192.168.8.100:5000"),
        member_count=election["participants"] or 0,
        is_demo=is_demo,
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
        return redirect(url_for("admin_codes", election_id=election_id))

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

    is_demo = get_setting("is_demo", "0") == "1"
    cong_name = get_setting("congregation_name", "Free Reformed Church")

    buf = generate_printer_pack_zip(
        election_name=election["name"],
        short_name=get_setting("congregation_short", "FRC"),
        round_number=election["current_round"],
        office_data=office_data,
        codes=unused_codes,
        wifi_ssid=get_setting("wifi_ssid", "ChurchVote"),
        wifi_password=get_setting("wifi_password", ""),
        base_url=get_setting("voting_base_url", "http://192.168.8.100:5000"),
        congregation_name=cong_name,
        members=[dict(m) for m in members],
        election_date=election["election_date"],
        member_count=election["participants"] or 0,
        is_demo=is_demo,
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

    is_demo = get_setting("is_demo", "0") == "1"
    buf = generate_results_pdf(
        election_name=election["name"],
        rounds_data=rounds_data,
        is_demo=is_demo,
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
            vacancies = office["vacancies"] or office["max_selections"]

            candidates = db.execute(
                "SELECT * FROM candidates WHERE office_id = ? "
                "ORDER BY surname_sort_key(name)",
                (office["id"],)
            ).fetchall()

            # Thresholds
            t6a, t6b = (0, 0)
            if participants > 0 and vacancies > 0:
                t6a, t6b = calculate_thresholds(
                    vacancies, total_ballots, participants
                )

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

                total = digital + paper + postal
                passes_6a = False
                passes_6b = False
                if participants > 0 and vacancies > 0:
                    _, passes_6a, passes_6b = check_candidate_elected(total, t6a, t6b)

                cand_list.append({
                    "name": cand["name"],
                    "digital": digital,
                    "paper": paper,
                    "postal": postal,
                    "total": total,
                    "elected": False,
                    "passes_6a": passes_6a,
                    "passes_6b": passes_6b,
                })

            resolve_elected_status(cand_list, vacancies)

            offices_list.append({
                "name": office["name"],
                "vacancies": vacancies,
                "max_selections": office["max_selections"],
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

    # Build elected summary from the final round
    elected_summary = []
    if rounds_data:
        last_round = rounds_data[-1]
        for office in last_round["offices"]:
            elected_names = [
                c["name"] for c in office["candidates"] if c["elected"]
            ]
            elected_summary.append({
                "office": office["name"],
                "names": elected_names,
            })

    is_demo = get_setting("is_demo", "0") == "1"
    buf = generate_minutes_docx(
        congregation_name=congregation_name,
        election_name=election["name"],
        election_date=election["election_date"] or "",
        rounds_data=rounds_data,
        elected_summary=elected_summary,
        is_demo=is_demo,
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


@app.route("/api/captive-portal")
@app.route("/.well-known/captive-portal")
def captive_portal_api():
    """RFC 8908 Captive Portal API — tells phones the network is open."""
    from flask import Response, json as flask_json
    data = flask_json.dumps({"captive": False})
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
    """Redirect unknown paths to the voting entry page."""
    return redirect("/", code=302)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()
    migrate_db()

if __name__ == "__main__":
    print("Do not run this file directly. Use start.bat (Windows) or run.sh (Linux/Mac).")
    print("See docs/SETUP.md for instructions.")
