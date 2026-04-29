# Admin Wizard Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragmented Dashboard / Members / Election Setup / Codes / Manage page flow with a single per-election shell that has a persistent left-rail progress sidebar (Setup / Round N / Finish) and 12 step routes. Also remove the auto-reveal of vote tallies when voting is closed.

**Architecture:** Add one Jinja partial (`_sidebar.html`), one base step template (`_step_base.html`), and one helper (`compute_sidebar_state`) to `app.py`. Add 12 `step/<slug>` GET routes that mostly extract sub-sections of the existing `manage.html`, `election_setup.html`, and `codes.html` into per-step templates. The existing form-post routes (`/voting`, `/participants`, `/display-phase`, `/codes/delete`, `/paper-votes`, `/next-round`, etc.) keep their URLs and continue to be the system of record for state changes. Old GET URLs (`/setup`, `/codes`, `/manage`) become permanent redirects.

**Tech Stack:** Flask 3, sqlite3 (stdlib), Jinja2, vanilla JS, no build step. Pytest for backend tests.

**Spec:** `docs/superpowers/specs/2026-04-29-admin-wizard-sidebar-design.md`

---

## File Structure

**Create:**
- `voting-app/templates/admin/_sidebar.html` - sidebar partial, included by `_step_base.html`
- `voting-app/templates/admin/_step_base.html` - base template that lays out the 220px sidebar + main pane and includes `_sidebar.html`
- `voting-app/templates/admin/step_details.html` - step 1
- `voting-app/templates/admin/step_offices.html` - step 3
- `voting-app/templates/admin/step_settings.html` - step 4
- `voting-app/templates/admin/step_codes.html` - step 5 (codes status + printer pack + early postal entry)
- `voting-app/templates/admin/step_attendance.html` - step 6
- `voting-app/templates/admin/step_welcome.html` - step 7
- `voting-app/templates/admin/step_voting.html` - step 8
- `voting-app/templates/admin/step_count.html` - step 9
- `voting-app/templates/admin/step_decide.html` - step 10
- `voting-app/templates/admin/step_final.html` - step 11
- `voting-app/templates/admin/step_minutes.html` - step 12
- `voting-app/tests/test_wizard_sidebar.py` - all backend tests for this feature

**Modify:**
- `voting-app/app.py` - `compute_sidebar_state` helper (~80 LOC, near the existing `get_round_counts` helper at ~line 920 area), 12 step GET routes (after the existing `admin_election_manage` route at line 1196), redirects for `/setup`, `/codes`, `/manage`, and the 1-line `show_results = 1` removal in `admin_toggle_voting` (line 1071-1075).
- `voting-app/templates/admin/dashboard.html` - point the "Manage" link at the new step shell entry route (no template-level visual change, just URL).
- `voting-app/templates/admin/members.html` - render with sidebar shell when `?election_id=N` query param is present.
- `voting-app/static/css/style.css` - add `.wizard-shell`, `.wizard-sidebar`, `.wizard-main`, sidebar item styles.

**Delete (after migration is verified at the end):** none. The existing `manage.html`, `election_setup.html`, `codes.html` are kept as the source-of-truth for content during extraction; only their **routes** stop pointing at them. Final cleanup task removes them.

---

## Conventions used by the existing codebase

The engineer should match these (verified against current code):

