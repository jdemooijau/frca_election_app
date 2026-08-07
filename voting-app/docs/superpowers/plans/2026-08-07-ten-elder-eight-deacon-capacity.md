# 10 Elder + 8 Deacon Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demo db seeds 10 elder candidates (5 vacancies) and 8 deacon candidates (4 vacancies), and every display screen fits that slate at 1080p and 720p; ballots already scale and get a regression scenario.

**Architecture:** Data changes in the two seeders and the fallback name lists; display fixes are template-local (slate two-column lists plus shrink floor, projector scaler floor plus viewport clamp); a committed Playwright script becomes the repeatable fit check.

**Tech Stack:** Flask + Jinja templates, SQLite, ReportLab (PDFs), Playwright + PyMuPDF (verification), pytest.

**Spec:** `voting-app/docs/superpowers/specs/2026-08-07-ten-elder-eight-deacon-capacity-design.md`

## Global Constraints

- No new hard cap on candidate counts anywhere. 10/8 is demo data and a verification target only.
- Fallback demo names: Australian-sounding first names from the existing `FIRST_NAMES` style, INVENTED Dutch-ish surnames (mashups, never real surnames from `DUTCH_SURNAMES`).
- Demo shape everywhere it is described: Elder 5 vacancies / 10 candidates, Deacon 4 vacancies / 8 candidates.
- Slate fix is Option B: two-column candidate lists at 6+ names AND scale shrink floor 0.6.
- Projector summary strip (big numbers, progress bar) stays fixed-size; only office lists scale.
- All commands run from `voting-app/` unless stated otherwise. Never touch `voting-app/data/frca_election.db` (the real db); scratch dbs only.
- Commit locally per task. Do NOT push without Jan's explicit approval.
- No em-dashes in any code comment, commit message, or doc text.

---

### Task 1: Extend fallback demo names to 10 elder + 8 deacon

**Files:**
- Modify: `demo_names.py:30-48`
- Test: `tests/test_demo_names.py` (create)

