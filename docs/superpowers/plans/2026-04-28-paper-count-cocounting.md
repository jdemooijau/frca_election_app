# Paper Ballot Co-Counting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in per-election helper that lets multiple volunteers co-count paper ballots from their phones during the chairman read-out, with admin-supervised consensus across helpers and one-click persist of agreed totals to a side-table.

**Architecture:** New routes on the existing Flask app. New SQLite tables (`count_sessions`, `count_session_helpers`, `count_session_tallies`, `count_session_results`). Two new templates (`admin/count.html`, `voter/count_helper.html`). Polling-based live updates, no websockets. Existing paper-vote flow untouched.

**Tech Stack:** Flask 3, sqlite3 (stdlib), Jinja2, vanilla JS, no build step. Pytest for backend tests.

**Spec:** `docs/superpowers/specs/2026-04-28-paper-count-cocounting-design.md`

---

## File Structure

**Create:**
- `voting-app/templates/admin/count.html` - admin live consensus dashboard
- `voting-app/templates/voter/count_helper.html` - helper tap grid + end-state screens
- `voting-app/tests/test_paper_count.py` - backend tests for new routes / consensus logic

**Modify:**
- `voting-app/app.py` - migration, 9 routes, consensus helper, soft/hard-reset hooks
- `voting-app/templates/admin/election_setup.html` - opt-in checkbox + form
- `voting-app/templates/admin/manage.html` - dashboard link
- `voting-app/templates/voter/confirmation.html` - "Assist with Paper Counting" button
- `voting-app/static/css/style.css` - count UI styles

---

## Conventions used by the existing codebase

The engineer should match these:

- All admin routes use `@admin_required` decorator (defined at line ~400 of `app.py`).
- DB connection: `db = get_db()` returns a sqlite3 connection (Row factory).
- Migrations: append a string to the `migrations` list inside `_migrate_db_on()` (line ~354). Each `ALTER` is wrapped in a try/except that swallows `OperationalError` so reruns are safe. For new tables, `CREATE TABLE IF NOT EXISTS` belongs in `init_db()` (line ~125) **and** can also be added to `_migrate_db_on()` for existing databases.
- Audit log: `log_voter_audit(election_id, code, result, detail=None, round_number=None)` is the existing helper (line ~415).
- Voter session keys: `session["used_code"]` (plaintext code, set at successful submit), `session["election_id"]`, `session["code_hash"]`. Currently `voter_confirmation` (line 2473) **pops** `used_code` on first GET; we will change that.
- CSRF: all POST forms include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
- Surname sort: `surname_sort_key(name)` is registered as a SQLite function and used in `ORDER BY surname_sort_key(name)`.

---

### Task 1: Database migration

**Files:**
- Modify: `voting-app/app.py:125-275` (init_db CREATE TABLE block)
- Modify: `voting-app/app.py:354-388` (_migrate_db_on)
- Test: `voting-app/tests/test_paper_count.py` (new)

- [ ] **Step 1: Write failing test for schema**

Create `voting-app/tests/test_paper_count.py`:

```python
"""Tests for the paper ballot co-counting feature."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db, get_db


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    import app as app_module
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client
    app_module.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)


def test_paper_count_enabled_column_exists(client):
    with app.app_context():
        cols = [r["name"] for r in get_db().execute("PRAGMA table_info(elections)")]
        assert "paper_count_enabled" in cols


def test_count_sessions_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_sessions'"
        ).fetchone()
        assert rows is not None


def test_count_session_helpers_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_session_helpers'"
        ).fetchone()
        assert rows is not None


def test_count_session_tallies_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_session_tallies'"
        ).fetchone()
        assert rows is not None


def test_count_session_results_table_exists(client):
    with app.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='count_session_results'"
        ).fetchone()
        assert rows is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: 5 FAILs (column / tables don't exist).

- [ ] **Step 3: Add new tables to init_db**

In `voting-app/app.py`, inside `init_db()` (after the existing `voter_audit_log` block ending around line 268), add:

```python
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
```

- [ ] **Step 4: Add migrations for existing databases**

In `_migrate_db_on()` (around line 356), append to the `migrations` list:

```python
        "ALTER TABLE elections ADD COLUMN paper_count_enabled INTEGER NOT NULL DEFAULT 0",