- Admin routes use the `@admin_required` decorator (line ~647).
- DB connection: `db = get_db()` returns a sqlite3 connection (Row factory). Migrations live in `_migrate_db_on()` (line ~354).
- All templates extend `base.html`. Per-step templates will instead extend `_step_base.html`.
- CSRF tokens: every POST form includes `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
- Per-round attendance is read via `get_round_counts(election_id, round_no) -> (in_person, paper_ballots, digital_ballots)` (already exists).
- Per-round per-candidate paper votes are in the `paper_votes` table (`SELECT COALESCE(SUM(count), 0) FROM paper_votes WHERE election_id=? AND round_number=?`).
- Test fixtures: `client`, `admin_client`, `election_with_codes` are defined in `tests/test_app.py`. New tests should import from `tests/test_app.py` or define fresh fixtures locally if the shape needs to differ.
- The existing `manage.html` has phases 1-5 with sub-sections clearly marked by HTML comment banners (`<!-- =================================================================`). When extracting, copy the full sub-section content (HTML + Jinja blocks + inline JS) so behavior is preserved exactly.
- Display phase state machine: `display_phase = 1` (Welcome), `2` (Rules), `3` (Voting), `4` (Final). Set via `POST /admin/election/<id>/display-phase` (line 1113).

---

## Step slug -> route -> Done condition (reference table)

| Slug         | Step name              | Done when (per round for 6-10)                                          |
|--------------|------------------------|-------------------------------------------------------------------------|
| `details`    | Election details       | row exists in `elections`                                               |
| `members`    | Members                | `SELECT COUNT(*) FROM members > 0`                                      |
| `offices`    | Offices & Candidates   | at least one office with at least one candidate                         |
| `settings`   | Election settings      | always (visiting marks done; safe defaults)                             |
| `codes`      | Codes & printing       | `SELECT COUNT(*) FROM codes WHERE election_id=? > 0`                    |
| `attendance` | Attendance & postal    | `in_person_participants > 0` for `election.current_round`               |
| `welcome`    | Welcome & Rules        | `display_phase >= 2` OR `voting_open=1` OR round has any digital votes  |
| `voting`     | Voting                 | round has been opened (= digital votes exist OR voting_open was set)    |
| `count`      | Count & tally          | per-candidate `paper_votes` row exists for current round                |
| `decide`     | Decide                 | next round started (current_round advanced) OR display_phase = 4        |
| `final`      | Final results          | `display_phase = 4`                                                     |
| `minutes`    | Minutes & archive      | user-controlled (always reachable once `final` is reachable)            |

The current step on entry = lowest-numbered step with state Locked or Current. If all are Done, current = `minutes`.

---

### Task 1: `compute_sidebar_state` helper + tests

**Files:**
- Modify: `voting-app/app.py` (add helper; insert after the existing `get_round_counts` helper around line 920)
- Create: `voting-app/tests/test_wizard_sidebar.py`

- [ ] **Step 1: Write failing test for `compute_sidebar_state` shape on a fresh election**

Create `voting-app/tests/test_wizard_sidebar.py`:

```python
"""Tests for the admin wizard sidebar shell."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, init_db
import app as app_module


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    original_db_path = app_module.DB_PATH
    app_module.DB_PATH = db_path
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client
    app_module.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def admin_client(client):
    client.post("/admin/login", data={"password": "admin"})
    return client


@pytest.fixture
def fresh_election(admin_client):
    """Election created, no offices, no codes, no members."""
    admin_client.post("/admin/election/new", data={
        "name": "Test Election",
        "max_rounds": "2",
    })
    return admin_client


def test_sidebar_state_fresh_election_has_only_details_done(fresh_election):
    """A just-created election has only step 1 done; everything else locked or current."""
    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    # Election header
    assert state["election"]["id"] == 1
    assert state["election"]["name"] == "Test Election"
    assert state["election"]["current_round"] == 1
    # Setup group: details done, members locked (no members yet),
    # offices locked, settings locked, codes locked
    setup = next(g for g in state["groups"] if g["label"] == "Setup")
    states_by_slug = {item["slug"]: item["state"] for item in setup["items"]}
    assert states_by_slug["details"] == "done"
    assert states_by_slug["members"] in ("current", "locked")
    assert states_by_slug["offices"] == "locked"
    assert states_by_slug["codes"] == "locked"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py::test_sidebar_state_fresh_election_has_only_details_done -v
```

Expected: FAIL with `ImportError: cannot import name 'compute_sidebar_state' from 'app'`.

- [ ] **Step 3: Implement `compute_sidebar_state`**

Insert into `voting-app/app.py` immediately after `get_round_counts` (search for `def get_round_counts` and insert below the function):

```python
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
        # If any digital vote exists for this round, voting was opened at
        # some point.
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
        # Successor action: next round started (current_round advanced past this round_no)
        # or election finalised.
        if (election["current_round"] or 1) > round_no:
            return True
        return (election["display_phase"] or 1) >= 4
    if slug == "final":
        return (election["display_phase"] or 1) >= 4
    if slug == "minutes":
        return False  # user-controlled, never auto-marked
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
        # Voting must have been opened AND closed at least once for this round
        if not _step_done(db, election, "voting", round_no):
            return False
        # Round is "closed" when voting_open=0 for the current round
        return not election["voting_open"] or (election["current_round"] or 1) != round_no
    if slug == "decide":
        return _step_prerequisites_met(db, election, "count", round_no)
    if slug == "final":
        return _step_done(db, election, "decide", round_no)
    if slug == "minutes":
        return _step_done(db, election, "final", round_no)
    return False


def compute_sidebar_state(election_id):
    """Build the dict consumed by `_sidebar.html`.

    Shape:
      {
        "election": {id, name, date, current_round, max_rounds, voting_open},
        "current_step": "<slug>",
        "groups": [
          {"label": "Setup",       "items": [{slug, label, state, url}, ...]},
          {"label": "Round 1",     "collapsed": True, "summary": "Closed - X elected", "items": [...]},
          {"label": "Round 2",     "items": [...]},
          {"label": "Finish",      "items": [...]},
        ],
      }
    """
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        return None

    current_round = election["current_round"] or 1

    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    # Decide each step's state for the current round.
    items_by_slug = {}
    for slug, label, _group in WIZARD_STEPS:
        done = _step_done(db, election, slug, current_round)
        reachable = _step_prerequisites_met(db, election, slug, current_round)
        # Members label gets the count appended.
        item_label = label
        if slug == "members" and member_count > 0:
            item_label = f"Members ({member_count})"
        items_by_slug[slug] = {
            "slug": slug,
            "label": item_label,
            "done": done,
            "reachable": reachable,
            "url": url_for(f"admin_step_{slug}", election_id=election_id),
        }

    # The current step is the lowest-numbered step that is reachable
    # but not done. If all are done, fall back to "minutes".
    current_step = "minutes"
    for slug, _label, _group in WIZARD_STEPS:
        item = items_by_slug[slug]
        if item["reachable"] and not item["done"]:
            current_step = slug
            break

    # Mark each step's state.
    for slug in items_by_slug:
        item = items_by_slug[slug]
        if slug == current_step:
            item["state"] = "current"
        elif item["done"]:
            item["state"] = "done"
        elif item["reachable"]:
            # Reachable but not done and not current = future, render as locked-but-clickable
            item["state"] = "locked"
        else:
            item["state"] = "locked"
        del item["done"]
        del item["reachable"]

    # Group rendering. The Round group's label is "Round N".
    groups = [
        {"label": "Setup", "items": [items_by_slug[s] for s, _, g in WIZARD_STEPS if g == "Setup"]},
        {"label": f"Round {current_round}", "items": [items_by_slug[s] for s, _, g in WIZARD_STEPS if g == "Round"]},
        {"label": "Finish", "items": [items_by_slug[s] for s, _, g in WIZARD_STEPS if g == "Finish"]},
    ]

    # Prior rounds collapse into a one-line summary.
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
                {"label": f"Round {r}", "collapsed": True, "summary": summary, "items": []},
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
```

The route URL builders `admin_step_<slug>` referenced via `url_for` will be created in Tasks 3-14. To get the test to pass before those routes exist, the helper must not call `url_for` until we register placeholder routes. Adjust by registering 12 stub routes first (next step).

- [ ] **Step 4: Register 12 stub routes so `url_for` resolves**

Append to `voting-app/app.py` (after `compute_sidebar_state`):

```python
def _make_step_stub(slug):
    """Stub route used to make url_for() resolve before real routes exist."""
    def _stub(election_id):
        return f"step {slug} not yet implemented", 501
    _stub.__name__ = f"admin_step_{slug}"
    return _stub


for _slug, _label, _group in WIZARD_STEPS:
    _view = _make_step_stub(_slug)
    app.add_url_rule(
        f"/admin/election/<int:election_id>/step/{_slug}",
        endpoint=f"admin_step_{_slug}",
        view_func=admin_required(_view),
        methods=["GET"],
    )
```

These stubs will be replaced one by one in Tasks 3-14.

- [ ] **Step 5: Run test to verify it passes**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py::test_sidebar_state_fresh_election_has_only_details_done -v
```

Expected: PASS.

- [ ] **Step 6: Add tests for the other Done conditions**

Append to `voting-app/tests/test_wizard_sidebar.py`:

```python
def test_sidebar_state_with_offices_codes_marks_them_done(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder",
        "vacancies": "1",
        "max_selections": "1",
        "candidate_names": "Cand A\nCand B\nCand C",
        "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})

    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    setup = next(g for g in state["groups"] if g["label"] == "Setup")
    states = {it["slug"]: it["state"] for it in setup["items"]}
    assert states["offices"] == "done"
    assert states["codes"] == "done"


def test_sidebar_state_attendance_done_when_participants_set(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})
    admin_client.post("/admin/election/1/participants", data={"participants": "10"})

    from app import compute_sidebar_state
    with app.app_context():
        state = compute_sidebar_state(election_id=1)
    round_group = next(g for g in state["groups"] if g["label"].startswith("Round"))
    states = {it["slug"]: it["state"] for it in round_group["items"]}
    assert states["attendance"] == "done"
```

- [ ] **Step 7: Run all sidebar tests**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```
git add voting-app/app.py voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): add compute_sidebar_state helper + 12 step stubs"
```

---

### Task 2: `_sidebar.html` partial + `_step_base.html` + CSS

**Files:**
- Create: `voting-app/templates/admin/_sidebar.html`
- Create: `voting-app/templates/admin/_step_base.html`
- Modify: `voting-app/static/css/style.css`

- [ ] **Step 1: Write the sidebar partial**

Create `voting-app/templates/admin/_sidebar.html`:

```jinja
{# Renders the wizard sidebar from `sidebar_state`. Included by _step_base.html. #}
<aside class="wizard-sidebar">
    <div class="wizard-sidebar-head">
        <div class="wizard-sidebar-ename">{{ sidebar_state.election.name }}</div>
        <div class="wizard-sidebar-meta">
            {% if sidebar_state.election.date %}{{ sidebar_state.election.date }} &middot; {% endif %}
            Round {{ sidebar_state.election.current_round }} of {{ sidebar_state.election.max_rounds }}
            {% if sidebar_state.election.voting_open %}
                &middot; <strong style="color: var(--green);">OPEN</strong>
            {% endif %}
        </div>
        <a href="{{ url_for('admin_dashboard') }}" class="wizard-sidebar-back">&larr; All elections</a>
    </div>

    {% for group in sidebar_state.groups %}
    <div class="wizard-sidebar-group-label">{{ group.label }}</div>
    {% if group.collapsed %}
    <div class="wizard-sidebar-collapsed">{{ group.summary }}</div>
    {% else %}
    {% for item in group.items %}
    {% if item.state == 'locked' %}
    <span class="wizard-sidebar-item locked" title="Complete prior steps first">
        <span class="ico">&#9679;</span><span>{{ item.label }}</span>
    </span>
    {% else %}
    <a href="{{ item.url }}" class="wizard-sidebar-item {{ item.state }}">
        <span class="ico">{% if item.state == 'done' %}&#10003;{% else %}&#9679;{% endif %}</span>
        <span>{{ item.label }}</span>
    </a>
    {% endif %}
    {% endfor %}
    {% endif %}
    {% endfor %}
</aside>
```

- [ ] **Step 2: Write the base step template**

Create `voting-app/templates/admin/_step_base.html`:

```jinja
{% extends "base.html" %}
{% block body_class %}wizard-shell-body{% endblock %}
{% block content %}
<div class="wizard-shell">
    {% include "admin/_sidebar.html" %}
    <main class="wizard-main">
        <div class="wizard-main-head">
            <span class="wizard-step-tag">{% block step_tag %}{% endblock %}</span>
            <h1 class="wizard-step-heading">{% block step_heading %}{% endblock %}</h1>
        </div>
        {% block step_content %}{% endblock %}
    </main>
</div>
{% endblock %}
```

- [ ] **Step 3: Add CSS**

Append to `voting-app/static/css/style.css`:

```css
/* ============== Wizard shell ============== */
.wizard-shell-body { background: #f5f5f7; }
.wizard-shell {
    display: flex;
    gap: 16px;
    max-width: 1280px;
    margin: 16px auto;
    padding: 0 16px;
}
.wizard-sidebar {
    flex: 0 0 220px;
    background: #f8f9fa;
    border: 1px solid var(--grey);
    border-radius: 8px;
    padding: 12px;
    align-self: flex-start;
    position: sticky;
    top: 16px;
    font-size: 13px;
}
.wizard-sidebar-head {
    padding-bottom: 10px;
    margin-bottom: 6px;
    border-bottom: 1px solid var(--grey);
}
.wizard-sidebar-ename { font-weight: 700; color: var(--navy); font-size: 14px; }
.wizard-sidebar-meta { font-size: 11px; color: #6c757d; margin-top: 2px; }
.wizard-sidebar-back {
    display: inline-block; margin-top: 6px;
    font-size: 11px; color: #6c757d; text-decoration: none;
}
.wizard-sidebar-back:hover { text-decoration: underline; }
.wizard-sidebar-group-label {
    font-size: 10px; text-transform: uppercase; color: #6c757d;
    margin: 10px 6px 4px; letter-spacing: 0.5px; font-weight: 700;
}
.wizard-sidebar-item {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 8px; border-radius: 4px; margin-bottom: 2px;
    color: #495057; font-size: 13px; text-decoration: none;
}
.wizard-sidebar-item:hover { background: #eef0f3; }
.wizard-sidebar-item .ico { width: 14px; text-align: center; color: #ced4da; }
.wizard-sidebar-item.done { color: #0f5132; }
.wizard-sidebar-item.done .ico { color: #198754; }
.wizard-sidebar-item.current {
    background: var(--navy); color: var(--gold); font-weight: 700;
}
.wizard-sidebar-item.current .ico { color: var(--gold); }
.wizard-sidebar-item.locked { color: #adb5bd; cursor: not-allowed; }
.wizard-sidebar-collapsed {
    color: #6c757d; font-size: 11px; padding: 4px 8px; font-style: italic;
}
.wizard-main {
    flex: 1; min-width: 0;
    background: #fff; border: 1px solid var(--grey); border-radius: 8px;
    padding: 18px 22px;
}
.wizard-main-head {
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid #eee;
}
.wizard-step-tag {
    display: inline-block; padding: 2px 10px; background: var(--gold);
    color: var(--navy); border-radius: 12px; font-size: 11px;
    font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
}
.wizard-step-heading { margin: 6px 0 0; color: var(--navy); font-size: 22px; }

@media (max-width: 900px) {
    .wizard-shell { flex-direction: column; }
    .wizard-sidebar { flex: 0 0 auto; position: static; }
}
```

- [ ] **Step 4: Commit**

```
git add voting-app/templates/admin/_sidebar.html voting-app/templates/admin/_step_base.html voting-app/static/css/style.css
git commit -m "feat(wizard): add sidebar partial, step base template, shell CSS"
```

---

### Task 3: Step 1 - Election details (`step/details`)

**Files:**
- Create: `voting-app/templates/admin/step_details.html`
- Modify: `voting-app/app.py` (replace the `details` stub with real route, near where stubs were registered)

- [ ] **Step 1: Write failing test for the route**

Append to `voting-app/tests/test_wizard_sidebar.py`:

```python
def test_step_details_renders_form(admin_client):
    admin_client.post("/admin/election/new", data={"name": "Details Test", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/step/details")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Details Test" in body
    assert "Election details" in body
    # Sidebar should be present
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Run to verify it fails**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py::test_step_details_renders_form -v
```

Expected: FAIL with stub returning 501.

- [ ] **Step 3: Create the template**

Create `voting-app/templates/admin/step_details.html`:

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Election details - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Election details{% endblock %}
{% block step_heading %}Name, date, and number of rounds{% endblock %}
{% block step_content %}
<form method="POST" action="{{ url_for('admin_step_details_save', election_id=sidebar_state.election.id) }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-group">
        <label for="name">Election name</label>
        <input type="text" id="name" name="name" required value="{{ election.name }}">
    </div>
    <div class="form-group">
        <label for="election_date">Election date</label>
        <input type="text" id="election_date" name="election_date"
               placeholder="e.g. 20 October 2026"
               value="{{ election.election_date or '' }}">
    </div>
    <div class="form-group">
        <label for="max_rounds">Maximum rounds</label>
        <input type="number" id="max_rounds" name="max_rounds" min="1" max="5"
               value="{{ election.max_rounds }}">
    </div>
    <button type="submit" class="btn btn-primary">Save</button>
    <a href="{{ url_for('admin_step_members', election_id=sidebar_state.election.id) }}"
       class="btn btn-outline" style="margin-left: 8px;">Next: Members &rarr;</a>
</form>
{% endblock %}
```

- [ ] **Step 4: Replace the `details` stub with the real route**

In `voting-app/app.py`, find the stub-registration loop (added in Task 1 Step 4). **Above** that loop, add the real route:

```python
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
```

Then change the stub-registration loop to skip `details`:

```python
for _slug, _label, _group in WIZARD_STEPS:
    if _slug == "details":
        continue  # real route registered above
    _view = _make_step_stub(_slug)
    app.add_url_rule(
        f"/admin/election/<int:election_id>/step/{_slug}",
        endpoint=f"admin_step_{_slug}",
        view_func=admin_required(_view),
        methods=["GET"],
    )
```

(Each subsequent step task adds its slug to the skip-list.)

- [ ] **Step 5: Verify `election_date` column exists**

```
cd voting-app && python -c "import sqlite3; c = sqlite3.connect('data/frca_election.db'); print([r for r in c.execute('PRAGMA table_info(elections)')])"
```

If `election_date` is missing, add a migration. Search `_migrate_db_on` in `app.py` and append:

```python
"ALTER TABLE elections ADD COLUMN election_date TEXT DEFAULT ''",
```

(Wrapped in the existing try/except `OperationalError` pattern so reruns are safe.)

- [ ] **Step 6: Run test to verify it passes**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py::test_step_details_renders_form -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```
git add voting-app/app.py voting-app/templates/admin/step_details.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 1 - election details route + template"
```

---

### Task 4: Step 2 - Members (`step/members`)

**Files:**
- Modify: `voting-app/templates/admin/members.html` (render with sidebar when called from election context)
- Modify: `voting-app/app.py` (replace `members` stub)

- [ ] **Step 1: Write failing test**

Append to `voting-app/tests/test_wizard_sidebar.py`:

```python
def test_step_members_renders_with_sidebar(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/step/members")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Import Members" in body  # existing CSV upload form copy
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Run to verify it fails (501 from stub)**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py::test_step_members_renders_with_sidebar -v
```

- [ ] **Step 3: Refactor `members.html` to extend either `base.html` or `_step_base.html`**

Open `voting-app/templates/admin/members.html`. Change the first line from:

```jinja
{% extends "base.html" %}
```

to:

```jinja
{% extends parent_template|default("base.html") %}
```

This lets the route choose the parent template at render time.

Wrap the existing content in conditional sidebar-aware blocks. Specifically, change the `{% block content %}` opening to dispatch to step blocks when in wizard mode. **Simpler approach:** keep `{% block content %}` for the standalone use, and add a new `{% block step_content %}` that re-emits the same body for sidebar use. Easier: just keep one template, set `{% block step_tag %}` and `{% block step_heading %}` defensively at the top.

Concretely, replace the top of `members.html` from:

```jinja
{% extends "base.html" %}
{% block title %}Members - Office Bearer Election{% endblock %}

{% block content %}
<div class="admin-header">
    <h1>Member Directory</h1>
    <a href="{{ url_for('admin_dashboard') }}">Back</a>
</div>

<div class="container-wide">
```

to:

```jinja
{% extends parent_template|default("base.html") %}
{% block title %}Members{% if sidebar_state %} - {{ sidebar_state.election.name }}{% endif %}{% endblock %}
{% block step_tag %}Members{% endblock %}
{% block step_heading %}Member directory{% endblock %}

{% block content %}
{% if not sidebar_state %}
<div class="admin-header">
    <h1>Member Directory</h1>
    <a href="{{ url_for('admin_dashboard') }}">Back</a>
</div>
<div class="container-wide">
{% endif %}
{% block step_content %}
```

And at the end of the file, change:

```jinja
</div>
{% endblock %}
```

to:

```jinja
{% endblock %}{# step_content #}
{% if not sidebar_state %}</div>{% endif %}
{% endblock %}{# content #}
```

This way the same template renders standalone (legacy `/admin/members` direct hit) and wrapped (`step/members` hit).

- [ ] **Step 4: Replace the `members` stub with the real route**

In `voting-app/app.py`, add above the stub-registration loop:

```python
@app.route("/admin/election/<int:election_id>/step/members", methods=["GET"], endpoint="admin_step_members")
@admin_required
def _admin_step_members(election_id):
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
```

Add `members` to the skip-list in the stub-registration loop.

- [ ] **Step 5: Verify members.html standalone still works**

```
cd voting-app && python -m pytest tests/test_app.py -v -k members
```

Expected: existing tests still pass (no regression).

- [ ] **Step 6: Run new test**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py::test_step_members_renders_with_sidebar -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```
git add voting-app/app.py voting-app/templates/admin/members.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 2 - members rendered inside step shell"
```

---

### Task 5: Step 3 - Offices & Candidates (`step/offices`)

**Files:**
- Create: `voting-app/templates/admin/step_offices.html`
- Modify: `voting-app/app.py` (replace `offices` stub)

- [ ] **Step 1: Write failing test**

```python
def test_step_offices_renders_existing_office_with_candidates(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    rv = admin_client.get("/admin/election/1/step/offices")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Elder" in body
    assert "Cand" in body or "A" in body  # at least one candidate name
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Create `step_offices.html` by copying the offices content from `election_setup.html`**

Open `voting-app/templates/admin/election_setup.html` and copy the **office-related sections only** (the existing offices listing, the "Add Office" form, and the JS at the end). Skip the "Election settings" details disclosure (that becomes step 4).

Create `voting-app/templates/admin/step_offices.html`:

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Offices &amp; Candidates - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Offices &amp; Candidates{% endblock %}
{% block step_heading %}Add the offices and candidate slates{% endblock %}
{% block step_content %}

{% if not offices %}
<details style="margin-bottom: 14px;">
    <summary style="cursor: pointer; color: #888; font-size: 13px;">Quick start (testing &amp; dry runs)</summary>
    <form method="POST" action="{{ url_for('admin_load_sample_offices', election_id=sidebar_state.election.id) }}" style="margin-top: 8px;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <p style="font-size: 13px; color: #666; margin-bottom: 6px;">
            Pre-fills <strong>Elder</strong> (3 vacancies, 6 candidates) and <strong>Deacon</strong> (2 vacancies, 4 candidates) with names from the sample pool. Useful for dry runs and demos.
        </p>
        <button type="submit" class="btn btn-outline btn-small">Load sample candidates</button>
    </form>
</details>
{% endif %}

{# Existing offices #}
{% if offices %}
<h2 style="margin-bottom: 12px;">Offices</h2>
{% for office in offices %}
<div class="card">
    <div class="card-header">
        {{ office.name }}
        <span style="font-weight: normal; font-size: 14px; color: #666;">
            ({{ office.vacancies or office.max_selections }} {% if (office.vacancies or office.max_selections) == 1 %}vacancy{% else %}vacancies{% endif %}, select {{ office.max_selections }})
        </span>
    </div>
    <ul style="list-style: none; padding: 0;">
        {% for cand in candidates_by_office[office.id] %}
        <li style="padding: 8px 0; border-bottom: 1px solid #eee;">
            {{ cand.name }}
            {% if not cand.active %}<span style="color: #999;">(inactive)</span>{% endif %}
        </li>
        {% endfor %}
    </ul>
    <form method="POST" action="{{ url_for('admin_office_delete', election_id=sidebar_state.election.id, office_id=office.id) }}"
          style="margin-top: 12px;"
          onsubmit="return confirm('Delete this office and all its candidates?');">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="btn btn-danger btn-small">Remove Office</button>
    </form>
</div>
{% endfor %}
{% endif %}

{# Add new office (preserves existing form action — POST goes to admin_election_setup) #}
<div class="card">
    <div class="card-header">Add Office</div>
    <form method="POST" action="{{ url_for('admin_election_setup', election_id=sidebar_state.election.id) }}"
          id="add-office-form" onsubmit="return validateCandidates();">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div class="form-group">
            <label for="office_name">Office Name</label>
            <input type="text" id="office_name" name="office_name" required
                   placeholder="e.g. Elder, Deacon" autocomplete="off">
        </div>
        <div class="form-group">
            <label for="vacancies">Number of Vacancies</label>
            <input type="number" id="vacancies" name="vacancies"
                   value="{{ prefill_vacancies|default(1) }}" min="1" max="20">
            <p style="font-size: 14px; color: #666; margin-top: 4px;">
                Positions to fill. Article 2: the slate should be twice this number.
                Brothers vote for this many candidates.
            </p>
        </div>
        <details style="margin-bottom: 14px;">
            <summary style="cursor: pointer; color: #888; font-size: 13px;">Advanced options</summary>
            <div class="form-group" style="margin-top: 10px;">
                <label for="max_selections">Votes per voter (override)</label>
                <input type="number" id="max_selections" name="max_selections"
                       value="{{ prefill_max_selections|default(0) }}" min="0" max="20">
                <p style="font-size: 14px; color: #666; margin-top: 4px;">
                    Leave at 0 (the default). For a normal election, voters tick
                    as many names as there are vacancies, which is what 0 produces.
                    Only override if your council uses a different rule.
                </p>
            </div>
        </details>
        <div class="form-group">
            <label>Candidates</label>
            <div class="candidate-picker">
                <input type="text" id="candidate_search"
                       placeholder="Type a name to search members..."
                       autocomplete="off" autocorrect="off" spellcheck="false">
                <div id="candidate_dropdown" class="candidate-dropdown"></div>
            </div>
            <ul id="candidate_list" class="candidate-tag-list"></ul>
            <p style="font-size: 14px; color: #666; margin-top: 4px;">
                Search members by name. Press Enter to add a name manually.
            </p>
            <textarea id="candidate_names" name="candidate_names" style="display: none;"></textarea>
        </div>
        {% if slate_warning|default(false) %}
        <div class="flash flash-error" style="margin-bottom: 16px;">
            <strong>Article 2 Slate Size Warning</strong><br>
            Confirm below to proceed under Article 13 (deviation from rules).
        </div>
        <input type="hidden" name="confirm_slate_override" value="1">
        <button type="submit" class="btn btn-gold">Confirm and Add Office (Article 13 Deviation)</button>
        {% else %}
        <button type="submit" class="btn btn-gold">Add Office</button>
        {% endif %}
    </form>
</div>

{% if offices %}
<div style="margin-top: 16px;">
    <a href="{{ url_for('admin_step_settings', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Settings &rarr;
    </a>
</div>
{% endif %}
{% endblock %}

{% block scripts %}
{# Same JS as election_setup.html — copy verbatim from that template's scripts block #}
<script>
{# Copy the entire <script> body from voting-app/templates/admin/election_setup.html lines ~160-329 #}
</script>
{% endblock %}
```

**Concrete instruction:** open `voting-app/templates/admin/election_setup.html`, copy lines 160-327 (the entire IIFE candidate-picker JS), and paste inside the `{% block scripts %}` of `step_offices.html`.

- [ ] **Step 4: Replace the `offices` stub with the real route**

```python
@app.route("/admin/election/<int:election_id>/step/offices", methods=["GET"], endpoint="admin_step_offices")
@admin_required
def _admin_step_offices(election_id):
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
```

Add `offices` to the skip-list. The form-post URL stays at `/admin/election/<id>/setup` (existing route at line 764), but that route's redirect-on-success needs to point at the new step URL. Find the `admin_election_setup` view and update any `redirect(url_for("admin_election_setup", ...))` lines to `redirect(url_for("admin_step_offices", ...))`.

- [ ] **Step 5: Run tests**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
```

Expected: all PASS, including the new offices test.

- [ ] **Step 6: Commit**

```
git add voting-app/app.py voting-app/templates/admin/step_offices.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 3 - offices & candidates step shell"
```

---

### Task 6: Step 4 - Election settings (`step/settings`)

**Files:**
- Create: `voting-app/templates/admin/step_settings.html`
- Modify: `voting-app/app.py` (replace `settings` stub)

- [ ] **Step 1: Write failing test**

```python
def test_step_settings_renders_paper_count_toggle(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/step/settings")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "paper count" in body.lower() or "paper_count_enabled" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Create `step_settings.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Election settings - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Election settings{% endblock %}
{% block step_heading %}Optional features for this election{% endblock %}
{% block step_content %}
<form method="POST" action="{{ url_for('admin_election_settings', election_id=sidebar_state.election.id) }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

    <div class="form-group">
        <label style="display: flex; align-items: flex-start; gap: 10px;">
            <input type="checkbox" name="paper_count_enabled" value="1"
                   {% if election.paper_count_enabled %}checked{% endif %}
                   style="margin-top: 4px;">
            <span>
                <strong>Enable paper count helper</strong>
                <span style="display: block; font-size: 13px; color: #666; margin-top: 2px;">
                    Volunteers can opt in to co-count paper ballots on their phones during the chairman's read-out.
                </span>
            </span>
        </label>
    </div>

    <button type="submit" class="btn btn-primary">Save settings</button>
    <a href="{{ url_for('admin_step_codes', election_id=sidebar_state.election.id) }}"
       class="btn btn-outline" style="margin-left: 8px;">Next: Codes &amp; printing &rarr;</a>
</form>
{% endblock %}
```

- [ ] **Step 4: Replace `settings` stub**

```python
@app.route("/admin/election/<int:election_id>/step/settings", methods=["GET"], endpoint="admin_step_settings")
@admin_required
def _admin_step_settings(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template("admin/step_settings.html",
                           election=election, sidebar_state=sidebar_state)
```

Add `settings` to the skip-list. Update `admin_election_settings` (line 873) to redirect to `admin_step_settings` after save.

- [ ] **Step 5: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_settings.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 4 - election settings step shell"
```

---

### Task 7: Step 5 - Codes & printing (`step/codes`)

**Files:**
- Create: `voting-app/templates/admin/step_codes.html`
- Modify: `voting-app/app.py` (replace `codes` stub)

This step combines today's `codes.html` content **plus** the "Print & prepare" + "Postal votes (early)" sections from Phase 1 of `manage.html`.

- [ ] **Step 1: Write failing test**

```python
def test_step_codes_shows_status_and_printer_pack(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    admin_client.post("/admin/election/1/setup", data={
        "office_name": "Elder", "vacancies": "1", "max_selections": "1",
        "candidate_names": "A\nB\nC", "confirm_slate_override": "1",
    })
    admin_client.post("/admin/election/1/codes", data={"count": "10"})
    rv = admin_client.get("/admin/election/1/step/codes")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Total Codes" in body or "10" in body
    assert "Printer Pack" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_codes.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Codes &amp; printing - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Codes &amp; printing{% endblock %}
{% block step_heading %}Generate codes and print materials{% endblock %}
{% block step_content %}

{# ============= Code status (from codes.html lines 18-77) ============= #}
<div class="card">
    <div class="card-header">Code Status</div>
    <div class="stat-grid">
        <div class="stat-box">
            <div class="number">{{ total_codes }}</div>
            <div class="label">Total Codes</div>
        </div>
        <div class="stat-box">
            <div class="number">{{ used_codes }}</div>
            <div class="label">Used</div>
        </div>
        <div class="stat-box">
            <div class="number">{{ total_codes - used_codes }}</div>
            <div class="label">Available</div>
        </div>
    </div>

    {% if total_codes > 0 %}
    <details style="margin-top: 16px;">
        <summary style="cursor: pointer; color: var(--red); font-weight: 600;">
            Delete all codes (regenerate)
        </summary>
        <div style="margin-top: 12px; padding: 14px 16px; border: 1px solid var(--red); border-radius: 8px; background: #fff7f6;">
            <p style="font-size: 14px; color: #6B1A12; margin-bottom: 12px;">
                <strong>Warning.</strong> Codes may already be on printed slips
                or QR-coded handouts. If you regenerate without reprinting,
                every printed code will fail at the door on election day.
                {% if used_codes > 0 %}<br><br>
                <strong>{{ used_codes }} of these codes have already been used.</strong>
                Deleting is blocked while votes exist.{% endif %}
            </p>
            <form method="POST" action="{{ url_for('admin_codes_delete', election_id=sidebar_state.election.id) }}"
                  onsubmit="return confirm('Delete ALL {{ total_codes }} codes for {{ sidebar_state.election.name }}? This cannot be undone.');">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div class="form-group">
                    <label>Type the election name to confirm: <strong>{{ sidebar_state.election.name }}</strong></label>
                    <input type="text" name="confirm_name" autocomplete="off"
                           placeholder="{{ sidebar_state.election.name }}"
                           {% if used_codes > 0 %}disabled{% endif %}>
                </div>
                <div class="form-group">
                    <label>Admin password</label>
                    <input type="password" name="password" autocomplete="off"
                           placeholder="Re-enter password"
                           {% if used_codes > 0 %}disabled{% endif %}>
                </div>
                <button type="submit" class="btn btn-danger btn-small"
                        {% if used_codes > 0 %}disabled{% endif %}>Delete All Codes</button>
            </form>
        </div>
    </details>
    {% endif %}
</div>

{% if total_codes == 0 %}
<div class="card">
    <div class="card-header">Generate Codes</div>
    <p style="font-size: 14px; color: #666; margin-bottom: 12px;">
        No codes yet. Codes are normally created automatically the first
        time you visit this step after setting up offices.
    </p>
    <form method="POST" action="{{ url_for('admin_codes', election_id=sidebar_state.election.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div class="form-group">
            <label>Number of Codes</label>
            <input type="number" name="count" value="{{ default_count }}" min="1" max="999">
            {% if member_count > 0 %}
            <p style="font-size: 14px; color: #666; margin-top: 4px;">
                Based on {{ member_count }} members &times; {{ sidebar_state.election.max_rounds }} rounds + spares
            </p>
            {% endif %}
        </div>
        <button type="submit" class="btn btn-gold">Generate Codes</button>
    </form>
</div>
{% endif %}

{% if generated_codes %}
<div class="card">
    <div class="card-header">Generated Codes (save or print now!)</div>
    <p style="font-size: 14px; color: #666; margin-bottom: 12px;">
        These are shown only once. Use the Code Slips PDF to print them.
    </p>
    <div style="columns: 3; column-gap: 16px; font-family: monospace; font-size: 16px;">
        {% for code in generated_codes %}
        <div style="break-inside: avoid; padding: 4px 0;">{{ code }}</div>
        {% endfor %}
    </div>
</div>
{% endif %}

{# ============= Print & prepare (from manage.html Phase 1) ============= #}
<h3 style="margin: 18px 0 8px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">Print &amp; prepare</h3>
<div class="btn-row" style="flex-wrap: wrap; margin-bottom: 16px;">
    <a href="{{ url_for('admin_printer_pack_zip', election_id=sidebar_state.election.id) }}" class="btn btn-gold btn-small">
        Printer Pack ZIP (recommended)
    </a>
    <a href="{{ url_for('admin_attendance_pdf') }}" class="btn btn-outline btn-small">Attendance Register PDF</a>
</div>
<details>
    <summary style="cursor: pointer; font-size: 13px; color: #666;">More formats (individual PDFs)</summary>
    <div class="btn-row" style="flex-wrap: wrap; margin-top: 8px;">
        <a href="{{ url_for('admin_counter_sheet_pdf', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">Counter Sheet PDF</a>
        <a href="{{ url_for('admin_dual_sided_ballots_pdf', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">Dual-Sided Ballots PDF</a>
        <a href="{{ url_for('admin_paper_ballot_pdf', election_id=sidebar_state.election.id, round_number=sidebar_state.election.current_round) }}" class="btn btn-outline btn-small">Paper Ballot PDF</a>
        <a href="{{ url_for('admin_codes_pdf', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">Code Slips PDF</a>
    </div>
</details>

{# ============= Early postal votes (from manage.html Phase 1 bottom) ============= #}
<h3 style="margin: 18px 0 8px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">Postal votes (early)</h3>
<p style="font-size: 14px; color: #555; margin-bottom: 8px;">
    {% if postal_voter_count > 0 %}
    {{ postal_voter_count }} postal vote{{ '' if postal_voter_count == 1 else 's' }} entered.
    {% else %}
    No postal votes entered yet. You can also enter them on the day from <em>Attendance &amp; postal</em> (last-chance entry).
    {% endif %}
</p>
<div class="btn-row">
    <a href="{{ url_for('admin_postal_votes', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">Enter Postal Votes (Round 1)</a>
    <a href="{{ url_for('admin_postal_tally', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">Postal Tally Helper</a>
</div>

<div style="margin-top: 18px;">
    <a href="{{ url_for('admin_step_attendance', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Attendance &amp; postal (election day) &rarr;
    </a>
</div>
{% endblock %}
```

- [ ] **Step 3: Replace `codes` stub**

```python
@app.route("/admin/election/<int:election_id>/step/codes", methods=["GET"], endpoint="admin_step_codes")
@admin_required
def _admin_step_codes(election_id):
    db = get_db()
    election = db.execute(
        "SELECT * FROM elections WHERE id = ?", (election_id,)
    ).fetchone()
    if not election:
        abort(404)

    # Auto-generate codes on first visit if offices exist and no codes yet
    # (mirrors the existing behavior of /admin/election/<id>/codes GET).
    total_codes = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ?", (election_id,)
    ).fetchone()[0]
    generated_codes = []
    member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    default_count = max(member_count + 5, 50)
    if total_codes == 0:
        offices_exist = db.execute(
            "SELECT 1 FROM offices WHERE election_id = ? LIMIT 1", (election_id,)
        ).fetchone()
        if offices_exist and member_count > 0:
            generated_codes = generate_codes(election_id, default_count)
            total_codes = len(generated_codes)
    used_codes = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1", (election_id,)
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
```

Add `codes` to the skip-list.

- [ ] **Step 4: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_codes.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 5 - codes & printing combined step"
```

---

### Task 8: Step 6 - Attendance & postal (`step/attendance`)

**Files:**
- Create: `voting-app/templates/admin/step_attendance.html`
- Modify: `voting-app/app.py`

Extract from `manage.html` Phase 2 the "Step 1 Attendance" + "Step 2 Postal votes (last chance)" sections (lines 253-316 of current manage.html).

- [ ] **Step 1: Write failing test**

```python
def test_step_attendance_shows_participants_form(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/step/attendance")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Brothers Present" in body or "participants" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_attendance.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Attendance &amp; postal - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Attendance &amp; postal{% endblock %}
{% block step_heading %}Set the attendance count from the register{% endblock %}
{% block step_content %}
{% set attendance_missing = (in_person_participants or 0) <= 0 %}

<div style="margin-bottom: 14px; padding: 14px; border-radius: 8px;
            {% if attendance_missing %}background: #FFF6E5; border: 2px solid #C0392B;
            {% else %}background: #F4FAF6; border: 1px solid #B8E0C8;{% endif %}">
    <h3 style="margin: 0 0 6px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">
        {% if attendance_missing %}&#9888; Attendance not yet set (Article 4)
        {% else %}&#10003; Attendance set (Article 4){% endif %}
    </h3>
    <p style="font-size: 14px; color: #444; margin: 0 0 10px;">
        Count the brothers who have signed the <strong>attendance register</strong>
        at the door, and enter that number below. This drives the Article 6b
        threshold &mdash; without it, no candidate can be declared elected.
    </p>
    <form method="POST" action="{{ url_for('admin_set_participants', election_id=sidebar_state.election.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div style="display: flex; gap: 14px; flex-wrap: wrap; align-items: end;">
            <div class="form-group" style="flex: 1; min-width: 200px; margin: 0;">
                <label for="participants" style="font-weight: 700;">Brothers Present (from attendance register)</label>
                <input type="number" id="participants" name="participants"
                       value="{{ in_person_participants }}" min="0"
                       style="text-align: center; font-size: 22px; font-weight: 700;">
            </div>
            <button type="submit" class="btn btn-primary">Save attendance</button>
        </div>
    </form>
</div>

<div style="margin-bottom: 18px; padding: 12px 14px;
            background: #FFFAF0; border-left: 4px solid var(--gold);
            border-radius: 6px;">
    <h3 style="margin: 0 0 4px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">
        Postal votes (last chance)
    </h3>
    <p style="font-size: 14px; color: #444; margin: 0 0 8px;">
        {% if postal_voter_count > 0 %}<strong>{{ postal_voter_count }} postal vote{{ '' if postal_voter_count == 1 else 's' }}</strong> already entered.
        {% else %}<strong>No postal votes entered yet.</strong>{% endif %}
        Last chance to enter envelopes handed to the chairman just now &mdash; postal
        votes that arrive after voting opens cannot be added.
    </p>
    <div class="btn-row">
        <a href="{{ url_for('admin_postal_votes', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">
            {% if postal_voter_count > 0 %}Add or adjust postal votes{% else %}Enter postal votes{% endif %}
        </a>
        <a href="{{ url_for('admin_postal_tally', election_id=sidebar_state.election.id) }}" class="btn btn-outline btn-small">Postal Tally Helper</a>
    </div>
</div>

<div style="margin-top: 18px;">
    {% if attendance_missing %}
    <button class="btn btn-outline" disabled title="Set attendance first">Next: Welcome &amp; Rules &rarr;</button>
    <p style="font-size: 13px; color: #C0392B; margin-top: 6px;">Save attendance above before advancing.</p>
    {% else %}
    <a href="{{ url_for('admin_step_welcome', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Welcome &amp; Rules &rarr;
    </a>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Replace `attendance` stub**

```python
@app.route("/admin/election/<int:election_id>/step/attendance", methods=["GET"], endpoint="admin_step_attendance")
@admin_required
def _admin_step_attendance(election_id):
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
```

Add `attendance` to the skip-list. Update `admin_set_participants` (line 1453) to redirect to `admin_step_attendance` (instead of the old manage page) when called from the attendance step. Detection: check `request.referrer` ends with `/step/attendance`, or always redirect to the attendance step. Simplest: always redirect to `admin_step_attendance` since that's the new home for this form.

- [ ] **Step 4: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_attendance.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 6 - attendance & postal step shell"
```

---

### Task 9: Step 7 - Welcome & Rules (`step/welcome`)

**Files:**
- Create: `voting-app/templates/admin/step_welcome.html`
- Modify: `voting-app/app.py`

Extract from `manage.html` Phase 2 the "Step 3 Projector display" section (lines 318-355).

- [ ] **Step 1: Write failing test**

```python
def test_step_welcome_shows_projector_advance(election_with_codes):
    # Need attendance > 0 to reach this step; election_with_codes already sets it
    rv = election_with_codes.get("/admin/election/1/step/welcome")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Welcome" in body or "Election Rules" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_welcome.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Welcome &amp; Rules - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Welcome &amp; Rules{% endblock %}
{% block step_heading %}Walk the projector through Welcome and Election Rules{% endblock %}
{% block step_content %}

<p style="font-size: 14px; color: #555; margin-bottom: 14px;">
    Walk the projector through <strong>Welcome</strong> and <strong>Election Rules</strong>
    with the meeting. When ready, advance to <em>Voting</em> below to open the round.
</p>

<div style="display: flex; align-items: center; gap: 0; margin-bottom: 12px;">
    {% set proj_phases = [(1, "Welcome"), (2, "Election Rules")] %}
    {% for num, label in proj_phases %}
    <div style="flex: 1; text-align: center; padding: 8px 4px; font-size: 13px; font-weight: 600;
                {{ 'background: var(--navy); color: var(--white);' if phase == num else 'background: var(--grey-light); color: #999;' }}
                {{ 'border-radius: 6px 0 0 6px;' if loop.first else '' }}
                {{ 'border-radius: 0 6px 6px 0;' if loop.last else '' }}">
        {{ num }}. {{ label }}{% if phase == num %} &bull;{% endif %}
    </div>
    {% endfor %}
</div>

<div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 4px;">
    {% if phase == 2 %}
    <form method="POST" action="{{ url_for('admin_set_display_phase', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="direction" value="prev">
        <button type="submit" class="btn btn-outline btn-small">&larr; Back to Welcome</button>
    </form>
    {% endif %}
    {% if phase < 2 %}
    <form method="POST" action="{{ url_for('admin_set_display_phase', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="direction" value="next">
        <button type="submit" class="btn btn-gold">Next: Election Rules &rarr;</button>
    </form>
    {% endif %}
    <a href="{{ url_for('display') }}" target="_blank" class="btn btn-outline btn-small" style="margin-left: auto;">Open Display</a>
</div>

<div style="margin-top: 18px;">
    <a href="{{ url_for('admin_step_voting', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Voting &rarr;
    </a>
</div>
{% endblock %}
```

- [ ] **Step 3: Replace `welcome` stub**

```python
@app.route("/admin/election/<int:election_id>/step/welcome", methods=["GET"], endpoint="admin_step_welcome")
@admin_required
def _admin_step_welcome(election_id):
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
```

Add `welcome` to skip-list. Update `admin_set_display_phase` (line 1113) to redirect back to the step that called it (use `request.referrer` or a `next` form field). Simplest: redirect to `admin_step_welcome` if target phase <= 2, else redirect based on phase.

- [ ] **Step 4: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_welcome.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 7 - welcome & rules step shell"
```

---

### Task 10: Step 8 - Voting (`step/voting`) + behavior change

**Files:**
- Create: `voting-app/templates/admin/step_voting.html`
- Modify: `voting-app/app.py` - replace `voting` stub AND remove `show_results = 1` from `admin_toggle_voting` (line 1071-1075)

Extract from `manage.html` Phase 3 (lines 360-444) plus the Round N Tally table that follows (lines 446-562).

- [ ] **Step 1: Write failing test for the behavior change**

```python
def test_close_voting_does_not_auto_reveal_results(election_with_codes):
    # Open voting
    election_with_codes.post("/admin/election/1/voting")
    # Close voting
    election_with_codes.post("/admin/election/1/voting")
    # show_results should remain 0
    from app import get_db
    with app.app_context():
        db = get_db()
        row = db.execute("SELECT show_results FROM elections WHERE id = 1").fetchone()
    assert row["show_results"] == 0, "Closing voting must not auto-reveal results on the projector"


def test_step_voting_shows_open_close_button(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/step/voting")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Open" in body and "Round" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Run to verify both fail**

The behavior test fails because the existing handler still sets `show_results = 1`.

- [ ] **Step 3: Remove `show_results = 1` from `admin_toggle_voting`**

In `voting-app/app.py` find:

```python
    # Closing voting auto-reveals the results panel on the projector so the
    # chairman doesn't need a second click. The clean ELECTED-only summary
    # is still a separate manual step (advance display phase to 4).
    if new_state == 0:
        db.execute(
            "UPDATE elections SET voting_open = 0, show_results = 1 WHERE id = ?",
            (election_id,)
        )
    else:
```

Replace with:

```python
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
```

- [ ] **Step 4: Create `step_voting.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Voting - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Voting{% endblock %}
{% block step_heading %}Open the round, monitor ballots, close when ready{% endblock %}
{% block step_content %}
{% set total_ballots = used_codes + paper_ballot_count + postal_voter_count %}

<div style="margin-bottom: 14px;">
    <form method="POST" action="{{ url_for('admin_toggle_voting', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% if election.voting_open %}
        <button type="submit" class="btn btn-danger" onclick="return confirm('Close voting for round {{ election.current_round }}?');">
            Close Round {{ election.current_round }}
        </button>
        {% else %}
        <button type="submit" class="btn btn-success"
                onclick="return confirm('Open/Reopen round {{ election.current_round }}?');">
            Open Round {{ election.current_round }}
        </button>
        {% endif %}
    </form>
</div>

{% if this_round_opened %}
<div style="display: flex; gap: 12px; flex-wrap: wrap; align-items: baseline; font-size: 14px; color: #555; margin-bottom: 14px;">
    <span>Ballots received: <strong>{{ total_ballots }}</strong></span>
    <span>&middot;</span>
    <span>Brothers participating: <strong>{{ participants }}</strong></span>
    {% if participants > 0 %}
    <span>&middot;</span>
    <span>Still to vote: <strong>{{ (participants - total_ballots) if (participants - total_ballots) > 0 else 0 }}</strong></span>
    {% endif %}
</div>

<div class="btn-row" style="flex-wrap: wrap; margin-bottom: 14px;">
    <form method="POST" action="{{ url_for('admin_toggle_results', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% if election.show_results %}
        <button type="submit" class="btn btn-outline btn-small">Hide Results on Projector</button>
        {% else %}
        <button type="submit" class="btn btn-gold btn-small">Show Results on Projector</button>
        {% endif %}
    </form>
    <a href="{{ url_for('display') }}" target="_blank" class="btn btn-outline btn-small">Open Display</a>
    {% if election.paper_count_enabled %}
    <a href="{{ url_for('admin_count_dashboard', election_id=sidebar_state.election.id, round_no=sidebar_state.election.current_round) }}"
       target="_blank" class="btn btn-outline btn-small">Paper Count Dashboard</a>
    {% endif %}
</div>

<p style="font-size: 13px; margin-top: 10px;">
    <a href="{{ url_for('admin_voter_log', election_id=sidebar_state.election.id) }}" style="color: #666;">View voter audit log &rarr;</a>
</p>
{% endif %}

{% if this_round_opened and results %}
{# ============= Round tally table - copy verbatim from manage.html lines 449-562 ============= #}
<div style="margin: 18px 0; padding: 16px 18px; background: white; border: 1px solid var(--grey); border-radius: 8px;">
    <h3 style="margin: 0 0 12px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">
        Round {{ election.current_round }} tally
    </h3>
    {# COPY the entire {% for item in results %} ... {% endfor %} block from manage.html lines 453-561 here verbatim #}
</div>
{% endif %}

{% if not election.voting_open and this_round_opened %}
<div style="margin-top: 18px;">
    <a href="{{ url_for('admin_step_count', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Count &amp; tally &rarr;
    </a>
</div>
{% endif %}
{% endblock %}
```

**Concrete copy-paste:** the tally-table block under `{% if this_round_opened and results %}` is the same logic as `manage.html` lines 449-562. Copy that block verbatim into this template (replace `election.id` with `sidebar_state.election.id` if needed for url_for calls inside the block).

- [ ] **Step 5: Replace `voting` stub**

```python
@app.route("/admin/election/<int:election_id>/step/voting", methods=["GET"], endpoint="admin_step_voting")
@admin_required
def _admin_step_voting(election_id):
    """Render the voting step. The data shape mirrors what admin_election_manage
    builds for its Phase 3 + tally table sections; reuse that builder."""
    payload = _build_manage_view_payload(election_id)  # see refactor note below
    return render_template("admin/step_voting.html", **payload)
```

**Refactor note:** the existing `admin_election_manage` view (line 1196) builds a large context dict (`results`, `thresholds`, `total_ballots`, `participants`, `phase_done`, etc.). Extract that into a reusable helper `_build_manage_view_payload(election_id) -> dict` (defined just above `admin_election_manage`). Both the legacy manage view and the new step views call it. The helper returns a dict that includes `sidebar_state = compute_sidebar_state(election_id)`.

This refactor is a one-time move; it's worth doing now so steps 8, 9, 10, 11 don't each repeat 100 lines of query code.

- [ ] **Step 6: Run all tests**

```
cd voting-app && python -m pytest tests/ -v
```

Expected: all PASS (existing tests too — the `_build_manage_view_payload` extraction must not change behavior).

- [ ] **Step 7: Commit**

```
git add voting-app/app.py voting-app/templates/admin/step_voting.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 8 - voting; remove auto-reveal on close round"
```

---

### Task 11: Step 9 - Count & tally (`step/count`)

**Files:**
- Create: `voting-app/templates/admin/step_count.html`
- Modify: `voting-app/app.py`

Extract from `manage.html` Phase 4 (lines 568-619, the counting section, NOT the decide section).

- [ ] **Step 1: Write failing test**

```python
def test_step_count_shows_paper_inputs(election_with_codes):
    election_with_codes.post("/admin/election/1/voting")
    election_with_codes.post("/admin/election/1/voting")  # close
    rv = election_with_codes.get("/admin/election/1/step/count")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Paper Ballots Received" in body or "paper_ballot_count" in body
    assert "Enter Paper Votes" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_count.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Count &amp; tally - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Count &amp; tally{% endblock %}
{% block step_heading %}Enter paper ballot counts and per-candidate tally{% endblock %}
{% block step_content %}

<p style="font-size: 14px; color: #555; margin-bottom: 14px;">
    Voting closed. Count the paper ballots, enter the per-candidate
    tally below, then advance to <em>Decide</em>.
</p>

<h3 style="margin: 8px 0 8px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">Paper ballots received</h3>
<form method="POST" action="{{ url_for('admin_set_participants', election_id=sidebar_state.election.id) }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div style="display: flex; gap: 14px; flex-wrap: wrap; align-items: end; margin-bottom: 8px;">
        <div class="form-group" style="flex: 1; min-width: 200px;">
            <label>Paper Ballots Received</label>
            <input type="number" name="paper_ballot_count" value="{{ paper_ballot_count }}"
                   min="0" style="text-align: center;">
        </div>
        <button type="submit" class="btn btn-primary btn-small">Save</button>
    </div>
</form>

<div class="btn-row" style="margin-bottom: 16px;">
    <a href="{{ url_for('admin_paper_votes', election_id=sidebar_state.election.id) }}" class="btn btn-gold">
        Enter Paper Votes (per candidate)
    </a>
    {% if election.paper_count_enabled %}
    <a href="{{ url_for('admin_count_dashboard', election_id=sidebar_state.election.id, round_no=sidebar_state.election.current_round) }}"
       target="_blank" class="btn btn-outline">Paper Count Dashboard</a>
    {% endif %}
    <form method="POST" action="{{ url_for('admin_toggle_results', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% if election.show_results %}
        <button type="submit" class="btn btn-outline btn-small">Hide Results on Projector</button>
        {% else %}
        <button type="submit" class="btn btn-gold btn-small">Show Results on Projector</button>
        {% endif %}
    </form>
</div>

{# ============= Round tally table - same block as step 8 ============= #}
{% if this_round_opened and results %}
<div style="margin: 18px 0; padding: 16px 18px; background: white; border: 1px solid var(--grey); border-radius: 8px;">
    <h3 style="margin: 0 0 12px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">
        Round {{ election.current_round }} tally
    </h3>
    {# COPY the same {% for item in results %} block as step_voting.html (which itself was copied from manage.html lines 453-561) #}
</div>
{% endif %}

<div style="margin-top: 18px;">
    <a href="{{ url_for('admin_step_decide', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Decide &rarr;
    </a>
</div>
{% endblock %}
```

- [ ] **Step 3: Replace `count` stub**

```python
@app.route("/admin/election/<int:election_id>/step/count", methods=["GET"], endpoint="admin_step_count")
@admin_required
def _admin_step_count(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_count.html", **payload)
```

Add `count` to skip-list.

- [ ] **Step 4: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_count.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 9 - count & tally step shell"
```

---

### Task 12: Step 10 - Decide (`step/decide`)

**Files:**
- Create: `voting-app/templates/admin/step_decide.html`
- Modify: `voting-app/app.py`

Extract from `manage.html` Phase 4 lines 620-664 (the "Decide what's next" panel with carry-forward picker and Show Final Results form).

- [ ] **Step 1: Write failing test**

```python
def test_step_decide_shows_options_after_close(election_with_codes):
    election_with_codes.post("/admin/election/1/voting")
    election_with_codes.post("/admin/election/1/voting")
    rv = election_with_codes.get("/admin/election/1/step/decide")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Start Round" in body or "Show Final Results" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_decide.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Decide - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Decide{% endblock %}
{% block step_heading %}Another round, or finalise the election?{% endblock %}
{% block step_content %}

<p style="font-size: 14px; color: #555; margin-bottom: 14px;">
    Review the round {{ election.current_round }} result. You can either start
    another round (carry forward unelected candidates), or finalise the
    election with the result as it stands.
</p>

{% if not election.voting_open and not election_complete %}
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
    <div style="border: 1px solid var(--grey); border-radius: 8px; padding: 14px;">
        <h4 style="margin: 0 0 8px; color: var(--navy);">Start Round {{ election.current_round + 1 }}</h4>
        <p style="font-size: 13px; color: #666; margin-bottom: 10px;">
            Select the candidates to carry forward. Article 7: if no candidate
            is elected this round, reduce the slate to twice the remaining
            vacancies by eliminating those with the lowest votes.
        </p>
        <form method="POST" action="{{ url_for('admin_next_round', election_id=sidebar_state.election.id) }}"
              onsubmit="return confirm('Start round {{ election.current_round + 1 }}? This cannot be undone.');">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            {% for item in results %}
            <p style="margin: 8px 0 4px; font-weight: 700;">{{ item.office.name }}</p>
            {% for cand in item.candidates %}
            {% if cand.active %}
            <label class="checkbox-label" style="display: block; margin-bottom: 4px; font-size: 13px;">
                <input type="checkbox" name="carry_forward" value="{{ cand.id }}"
                       {% if cand.meets_threshold|default(false) %}disabled{% endif %}>
                {{ cand.name }} ({{ cand.total }} votes)
                {% if cand.meets_threshold|default(false) %}
                <span style="color: var(--green); font-size: 12px;">- ELECTED</span>
                {% endif %}
            </label>
            {% endif %}
            {% endfor %}
            {% endfor %}
            <button type="submit" class="btn btn-gold btn-small" style="margin-top: 10px;">
                Start Round {{ election.current_round + 1 }} &rarr;
            </button>
        </form>
    </div>

    <div style="border: 1px solid var(--grey); border-radius: 8px; padding: 14px;">
        <h4 style="margin: 0 0 8px; color: var(--navy);">Finalise the election</h4>
        <p style="font-size: 13px; color: #666; margin-bottom: 10px;">
            Conclude with the result as it stands. The projector and phone
            displays will switch to the Final Results screen.
        </p>
        <form method="POST" action="{{ url_for('admin_set_display_phase', election_id=sidebar_state.election.id) }}" class="inline-form">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="target" value="4">
            <button type="submit" class="btn btn-primary btn-small">Show Final Results &rarr;</button>
        </form>
    </div>
</div>
{% else %}
<p style="color: #666;">
    {% if election.voting_open %}Voting is still open. Close the round on <em>Voting</em> first.
    {% elif election_complete %}Election complete. Continue to <em>Final results</em>.{% endif %}
</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Replace `decide` stub**

```python
@app.route("/admin/election/<int:election_id>/step/decide", methods=["GET"], endpoint="admin_step_decide")
@admin_required
def _admin_step_decide(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_decide.html", **payload)
```

- [ ] **Step 4: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_decide.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 10 - decide step shell"
```

---

### Task 13: Step 11 - Final results (`step/final`)

**Files:**
- Create: `voting-app/templates/admin/step_final.html`
- Modify: `voting-app/app.py`

Extract from `manage.html` Phase 5 (lines 670-724).

- [ ] **Step 1: Write failing test**

```python
def test_step_final_renders_when_phase_4(election_with_codes):
    # Force phase 4
    election_with_codes.post("/admin/election/1/display-phase",
                              data={"target": "4"})
    rv = election_with_codes.get("/admin/election/1/step/final")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Final Results" in body or "Final results" in body
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_final.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Final results - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Final results{% endblock %}
{% block step_heading %}Reveal the elected brothers{% endblock %}
{% block step_content %}

{% if elected_summary_by_office %}
<h3 style="margin: 0 0 10px; font-size: 14px; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px;">Elected brothers</h3>
{% for entry in elected_summary_by_office %}
<div style="margin-bottom: 12px;">
    <strong>For {{ entry.office_name }}:</strong>
    {% if entry.names %}
    {{ entry.names | join(', ') | replace('Br ', 'Br. ') }}
    - {{ entry.names | length }} of {{ entry.original_vacancies }}
    {% else %}
    <em>no candidate met the required thresholds</em>
    {% endif %}
</div>
{% endfor %}
{% endif %}

<div class="btn-row" style="margin-top: 14px; flex-wrap: wrap;">
    {% if phase != 4 %}
    <form method="POST" action="{{ url_for('admin_set_display_phase', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="target" value="4">
        <button type="submit" class="btn btn-gold">Show Final Results on Projector</button>
    </form>
    {% else %}
    <span style="color: #555; font-size: 14px;">
        Projector showing: <strong>{% if election.show_results %}Vote Details{% else %}Final Summary{% endif %}</strong>
    </span>
    <form method="POST" action="{{ url_for('admin_toggle_results', election_id=sidebar_state.election.id) }}" class="inline-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% if election.show_results %}
        <button type="submit" class="btn btn-outline btn-small">Show Final Summary</button>
        {% else %}
        <button type="submit" class="btn btn-gold btn-small">Show Vote Details</button>
        {% endif %}
    </form>
    {% endif %}
</div>

<div style="margin-top: 18px;">
    <a href="{{ url_for('admin_step_minutes', election_id=sidebar_state.election.id) }}" class="btn btn-primary">
        Next: Minutes &amp; archive &rarr;
    </a>
</div>
{% endblock %}
```

- [ ] **Step 3: Replace `final` stub**

```python
@app.route("/admin/election/<int:election_id>/step/final", methods=["GET"], endpoint="admin_step_final")
@admin_required
def _admin_step_final(election_id):
    payload = _build_manage_view_payload(election_id)
    return render_template("admin/step_final.html", **payload)
```

- [ ] **Step 4: Run + commit**

```
cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v
git add voting-app/app.py voting-app/templates/admin/step_final.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 11 - final results step shell"
```

---

### Task 14: Step 12 - Minutes & archive (`step/minutes`)

**Files:**
- Create: `voting-app/templates/admin/step_minutes.html`
- Modify: `voting-app/app.py`

- [ ] **Step 1: Write failing test**

```python
def test_step_minutes_links_to_docx(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/step/minutes")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Minutes" in body
    assert "/admin/election/1/minutes" in body or "minutes" in body.lower()
    assert "wizard-sidebar" in body
```

- [ ] **Step 2: Create `step_minutes.html`**

```jinja
{% extends "admin/_step_base.html" %}
{% block title %}Minutes &amp; archive - {{ sidebar_state.election.name }}{% endblock %}
{% block step_tag %}Minutes &amp; archive{% endblock %}
{% block step_heading %}Download the minutes and archive the database{% endblock %}
{% block step_content %}

<div class="card">
    <div class="card-header">Election minutes</div>
    <p style="font-size: 14px; color: #555; margin-bottom: 12px;">
        Narrative minutes with one section per round, ready for the secretary
        to fill in placeholders (chairman name, scripture reference, helpers'
        names, etc.).
    </p>
    <a href="{{ url_for('admin_minutes_docx', election_id=sidebar_state.election.id) }}"
       class="btn btn-primary">Download Election Minutes (DOCX)</a>
</div>

<div class="card">
    <div class="card-header">Archive the database</div>
    <p style="font-size: 14px; color: #555; margin-bottom: 12px;">
        Copy the database file at <code>data/frca_election.db</code> to a safe
        location for the congregation's records (e.g. a USB stick or the
        secretary's encrypted folder). You can do this at any time after the
        election concludes.
    </p>
    <p style="font-size: 13px; color: #999;">
        Tip: rename the copy with the date and election name, e.g.
        <code>frca_election_2026-10-20_office-bearers.db</code>.
    </p>
</div>
{% endblock %}
```

- [ ] **Step 3: Replace `minutes` stub**

```python
@app.route("/admin/election/<int:election_id>/step/minutes", methods=["GET"], endpoint="admin_step_minutes")
@admin_required
def _admin_step_minutes(election_id):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    sidebar_state = compute_sidebar_state(election_id)
    return render_template("admin/step_minutes.html", election=election, sidebar_state=sidebar_state)
```

- [ ] **Step 4: Verify the stub-registration loop is now empty**

After this task, the stub-registration loop's skip-list contains all 12 slugs. Replace the loop with a deletion of the loop entirely (and also delete `_make_step_stub`, since it's no longer used):

```python
# (delete the entire `for _slug, _label, _group in WIZARD_STEPS:` loop and `_make_step_stub` definition)
```

- [ ] **Step 5: Run all tests**

```
cd voting-app && python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```
git add voting-app/app.py voting-app/templates/admin/step_minutes.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): step 12 - minutes & archive; remove stub loop"
```

---

### Task 15: Old URL redirects + dashboard "Manage" link

**Files:**
- Modify: `voting-app/app.py`
- Modify: `voting-app/templates/admin/dashboard.html`

- [ ] **Step 1: Write failing test**

```python
def test_old_manage_url_redirects_to_step(election_with_codes):
    rv = election_with_codes.get("/admin/election/1/manage", follow_redirects=False)
    assert rv.status_code in (301, 302, 308)
    assert "/step/" in rv.location


def test_old_setup_url_redirects_to_offices_step(admin_client):
    admin_client.post("/admin/election/new", data={"name": "E", "max_rounds": "2"})
    rv = admin_client.get("/admin/election/1/setup", follow_redirects=False)
    assert rv.status_code in (301, 302, 308)
    assert "/step/offices" in rv.location


def test_dashboard_manage_link_targets_step(election_with_codes):
    rv = election_with_codes.get("/admin")
    assert b"/step/" in rv.data
```

- [ ] **Step 2: Implement redirects**

In `voting-app/app.py`, find the existing `admin_election_manage` GET route (line 1196). **Rename it** to `admin_election_manage_legacy` and convert to a redirect:

```python
@app.route("/admin/election/<int:election_id>/manage")
@admin_required
def admin_election_manage_legacy(election_id):
    """Legacy URL. Redirect to the step shell at the current default step."""
    state = compute_sidebar_state(election_id)
    if not state:
        abort(404)
    return redirect(url_for(f"admin_step_{state['current_step']}", election_id=election_id), code=301)
```

The existing `admin_election_setup` route (line 764) handles both GET and POST. Split it:

```python
@app.route("/admin/election/<int:election_id>/setup", methods=["GET"])
@admin_required
def admin_election_setup_legacy_get(election_id):
    return redirect(url_for("admin_step_offices", election_id=election_id), code=301)


# Keep the existing admin_election_setup function but restrict to POST only,
# and rename if needed. The endpoint name `admin_election_setup` stays the same
# (since templates' url_for("admin_election_setup", ...) is the office form action).
@app.route("/admin/election/<int:election_id>/setup", methods=["POST"], endpoint="admin_election_setup")
@admin_required
def admin_election_setup(election_id):
    # ...existing function body unchanged, except its final redirect targets
    # admin_step_offices instead of admin_election_setup...
```

For the codes legacy URL:

```python
@app.route("/admin/election/<int:election_id>/codes", methods=["GET"])
@admin_required
def admin_codes_legacy_get(election_id):
    return redirect(url_for("admin_step_codes", election_id=election_id), code=301)


# admin_codes existing function: restrict to POST only; final redirects to step_codes
@app.route("/admin/election/<int:election_id>/codes", methods=["POST"], endpoint="admin_codes")
@admin_required
def admin_codes(election_id):
    # ...existing body, with final redirect changed to admin_step_codes...
```

- [ ] **Step 3: Update dashboard.html**

In `voting-app/templates/admin/dashboard.html` find the per-election action buttons (around line 73-77):

```jinja
<a href="{{ url_for('admin_election_manage', election_id=election.id) }}" class="btn btn-primary btn-small">Manage</a>
<a href="{{ url_for('admin_election_setup', election_id=election.id) }}" class="btn btn-outline btn-small">Offices &amp; Candidates</a>
<a href="{{ url_for('admin_codes', election_id=election.id) }}" class="btn btn-outline btn-small">Codes</a>
```

Since `admin_election_manage` is now `admin_election_manage_legacy` and `admin_election_setup` GET is the legacy redirect (POST endpoint kept under `admin_election_setup` for forms), update the dashboard link to point at the step shell entry helper. Add a new helper endpoint:

```python
@app.route("/admin/election/<int:election_id>")
@admin_required
def admin_election_open(election_id):
    """Dashboard 'Manage' click target. Lands on the current default step."""
    state = compute_sidebar_state(election_id)
    if not state:
        abort(404)
    return redirect(url_for(f"admin_step_{state['current_step']}", election_id=election_id))
```

Then in `dashboard.html`:

```jinja
<a href="{{ url_for('admin_election_open', election_id=election.id) }}" class="btn btn-primary btn-small">Open</a>
```

(One button; the sidebar replaces the three sub-tabs.)

- [ ] **Step 4: Run all tests**

```
cd voting-app && python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```
git add voting-app/app.py voting-app/templates/admin/dashboard.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(wizard): legacy URL redirects + dashboard single-button entry"
```

---

### Task 16: Manual UAT walkthrough

**Files:** none (manual)

This task is verification, not code.

- [ ] **Step 1: Start the app**

```
cd voting-app && python app.py
```

- [ ] **Step 2: Wipe the database to start fresh**

In the running app, log in (`admin`), go to Dashboard -> Advanced Actions -> Wipe Database. Type `DELETE EVERYTHING`, re-enter password, confirm.

- [ ] **Step 3: Run through the 12 steps end to end**

Open `voting-app/docs/UAT_SCRIPT.md`. Follow it step by step **using the new sidebar**. The flow should be:

1. Setup wizard (one-time): congregation name, WiFi, password
2. Click "Open" on Dashboard -> lands on **Election details** step (after creating one)
3. Sidebar -> **Members** step -> upload sample CSV
4. Sidebar -> **Offices & Candidates** -> Quick start -> load samples
5. Sidebar -> **Election settings** -> enable paper count -> save
6. Sidebar -> **Codes & printing** -> codes auto-generate -> download Printer Pack
7. Sidebar -> **Attendance & postal** -> set attendance to 10 -> save
8. Sidebar -> **Welcome & Rules** -> click Next: Election Rules
9. Sidebar -> **Voting** -> Open Round 1 -> verify projector shows ballot count
10. Submit a few test votes via the voter UI
11. Sidebar -> **Voting** -> Close Round 1 -> verify projector does **NOT** auto-show results
12. Click "Show Results on Projector" -> verify projector now shows tally
13. Sidebar -> **Count & tally** -> set paper ballots received -> Enter Paper Votes
14. Sidebar -> **Decide** -> if not all elected, Start Round 2 -> sidebar updates to Round 2 group; Round 1 collapses
15. Run Round 2 (steps 6-10 again)
16. Sidebar -> **Final results** -> Show Final Results on Projector
17. Sidebar -> **Minutes & archive** -> Download DOCX -> verify file opens

- [ ] **Step 4: Verify each "Done" tick is correct**

After each step, check that the sidebar marks the just-completed step as Done and advances "Current" to the next step.

- [ ] **Step 5: Verify the Close-Round-no-auto-reveal change**

Specifically: after Close Round, the projector at `/display` (in a separate browser/tab) should still show the live ballot view with counts hidden. Click "Show Results on Projector" and verify it now reveals.

- [ ] **Step 6: Verify legacy URLs redirect correctly**

In a browser, manually visit:
- `/admin/election/1/manage` -> should redirect to a `/step/<slug>` URL
- `/admin/election/1/setup` -> should redirect to `/step/offices`
- `/admin/election/1/codes` -> should redirect to `/step/codes`

- [ ] **Step 7: Take screenshots for documentation**

Capture sidebar in three states:
- Mid-setup (Round 1 not yet opened)
- Mid-Round-2 (Round 1 collapsed)
- Final-results active

Save under `voting-app/docs/screenshots/wizard/`. (Update `USER_GUIDE.md` in a follow-up commit; out of scope here.)

- [ ] **Step 8: If everything works, merge to main**

```
git checkout main
git merge --no-ff wizard-sidebar -m "Merge wizard-sidebar: admin shell with progress sidebar"
git tag -a v1.2.0 -m "v1.2.0 - admin wizard sidebar"
git push origin main
git push origin v1.2.0
```

If anything fails, **do not merge**. Stay on `wizard-sidebar`, fix, re-test, repeat.

---

## Self-Review

Spec coverage check (against `2026-04-29-admin-wizard-sidebar-design.md`):

- ✓ Persistent left-rail sidebar (Task 2)
- ✓ Three groups Setup / Round N / Finish (Task 1, `compute_sidebar_state`)
- ✓ 12 steps with the right slugs/labels (Task 1, `WIZARD_STEPS`)
- ✓ Step state semantics (Done/Current/Locked) (Task 1, `_step_done` + `_step_prerequisites_met`)
- ✓ Per-round Done semantics for steps 6-10 (Task 1)
- ✓ Multi-round collapse behavior (Task 1, group prepend logic)
- ✓ Per-step content extraction from existing templates (Tasks 3-14)
- ✓ Behavior change: Close Round no longer auto-reveals (Task 10)
- ✓ Legacy URL redirects (Task 15)
- ✓ Dashboard "Manage" -> single "Open" entry button (Task 15)
- ✓ `_build_manage_view_payload` extraction so steps 8-11 reuse the manage query code (Task 10 step 5)
- ✓ Members step renders with sidebar when entered from election context (Task 4)
- ✓ Manual UAT (Task 16)

No placeholders remain. Type/method names consistent across tasks (`compute_sidebar_state`, `WIZARD_STEPS`, `_step_done`, `_step_prerequisites_met`, `_build_manage_view_payload`, route endpoint pattern `admin_step_<slug>`).