**Interfaces:**
- Produces: `FALLBACK_ELDER_CANDIDATES` (list of 10 str), `FALLBACK_DEACON_CANDIDATES` (list of 8 str), `generate_demo_names(count=18, member_names=None)` returning 18 names in fallback mode. Tasks 2 and 3 rely on the 18-name fallback.

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_names.py`:

```python
"""Tests for demo candidate name generation (10 elder + 8 deacon capacity)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demo_names import (
    DUTCH_SURNAMES,
    FALLBACK_DEACON_CANDIDATES,
    FALLBACK_ELDER_CANDIDATES,
    FIRST_NAMES,
    generate_demo_names,
)


class TestFallbackLists:
    def test_fallback_supports_ten_elders_and_eight_deacons(self):
        assert len(FALLBACK_ELDER_CANDIDATES) == 10
        assert len(FALLBACK_DEACON_CANDIDATES) == 8

    def test_fallback_names_are_unique(self):
        combined = FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES
        assert len(set(combined)) == 18

    def test_fallback_surnames_are_invented_not_pool(self):
        # Fallback surnames must be mashups, never real pool surnames,
        # so demo candidates cannot collide with real families.
        pool = {s.lower() for s in DUTCH_SURNAMES}
        for full in FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES:
            surname = full.split(" ", 1)[1].lower()
            assert surname not in pool, f"{full} uses a real pool surname"

    def test_fallback_first_names_come_from_first_names_list(self):
        allowed = set(FIRST_NAMES) | {"Henry", "James", "William", "Neil",
                                      "Gary", "Peter", "Fred", "Ryan",
                                      "Derek", "Andrew"}
        for full in FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES:
            first = full.split(" ", 1)[0]
            assert first in allowed, f"{full} first name not Australian style"


class TestGenerateDemoNames:
    def test_fallback_mode_returns_all_18(self):
        names = generate_demo_names(count=18, member_names=None)
        assert len(names) == 18

    def test_pool_mode_yields_18_unique_names(self):
        members = ["John Smith", "Adam Brown", "Carl Jones", "Dan White"]
        names = generate_demo_names(count=18, member_names=members)
        assert len(names) == 18
        assert len(set(names)) == 18
```

- [ ] **Step 2: Run tests to verify the new expectations fail**

Run: `python -m pytest tests/test_demo_names.py -v`
Expected: `test_fallback_supports_ten_elders_and_eight_deacons`, `test_fallback_names_are_unique`, and `test_fallback_mode_returns_all_18` FAIL (lists are 6 and 4, fallback returns 10). The other tests may already pass.

- [ ] **Step 3: Extend the fallback lists**

In `demo_names.py`, replace the two fallback lists:

```python
FALLBACK_ELDER_CANDIDATES = [
    "Henry Brouwerhof",
    "James Groenevelt",
    "William de Kempenaar",
    "Neil ten Heuvel",
    "Gary van Dijkstra",
    "Peter van Rijksen",
    "Scott Veldhoeven",
    "Mark ten Boskamp",
    "Adrian Kuiperveld",
    "Tony Zuiderhoek",
]

FALLBACK_DEACON_CANDIDATES = [
    "Fred Bosveldt",
    "Ryan Mulderhoek",
    "Derek van Leeuwenburg",
    "Andrew Visserman",
    "Chris Molenaarshof",
    "Rob Duinhoven",
    "Isaac Westerhoek",
    "Tom Kortenhoeve",
]
```

Also update the stale comment above `DUTCH_SURNAMES` (line 46-48): change "we can still pick 8+ unique candidates" to "we can still pick 18+ unique candidates".

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_demo_names.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add demo_names.py tests/test_demo_names.py
git commit -m "feat(demo): extend fallback candidate names to 10 elders + 8 deacons"
```

---

### Task 2: Sample-offices helper seeds 10/8 with vacancies 5/4

**Files:**
- Modify: `app.py:3009-3044` (`admin_load_sample_offices`)
- Modify: `templates/admin/step_offices.html:13`
- Test: `tests/test_sample_offices.py` (create)

**Interfaces:**
- Consumes: `generate_demo_names(count=18, member_names=...)` from Task 1.
- Produces: POST `/admin/election/<id>/load-sample-offices` creates Elder (vacancies=5, max_selections=5, original_vacancies=5, 10 candidates) and Deacon (4, 4, 4, 8 candidates).

- [ ] **Step 1: Write the failing test**

Create `tests/test_sample_offices.py`:

```python
"""Tests for the one-click sample-offices helper (10 elder + 8 deacon)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_db
# Reuse fixtures: pytest discovers them via this import.
from tests.test_app import client, admin_client  # noqa: F401