```

Then below the existing `for sql in migrations:` loop, add the same `executescript` block from Step 3 (so existing databases get the new tables). Use `CREATE TABLE IF NOT EXISTS` so it's idempotent. Wrap in try/except since it will run multiple times.

```python
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS count_sessions ( ... );  -- copy from Step 3
            ...
        """)
        db.commit()
    except sqlite3.OperationalError:
        pass
```

(Engineer: paste the same script body as Step 3.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add voting-app/app.py voting-app/tests/test_paper_count.py
git commit -m "Paper count: add schema (4 tables + paper_count_enabled column)"
```

---

### Task 2: Election-level paper_count_enabled toggle

**Files:**
- Modify: `voting-app/app.py` (new route `admin_election_settings_post`)
- Modify: `voting-app/templates/admin/election_setup.html`
- Test: `voting-app/tests/test_paper_count.py`

The existing `admin_election_setup` POST handler is dedicated to adding offices; do not overload it. Add a new small route specifically for election-level settings.

- [ ] **Step 1: Write failing test for the toggle**

Append to `tests/test_paper_count.py`:

```python
def _create_election(client):
    """Helper: log in as admin and create an election. Returns election_id."""
    # Login (the app uses session-based admin auth)
    with client.session_transaction() as sess:
        sess["admin"] = True
    resp = client.post("/admin/election/new", data={
        "name": "Test", "max_rounds": "2", "election_date": "2026-04-28"
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        row = get_db().execute("SELECT id FROM elections ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"]


def test_paper_count_toggle_via_settings_post(client):
    election_id = _create_election(client)
    # Default off
    with app.app_context():
        row = get_db().execute(
            "SELECT paper_count_enabled FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        assert row["paper_count_enabled"] == 0
    # Enable
    resp = client.post(f"/admin/election/{election_id}/settings", data={
        "paper_count_enabled": "1"
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        row = get_db().execute(
            "SELECT paper_count_enabled FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        assert row["paper_count_enabled"] == 1
    # Disable
    resp = client.post(f"/admin/election/{election_id}/settings", data={})
    assert resp.status_code in (200, 302)
    with app.app_context():
        row = get_db().execute(
            "SELECT paper_count_enabled FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        assert row["paper_count_enabled"] == 0
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py::test_paper_count_toggle_via_settings_post -v
```

Expected: FAIL (route 404).

- [ ] **Step 3: Add the settings route**

In `voting-app/app.py`, add after `admin_election_setup` (around line 764):

```python
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
        return redirect(url_for("admin_election_setup", election_id=election_id))

    paper_count_enabled = 1 if request.form.get("paper_count_enabled") == "1" else 0
    db.execute(
        "UPDATE elections SET paper_count_enabled = ? WHERE id = ?",
        (paper_count_enabled, election_id)
    )
    db.commit()
    flash("Settings updated.", "success")
    return redirect(url_for("admin_election_setup", election_id=election_id))
```

- [ ] **Step 4: Add the checkbox form to election_setup.html**

In `voting-app/templates/admin/election_setup.html`, add a new section above the "Existing offices" block (before the `{% if offices %}` line around line 34):

```html
    <details class="card" style="margin-bottom: 14px;">
        <summary style="cursor: pointer; font-weight: 600;">Election settings</summary>
        <form method="POST" action="{{ url_for('admin_election_settings', election_id=election.id) }}" style="margin-top: 12px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <label style="display: flex; align-items: center; gap: 8px;">
                <input type="checkbox" name="paper_count_enabled" value="1"
                       {% if election.paper_count_enabled %}checked{% endif %}>
                <span>
                    <strong>Enable paper count helper</strong>
                    <span style="display: block; font-size: 13px; color: #666;">
                        Volunteers can opt in to co-count paper ballots on their phones during the chairman's read-out.
                    </span>
                </span>
            </label>
            <button type="submit" class="btn btn-outline btn-small" style="margin-top: 8px;">Save settings</button>
        </form>
    </details>
```

- [ ] **Step 5: Run test, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py::test_paper_count_toggle_via_settings_post -v
```

Expected: PASS.

- [ ] **Step 6: Manual verify**

Run the app (`./run.sh` or `python app.py`), create an election, navigate to Setup, expand "Election settings", check the box, save. Reload and confirm checkbox is checked. Open voting and verify the form does not allow changing the toggle (flash error).

- [ ] **Step 7: Commit**

```bash
git add voting-app/app.py voting-app/templates/admin/election_setup.html voting-app/tests/test_paper_count.py
git commit -m "Paper count: add per-election opt-in toggle in setup"
```

---

### Task 3: Helper join + lazy session creation (backend)

**Files:**
- Modify: `voting-app/app.py` (new route `count_join`, helper functions)
- Modify: `voting-app/app.py:2475` (stop popping `used_code`)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing test for join flow**

Append to `tests/test_paper_count.py`:

```python
def _setup_paper_count_election(client):
    """Create election, enable paper count, add 2 offices, generate codes, close voting."""
    election_id = _create_election(client)
    # Enable paper count
    client.post(f"/admin/election/{election_id}/settings", data={"paper_count_enabled": "1"})
    # Add an office and candidates via setup
    client.post(f"/admin/election/{election_id}/setup", data={
        "office_name": "Elder", "vacancies": "2", "max_selections": "2",
        "candidate_names": "Smith\nJones\nBrown\nWhite",
        "confirm_slate_override": "1",
    })
    # Generate codes (1 code so we have a known plaintext)
    client.post(f"/admin/election/{election_id}/codes", data={"count": "3"})
    with app.app_context():
        codes = get_db().execute(
            "SELECT plaintext FROM codes WHERE election_id = ?", (election_id,)
        ).fetchall()
        return election_id, [c["plaintext"] for c in codes]


def test_count_join_creates_session_and_helper(client):
    election_id, codes = _setup_paper_count_election(client)
    # Open voting then close it
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    # Simulate burned-code session
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
        sess.pop("admin", None)
    resp = client.post("/count/join", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/count/")
    # DB state
    with app.app_context():
        sess_row = get_db().execute(
            "SELECT * FROM count_sessions WHERE election_id = ?", (election_id,)
        ).fetchone()
        assert sess_row is not None
        assert sess_row["status"] == "active"
        helper_row = get_db().execute(
            "SELECT * FROM count_session_helpers WHERE session_id = ?", (sess_row["id"],)
        ).fetchone()
        assert helper_row["voter_code"] == codes[0]
        assert helper_row["short_id"] == codes[0][-6:].upper()


def test_count_join_idempotent(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
    client.post("/count/join")
    client.post("/count/join")  # re-join
    with app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) AS n FROM count_session_helpers"
        ).fetchone()["n"]
        assert n == 1


def test_count_join_blocked_when_disabled(client):
    election_id = _create_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    with client.session_transaction() as sess:
        sess["used_code"] = "DUMMYCODE"
        sess["election_id"] = election_id
    resp = client.post("/count/join")
    assert resp.status_code in (400, 403)
```

(Engineer: the existing voting/toggle route is at `/admin/election/<id>/voting/toggle` - confirm by reading `app.py` around line 920. Adjust if path differs.)

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k test_count_join
```

Expected: 3 FAILs (route 404).

- [ ] **Step 3: Stop popping `used_code` in voter_confirmation**

In `voting-app/app.py` line 2475, change:

```python
@app.route("/confirmation")
def voter_confirmation():
    used_code = session.pop("used_code", None)
```

to:

```python
@app.route("/confirmation")
def voter_confirmation():
    used_code = session.get("used_code")
```

The code remains in session so the "Assist with Paper Counting" button can use it. The session is short-lived and the code is already burned; this is not a security regression.

- [ ] **Step 4: Add helper functions and the join route**

In `voting-app/app.py`, add a new section near other voter routes (before `# Projector display` divider around line 2480):

```python
# ---------------------------------------------------------------------------
# Paper ballot co-counting
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _short_id_from_code(code):
    return (code or "")[-6:].upper()


def _get_or_create_count_session(db, election_id, round_no):
    """Find or create the count_sessions row for this (election, round). Returns the row."""
    row = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if row:
        return row
    db.execute(
        "INSERT INTO count_sessions (election_id, round_no, status, started_at) "
        "VALUES (?, ?, 'active', ?)",
        (election_id, round_no, _now_iso())
    )
    db.commit()
    return db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()


def _paper_count_active_for_round(db, election):
    """Return True if paper count is enabled for this election AND voting is closed for the current round AND no session is persisted/cancelled."""
    if not election["paper_count_enabled"]:
        return False
    if election["voting_open"]:
        return False
    sess = db.execute(
        "SELECT status FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election["id"], election["current_round"])
    ).fetchone()
    if sess and sess["status"] in ("persisted", "cancelled"):
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
    if election["voting_open"]:
        return ("Voting still open", 400)

    sess = _get_or_create_count_session(db, election_id, election["current_round"])
    if sess["status"] != "active":
        return ("Session is not active", 400)

    # Find or create helper row
    helper = db.execute(
        "SELECT * FROM count_session_helpers WHERE session_id = ? AND voter_code = ?",
        (sess["id"], code)
    ).fetchone()
    now = _now_iso()
    if helper is None:
        db.execute(
            "INSERT INTO count_session_helpers "
            "(session_id, voter_code, short_id, joined_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sess["id"], code, _short_id_from_code(code), now, now)
        )
        db.commit()
        log_voter_audit(
            election_id, code, "paper_count_helper_joined",
            detail=_short_id_from_code(code),
            round_number=election["current_round"]
        )
    else:
        db.execute(
            "UPDATE count_session_helpers SET last_seen_at = ? WHERE id = ?",
            (now, helper["id"])
        )
        db.commit()
    return redirect(url_for("count_helper_page", session_id=sess["id"]))


@app.route("/count/<int:session_id>")
def count_helper_page(session_id):
    """Helper grid. Filled in by Task 4."""
    return ("Helper page placeholder", 200)
```

(`datetime` is already imported. Confirm import at top of file.)

- [ ] **Step 5: Run tests, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k test_count_join
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add voting-app/app.py voting-app/tests/test_paper_count.py
git commit -m "Paper count: helper join + lazy session creation"
```

---

### Task 4: Helper grid template (server-rendered, no JS yet)

**Files:**
- Create: `voting-app/templates/voter/count_helper.html`
- Modify: `voting-app/app.py` (flesh out `count_helper_page`)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing test for the helper page**

Append to `tests/test_paper_count.py`:

```python
def test_count_helper_page_shows_candidates(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
    join_resp = client.post("/count/join")
    assert join_resp.status_code == 302
    helper_resp = client.get(join_resp.headers["Location"])
    assert helper_resp.status_code == 200
    body = helper_resp.get_data(as_text=True)
    # Header shows last 6 chars of code
    assert codes[0][-6:].upper() in body
    # Candidates appear (surnames only)
    assert "Smith" in body
    assert "Jones" in body
    # The −1 pill text appears once per candidate
    assert body.count("−1") >= 4
    # No running count number is rendered next to surnames in initial HTML
    # (counts are server-only; helper UI shows nothing)
    assert "data-count=\"0\"" in body or "data-count='0'" in body or "Smith</span>" in body
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py::test_count_helper_page_shows_candidates -v
```

Expected: FAIL (placeholder body).

- [ ] **Step 3: Replace `count_helper_page` with the real handler**

Replace the placeholder in `app.py`:

```python
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
    if not helper:
        # Voter is not a helper in this session; bounce to voter entry.
        return redirect(url_for("voter_enter_code"))

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
```

- [ ] **Step 4: Create the template**

Create `voting-app/templates/voter/count_helper.html`:

```html
{% extends "base.html" %}
{% block title %}Counter {{ helper.short_id }}{% endblock %}
{% block content %}
{% if state == "active" %}
<div class="count-helper-page">
    <div class="count-helper-header">
        <span class="count-helper-id">Counter {{ helper.short_id }}</span>
        <button type="button" id="count-done-btn" class="btn btn-outline btn-small">Done</button>
    </div>
    <div class="count-grid"
         data-session-id="{{ sess.id }}"
         data-tap-url="{{ url_for('count_tap', session_id=sess.id) }}"
         data-done-url="{{ url_for('count_done', session_id=sess.id) }}"
         data-heartbeat-url="{{ url_for('count_heartbeat', session_id=sess.id) }}">
        {% for office in offices %}
        <div class="count-office">
            <h3 class="count-office-title">{{ office.name|upper }}</h3>
            <ul class="count-candidate-list">
                {% for cand in candidates_by_office[office.id] %}
                <li class="count-candidate-row" data-candidate-id="{{ cand.id }}">
                    <button type="button" class="count-plus-btn" data-delta="1">
                        <span class="count-surname">{{ cand.name }}</span>
                    </button>
                    <button type="button" class="count-minus-btn" data-delta="-1" aria-label="minus 1">−1</button>
                </li>
                {% endfor %}
            </ul>
        </div>
        {% endfor %}
    </div>
</div>
{% elif state == "thanks" %}
<div class="count-end-screen">
    <div class="checkmark" aria-hidden="true">&#10003;</div>
    <h2>Thanks for helping count.</h2>
    <a href="{{ url_for('voter_enter_code') }}" class="btn btn-outline">Done</a>
</div>
{% elif state == "cancelled" %}
<div class="count-end-screen">
    <h2>Counting was cancelled.</h2>
    <a href="{{ url_for('voter_enter_code') }}" class="btn btn-outline">Done</a>
</div>
{% endif %}
{% endblock %}
```

(JS will be added in Task 6. The template references `count_tap`, `count_done`, `count_heartbeat` routes that don't exist yet - the page will render but JS won't work. That's OK for this task.)

- [ ] **Step 5: Stub the routes that the template references (so url_for works)**

In `app.py`, add stub routes (will be filled in Task 5 and 6):

```python
@app.route("/count/<int:session_id>/tap", methods=["POST"])
def count_tap(session_id):
    return ("Not implemented", 501)


@app.route("/count/<int:session_id>/done", methods=["POST"])
def count_done(session_id):
    return ("Not implemented", 501)


@app.route("/count/<int:session_id>/heartbeat", methods=["GET"])
def count_heartbeat(session_id):
    return ("Not implemented", 501)
```

- [ ] **Step 6: Run, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: all paper-count tests PASS, no regressions in other tests.

- [ ] **Step 7: Manual verify**

Run the app. Create an election with paper count enabled, add Elder + Deacon offices with 4 candidates each. Cast a vote on a phone. After confirmation page, navigate by URL to `/count/1` (replacing 1 with the actual session id from db). Verify the grid shows all 8 candidates, two columns in landscape, no scroll.

- [ ] **Step 8: Commit**

```bash
git add voting-app/app.py voting-app/templates/voter/count_helper.html voting-app/tests/test_paper_count.py
git commit -m "Paper count: helper grid template (server-rendered, no JS)"
```

---

### Task 5: Tap and Done endpoints

**Files:**
- Modify: `voting-app/app.py` (flesh out `count_tap`, `count_done`, `count_heartbeat`)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_paper_count.py`:

```python
def _join_count(client, election_id, code):
    with client.session_transaction() as sess:
        sess["used_code"] = code
        sess["election_id"] = election_id
    resp = client.post("/count/join", follow_redirects=False)
    return int(resp.headers["Location"].rsplit("/", 1)[-1])


def _candidate_ids(election_id):
    with app.app_context():
        rows = get_db().execute(
            "SELECT c.id FROM candidates c "
            "JOIN offices o ON c.office_id = o.id "
            "WHERE o.election_id = ? ORDER BY c.id",
            (election_id,)
        ).fetchall()
        return [r["id"] for r in rows]


def test_count_tap_increments_and_decrements(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)

    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 200
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 200
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": -1})
    assert r.status_code == 200

    with app.app_context():
        row = get_db().execute(
            "SELECT count FROM count_session_tallies WHERE candidate_id = ?", (cands[0],)
        ).fetchone()
        assert row["count"] == 1


def test_count_tap_clamps_at_zero(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": -1})
    assert r.status_code == 200
    with app.app_context():
        row = get_db().execute(
            "SELECT count FROM count_session_tallies WHERE candidate_id = ?", (cands[0],)
        ).fetchone()
        assert row["count"] == 0


def test_count_done_marks_helper_and_locks_taps(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    r = client.post(f"/count/{sid}/done", json={})
    assert r.status_code == 200
    # After done, taps must be rejected
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 403


def test_count_heartbeat_returns_session_status(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    r = client.get(f"/count/{sid}/heartbeat")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["session_status"] == "active"
    assert payload["helper_done"] is False
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k tap or done or heartbeat
```

Expected: 4 FAILs.

- [ ] **Step 3: Implement the endpoints**

Replace the three stubs in `app.py` with:

```python
def _resolve_helper(db, session_id, voter_code):
    """Return (sess_row, helper_row) or (None, None) if not a member."""
    sess = db.execute("SELECT * FROM count_sessions WHERE id = ?", (session_id,)).fetchone()
    if not sess:
        return None, None
    helper = db.execute(
        "SELECT * FROM count_session_helpers WHERE session_id = ? AND voter_code = ?",
        (session_id, voter_code)
    ).fetchone()
    return sess, helper


@app.route("/count/<int:session_id>/tap", methods=["POST"])
def count_tap(session_id):
    code = session.get("used_code")
    if not code:
        return ("Not eligible", 403)
    db = get_db()
    sess, helper = _resolve_helper(db, session_id, code)
    if sess is None or helper is None:
        return ("Not a member", 403)
    if sess["status"] != "active":
        return ("Session not active", 403)
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

    # Verify candidate belongs to this election (defence in depth)
    cand = db.execute(
        "SELECT c.id FROM candidates c JOIN offices o ON c.office_id = o.id "
        "WHERE c.id = ? AND o.election_id = ?",
        (candidate_id, sess["election_id"])
    ).fetchone()
    if not cand:
        return ("Bad candidate", 400)

    # Atomic upsert: ensure row exists, then update with clamp.
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
    db.execute(
        "UPDATE count_session_helpers SET last_seen_at = ? WHERE id = ?",
        (_now_iso(), helper["id"])
    )
    db.commit()
    return ("", 200)


@app.route("/count/<int:session_id>/done", methods=["POST"])
def count_done(session_id):
    code = session.get("used_code")
    if not code:
        return ("Not eligible", 403)
    db = get_db()
    sess, helper = _resolve_helper(db, session_id, code)
    if sess is None or helper is None:
        return ("Not a member", 403)
    if sess["status"] != "active":
        return ("Session not active", 403)
    if helper["marked_done_at"]:
        return ("Already done", 200)
    db.execute(
        "UPDATE count_session_helpers SET marked_done_at = ?, last_seen_at = ? WHERE id = ?",
        (_now_iso(), _now_iso(), helper["id"])
    )
    db.commit()
    return ("", 200)


@app.route("/count/<int:session_id>/heartbeat", methods=["GET"])
def count_heartbeat(session_id):
    code = session.get("used_code")
    if not code:
        return jsonify({"error": "not eligible"}), 403
    db = get_db()
    sess, helper = _resolve_helper(db, session_id, code)
    if sess is None or helper is None:
        return jsonify({"error": "not a member"}), 403
    db.execute(
        "UPDATE count_session_helpers SET last_seen_at = ? WHERE id = ?",
        (_now_iso(), helper["id"])
    )
    db.commit()
    return jsonify({
        "session_status": sess["status"],
        "helper_done": bool(helper["marked_done_at"]),
    })
```

(`jsonify` should already be imported. Confirm.)

- [ ] **Step 4: Run, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add voting-app/app.py voting-app/tests/test_paper_count.py
git commit -m "Paper count: tap, done, heartbeat endpoints"
```

---

### Task 6: Helper grid JS (taps, heartbeat, end-state transitions)

**Files:**
- Modify: `voting-app/templates/voter/count_helper.html` (add `<script>` block)

- [ ] **Step 1: Add the JS to count_helper.html**

In `voting-app/templates/voter/count_helper.html`, just before `{% endblock %}`, add:

```html
{% if state == "active" %}
<script>
(function() {
    const grid = document.querySelector(".count-grid");
    if (!grid) return;
    const tapUrl = grid.dataset.tapUrl;
    const doneUrl = grid.dataset.doneUrl;
    const heartbeatUrl = grid.dataset.heartbeatUrl;

    function pulse(row, ok) {
        row.classList.add(ok ? "count-row-flash-ok" : "count-row-flash-fail");
        setTimeout(() => {
            row.classList.remove("count-row-flash-ok");
            row.classList.remove("count-row-flash-fail");
        }, 150);
    }

    async function postTap(candidateId, delta, row) {
        try {
            const r = await fetch(tapUrl, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({candidate_id: candidateId, delta: delta})
            });
            pulse(row, r.ok);
            if (!r.ok) row.classList.add("count-row-error");
            else row.classList.remove("count-row-error");
        } catch (e) {
            pulse(row, false);
            row.classList.add("count-row-error");
        }
    }

    grid.addEventListener("click", function(ev) {
        const plusBtn = ev.target.closest(".count-plus-btn");
        const minusBtn = ev.target.closest(".count-minus-btn");
        const btn = plusBtn || minusBtn;
        if (!btn) return;
        const row = btn.closest(".count-candidate-row");
        if (!row) return;
        ev.stopPropagation();
        const candidateId = parseInt(row.dataset.candidateId, 10);
        const delta = btn === plusBtn ? 1 : -1;
        postTap(candidateId, delta, row);
    });

    const doneBtn = document.getElementById("count-done-btn");
    doneBtn.addEventListener("click", async function() {
        if (!confirm("Mark yourself as Done? You will not be able to tap again.")) return;
        await fetch(doneUrl, {method: "POST"});
        window.location.reload();  // server will render the Thanks screen
    });

    async function heartbeat() {
        try {
            const r = await fetch(heartbeatUrl);
            if (!r.ok) return;
            const data = await r.json();
            if (data.session_status !== "active" || data.helper_done) {
                window.location.reload();
            }
        } catch (e) {
            // ignore
        }
    }
    setInterval(heartbeat, 5000);
})();
</script>
{% endif %}
```

- [ ] **Step 2: Manual verify**

Run the app. Open helper grid on a phone (or DevTools mobile mode). Tap a surname row, verify a brief flash. Tap −1, verify another flash. Tap "Done", confirm, verify page replaces with "Thanks". On admin's psql/sqlite check, verify count went up correctly.

- [ ] **Step 3: Commit**

```bash
git add voting-app/templates/voter/count_helper.html
git commit -m "Paper count: helper grid JS (taps, heartbeat, done transition)"
```

---

### Task 7: "Assist with Paper Counting" button on confirmation page

**Files:**
- Modify: `voting-app/app.py:2473-2477` (pass paper-count gating to template)
- Modify: `voting-app/templates/voter/confirmation.html`

- [ ] **Step 1: Update voter_confirmation to pass gating context**

Replace `voter_confirmation` (line 2473-2477):

```python
@app.route("/confirmation")
def voter_confirmation():
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
        show_assist=show_assist
    ))
    return no_cache(resp)
```

- [ ] **Step 2: Add the button to confirmation.html**

In `voting-app/templates/voter/confirmation.html`, before the closing `</div>` of the container (after the "View Live Results" link), add:

```html
    {% if show_assist %}
    <hr style="border: none; border-top: 1px solid #ddd; margin: 16px 0;">
    <div style="text-align: center;">
        <form method="POST" action="{{ url_for('count_join') }}" style="display: inline;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" class="btn btn-outline btn-small">Assist with Paper Counting</button>
        </form>
        <p style="font-size: 12px; color: #888; margin-top: 6px;">
            Help count paper ballots from your phone.
        </p>
    </div>
    {% endif %}
```

- [ ] **Step 3: Manual verify**

Run the app. Vote on a phone. After confirmation, verify:
- If paper count is **disabled** for the election: button does NOT appear.
- If paper count is **enabled** but voting is open: button does NOT appear.
- If paper count is **enabled** and voting is closed for the round: button appears. Tap it. Verify redirect to helper grid.

- [ ] **Step 4: Commit**

```bash
git add voting-app/app.py voting-app/templates/voter/confirmation.html
git commit -m "Paper count: 'Assist with Paper Counting' button on confirmation page"
```

---

### Task 8: Admin dashboard skeleton + link in manage

**Files:**
- Modify: `voting-app/app.py` (new route `admin_count_dashboard`)
- Create: `voting-app/templates/admin/count.html`
- Modify: `voting-app/templates/admin/manage.html` (add link)

- [ ] **Step 1: Add the admin dashboard route**

In `voting-app/app.py`, after `count_helper_page`:

```python
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
```

- [ ] **Step 2: Create the dashboard template (skeleton; polling JS in Task 9)**

Create `voting-app/templates/admin/count.html`:

```html
{% extends "base.html" %}
{% block title %}Paper Count - {{ election.name }} - Round {{ round_no }}{% endblock %}
{% block content %}
<div class="admin-header">
    <h1>Paper Count - Round {{ round_no }}</h1>
    <a href="{{ url_for('admin_election_manage', election_id=election.id) }}">Back to Manage</a>
</div>
<div class="container-wide">
    <div class="count-dashboard"
         data-state-url="{{ url_for('admin_count_state', election_id=election.id, round_no=round_no) }}"
         data-disregard-url="{{ url_for('admin_count_disregard', election_id=election.id, round_no=round_no) }}"
         data-persist-url="{{ url_for('admin_count_persist', election_id=election.id, round_no=round_no) }}"
         data-cancel-url="{{ url_for('admin_count_cancel', election_id=election.id, round_no=round_no) }}"
         data-session-status="{{ sess.status }}">

        <div class="count-dashboard-header">
            <span id="count-summary">N helpers joined - M done</span>
            <button type="button" id="count-cancel-btn" class="btn btn-outline btn-small">Cancel session</button>
        </div>

        <div id="count-banner" class="count-banner count-banner-grey">No data yet.</div>

        <div id="count-table-host"><!-- populated by JS --></div>

        <div style="margin-top: 16px;">
            <button type="button" id="count-persist-btn" class="btn btn-primary" disabled>Persist Paper Ballot Count</button>
        </div>

        {% if sess.status == "persisted" %}
        <div class="count-end-banner">Session persisted at {{ sess.persisted_at }}.</div>
        {% elif sess.status == "cancelled" %}
        <div class="count-end-banner">Session cancelled at {{ sess.cancelled_at }}.</div>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Stub the routes the template references**

In `app.py`, add stubs:

```python
@app.route("/admin/election/<int:election_id>/count/<int:round_no>/state")
@admin_required
def admin_count_state(election_id, round_no):
    return ("Not implemented", 501)


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/disregard", methods=["POST"])
@admin_required
def admin_count_disregard(election_id, round_no):
    return ("Not implemented", 501)


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/persist", methods=["POST"])
@admin_required
def admin_count_persist(election_id, round_no):
    return ("Not implemented", 501)


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/cancel", methods=["POST"])
@admin_required
def admin_count_cancel(election_id, round_no):
    return ("Not implemented", 501)
```

- [ ] **Step 4: Add the link in manage.html**

Find the post-close-voting panel in `voting-app/templates/admin/manage.html` (the area shown when `voting_open == 0`). Add this near the other Phase 4 / Tally controls:

```html
{% if election.paper_count_enabled and not election.voting_open %}
<a href="{{ url_for('admin_count_dashboard', election_id=election.id, round_no=election.current_round) }}"
   class="btn btn-outline">
    Paper Count Dashboard
</a>
{% endif %}
```

(Engineer: read `manage.html` to find the right location. The hint is to find where existing "Open Voting" / "Close Voting" / "Postal Votes" buttons live.)

- [ ] **Step 5: Manual verify**

Run app. Create paper-count-enabled election, open and close voting. Open manage page, verify "Paper Count Dashboard" link appears. Click it; verify the empty dashboard renders without 500.

- [ ] **Step 6: Commit**

```bash
git add voting-app/app.py voting-app/templates/admin/count.html voting-app/templates/admin/manage.html
git commit -m "Paper count: admin dashboard skeleton + link from manage"
```

---

### Task 9: State JSON + dashboard polling JS (consensus calculation)

**Files:**
- Modify: `voting-app/app.py` (`admin_count_state` plus `_compute_consensus` helper)
- Modify: `voting-app/templates/admin/count.html` (add `<script>` block)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing tests for consensus**

Append to `tests/test_paper_count.py`:

```python
def test_state_endpoint_returns_consensus(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sids = []
    cands = _candidate_ids(election_id)
    for c in codes[:3]:
        sids.append(_join_count(client, election_id, c))
        # Each helper taps cand[0] twice => agreement
        client.post(f"/count/{sids[-1]}/tap", json={"candidate_id": cands[0], "delta": 1})
        client.post(f"/count/{sids[-1]}/tap", json={"candidate_id": cands[0], "delta": 1})
    # Use first session id (all share the same since same election+round)
    sid = sids[0]
    # Admin call
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    assert r.status_code == 200
    data = r.get_json()
    assert data["helper_count"] == 3
    # Per-candidate consensus
    cand_state = next(c for c in data["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "ok"
    assert cand_state["consensus"]["value"] == 2


def test_state_endpoint_marks_mismatch(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    cands = _candidate_ids(election_id)
    for i, c in enumerate(codes[:3]):
        sid = _join_count(client, election_id, c)
        # First two helpers tap once, third taps twice => mismatch
        n = 2 if i == 2 else 1
        for _ in range(n):
            client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    data = r.get_json()
    cand_state = next(c for c in data["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "mismatch"


def test_state_endpoint_excludes_idle_helpers(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    cands = _candidate_ids(election_id)
    # Three active helpers all agree
    for c in codes[:3]:
        sid = _join_count(client, election_id, c)
        client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    # The fourth (codes does not have a fourth in this fixture; expand if needed)
    # We instead test that helper_count counts active ones correctly.
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    data = r.get_json()
    cand_state = next(c for c in data["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "ok"
    assert cand_state["consensus"]["value"] == 1
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k state_endpoint
```

Expected: 3 FAILs (state route stubbed).

- [ ] **Step 3: Implement state endpoint**

Replace the `admin_count_state` stub in `app.py`:

```python
def _compute_consensus_for_candidate(active_counts):
    """Given a list of active, non-disregarded helpers' counts for one candidate,
    return a dict describing the consensus state."""
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
    """Return the set of helper short_ids whose counts differ from the per-candidate
    mode on >30% of candidates that have a defined mode.

    per_helper_counts: dict[helper_short_id -> dict[candidate_id -> count]]
    candidate_modes: dict[candidate_id -> mode_value or None]
    """
    flagged = set()
    candidates_with_mode = [c for c, m in candidate_modes.items() if m is not None]
    if not candidates_with_mode:
        return flagged
    for sid, counts in per_helper_counts.items():
        diffs = sum(1 for c in candidates_with_mode if counts.get(c, 0) != candidate_modes[c])
        if diffs / len(candidates_with_mode) > 0.30:
            flagged.add(sid)
    return flagged


@app.route("/admin/election/<int:election_id>/count/<int:round_no>/state")
@admin_required
def admin_count_state(election_id, round_no):
    db = get_db()
    sess = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if sess is None:
        return jsonify({"helpers": [], "candidates": [], "helper_count": 0,
                        "done_count": 0, "session_status": "none"})

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

    # Build per-helper-per-candidate count map
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
    candidate_modes = {}  # candidate_id -> mode value (for flag calc)
    for office in offices:
        cands = db.execute(
            "SELECT * FROM candidates WHERE office_id = ? ORDER BY surname_sort_key(name)",
            (office["id"],)
        ).fetchall()
        for c in cands:
            active_counts = [counts_by_hc.get(hid, {}).get(c["id"], 0) for hid in active_helper_ids
                             if c["id"] in counts_by_hc.get(hid, {})]
            consensus = _compute_consensus_for_candidate(active_counts)
            per_helper = {h["short_id"]: counts_by_hc.get(h["id"], {}).get(c["id"]) for h in helpers}
            # Compute mode for flag detection (using only active, non-disregarded)
            from collections import Counter
            mode_val = None
            if active_counts:
                cnt = Counter(active_counts)
                top, freq = cnt.most_common(1)[0]
                if freq * 2 > len(active_counts):  # strict majority
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

    # Compute out-of-sync flags
    per_helper_counts = {h["short_id"]: counts_by_hc.get(h["id"], {}) for h in helpers
                         if _helper_is_active(db, h["id"]) and h["disregarded_at"] is None}
    flagged = _flag_out_of_sync(per_helper_counts, candidate_modes)
    for h in helper_rows:
        h["out_of_sync"] = h["short_id"] in flagged

    active_count = sum(1 for h in helper_rows if h["active"] and not h["disregarded"])
    done_count = sum(1 for h in helper_rows if h["done"] and h["active"] and not h["disregarded"])

    # Banner state
    banner = "grey"
    if active_count == 0:
        banner = "grey"
    elif any(c["consensus"]["status"] == "mismatch" for c in candidate_states):
        banner = "red"
    elif active_count >= 3 and done_count == active_count and \
         all(c["consensus"]["status"] in ("ok", "no_data") for c in candidate_states):
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
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k state_endpoint
```

Expected: 3 PASS.

- [ ] **Step 5: Add polling + rendering JS to admin/count.html**

In `voting-app/templates/admin/count.html`, before `{% endblock %}`, add:

```html
<script>
(function() {
    const root = document.querySelector(".count-dashboard");
    if (!root) return;
    const stateUrl = root.dataset.stateUrl;
    const persistBtn = document.getElementById("count-persist-btn");
    const cancelBtn = document.getElementById("count-cancel-btn");
    const tableHost = document.getElementById("count-table-host");
    const banner = document.getElementById("count-banner");
    const summary = document.getElementById("count-summary");
    let lastState = null;
    let pollPaused = false;

    async function loadState() {
        if (pollPaused) return;
        try {
            const r = await fetch(stateUrl);
            if (!r.ok) return;
            const data = await r.json();
            lastState = data;
            render(data);
        } catch (e) {}
    }

    function render(data) {
        summary.textContent = `${data.helper_count} active helpers - ${data.done_count} done`;
        banner.className = "count-banner count-banner-" + data.banner;
        banner.textContent = bannerText(data);

        // Build table grouped by office
        const byOffice = {};
        for (const c of data.candidates) {
            if (!byOffice[c.office_id]) byOffice[c.office_id] = {name: c.office_name, candidates: []};
            byOffice[c.office_id].candidates.push(c);
        }
        let html = "";
        const helperHeaders = data.helpers.map(h => {
            const cls = ["count-helper-col"];
            if (h.disregarded) cls.push("count-helper-disregarded");
            if (h.out_of_sync) cls.push("count-helper-flagged");
            const flag = h.out_of_sync && !h.disregarded ? '<span class="count-flag-chip">out of sync</span>' : "";
            const btn = h.disregarded
                ? `<button class="count-helper-restore-btn" data-helper-id="${h.id}">Restore</button>`
                : `<button class="count-helper-disregard-btn" data-helper-id="${h.id}">Disregard</button>`;
            const stale = isStale(h.last_seen_at) ? '<span class="count-stale">(stale)</span>' : "";
            return `<th class="${cls.join(' ')}">${h.short_id} ${flag} ${stale}<br>${btn}</th>`;
        }).join("");
        html += `<table class="count-table"><thead><tr><th>Candidate</th>${helperHeaders}<th>Consensus</th></tr></thead><tbody>`;
        for (const offId of Object.keys(byOffice)) {
            const off = byOffice[offId];
            html += `<tr class="count-office-row"><th colspan="${data.helpers.length + 2}">${escapeHtml(off.name)}</th></tr>`;
            for (const c of off.candidates) {
                const cells = data.helpers.map(h => {
                    const v = c.per_helper[h.short_id];
                    return `<td class="${h.disregarded ? 'count-cell-disregarded' : ''}">${v == null ? "" : v}</td>`;
                }).join("");
                let consensusCell = "";
                if (c.consensus.status === "ok") consensusCell = `<td class="count-cell-ok">✓ ${c.consensus.value}</td>`;
                else if (c.consensus.status === "mismatch") consensusCell = `<td class="count-cell-mismatch">✗ Mismatch</td>`;
                else consensusCell = `<td class="count-cell-pending">-</td>`;
                html += `<tr><td>${escapeHtml(c.name)}</td>${cells}${consensusCell}</tr>`;
            }
        }
        html += "</tbody></table>";
        tableHost.innerHTML = html;

        persistBtn.disabled = (data.helper_count === 0 && data.candidates.every(c => c.consensus.status === "no_data"));

        if (data.session_status !== "active") {
            persistBtn.disabled = true;
            cancelBtn.disabled = true;
        }
    }

    function isStale(iso) {
        if (!iso) return false;
        const then = new Date(iso + "Z");
        return (Date.now() - then.getTime()) > 30000;
    }
    function bannerText(d) {
        if (d.banner === "green") return "✓ ALL CANDIDATES AGREE (" + d.done_count + " of " + d.helper_count + " helpers, all marked done)";
        if (d.banner === "red") {
            const mismatched = d.candidates.filter(c => c.consensus.status === "mismatch").map(c => c.name);
            return "Mismatch on: " + mismatched.join(", ");
        }
        if (d.banner === "amber") return "Counting in progress.";
        return "No active helpers.";
    }
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
    }

    loadState();
    setInterval(loadState, 1000);

    // Disregard / Restore handler (delegated)
    tableHost.addEventListener("click", async function(ev) {
        const dis = ev.target.closest(".count-helper-disregard-btn");
        const res = ev.target.closest(".count-helper-restore-btn");
        const btn = dis || res;
        if (!btn) return;
        const helperId = parseInt(btn.dataset.helperId, 10);
        await fetch(root.dataset.disregardUrl, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({helper_id: helperId, disregard: dis ? true : false}),
        });
        loadState();
    });

    // Persist / Cancel hooks (filled in Task 11 / 12)
    window.__paperCount = {
        loadState, pausePolling: () => pollPaused = true, resumePolling: () => pollPaused = false,
        getState: () => lastState
    };
})();
</script>
```

- [ ] **Step 6: Manual verify**

Run app, set up an election with paper count, close voting. From three phones join the count and tap. Open admin dashboard. Verify rows appear, counts update within ~1s, consensus column shows green ticks when all three agree.

- [ ] **Step 7: Commit**

```bash
git add voting-app/app.py voting-app/templates/admin/count.html voting-app/tests/test_paper_count.py
git commit -m "Paper count: state JSON + dashboard polling/rendering"
```

---

### Task 10: Disregard mechanism + auto-flag (server-side)

**Files:**
- Modify: `voting-app/app.py` (`admin_count_disregard`)
- Test: `voting-app/tests/test_paper_count.py`

(Auto-flag logic was added in Task 9 - this task wires up the disregard endpoint.)

- [ ] **Step 1: Write failing test**

Append to `tests/test_paper_count.py`:

```python
def test_disregard_excludes_helper_from_consensus(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    cands = _candidate_ids(election_id)
    # 3 helpers, third one wildly off
    for i, c in enumerate(codes[:3]):
        sid = _join_count(client, election_id, c)
        n = 5 if i == 2 else 1
        for _ in range(n):
            client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})

    # Find third helper
    with app.app_context():
        third = get_db().execute(
            "SELECT id FROM count_session_helpers WHERE voter_code = ?", (codes[2],)
        ).fetchone()
        third_id = third["id"]

    with client.session_transaction() as sess:
        sess["admin"] = True
    # Mismatch before
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    cand_state = next(c for c in r.get_json()["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "mismatch"

    # Disregard third
    r = client.post(f"/admin/election/{election_id}/count/1/disregard", json={
        "helper_id": third_id, "disregard": True
    })
    assert r.status_code == 200

    # Now should be ok consensus = 1
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    cand_state = next(c for c in r.get_json()["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "ok"
    assert cand_state["consensus"]["value"] == 1

    # Restore
    r = client.post(f"/admin/election/{election_id}/count/1/disregard", json={
        "helper_id": third_id, "disregard": False
    })
    assert r.status_code == 200
    r = client.get(f"/admin/election/{election_id}/count/1/state")
    cand_state = next(c for c in r.get_json()["candidates"] if c["id"] == cands[0])
    assert cand_state["consensus"]["status"] == "mismatch"
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k disregard
```

Expected: FAIL.

- [ ] **Step 3: Implement disregard endpoint**

Replace the stub in `app.py`:

```python
@app.route("/admin/election/<int:election_id>/count/<int:round_no>/disregard", methods=["POST"])
@admin_required
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
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: all PASS.

- [ ] **Step 5: Manual verify**

Run app. With 4 helpers (3 in agreement, 1 off), open admin dashboard. Verify the off helper's column shows the amber `out of sync` chip. Click "Disregard" on that column. Verify the column greys out and the consensus banner turns green based on the other 3. Click "Restore" - mismatch returns.

- [ ] **Step 6: Commit**

```bash
git add voting-app/app.py voting-app/tests/test_paper_count.py
git commit -m "Paper count: disregard endpoint (manual exclusion of out-of-sync helpers)"
```

---

### Task 11: Persist flow with override modal

**Files:**
- Modify: `voting-app/app.py` (`admin_count_persist`)
- Modify: `voting-app/templates/admin/count.html` (add modal HTML + JS hook)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_paper_count.py`:

```python
def test_persist_writes_results_and_marks_session(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    cands = _candidate_ids(election_id)
    for c in codes[:3]:
        sid = _join_count(client, election_id, c)
        client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
        client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
        # Mark done
        client.post(f"/count/{sid}/done", json={})
    with client.session_transaction() as sess:
        sess["admin"] = True
    # Build totals payload (admin confirms consensus, no overrides needed)
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 2}  # plus any other candidates with data
    })
    assert r.status_code == 200
    with app.app_context():
        sess = get_db().execute(
            "SELECT * FROM count_sessions WHERE election_id = ?", (election_id,)
        ).fetchone()
        assert sess["status"] == "persisted"
        results = get_db().execute(
            "SELECT * FROM count_session_results WHERE session_id = ?", (sess["id"],)
        ).fetchall()
        cand0 = next(r for r in results if r["candidate_id"] == cands[0])
        assert cand0["final_count"] == 2


def test_persist_rejected_when_already_persisted(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 1}
    })
    assert r.status_code == 200
    r = client.post(f"/admin/election/{election_id}/count/1/persist", json={
        "totals": {str(cands[0]): 1}
    })
    assert r.status_code == 400
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k persist
```

Expected: 2 FAILs.

- [ ] **Step 3: Implement persist endpoint**

Replace the stub:

```python
@app.route("/admin/election/<int:election_id>/count/<int:round_no>/persist", methods=["POST"])
@admin_required
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

    # Compute consensus once to record source per candidate
    # (We re-derive what the dashboard shows so the client can't lie about consensus.)
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

    # Iterate every candidate in the election (so we record an explicit 0 if needed)
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
                # No admin pick AND no consensus => default to 0
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

    admin_id = session.get("admin_id")  # may be None if app uses simple bool admin
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
```

- [ ] **Step 4: Wire up the persist button + modal in count.html**

In `voting-app/templates/admin/count.html`, add modal HTML inside `count-dashboard`:

```html
<dialog id="count-persist-modal" style="border: 1px solid #ccc; padding: 16px; max-width: 600px;">
    <h3 style="margin-top: 0;">Persist Paper Ballot Count</h3>
    <p>Confirm the final totals. Mismatched or low-confidence rows are highlighted - edit if needed.</p>
    <table id="count-persist-table" class="count-persist-table"></table>
    <div style="margin-top: 12px; text-align: right;">
        <button type="button" id="count-persist-modal-cancel" class="btn btn-outline">Cancel</button>
        <button type="button" id="count-persist-modal-confirm" class="btn btn-primary">Persist</button>
    </div>
</dialog>
```

In the same file's `<script>` block (extending what was added in Task 9), add:

```javascript
    persistBtn.addEventListener("click", function() {
        if (!lastState) return;
        const modal = document.getElementById("count-persist-modal");
        const tbl = document.getElementById("count-persist-table");
        let rows = "";
        for (const c of lastState.candidates) {
            let suggested = 0;
            let cls = "count-persist-mismatch";
            if (c.consensus.status === "ok") { suggested = c.consensus.value; cls = ""; }
            else if (c.consensus.status === "insufficient" && c.consensus.values.length) {
                suggested = Math.max(...c.consensus.values);
            } else if (c.consensus.status === "mismatch") {
                const counts = {};
                for (const v of c.consensus.values) counts[v] = (counts[v]||0) + 1;
                const mode = Object.entries(counts).sort((a,b) => b[1]-a[1])[0];
                suggested = parseInt(mode[0], 10);
            }
            rows += `<tr class="${cls}"><td>${escapeHtml(c.name)}</td><td><input type="number" min="0" data-cand="${c.id}" value="${suggested}" style="width: 80px;"></td><td>${c.consensus.status}</td></tr>`;
        }
        tbl.innerHTML = `<thead><tr><th>Candidate</th><th>Final</th><th>Status</th></tr></thead><tbody>${rows}</tbody>`;
        pollPaused = true;
        modal.showModal();
    });

    document.getElementById("count-persist-modal-cancel").addEventListener("click", function() {
        document.getElementById("count-persist-modal").close();
        pollPaused = false;
    });

    document.getElementById("count-persist-modal-confirm").addEventListener("click", async function() {
        const inputs = document.querySelectorAll("#count-persist-table input[data-cand]");
        const totals = {};
        for (const i of inputs) totals[i.dataset.cand] = parseInt(i.value, 10) || 0;
        const r = await fetch(root.dataset.persistUrl, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({totals: totals}),
        });
        if (r.ok) {
            document.getElementById("count-persist-modal").close();
            window.location.reload();
        } else {
            alert("Persist failed: " + r.status);
            pollPaused = false;
        }
    });
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: all PASS.

- [ ] **Step 6: Manual verify**

Run app, drive a full count to consensus, click Persist. Verify modal pops with pre-filled totals. Confirm. Verify dashboard reloads, shows "Session persisted at ...". Helper phones transition to Thanks within ~5s.

- [ ] **Step 7: Commit**

```bash
git add voting-app/app.py voting-app/templates/admin/count.html voting-app/tests/test_paper_count.py
git commit -m "Paper count: persist flow with override modal"
```

---

### Task 12: Cancel flow

**Files:**
- Modify: `voting-app/app.py` (`admin_count_cancel`)
- Modify: `voting-app/templates/admin/count.html` (cancel button hook)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_paper_count.py`:

```python
def test_cancel_marks_session_and_blocks_taps(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    cands = _candidate_ids(election_id)
    client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})

    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/count/1/cancel")
    assert r.status_code == 200

    # Restore voter session
    with client.session_transaction() as sess:
        sess["used_code"] = codes[0]
        sess["election_id"] = election_id
        sess.pop("admin", None)
    r = client.post(f"/count/{sid}/tap", json={"candidate_id": cands[0], "delta": 1})
    assert r.status_code == 403
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k cancel
```

Expected: FAIL.

- [ ] **Step 3: Implement cancel endpoint**

```python
@app.route("/admin/election/<int:election_id>/count/<int:round_no>/cancel", methods=["POST"])
@admin_required
def admin_count_cancel(election_id, round_no):
    db = get_db()
    sess = db.execute(
        "SELECT * FROM count_sessions WHERE election_id = ? AND round_no = ?",
        (election_id, round_no)
    ).fetchone()
    if sess is None:
        return ("No session", 404)
    if sess["status"] != "active":
        return ("Session not active", 400)
    helper_count = db.execute(
        "SELECT COUNT(*) AS n FROM count_session_helpers WHERE session_id = ?",
        (sess["id"],)
    ).fetchone()["n"]
    db.execute(
        "UPDATE count_sessions SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
        (_now_iso(), sess["id"])
    )
    db.commit()
    log_voter_audit(
        election_id, None, "paper_count_cancelled",
        detail=f"helpers={helper_count}",
        round_number=round_no
    )
    return ("", 200)
```

- [ ] **Step 4: Wire up cancel button in count.html**

In the dashboard's `<script>` block, add:

```javascript
    cancelBtn.addEventListener("click", async function() {
        if (!confirm("Cancel this count session? No totals will be saved.")) return;
        const r = await fetch(root.dataset.cancelUrl, {method: "POST"});
        if (r.ok) window.location.reload();
        else alert("Cancel failed: " + r.status);
    });
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: all PASS.

- [ ] **Step 6: Manual verify**

Run app, start a count, cancel from dashboard, confirm modal. Verify status reflects "cancelled" on dashboard. Helper phones transition to "Counting was cancelled" within 5s.

- [ ] **Step 7: Commit**

```bash
git add voting-app/app.py voting-app/templates/admin/count.html voting-app/tests/test_paper_count.py
git commit -m "Paper count: cancel session flow"
```

---

### Task 13: Soft-reset / hard-reset / next-round integration

**Files:**
- Modify: `voting-app/app.py` (admin_soft_reset, admin_hard_reset)
- Test: `voting-app/tests/test_paper_count.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_soft_reset_cancels_active_count_session(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/soft-reset")
    assert r.status_code in (200, 302)
    with app.app_context():
        s = get_db().execute(
            "SELECT * FROM count_sessions WHERE election_id = ?", (election_id,)
        ).fetchone()
        assert s["status"] == "cancelled"


def test_hard_reset_deletes_count_data(client):
    election_id, codes = _setup_paper_count_election(client)
    client.post(f"/admin/election/{election_id}/voting/toggle")
    client.post(f"/admin/election/{election_id}/voting/toggle")
    sid = _join_count(client, election_id, codes[0])
    with client.session_transaction() as sess:
        sess["admin"] = True
    r = client.post(f"/admin/election/{election_id}/hard-reset")
    assert r.status_code in (200, 302)
    with app.app_context():
        n_sess = get_db().execute(
            "SELECT COUNT(*) AS n FROM count_sessions WHERE election_id = ?",
            (election_id,)
        ).fetchone()["n"]
        n_helpers = get_db().execute(
            "SELECT COUNT(*) AS n FROM count_session_helpers"
        ).fetchone()["n"]
        assert n_sess == 0
        assert n_helpers == 0
```

(Engineer: confirm soft-reset and hard-reset URLs by reading `app.py`. Adjust if paths differ.)

- [ ] **Step 2: Run, verify FAIL**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v -k reset
```

Expected: 2 FAILs.

- [ ] **Step 3: Hook into existing reset routes**

Find `admin_soft_reset` (line ~1767) in `app.py`. Just before its existing `db.commit()`, add:

```python
    # Cancel any active count session for the current round
    db.execute(
        "UPDATE count_sessions SET status = 'cancelled', cancelled_at = ? "
        "WHERE election_id = ? AND round_no = ? AND status = 'active'",
        (_now_iso(), election_id, election["current_round"])
    )
```

(Engineer: read the function to find a clean insertion point. The intent is "before commit, also cancel active count sessions for this round".)

Find `admin_hard_reset` (line ~1811). Before its `db.commit()`, add:

```python
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
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd voting-app && python -m pytest tests/test_paper_count.py -v
```

Expected: all PASS.

- [ ] **Step 5: Manual verify**

Run app. Start a count, then click Soft Reset on manage. Verify count session shows "cancelled" if reopened. Then Hard Reset; verify count tables are empty for that election.

- [ ] **Step 6: Commit**

```bash
git add voting-app/app.py voting-app/tests/test_paper_count.py
git commit -m "Paper count: soft-reset cancels active session, hard-reset wipes count data"
```

---

### Task 14: CSS styling

**Files:**
- Modify: `voting-app/static/css/style.css`

- [ ] **Step 1: Add count UI styles**

Append to `voting-app/static/css/style.css`:

```css
/* ============================================================
   Paper count helper (voter-side grid)
   ============================================================ */
.count-helper-page {
    padding: 6px 8px;
    box-sizing: border-box;
    height: 100vh;
    display: flex;
    flex-direction: column;
}
.count-helper-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    color: #666;
    padding: 0 4px 4px;
}
.count-helper-id {
    font-family: monospace;
    letter-spacing: 1px;
}
.count-grid {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    overflow: hidden;
}
@media (orientation: portrait) {
    .count-grid { grid-template-columns: 1fr; }
}
.count-office {
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.count-office-title {
    font-size: 12px;
    color: #888;
    margin: 0 0 4px;
    text-align: center;
    letter-spacing: 1px;
}
.count-candidate-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
}
.count-candidate-row {
    display: flex;
    align-items: stretch;
    gap: 4px;
    transition: background 100ms ease;
}
.count-plus-btn {
    flex: 1;
    text-align: left;
    background: #f4f4f4;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 16px;
    cursor: pointer;
}
.count-plus-btn:active {
    background: #e0e0e0;
}
.count-minus-btn {
    width: 48px;
    background: #fdecec;
    border: 1px solid #f0c4c4;
    color: #b52424;
    font-weight: 700;
    border-radius: 6px;
    cursor: pointer;
}
.count-minus-btn:active {
    background: #fad6d6;
}
.count-row-flash-ok {
    background: #d8f3d8 !important;
}
.count-row-flash-fail {
    background: #f3d8d8 !important;
}
.count-row-error .count-plus-btn {
    border-color: #b52424;
}
.count-end-screen {
    text-align: center;
    padding: 48px 16px;
}
.count-end-screen .checkmark {
    font-size: 56px;
    color: #2a8a2a;
}

/* ============================================================
   Admin count dashboard
   ============================================================ */
.count-dashboard-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}
.count-banner {
    padding: 12px 16px;
    border-radius: 6px;
    margin-bottom: 12px;
    font-weight: 600;
}
.count-banner-green { background: #d8f3d8; color: #1d6d1d; }
.count-banner-amber { background: #fff3d8; color: #7d6420; }
.count-banner-red   { background: #f3d8d8; color: #8d2424; }
.count-banner-grey  { background: #eee; color: #555; }

.count-table {
    border-collapse: collapse;
    width: 100%;
    margin-bottom: 12px;
}
.count-table th, .count-table td {
    border: 1px solid #ddd;
    padding: 6px 8px;
    text-align: left;
    font-size: 14px;
}
.count-table .count-office-row th {
    background: #f4f4f4;
    font-size: 13px;
    letter-spacing: 1px;
    color: #666;
}
.count-helper-col {
    text-align: center !important;
    font-family: monospace;
    font-size: 12px;
    min-width: 90px;
}
.count-helper-disregarded {
    opacity: 0.4;
    text-decoration: line-through;
}
.count-helper-flagged {
    background: #fff3d8;
}
.count-flag-chip {
    display: block;
    font-size: 10px;
    color: #7d6420;
    background: #fde9b6;
    padding: 1px 4px;
    border-radius: 8px;
    margin-top: 2px;
}
.count-helper-disregard-btn,
.count-helper-restore-btn {
    font-size: 11px;
    padding: 2px 6px;
    margin-top: 4px;
    cursor: pointer;
}
.count-cell-disregarded { color: #aaa; }
.count-cell-ok { background: #d8f3d8; color: #1d6d1d; font-weight: 600; }
.count-cell-mismatch { background: #f3d8d8; color: #8d2424; font-weight: 600; }
.count-cell-pending { color: #999; }
.count-stale {
    font-size: 10px;
    color: #999;
    display: block;
}
.count-persist-table {
    border-collapse: collapse;
    width: 100%;
}
.count-persist-table td, .count-persist-table th {
    border: 1px solid #ddd;
    padding: 4px 8px;
    font-size: 13px;
}
.count-persist-mismatch { background: #fff3d8; }
.count-end-banner {
    padding: 8px 12px;
    background: #eee;
    border-radius: 6px;
    margin-top: 12px;
    color: #555;
}
```

- [ ] **Step 2: Manual verify**

Run app. Open helper grid in landscape phone view. Verify:
- Two columns
- All 14 candidates visible without scrolling
- Surnames left-aligned, `−1` pill on the right
- Tap flash visible (brief green tint)
- Header is small + monospace counter id

Open admin dashboard. Verify:
- Banner colour reflects state
- Helper columns aligned
- Disregarded helper column greys with strikethrough
- Out-of-sync chip visible

- [ ] **Step 3: Commit**

```bash
git add voting-app/static/css/style.css
git commit -m "Paper count: CSS styling for helper grid + admin dashboard"
```

---

### Task 15: Manual end-to-end verification (full spec test plan)

**Files:** None (testing only)

- [ ] **Step 1: Run all automated tests**

```bash
cd voting-app && python -m pytest tests/ -v
```

Expected: ALL pass (paper_count tests + existing tests intact).

- [ ] **Step 2: Walk through the spec's manual test plan**

From `docs/superpowers/specs/2026-04-28-paper-count-cocounting-design.md`, "Manual test plan" section. Run all 16 steps end to end, ticking each off.

- [ ] **Step 3: Verify untouched tables**

After a full persist, run:

```bash
sqlite3 voting-app/data/frca_election.db "SELECT COUNT(*) FROM paper_votes;"
sqlite3 voting-app/data/frca_election.db "SELECT COUNT(*) FROM votes;"
sqlite3 voting-app/data/frca_election.db "SELECT COUNT(*) FROM codes WHERE used = 1;"
```

Note the values. Then start and persist a paper count. Re-run the same queries. The values must be unchanged.

- [ ] **Step 4: Confirm the feature is fully invisible when disabled**

Create a new election with `paper_count_enabled = 0`. Verify:
- No "Assist" button on confirmation page.
- No "Paper Count Dashboard" link on manage page.
- `GET /admin/election/<id>/count/1` returns 404.
- `POST /count/join` returns 400 ("Paper count not enabled").

- [ ] **Step 5: Final commit (if any drift was fixed)**

```bash
git status
# If untracked or modified, commit any final cleanups.
git commit -am "Paper count: final polish from manual verification"
```

---

## Rollback / disable plan

If the feature misbehaves in production:

1. **Soft disable per election:** uncheck "Enable paper count helper" in election setup. The feature becomes invisible. Existing session rows are kept for audit.
2. **Hard disable globally:** add a feature flag check in `count_join` and `admin_count_dashboard` early returns. (Out of scope for this plan, but trivial.)
3. **Schema rollback:** the new tables are isolated. Dropping them and the column does not affect any other functionality. Migration script: `DROP TABLE count_session_results; DROP TABLE count_session_tallies; DROP TABLE count_session_helpers; DROP TABLE count_sessions; ALTER TABLE elections DROP COLUMN paper_count_enabled;`.

---

## Self-Review Checklist (for the engineer before declaring complete)

- [ ] All 16 spec test plan items executed and pass
- [ ] No changes visible to existing voter / admin / projector flows when feature is disabled
- [ ] `paper_votes`, `votes`, `codes` tables unchanged after a persist (verified via row counts)
- [ ] All helper devices transition to Thanks within 5s of admin persist
- [ ] All audit log events appear in `voter_audit_log` with correct `result` strings
- [ ] No CSP / inline-script violations in browser console
- [ ] Helper grid fits 14 candidates in landscape on a 360x640 phone with no scrolling
- [ ] Two simultaneous taps on different rows complete correctly (no race)