def test_load_sample_offices_seeds_ten_elders_eight_deacons(admin_client):
    admin_client.post("/admin/election/new", data={
        "name": "Sample Test", "max_rounds": "2",
    })
    resp = admin_client.post(
        "/admin/election/1/load-sample-offices", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        db = get_db()
        offices = db.execute(
            "SELECT * FROM offices WHERE election_id = 1 ORDER BY sort_order"
        ).fetchall()
        assert len(offices) == 2
        elder, deacon = offices
        assert elder["name"] == "Elder"
        assert (elder["vacancies"], elder["max_selections"]) == (5, 5)
        assert deacon["name"] == "Deacon"
        assert (deacon["vacancies"], deacon["max_selections"]) == (4, 4)
        n_elder = db.execute(
            "SELECT COUNT(*) FROM candidates WHERE office_id = ?",
            (elder["id"],)).fetchone()[0]
        n_deacon = db.execute(
            "SELECT COUNT(*) FROM candidates WHERE office_id = ?",
            (deacon["id"],)).fetchone()[0]
        assert n_elder == 10
        assert n_deacon == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sample_offices.py -v`
Expected: FAIL on `(elder["vacancies"], elder["max_selections"]) == (5, 5)` (currently 3, 3).

- [ ] **Step 3: Update `admin_load_sample_offices` in `app.py`**

In `admin_load_sample_offices` (around line 3010):

- `candidate_names = generate_demo_names(count=10, ...)` becomes `count=18`.
- Elder block: comment becomes `# Elder office: 5 vacancies, 10 candidates, max_selections = 5`; the INSERT values become `'Elder', 5, 5, 5, 1`; the loop slices `candidate_names[:10]`.
- Deacon block: comment becomes `# Deacon office: 4 vacancies, 8 candidates, max_selections = 4`; the INSERT values become `'Deacon', 4, 4, 4, 2`; the loop slices `candidate_names[10:18]`.
- Flash message becomes:
  `"Sample offices loaded: Elder (5 vacancies, 10 candidates) and Deacon (4 vacancies, 8 candidates)."`

- [ ] **Step 4: Update the helper description in `templates/admin/step_offices.html`**

Line 13, replace the counts:

```html
Pre-fills <strong>Elder</strong> (5 vacancies, 10 candidates) and <strong>Deacon</strong> (4 vacancies, 8 candidates) with names from the sample pool. Useful for dry runs and demos.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_sample_offices.py tests/test_app.py -v`
Expected: new test PASS, no regressions in test_app.py.

- [ ] **Step 6: Commit**

```bash
git add app.py templates/admin/step_offices.html tests/test_sample_offices.py
git commit -m "feat(admin): sample offices load 10 elder / 8 deacon candidates (5/4 vacancies)"
```

---

### Task 3: seed_demo.py seeds 10/8 with vacancies 5/4

**Files:**
- Modify: `scripts/seed_demo.py:151-191` (`_create_demo_election`), `scripts/seed_demo.py:307` (name count), `scripts/seed_demo.py:353` (summary print)

**Interfaces:**
- Consumes: `generate_demo_names(count=18, member_names=...)` from Task 1.
- Produces: demo db with Elder (5 vacancies, max_selections 5, 10 candidates) and Deacon (4, 4, 8). Task 7's fit-check script mirrors this shape.

There is no unit test for this interactive script; verification is a scripted run against a scratch db.

- [ ] **Step 1: Update `_create_demo_election`**

- Elder block comment becomes `# Elder office: 5 vacancies, 10 candidates, max_selections = 5`; INSERT values `'Elder', 5, 5, 1`; slice `candidate_names[:10]`.
- Deacon block comment becomes `# Deacon office: 4 vacancies, 8 candidates, max_selections = 4`; INSERT values `'Deacon', 4, 4, 2`; slice `candidate_names[10:18]`.

- [ ] **Step 2: Update the name count and summary line**

- Line 307: `generate_demo_names(count=10, ...)` becomes `count=18`.
- Line 353 print becomes:
  `print(f"  [OK] Offices: Elder (5 vacancies, 10 candidates), Deacon (4 vacancies, 8 candidates)")`

- [ ] **Step 3: Verify with a scratch db run**

From `voting-app/` in Git Bash (scratch path, never the real db):

```bash
SCRATCH=$(mktemp -d)
echo YES | FRCA_DB_PATH="$SCRATCH/seed_test.db" FRCA_SKIP_PORT_CHECK=1 python scripts/seed_demo.py --codes 20
python - <<EOF
import sqlite3, os
db = sqlite3.connect(os.path.join(r"$SCRATCH", "seed_test.db"))
rows = db.execute(
    "SELECT o.name, o.vacancies, o.max_selections, COUNT(c.id) "
    "FROM offices o JOIN candidates c ON c.office_id = o.id "
    "GROUP BY o.id ORDER BY o.sort_order").fetchall()
print(rows)
assert rows[0] == ("Elder", 5, 5, 10), rows[0]
assert rows[1] == ("Deacon", 4, 4, 8), rows[1]
print("seed shape OK")
EOF
```

Expected: `seed shape OK`. Also eyeball the generated `demo_paper_ballots.pdf` and `demo_code_slips.pdf` in `voting-app/` (they now carry 10+8; delete them afterwards if not wanted).

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_demo.py
git commit -m "feat(demo): seed_demo creates 10 elder / 8 deacon candidates (5/4 vacancies)"
```

---

### Task 4: Slate screen fits (two-column lists + shrink floor 0.6)

**Files:**
- Modify: `templates/display/slate.html` (CSS block lines 76-89, list markup line 145, scaler line 217)
- Test: `tests/test_display_fill.py` (extend `TestSlateScreen`)

**Interfaces:**
- Consumes: nothing from other tasks (independent).
- Produces: `.candidate-list.two-col` CSS hook and `Math.max(0.6, scale)` floor; Task 7's fit script asserts the visual result.

- [ ] **Step 1: Write the failing test**

Add to `TestSlateScreen` in `tests/test_display_fill.py` (fixtures `client`/`admin_client` are already imported at the top of the file; add `admin_client` to the import if the linter flags it, it is already in the noqa import list):

```python
    def test_slate_two_col_list_and_shrink_floor(self, admin_client):
        # A 10-candidate office flows its name list into two columns and
        # the scaler may shrink below 1 so the slate always fits a beamer.
        admin_client.post("/admin/election/new", data={
            "name": "Slate Fit", "max_rounds": "2",
        })
        admin_client.post("/admin/election/1/setup", data={
            "office_name": "Elder",
            "vacancies": "5",
            "max_selections": "5",
            "candidate_names": "\n".join(
                f"Candidate {i}" for i in range(1, 11)),
            "confirm_slate_override": "1",
        })
        _set_phase(1, display_phase=2)
        resp = admin_client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Two-column list kicks in at 6+ candidates.
        assert 'candidate-list two-col' in html
        assert "column-count: 2" in html
        # Shrink floor replaced the old grow-only clamp.
        assert "Math.max(0.6, scale)" in html
        assert "Math.max(1, scale)" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_display_fill.py::TestSlateScreen -v`
Expected: new test FAILS (`candidate-list two-col` not in html). Existing test passes.

- [ ] **Step 3: Implement the slate changes**

In `templates/display/slate.html`:

a) CSS: replace the `.candidate-list li` rule block (lines 81-89) with:

```css
    .candidate-list li {
        font-size: calc(34px * var(--slate-scale));
        padding: calc(12px * var(--slate-scale)) calc(16px * var(--slate-scale));
        border-bottom: 1px solid var(--grey);
        color: var(--navy);
        break-inside: avoid;
    }
    .candidate-list li:last-child {
        border-bottom: none;
    }
    /* Long slates (6+ names) flow into two columns so ten names become
       five rows and the text stays readable from the back of the church.
       Same idea as the projector's two-col treatment. */
    .candidate-list.two-col {
        column-count: 2;
        column-gap: calc(48px * var(--slate-scale));
    }
```

b) Markup line 145: change

```html
            <ul class="candidate-list">
```

to

```html
            <ul class="candidate-list{% if item.candidates|length >= 6 %} two-col{% endif %}">
```

c) Scaler line 217: change

```js
            scale = Math.max(1, scale);
```

to

```js
            // Shrink floor: a slate that cannot fit at scale 1 must shrink
            // to fit the beamer (nobody scrolls a projector). 0.6 keeps the
            // text readable; the page-scroll override below stays as a last
            // resort for pathological cases.
            scale = Math.max(0.6, scale);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_display_fill.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/display/slate.html tests/test_display_fill.py
git commit -m "fix(display): slate fits 10-candidate offices (two-col lists, shrink floor 0.6)"
```

---

### Task 5: Projector closed-results fits at 720p

**Files:**
- Modify: `templates/display/projector.html:838-886` (`autoSizeOffices`)
- Test: `tests/test_display_fill.py` (extend `TestProjectorLiveResultsFill`)

**Interfaces:**
- Consumes: nothing from other tasks (independent).
- Produces: scaler floor 0.45 and viewport-clamped available height; Task 7's fit script asserts the visual result at 720p.

Background from the spec: at 1280x720 with 10 elder candidates the Total row clips even though the scaler ran. Two compounding causes are addressed: the 0.6 floor is too high once the fixed-size summary strip and runoff banner take their share, and `resultsContainer.clientHeight` can exceed the actually visible area.

- [ ] **Step 1: Write the failing test**

Add to `TestProjectorLiveResultsFill` in `tests/test_display_fill.py`:

```python
    def test_scaler_floor_and_viewport_clamp(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=3)
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Floor lowered so a 10-candidate office + summary strip fits 720p.
        assert "Math.max(0.45," in html
        assert "Math.max(0.6," not in html
        # Available height is clamped to the visible viewport, not just
        # the container's clientHeight.
        assert "window.innerHeight" in html.split("function availableHeight")[1][:400]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_display_fill.py::TestProjectorLiveResultsFill -v`
Expected: new test FAILS (floor is 0.6, no viewport clamp). Existing test passes.

- [ ] **Step 3: Implement the scaler changes**

In `templates/display/projector.html`, inside `autoSizeOffices()`:

a) In `availableHeight()` (line ~840), replace

```js
            var available = resultsContainer.clientHeight;
```

with

```js
            // Clamp to what is actually visible: on short beamers the
            // container can report more height than the viewport shows,
            // which left the Total row clipped off the bottom.
            var rcTop = resultsContainer.getBoundingClientRect().top;
            var available = Math.min(
                resultsContainer.clientHeight,
                window.innerHeight - rcTop - 8);
```

b) Both floor clamps (lines ~876 and ~884): change `Math.max(0.6,` to `Math.max(0.45,` and update the nearby comment to note the floor must clear a 10-candidate office plus Blank/Spoilt/Total rows on a 720p beamer.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_display_fill.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/display/projector.html tests/test_display_fill.py
git commit -m "fix(display): projector results fit 720p with 10 candidates (floor 0.45, viewport clamp)"
```

---

### Task 6: Ballot layout regression scenario at 10+8

**Files:**
- Modify: `scripts/test_ballot_layouts.py:34-94`

**Interfaces:**
- Consumes: `generate_paper_ballot_pdf` (unchanged).
- Produces: scenario `08_2offices_10plus8` in `SCENARIOS`.

- [ ] **Step 1: Add the scenario**

In `scripts/test_ballot_layouts.py`, update the comment on line 34 from "max 8 candidates per office" to "max 10 candidates per office", and append to `SCENARIOS`:

```python
    (
        "08_2offices_10plus8",
        "2 offices, 10 + 8 (new maximum)",
        [
            _office("Elder", 5, ["Pieter van der Berg"]
                                + [f"Elder Candidate {n}" for n in "ABCDEFGHI"]),
            _office("Deacon", 4, ["Pieter van der Berg"]
                                 + [f"Deacon Candidate {n}" for n in "ABCDEFG"]),
        ],
    ),
```

- [ ] **Step 2: Generate and eyeball the PDFs**

```bash
python scripts/test_ballot_layouts.py --out ballot_test_output
```

Open `ballot_test_output/08_2offices_10plus8.pdf`. Check: 6 ballots per A4, all 18 names legible, checkboxes aligned, nothing clipped by the tile border. (`ballot_test_output/` is throwaway output; do not commit it.)

- [ ] **Step 3: Commit**

```bash
git add scripts/test_ballot_layouts.py
git commit -m "test(ballots): add 10+8 layout scenario for the new demo maximum"
```

---

### Task 7: Committed display fit-check script + acceptance run

**Files:**
- Create: `scripts/check_display_fit.py`

**Interfaces:**
- Consumes: `app` module (`_init_db_on`, `_migrate_db_on`, `DB_PATH` monkeypatch), `generate_demo_names` from Task 1, the slate/projector fixes from Tasks 4-5.
- Produces: `python scripts/check_display_fit.py` exits 0 when every display state fits at 1920x1080 AND 1280x720; screenshots land in `display_fit_output/`.

Scope note: the script covers the four states whose layout depends on slate size (live tally, closed results, phase-2 slate, round-2 instructions). The welcome and final-summary screens do not render candidate lists at these sizes and are excluded deliberately.

- [ ] **Step 1: Write the script**

Create `scripts/check_display_fit.py`:

```python
"""Screenshot-and-assert harness for the projector display screens.

Seeds a scratch db with the demo maximum (10 elder / 8 deacon candidates),
serves the app on port 5001 with a monkeypatched DB_PATH (the real
data/frca_election.db is never touched), then drives Playwright through
the display states at 1920x1080 and 1280x720. Each state must fit its
viewport: no vertical overflow, no clipped rows.

Usage:
    cd voting-app
    python scripts/check_display_fit.py

Exit code 0 = all states fit. Screenshots are written to
display_fit_output/ for eyeballing either way.
"""

import os
import random
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

PORT = 5001
BASE = f"http://127.0.0.1:{PORT}"
OUT = os.path.join(_VOTING_APP_DIR, "display_fit_output")
DB = os.path.join(OUT, "fit_check.db")
VIEWPORTS = [(1920, 1080), (1280, 720)]


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

OVERFLOW_JS = """
() => {
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
    return {pageOverflow, clipped};
}
"""


def main():
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
                result = page.evaluate(OVERFLOW_JS)
                ok = (result["pageOverflow"] <= 2
                      and not result["clipped"])
                print(f"  {'OK  ' if ok else 'FAIL'} {name} at "
                      f"{width}x{height}  overflow={result['pageOverflow']}"
                      f" clipped={result['clipped']}")
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
```

- [ ] **Step 2: Run the fit check**

```bash
python scripts/check_display_fit.py
```

Expected: `All display states fit.` and exit code 0. If a state fails, the console names it and the screenshot in `display_fit_output/` shows the clipping; fix the corresponding template (Task 4 or 5) before proceeding. Note the port must be free (stop any running dev server first).

- [ ] **Step 3: Eyeball every screenshot**

Open each PNG in `display_fit_output/` (8 files). Check readability, not just fit: names large enough for the back of the church, ELECTED badges visible, no odd wrapping. The names must look like generator output (Australian first names, Dutch surnames).

- [ ] **Step 4: Commit**

```bash
git add scripts/check_display_fit.py
git commit -m "test(display): committed fit-check harness for 10+8 slate at 1080p and 720p"
```

(`display_fit_output/` is throwaway output; do not commit it. Add it to `.gitignore` if git status shows it.)

---

### Task 8: Changelog, full test suite, wrap-up

**Files:**
- Modify: `CHANGELOG.md` (repo root, under `[Unreleased]`; create the section if absent)

**Interfaces:**
- Consumes: everything above.
- Produces: green suite, changelog entry, summary for Jan.

- [ ] **Step 1: Add the changelog entry**

Under `[Unreleased]` in the repo-root `CHANGELOG.md`, following the existing Keep-a-Changelog style:

```markdown
### Added
- Demo election now seeds the supported maximum slate: 10 elder candidates
  (5 vacancies) and 8 deacon candidates (4 vacancies), in both
  `seed_demo.py` and the admin "Load sample candidates" helper.
- `scripts/check_display_fit.py`: automated projector-fit check (Playwright)
  for the demo maximum at 1920x1080 and 1280x720.
- Ballot layout test scenario for 10+8 candidates.

### Fixed
- Candidates slate screen clipped long slates on the projector: name lists
  now flow into two columns at 6+ names and the auto-scaler can shrink
  below 1 (floor 0.6).
- Projector results screen clipped the bottom rows on 720p beamers with
  large slates: scale floor lowered to 0.45 and available height clamped
  to the visible viewport.
```

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all PASS. Investigate any failure before committing; do not skip tests.

- [ ] **Step 3: Commit**

```bash
git add ../CHANGELOG.md
git commit -m "docs: changelog for 10 elder / 8 deacon capacity work"
```

- [ ] **Step 4: Report and ask about push**

Summarise for Jan: commits made (hash + one-liner each), fit-check result, screenshot locations. Ask before pushing anything.
