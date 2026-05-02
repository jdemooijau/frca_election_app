# Paper Ballot QR Scanner and Phone Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two integrity features that close the phone-vs-paper double-count gap. Part A is a localStorage-based phone receipt that lists codes voted on the device. Part B is an admin QR-scanner page that, during the count phase, reads paper-ballot QRs and atomically decrements `paper_ballot_count` for any ballot whose code was already burned online.

**Architecture:** Zero schema changes. Part A is pure client-side (localStorage + small server-side template-context tweak). Part B reuses the existing `voter_audit_log` table with a new `result` value, the existing `paper_ballot_count` column on `round_counts`, and the existing `_build_manage_view_payload` for the reconciliation panel. Scanner page uses the browser `BarcodeDetector` API with a vendored `jsQR` fallback. A 32 mm QR-size prerequisite is shipped first to make camera scanning reliable.

**Tech Stack:** Flask, Jinja2, SQLite, ReportLab (PDF), `qrcode` library, vanilla JS (no React/build pipeline), `BarcodeDetector` API + `jsQR` (vendored), pytest.

**Reference docs:** [`docs/superpowers/specs/2026-05-02-paper-scan-and-phone-receipt-design.md`](../specs/2026-05-02-paper-scan-and-phone-receipt-design.md)

---

## File map

**Modify:**
- `voting-app/app.py` (multiple sections; see per-task line ranges)
- `voting-app/pdf_generators.py` (line 165 area: QR size)
- `voting-app/templates/base.html` (no change required, template-injection happens via voter pages)
- `voting-app/templates/voter/confirmation.html` (localStorage write + badge include)
- `voting-app/templates/voter/enter_code.html` (badge include)
- `voting-app/templates/voter/ballot.html` (badge include)
- `voting-app/templates/admin/step_count.html` (reconciliation panel + scan button + banner)

**Create:**
- `voting-app/templates/voter/_receipt_badge.html` (partial, badge + modal)
- `voting-app/templates/admin/scan_ballots.html` (scanner page)
- `voting-app/static/vendor/jsqr.min.js` (vendored)
- `voting-app/tests/test_paper_scan.py` (new test module)

**Test extensions:**
- `voting-app/tests/test_pdf_generators.py` (PDF size regression)
- `voting-app/tests/test_app.py` (template context, e2e double-vote)

---

## Section 1: Prerequisite. QR size enlargement

### Task 1: Enlarge code-slip QR to 32 mm

**Files:**
- Modify: `voting-app/pdf_generators.py:165` (`qr_size = 24 * mm` → `32 * mm`)
- Modify: `voting-app/pdf_generators.py:86` (verify `_calc_code_slip_height` Step-2 envelope of `32 * mm` still accommodates the larger QR)
- Test: `voting-app/tests/test_pdf_generators.py`

- [ ] **Step 1.1: Add a smoke test for the enlarged QR**

Append to `voting-app/tests/test_pdf_generators.py`:

```python
def test_code_slip_qr_size_is_32mm():
    """Regression: the QR rendered on the code slip must be at least 32 mm
    wide so phone cameras can scan it reliably during count-time triage.
    See docs/superpowers/specs/2026-05-02-paper-scan-and-phone-receipt-design.md.
    """
    import inspect
    from pdf_generators import draw_code_slip
    src = inspect.getsource(draw_code_slip)
    assert "qr_size = 32 * mm" in src, (
        "draw_code_slip must use a 32 mm QR for reliable count-time scanning"
    )


def test_dual_sided_ballots_pdf_still_generates_with_larger_qr():
    """Regression: the dual-sided grid layout must still produce a PDF
    without overflowing cells when the QR is 32 mm."""
    pdf_bytes = _generate_sample_pdf().getvalue()
    assert pdf_bytes.startswith(b"%PDF-")
    # 8 codes => 4 pages (2x2 grid front + back, dual-sided). The exact
    # page count is implementation-specific; assert non-empty PDF and
    # presence of the QR data marker that the reportlab Image stream
    # writes when an image is embedded.
    assert b"/Image" in pdf_bytes
    assert len(pdf_bytes) > 5000, "PDF appears truncated"
```

- [ ] **Step 1.2: Run the test (it should fail because the source still says `24 * mm`)**

Run:
```
pytest voting-app/tests/test_pdf_generators.py::test_code_slip_qr_size_is_32mm -v
```

Expected: `FAILED` with `AssertionError: draw_code_slip must use a 32 mm QR...`

- [ ] **Step 1.3: Bump the QR size**

Edit `voting-app/pdf_generators.py` around line 165:

```python
    # --- Step 2: Scan QR code ---
    label_x = x + 5 * mm
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(label_x, y, "Scan QR code with your phone camera")

    # QR image only (voting code moved to step 3)
    qr_size = 32 * mm
    y -= qr_size
    qr_img = _generate_qr_image(vote_url)
```

(Change only the assignment; the `_calc_code_slip_height` already reserves `32 * mm` for Step 2, which absorbs the new QR width without further changes.)

- [ ] **Step 1.4: Run both PDF tests, verify they pass**

Run:
```
pytest voting-app/tests/test_pdf_generators.py -v
```

Expected: all tests `PASSED`. If `test_dual_sided_ballots_pdf_still_generates_with_larger_qr` fails with a layout-overflow error from ReportLab, fall back to `qr_size = 30 * mm` and re-run.

- [ ] **Step 1.5: Generate a sample PDF and verify visually**

Run from `voting-app/`:
```
python -c "from pdf_generators import generate_ballot_front_pdf; from tests.test_pdf_generators import SAMPLE_OFFICE_DATA; buf = generate_ballot_front_pdf('Test Election', SAMPLE_OFFICE_DATA, 'wifi-pass', 'http://localhost:5000'); open('/tmp/sample_ballot.pdf', 'wb').write(buf.getvalue())"
```

Open `/tmp/sample_ballot.pdf` and confirm the QR is visibly larger than before, fits inside Step 2, and does not overlap surrounding labels.

- [ ] **Step 1.6: Commit**

```
git add voting-app/pdf_generators.py voting-app/tests/test_pdf_generators.py
git commit -m "feat(pdf): enlarge code-slip QR to 32mm for count-time scanning

The 24mm QR forced phone cameras to focus at 5-10cm with narrow angle
tolerance, making count-time triage scanning fussy. Bumping to 32mm
roughly doubles fold tolerance per module and lets the operator hold
a ballot at 15-25cm without focus hunting."
```

---

## Section 2: Part A. Phone receipt

### Task 2: Pass election context to the confirmation route

**Files:**
- Modify: `voting-app/app.py:3131-3148` (the `voter_confirmation` route)
- Test: `voting-app/tests/test_app.py`

- [ ] **Step 2.1: Add a failing test asserting election context is rendered**

Append to `voting-app/tests/test_app.py`:

```python
def test_voter_confirmation_renders_election_context_for_receipt(client, seeded_election):
    """The confirmation page must inject election_id and election_name
    into the page so the localStorage receipt write captures them.
    """
    election_id, code = seeded_election["id"], seeded_election["codes"][0]
    # Submit a vote so the confirmation page is reachable.
    with client.session_transaction() as sess:
        sess["used_code"] = code
        sess["election_id"] = election_id
    rv = client.get("/confirmation")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert f'data-election-id="{election_id}"' in body
    assert seeded_election["name"] in body
```

(If `seeded_election` fixture does not yet exist, replicate the pattern from existing tests in `test_app.py`. Look for `client` fixture and an in-memory DB pattern.)

- [ ] **Step 2.2: Run the test, verify it fails**

Run:
```
pytest voting-app/tests/test_app.py::test_voter_confirmation_renders_election_context_for_receipt -v
```

Expected: FAIL because `data-election-id="..."` is not in the rendered template.

- [ ] **Step 2.3: Update the route to fetch and pass election context**

Edit `voting-app/app.py` around line 3131:

```python
@app.route("/confirmation")
def voter_confirmation():
    used_code = session.get("used_code")
    election_id = session.get("election_id")
    show_assist = False
    election_name = None
    if used_code and election_id:
        db = get_db()
        election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
        if election:
            election_name = election["name"]
            if _paper_count_active_for_round(db, election):
                show_assist = True
    resp = make_response(render_template(
        "voter/confirmation.html",
        used_code=used_code,
        show_assist=show_assist,
        election_id=election_id,
        election_name=election_name,
    ))
    return no_cache(resp)
```

- [ ] **Step 2.4: Update the confirmation template to expose the context**

Edit `voting-app/templates/voter/confirmation.html` near the top of the `content` block, adding a hidden marker the JS can read:

```jinja
{% block content %}
<div class="header"
     data-election-id="{{ election_id or '' }}"
     data-election-name="{{ election_name or '' }}"
     data-used-code="{{ used_code or '' }}">
    <h1>Office Bearer Election</h1>
</div>
```

(Replace the existing `<div class="header">` opening tag.)

- [ ] **Step 2.5: Run the test, verify it passes**

Run:
```
pytest voting-app/tests/test_app.py::test_voter_confirmation_renders_election_context_for_receipt -v
```

Expected: PASS.

- [ ] **Step 2.6: Commit**

```
git add voting-app/app.py voting-app/templates/voter/confirmation.html voting-app/tests/test_app.py
git commit -m "feat(voter): expose election context on confirmation page

Adds election_id and election_name to the confirmation template so the
phone-receipt feature can persist a per-election entry to localStorage."
```

---

### Task 3: Write the vote receipt to localStorage on confirmation

**Files:**
- Modify: `voting-app/templates/voter/confirmation.html` (script block)

- [ ] **Step 3.1: Append the receipt-write script to the confirmation template**

Add inside the existing `<script>` block at the bottom of `voting-app/templates/voter/confirmation.html`, after the existing `(function() { ... })();` IIFE:

```html
<script>
(function() {
    var header = document.querySelector('.header[data-election-id]');
    if (!header) return;
    var eid = header.getAttribute('data-election-id');
    var ename = header.getAttribute('data-election-name');
    var code = header.getAttribute('data-used-code');
    if (!eid || !code) return;

    var KEY = 'frcdd_voted';
    var raw = localStorage.getItem(KEY);
    var arr;
    try { arr = raw ? JSON.parse(raw) : []; } catch (e) { arr = []; }
    if (!Array.isArray(arr)) arr = [];

    // Idempotent on reload: if the same code is already stored, do nothing.
    for (var i = 0; i < arr.length; i++) {
        if (arr[i] && arr[i].code === code && String(arr[i].election_id) === String(eid)) return;
    }
    arr.push({
        code: code,
        election_id: Number(eid),
        election_name: ename || '',
        used_at_iso: new Date().toISOString()
    });
    localStorage.setItem(KEY, JSON.stringify(arr));
})();
</script>
```

- [ ] **Step 3.2: Manual UAT**

1. Start the app: `cd voting-app && python app.py`
2. Open the voter URL in a browser, vote with one code.
3. On the confirmation page, open DevTools → Application → Local Storage → `http://...` and confirm `frcdd_voted` exists with one entry.
4. Reload the confirmation page; confirm `frcdd_voted` still has only one entry (idempotent).
5. Vote with a second code (different brother / family member). Confirm `frcdd_voted` now has two entries.

- [ ] **Step 3.3: Commit**

```
git add voting-app/templates/voter/confirmation.html
git commit -m "feat(voter): write voted-code receipt to localStorage on confirmation

Stores {code, election_id, election_name, used_at_iso} so the
upcoming receipt badge can list votes cast on this device. Idempotent
on reload; safe when localStorage is empty or holds prior-election
entries."
```

---

### Task 4: Receipt badge partial

**Files:**
- Create: `voting-app/templates/voter/_receipt_badge.html`

- [ ] **Step 4.1: Create the partial with badge + modal**

Create `voting-app/templates/voter/_receipt_badge.html`:

```html
{# Receipt badge: shows a "?" button at top right that opens a modal
   listing votes cast on this device for the active election.
   Reads localStorage key `frcdd_voted` (written by confirmation.html).
   Hidden when storage is empty or has no entry for the active election.
   Pages including this partial must set `active_election_id` in their
   template context (typically via the existing payload variable).
#}
<div id="frcdd-receipt-root"
     data-active-election-id="{{ active_election_id or '' }}"
     style="position: fixed; top: 6px; right: 6px; z-index: 1000; display: none;">
    <button type="button" id="frcdd-receipt-btn"
            aria-label="Show votes cast on this device"
            style="width: 32px; height: 32px; border-radius: 50%;
                   border: 1px solid #888; background: #fff; cursor: pointer;
                   font-size: 18px; font-weight: 700; color: #333;">?</button>
</div>

<div id="frcdd-receipt-modal" role="dialog" aria-modal="true"
     aria-labelledby="frcdd-receipt-title" style="display: none;
     position: fixed; inset: 0; z-index: 1001; background: rgba(0,0,0,0.5);">
    <div style="max-width: 420px; margin: 12vh auto; background: #fff;
                border-radius: 10px; padding: 20px;">
        <h2 id="frcdd-receipt-title" style="margin: 0 0 10px; font-size: 18px;">
            Votes cast on this device
        </h2>
        <ul id="frcdd-receipt-list" style="list-style: none; padding: 0; margin: 0 0 16px;
                                            font-size: 16px; line-height: 1.6;"></ul>
        <p style="font-size: 14px; color: #555;">
            If you see your code here, your vote is registered. You do
            not need to cast a paper ballot.
        </p>
        <div style="text-align: right; margin-top: 12px;">
            <button type="button" id="frcdd-receipt-close" class="btn btn-outline">Close</button>
        </div>
    </div>
</div>

<script>
(function() {
    var root = document.getElementById('frcdd-receipt-root');
    if (!root) return;
    var activeEid = root.getAttribute('data-active-election-id');
    if (!activeEid) return;

    var raw = localStorage.getItem('frcdd_voted');
    var entries;
    try { entries = raw ? JSON.parse(raw) : []; } catch (e) { entries = []; }
    if (!Array.isArray(entries)) entries = [];

    var matches = entries.filter(function(e) {
        return e && String(e.election_id) === String(activeEid);
    });
    if (matches.length === 0) return;

    root.style.display = 'block';

    var listEl = document.getElementById('frcdd-receipt-list');
    listEl.innerHTML = matches.map(function(e) {
        var t = '';
        try {
            var d = new Date(e.used_at_iso);
            t = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        } catch (err) {}
        return '<li>Code <strong>' + e.code + '</strong>'
             + (t ? ' at ' + t : '') + '</li>';
    }).join('');

    function show() { document.getElementById('frcdd-receipt-modal').style.display = 'block'; }
    function hide() { document.getElementById('frcdd-receipt-modal').style.display = 'none'; }
    document.getElementById('frcdd-receipt-btn').addEventListener('click', show);
    document.getElementById('frcdd-receipt-close').addEventListener('click', hide);
    document.getElementById('frcdd-receipt-modal').addEventListener('click', function(ev) {
        if (ev.target.id === 'frcdd-receipt-modal') hide();
    });
})();
</script>
```

- [ ] **Step 4.2: Commit**

```
git add voting-app/templates/voter/_receipt_badge.html
git commit -m "feat(voter): add receipt badge partial

Renders a '?' badge that lists localStorage 'frcdd_voted' entries for
the active election. Visible only when entries exist; hidden otherwise.
Independent partial; no template that includes it has been modified
yet (next task)."
```

---

### Task 5: Wire the badge into voter pages

**Files:**
- Modify: `voting-app/templates/voter/enter_code.html`
- Modify: `voting-app/templates/voter/ballot.html`
- Modify: `voting-app/templates/voter/confirmation.html`
- Modify: `voting-app/app.py` (the routes that render the above, to pass `active_election_id`)

- [ ] **Step 5.1: Add `active_election_id` to the three voter routes**

Identify the three voter routes that render the templates above. Search for `render_template("voter/enter_code.html"`, `render_template("voter/ballot.html"`, `render_template("voter/confirmation.html"`. For each, add `active_election_id=<the election id available in scope>` to the context.

For `voter_confirmation` (already at `app.py:3131`), reuse the `election_id` already in scope:

```python
    resp = make_response(render_template(
        "voter/confirmation.html",
        used_code=used_code,
        show_assist=show_assist,
        election_id=election_id,
        election_name=election_name,
        active_election_id=election_id,
    ))
```

For `enter_code` and `ballot` routes, the election ID is read from session or the active election lookup. Locate the `render_template` call for each and add `active_election_id=<election_id_in_scope>` similarly.

- [ ] **Step 5.2: Include the partial in each voter template**

Add this line near the top of the `{% block content %}` block in each of:
- `voting-app/templates/voter/enter_code.html`
- `voting-app/templates/voter/ballot.html`
- `voting-app/templates/voter/confirmation.html`

```jinja
{% include "voter/_receipt_badge.html" %}
```

- [ ] **Step 5.3: Manual UAT**

1. With localStorage empty (clear site data first), visit `/enter-code` → no `?` badge visible.
2. Vote with a code → confirmation page shows `?` badge.
3. Visit `/ballot` (start a new vote with a fresh code) → `?` badge visible at top right.
4. Tap the badge → modal lists the previous code with timestamp.
5. Tap "Close" → modal closes.
6. Reload the page; badge and entries persist.
7. Switch to a different election (or change active election ID via DevTools to mismatch the localStorage entry) → badge is hidden.

- [ ] **Step 5.4: Commit**

```
git add voting-app/app.py voting-app/templates/voter/
git commit -m "feat(voter): show receipt badge on enter-code, ballot, confirmation

Includes the receipt-badge partial on the three pages where the badge
is most useful (re-scan attempts and pre-vote entry). Badge filters by
active_election_id so cross-election entries do not leak across."
```

---

## Section 3: Part B. Scanner backend

### Task 6: Test scaffold for the scan endpoint

**Files:**
- Create: `voting-app/tests/test_paper_scan.py`

- [ ] **Step 6.1: Create the test module with fixtures**

Create `voting-app/tests/test_paper_scan.py`:

```python
"""Tests for the paper-ballot QR scan endpoint.

The endpoint is /admin/elections/<id>/scan-ballot-result. It accepts
a JSON body {code: "..."} and returns one of:
- {"result": "match"}        when the code is currently used in the election
- {"result": "paper_only"}   when the code exists but is not used
- {"result": "unknown"}      when the code is not in this election

Match also decrements paper_ballot_count for the current round and
writes a voter_audit_log entry with result='paper_set_aside_at_count'.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def scan_election(client, admin_login, db):
    """A seeded election in the count phase with one used and one unused code."""
    # Use the existing seeded-election helper from test_app.py if available.
    # Otherwise mirror its pattern: create election, generate codes, burn one.
    from tests.test_app import _seed_count_phase_election
    return _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=["AB3XY9"])


def _post_scan(client, election_id, code, csrf_token):
    return client.post(
        f"/admin/elections/{election_id}/scan-ballot-result",
        json={"code": code},
        headers={"X-CSRFToken": csrf_token},
    )
```

(Notes: `_seed_count_phase_election` is a helper you will need to add to `tests/test_app.py` if it does not exist. It should: insert an `elections` row with `voting_open=0` and `display_phase=3`, insert two codes via `hash_code`, insert a `round_counts` row with `paper_ballot_count=5`, and burn the code in `used_codes`. The `client`, `admin_login`, and `db` fixtures should already exist or be patterned on existing tests.)

- [ ] **Step 6.2: Verify the test file imports cleanly**

Run:
```
pytest voting-app/tests/test_paper_scan.py --collect-only
```

Expected: collection succeeds (zero tests reported, no import errors). If the helper `_seed_count_phase_election` does not exist, add it to `voting-app/tests/test_app.py`:

```python
def _seed_count_phase_election(db, used_codes=None, unused_codes=None,
                                paper_ballot_count=5):
    """Seed an election in the count phase. Returns dict with id, name, codes."""
    from app import hash_code
    used_codes = used_codes or []
    unused_codes = unused_codes or []
    cur = db.execute(
        "INSERT INTO elections (name, election_date, current_round, max_rounds, "
        "voting_open, display_phase, paper_count_enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Test Count Election", "2026-05-02", 1, 3, 0, 3, 0)
    )
    election_id = cur.lastrowid
    for c in used_codes:
        db.execute(
            "INSERT INTO codes (election_id, code_hash, used) VALUES (?, ?, 1)",
            (election_id, hash_code(c))
        )
    for c in unused_codes:
        db.execute(
            "INSERT INTO codes (election_id, code_hash, used) VALUES (?, ?, 0)",
            (election_id, hash_code(c))
        )
    db.execute(
        "INSERT INTO round_counts (election_id, round_number, participants, "
        "paper_ballot_count, digital_ballot_count) VALUES (?, ?, ?, ?, ?)",
        (election_id, 1, 50, paper_ballot_count, len(used_codes))
    )
    db.commit()
    return {
        "id": election_id,
        "name": "Test Count Election",
        "codes": list(used_codes) + list(unused_codes),
        "used_codes": list(used_codes),
        "unused_codes": list(unused_codes),
    }
```

- [ ] **Step 6.3: Commit the scaffold**

```
git add voting-app/tests/test_paper_scan.py voting-app/tests/test_app.py
git commit -m "test(scan): add scaffold + fixture helper for scan endpoint tests"
```

---

### Task 7: Match path. decrement and audit

**Files:**
- Modify: `voting-app/app.py` (new endpoint)
- Modify: `voting-app/tests/test_paper_scan.py` (test)

- [ ] **Step 7.1: Add the failing match-path test**

Append to `voting-app/tests/test_paper_scan.py`:

```python
def test_match_decrements_paper_count_and_logs_audit(client, scan_election, csrf_token):
    eid = scan_election["id"]
    used_code = scan_election["used_codes"][0]

    rv = _post_scan(client, eid, used_code, csrf_token)
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "match"}

    # paper_ballot_count must have decremented by exactly 1.
    from app import get_db
    db = get_db()
    row = db.execute(
        "SELECT paper_ballot_count FROM round_counts "
        "WHERE election_id = ? AND round_number = 1",
        (eid,)
    ).fetchone()
    assert row["paper_ballot_count"] == 4  # was seeded at 5

    # An audit row must exist with the correct result string.
    audit = db.execute(
        "SELECT result, code FROM voter_audit_log "
        "WHERE election_id = ? AND result = 'paper_set_aside_at_count'",
        (eid,)
    ).fetchall()
    assert len(audit) == 1
    assert audit[0]["code"] == used_code
```

- [ ] **Step 7.2: Run the test, verify it fails**

Run:
```
pytest voting-app/tests/test_paper_scan.py::test_match_decrements_paper_count_and_logs_audit -v
```

Expected: FAIL with 404 or similar (endpoint does not exist).

- [ ] **Step 7.3: Implement the endpoint with the match path only**

Add to `voting-app/app.py` near the other admin election routes (e.g. after `admin_step_minutes`):

```python
@app.route("/admin/elections/<int:election_id>/scan-ballot-result", methods=["POST"])
@admin_required
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
```

(Imports: ensure `jsonify` and `abort` are imported from Flask at the top of `app.py`.)

- [ ] **Step 7.4: Run the test, verify it passes**

Run:
```
pytest voting-app/tests/test_paper_scan.py::test_match_decrements_paper_count_and_logs_audit -v
```

Expected: PASS.

- [ ] **Step 7.5: Commit**

```
git add voting-app/app.py voting-app/tests/test_paper_scan.py
git commit -m "feat(admin): scan-ballot-result endpoint with match path

Decrements round_counts.paper_ballot_count atomically (clamped at 0)
and writes a voter_audit_log row with result paper_set_aside_at_count
when the scanned QR matches a code already burned online."
```

---

### Task 8: Paper-only path

**Files:**
- Modify: `voting-app/tests/test_paper_scan.py` (test only; endpoint already supports the path)

- [ ] **Step 8.1: Add the paper-only test**

Append to `voting-app/tests/test_paper_scan.py`:

```python
def test_paper_only_no_decrement_no_audit(client, scan_election, csrf_token):
    eid = scan_election["id"]
    unused_code = scan_election["unused_codes"][0]

    rv = _post_scan(client, eid, unused_code, csrf_token)
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "paper_only"}

    from app import get_db
    db = get_db()
    row = db.execute(
        "SELECT paper_ballot_count FROM round_counts "
        "WHERE election_id = ? AND round_number = 1",
        (eid,)
    ).fetchone()
    assert row["paper_ballot_count"] == 5  # unchanged

    audit_count = db.execute(
        "SELECT COUNT(*) AS n FROM voter_audit_log "
        "WHERE election_id = ? AND result = 'paper_set_aside_at_count'",
        (eid,)
    ).fetchone()["n"]
    assert audit_count == 0
```

- [ ] **Step 8.2: Run the test, verify it passes (endpoint already handles this path)**

Run:
```
pytest voting-app/tests/test_paper_scan.py::test_paper_only_no_decrement_no_audit -v
```

Expected: PASS.

- [ ] **Step 8.3: Commit**

```
git add voting-app/tests/test_paper_scan.py
git commit -m "test(scan): assert paper_only path is a no-op for count and audit"
```

---

### Task 9: Unknown path

**Files:**
- Modify: `voting-app/tests/test_paper_scan.py`

- [ ] **Step 9.1: Add the unknown-code test**

Append:

```python
def test_unknown_code_returns_unknown(client, scan_election, csrf_token):
    eid = scan_election["id"]
    rv = _post_scan(client, eid, "ZZZZZZ", csrf_token)
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "unknown"}


def test_empty_code_returns_unknown(client, scan_election, csrf_token):
    eid = scan_election["id"]
    rv = _post_scan(client, eid, "", csrf_token)
    assert rv.status_code == 200
    assert rv.get_json() == {"result": "unknown"}
```

- [ ] **Step 9.2: Run the tests, verify they pass**

Run:
```
pytest voting-app/tests/test_paper_scan.py::test_unknown_code_returns_unknown voting-app/tests/test_paper_scan.py::test_empty_code_returns_unknown -v
```

Expected: PASS.

- [ ] **Step 9.3: Commit**

```
git add voting-app/tests/test_paper_scan.py
git commit -m "test(scan): assert unknown-code path returns unknown without side effects"
```

---

### Task 10: Phase guards

The endpoint must reject requests when voting is open or the election is finalised.

**Files:**
- Modify: `voting-app/app.py` (the endpoint)
- Modify: `voting-app/tests/test_paper_scan.py`

- [ ] **Step 10.1: Add failing guard tests**

Append:

```python
def test_endpoint_rejects_when_voting_open(client, db, admin_login, csrf_token):
    from tests.test_app import _seed_count_phase_election
    info = _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=[])
    db.execute("UPDATE elections SET voting_open = 1 WHERE id = ?", (info["id"],))
    db.commit()

    rv = _post_scan(client, info["id"], "KR4T7N", csrf_token)
    assert rv.status_code == 409
    assert "count phase" in rv.get_json().get("error", "").lower()


def test_endpoint_rejects_when_finalised(client, db, admin_login, csrf_token):
    from tests.test_app import _seed_count_phase_election
    info = _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=[])
    db.execute("UPDATE elections SET display_phase = 4 WHERE id = ?", (info["id"],))
    db.commit()

    rv = _post_scan(client, info["id"], "KR4T7N", csrf_token)
    assert rv.status_code == 409
    assert "count phase" in rv.get_json().get("error", "").lower()
```

- [ ] **Step 10.2: Run the guard tests, verify they fail**

Run:
```
pytest voting-app/tests/test_paper_scan.py -k "rejects_when" -v
```

Expected: FAIL (current endpoint accepts both states).

- [ ] **Step 10.3: Add the guards to the endpoint**

In `voting-app/app.py`, just after the `election` lookup in `admin_scan_ballot_result`, before reading the JSON body:

```python
    if election["voting_open"] or election["display_phase"] == 4:
        return jsonify({"error": "Scanning is only available during the count phase."}), 409
```

- [ ] **Step 10.4: Run the guard tests, verify they pass**

Run:
```
pytest voting-app/tests/test_paper_scan.py -k "rejects_when" -v
```

Expected: PASS.

- [ ] **Step 10.5: Commit**

```
git add voting-app/app.py voting-app/tests/test_paper_scan.py
git commit -m "feat(admin): scan endpoint rejects requests outside count phase

Returns 409 when voting is still open or the election has been
finalised. Prevents accidental decrements or audit-log noise."
```

---

### Task 11: paper_ballot_count clamp at zero

The endpoint already clamps via `paper_ballot_count > 0` in the UPDATE, returning a `match` result with a `warning` payload. Add an explicit test.

**Files:**
- Modify: `voting-app/tests/test_paper_scan.py`

- [ ] **Step 11.1: Add a test for the clamp**

Append:

```python
def test_match_clamps_at_zero_paper_count(client, db, admin_login, csrf_token):
    from tests.test_app import _seed_count_phase_election
    info = _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=[],
                                       paper_ballot_count=0)

    rv = _post_scan(client, info["id"], "KR4T7N", csrf_token)
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["result"] == "match"
    assert "warning" in body

    from app import get_db
    db2 = get_db()
    row = db2.execute(
        "SELECT paper_ballot_count FROM round_counts "
        "WHERE election_id = ? AND round_number = 1",
        (info["id"],)
    ).fetchone()
    assert row["paper_ballot_count"] == 0  # not negative

    audit_count = db2.execute(
        "SELECT COUNT(*) AS n FROM voter_audit_log "
        "WHERE election_id = ? AND result = 'paper_set_aside_at_count'",
        (info["id"],)
    ).fetchone()["n"]
    assert audit_count == 1  # warning path still logs
```

- [ ] **Step 11.2: Run the test, verify it passes**

Run:
```
pytest voting-app/tests/test_paper_scan.py::test_match_clamps_at_zero_paper_count -v
```

Expected: PASS.

- [ ] **Step 11.3: Commit**

```
git add voting-app/tests/test_paper_scan.py
git commit -m "test(scan): assert paper_ballot_count clamps at zero with warning"
```

---

### Task 12: Voter audit reason label

**Files:**
- Modify: wherever `rejected_already_used` is mapped to a human-readable string. Search to find it.

- [ ] **Step 12.1: Locate the audit-reason label site**

Run:
```
grep -rn "rejected_already_used" voting-app/templates voting-app/app.py
```

Expected: at least one mapping site (e.g. a `dict` in `app.py` translating audit results to labels, and/or an inline `{% if result == 'rejected_already_used' %}...` block in `voting-app/templates/admin/voter_log.html`).

- [ ] **Step 12.2: Add the new label entry**

If a Python dict exists (typical pattern), e.g.:

```python
RESULT_LABELS = {
    "rejected_already_used": "Already used",
    ...
}
```

Add:

```python
    "paper_set_aside_at_count": "Paper ballot set aside (already voted online)",
```

If the mapping is inline in the template, add an `{% elif %}` arm with the same label.

- [ ] **Step 12.3: Manual UAT**

1. Trigger a scan match (use the existing test data or seed via the admin UI).
2. Open the voter audit log page.
3. Confirm the new label appears alongside other reason labels.

- [ ] **Step 12.4: Commit**

```
git add voting-app/app.py voting-app/templates/admin/voter_log.html
git commit -m "feat(admin): label paper_set_aside_at_count in audit log"
```

---

## Section 4: Part B. Scanner frontend

### Task 13: Vendor jsQR

**Files:**
- Create: `voting-app/static/vendor/jsqr.min.js`

- [ ] **Step 13.1: Download a pinned jsQR release**

Run from the repo root:

```
mkdir -p voting-app/static/vendor
curl -L -o voting-app/static/vendor/jsqr.min.js https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js
```

Verify the file is non-empty and starts with the expected UMD bundle marker:
```
head -c 200 voting-app/static/vendor/jsqr.min.js
```

Expected: starts with `(function (global, factory)` or similar UMD wrapper.

- [ ] **Step 13.2: Commit**

```
git add voting-app/static/vendor/jsqr.min.js
git commit -m "chore(vendor): add jsQR 1.4.0 as offline QR-decoder fallback

Used by scan_ballots.html when window.BarcodeDetector is unavailable
(iOS Safari < 17, older Android browsers). Vendored so the scanner
works fully offline on the count laptop / phone."
```

---

### Task 14: Scanner page HTML scaffold

**Files:**
- Create: `voting-app/templates/admin/scan_ballots.html`

- [ ] **Step 14.1: Create the scanner template**

Create `voting-app/templates/admin/scan_ballots.html`:

```html
{% extends "base.html" %}
{% block title %}Scan paper ballots - {{ election.name }}{% endblock %}
{% block content %}
<div class="container" style="max-width: 480px;">
    <h1 style="margin: 0 0 8px;">Scan paper ballots</h1>
    <p style="font-size: 14px; color: #666; margin: 0 0 12px;">
        Hold each ballot's QR under the camera. Green = paper-only,
        keep counting. Red = already voted online, set aside. Yellow =
        unknown, set aside or rescan.
    </p>

    <div id="frcdd-scanner-frame" style="position: relative;
         width: 100%; aspect-ratio: 1/1; background: #000;
         border-radius: 8px; overflow: hidden;">
        <video id="frcdd-scanner-video" playsinline autoplay muted
               style="width: 100%; height: 100%; object-fit: cover;"></video>
        <div id="frcdd-scanner-flash" style="position: absolute;
             inset: 0; opacity: 0; pointer-events: none;"></div>
    </div>

    <div style="display: flex; gap: 16px; justify-content: space-around;
                margin: 12px 0; font-size: 16px;">
        <div>Scanned: <strong id="frcdd-scan-count">0</strong></div>
        <div>Set aside: <strong id="frcdd-aside-count">0</strong></div>
    </div>

    <div id="frcdd-scan-last" style="min-height: 22px; font-size: 14px;
         color: #555; text-align: center;"></div>

    <div id="frcdd-scan-notice" style="display: none; padding: 10px;
         background: #ffe6e6; border: 1px solid #c00; border-radius: 6px;
         margin: 12px 0; font-size: 14px;"></div>

    <div style="text-align: center; margin-top: 16px;">
        <button type="button" id="frcdd-mute-btn" class="btn btn-outline btn-small">Mute</button>
        <a href="{{ url_for('admin_step_count', election_id=election.id) }}"
           class="btn btn-primary" style="margin-left: 8px;">Done</a>
    </div>
</div>

<input type="hidden" id="frcdd-csrf" value="{{ csrf_token() }}">
<input type="hidden" id="frcdd-endpoint"
       value="{{ url_for('admin_scan_ballot_result', election_id=election.id) }}">

<script src="{{ url_for('static', filename='vendor/jsqr.min.js') }}"></script>
{% block scanner_scripts %}{% endblock %}
{% endblock %}
```

- [ ] **Step 14.2: Commit**

```
git add voting-app/templates/admin/scan_ballots.html
git commit -m "feat(admin): scaffold scan_ballots.html template

Layout-only: video frame, counters, last-result line, dismissible
notice for warnings, Mute and Done buttons. Decoder, audio, and dedup
logic are added in the next task."
```

---

### Task 15: Camera + decoder + UI feedback JS

**Files:**
- Modify: `voting-app/templates/admin/scan_ballots.html` (add the script)

- [ ] **Step 15.1: Append the scanner JS**

Edit `voting-app/templates/admin/scan_ballots.html`, replacing the empty `{% block scanner_scripts %}{% endblock %}` line with:

```html
{% block scanner_scripts %}
<script>
(function() {
    var video = document.getElementById('frcdd-scanner-video');
    var flash = document.getElementById('frcdd-scanner-flash');
    var scanCountEl = document.getElementById('frcdd-scan-count');
    var asideCountEl = document.getElementById('frcdd-aside-count');
    var lastEl = document.getElementById('frcdd-scan-last');
    var noticeEl = document.getElementById('frcdd-scan-notice');
    var muteBtn = document.getElementById('frcdd-mute-btn');
    var csrf = document.getElementById('frcdd-csrf').value;
    var endpoint = document.getElementById('frcdd-endpoint').value;

    var scanCount = 0;
    var asideCount = 0;
    var muted = false;
    var lastSeen = new Map(); // code -> ms timestamp
    var detector = null;

    muteBtn.addEventListener('click', function() {
        muted = !muted;
        muteBtn.textContent = muted ? 'Unmute' : 'Mute';
    });

    function beep(durationMs, freq) {
        if (muted) return;
        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.frequency.value = freq;
            osc.connect(gain);
            gain.connect(ctx.destination);
            gain.gain.value = 0.15;
            osc.start();
            setTimeout(function() {
                osc.stop();
                ctx.close();
            }, durationMs);
        } catch (e) { /* AudioContext may be unavailable; ignore */ }
    }

    function flashColor(color, durationMs) {
        flash.style.background = color;
        flash.style.opacity = '0.6';
        setTimeout(function() { flash.style.opacity = '0'; }, durationMs);
    }

    function showResult(result, code, warning) {
        if (result === 'match') {
            asideCount += 1;
            asideCountEl.textContent = asideCount;
            lastEl.textContent = 'Set aside ' + code;
            flashColor('#c00', 1000);
            beep(600, 320);
            if (warning) {
                noticeEl.textContent = 'Warning: ' + warning;
                noticeEl.style.display = 'block';
            }
        } else if (result === 'paper_only') {
            scanCount += 1;
            scanCountEl.textContent = scanCount;
            lastEl.textContent = '✓ Paper-only (' + code + ')';
            flashColor('#0a7', 300);
            beep(150, 880);
        } else {
            lastEl.textContent = 'Unknown QR. Set aside or rescan.';
            flashColor('#cc0', 1000);
            beep(120, 660);
            setTimeout(function() { beep(120, 660); }, 180);
        }
    }

    function postCode(code) {
        fetch(endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf,
            },
            body: JSON.stringify({code: code}),
        }).then(function(r) {
            if (r.status === 409) {
                noticeEl.textContent = 'Scanning is only available during the count phase.';
                noticeEl.style.display = 'block';
                return null;
            }
            return r.json();
        }).then(function(j) {
            if (j) showResult(j.result, code, j.warning);
        }).catch(function() {
            lastEl.textContent = 'Network error. Retrying scan.';
        });
    }

    function handleQrText(text) {
        // Accept either a full URL ending in /v/<code> or a bare code.
        var m = text.match(/(?:^|\/)v\/([A-Z0-9]+)\/?$/i);
        var code = m ? m[1].toUpperCase() : text.replace(/[^A-Z0-9]/gi, '').toUpperCase();
        if (!code || code.length < 4) {
            showResult('unknown', '');
            return;
        }
        var now = Date.now();
        var last = lastSeen.get(code);
        if (last && (now - last) < 3000) return;
        lastSeen.set(code, now);
        postCode(code);
    }

    function setupDetector() {
        if ('BarcodeDetector' in window) {
            try {
                detector = new BarcodeDetector({formats: ['qr_code']});
                return 'native';
            } catch (e) { /* fall through to jsQR */ }
        }
        return 'jsqr';
    }

    function startCamera() {
        return navigator.mediaDevices.getUserMedia({
            video: {facingMode: 'environment'}
        }).then(function(stream) {
            video.srcObject = stream;
            return new Promise(function(resolve) { video.onloadedmetadata = resolve; });
        });
    }

    function loopNative() {
        if (!detector) return;
        detector.detect(video).then(function(codes) {
            if (codes && codes[0] && codes[0].rawValue) handleQrText(codes[0].rawValue);
        }).catch(function() {}).finally(function() {
            requestAnimationFrame(loopNative);
        });
    }

    function loopJsQr() {
        var canvas = document.createElement('canvas');
        var ctx = canvas.getContext('2d');
        function tick() {
            if (video.readyState === video.HAVE_ENOUGH_DATA) {
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
                var code = window.jsQR(img.data, img.width, img.height, {
                    inversionAttempts: 'dontInvert',
                });
                if (code && code.data) handleQrText(code.data);
            }
            requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    }

    var mode = setupDetector();
    startCamera().then(function() {
        if (mode === 'native') loopNative();
        else loopJsQr();
    }).catch(function(err) {
        noticeEl.textContent = 'Cannot access camera: ' + (err && err.message ? err.message : err);
        noticeEl.style.display = 'block';
    });
})();
</script>
{% endblock %}
```

- [ ] **Step 15.2: Manual UAT**

(Test on a phone or laptop with a webcam.)

1. Generate code slips for a small test election. Burn one of the codes via voting through the app.
2. Print one code slip (or display the QR on a second screen).
3. Open `/admin/elections/<id>/scan-ballots` (note: GET route is added in Task 16; if it does not yet exist, navigate by directly POSTing). For now, render the template via a temporary route or hand-craft the URL once Task 16 is complete.
4. Hold the burned-code QR under the camera. Confirm: red flash, alert tone, "Set aside" counter increments, "Set aside KR4T7N" appears.
5. Hold an unused-code QR under the camera. Confirm: green flash, short beep, "Scanned" counter increments, "Paper-only (AB3XY9)" appears.
6. Hold a non-election QR (any random QR code) under the camera. Confirm: yellow flash, double beep, "Unknown QR" message.
7. Hold the same burned-code QR under the camera again within 3 seconds. Confirm: nothing happens (dedup).
8. Wait 3+ seconds, hold it again. Confirm: it fires again as a re-scan.
9. Press Mute. Verify subsequent scans are silent.
10. Press Done. Verify return to the count step.

- [ ] **Step 15.3: Commit**

```
git add voting-app/templates/admin/scan_ballots.html
git commit -m "feat(admin): scanner JS with BarcodeDetector + jsQR fallback

Continuous video QR decode via window.BarcodeDetector when available,
jsQR fallback otherwise. 3-second per-code dedup. Audio (beep)
+ visual flash feedback for match/paper_only/unknown classes. Mute
toggle. Counters and last-result line update on each non-deduped
scan. Posts to admin_scan_ballot_result with CSRF."
```

---

### Task 16: Scanner GET route

**Files:**
- Modify: `voting-app/app.py`

- [ ] **Step 16.1: Add the GET route**

Add to `voting-app/app.py` near `admin_scan_ballot_result`:

```python
@app.route("/admin/elections/<int:election_id>/scan-ballots", methods=["GET"],
           endpoint="admin_scan_ballots")
@admin_required
def admin_scan_ballots(election_id):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        abort(404)
    if election["voting_open"] or election["display_phase"] == 4:
        flash("Scanning is only available during the count phase.", "error")
        return redirect(url_for("admin_step_count", election_id=election_id))
    return render_template("admin/scan_ballots.html", election=election)
```

- [ ] **Step 16.2: Add a route smoke test**

Append to `voting-app/tests/test_paper_scan.py`:

```python
def test_scan_ballots_page_renders(client, scan_election, admin_login):
    eid = scan_election["id"]
    rv = client.get(f"/admin/elections/{eid}/scan-ballots")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Scan paper ballots" in body
    assert "frcdd-scanner-video" in body


def test_scan_ballots_page_redirects_when_voting_open(client, db, admin_login):
    from tests.test_app import _seed_count_phase_election
    info = _seed_count_phase_election(db, used_codes=["KR4T7N"], unused_codes=[])
    db.execute("UPDATE elections SET voting_open = 1 WHERE id = ?", (info["id"],))
    db.commit()

    rv = client.get(f"/admin/elections/{info['id']}/scan-ballots", follow_redirects=False)
    assert rv.status_code == 302
    assert "/step/count" in rv.headers["Location"]
```

- [ ] **Step 16.3: Run, verify both pass**

Run:
```
pytest voting-app/tests/test_paper_scan.py -v
```

Expected: all tests PASS.

- [ ] **Step 16.4: Commit**

```
git add voting-app/app.py voting-app/tests/test_paper_scan.py
git commit -m "feat(admin): GET /admin/elections/<id>/scan-ballots route

Renders the scanner page for the count phase. Redirects with a flash
message when voting is still open or the election has been finalised."
```

---

## Section 5: Part B. Count screen integration

### Task 17: Reconciliation data in the manage payload

**Files:**
- Modify: `voting-app/app.py:1605` (`_build_manage_view_payload`)

- [ ] **Step 17.1: Add a failing template-context test**

Append to `voting-app/tests/test_app.py`:

```python
def test_step_count_payload_includes_reconciliation_fields(client, db, admin_login):
    info = _seed_count_phase_election(db, used_codes=["KR4T7N", "AB3XY9"],
                                       unused_codes=["JK5WL6"], paper_ballot_count=20)
    rv = client.get(f"/admin/election/{info['id']}/step/count")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    # Reconciliation panel labels
    assert "Reconciliation" in body
    assert "Attendees" in body
    assert "Paper ballots" in body
    assert "Gap" in body
```

- [ ] **Step 17.2: Run, verify it fails**

Run:
```
pytest voting-app/tests/test_app.py::test_step_count_payload_includes_reconciliation_fields -v
```

Expected: FAIL (panel not yet rendered).

- [ ] **Step 17.3: Add reconciliation fields to the payload**

In `voting-app/app.py`, locate the bottom of `_build_manage_view_payload` (just before the final return). Add:

```python
    # Reconciliation panel inputs (paper-scan feature). gap > 0 means
    # abstentions, gap == 0 means full turnout, gap < 0 means more
    # ballots than attendees (double-vote).
    used_codes_count = db.execute(
        "SELECT COUNT(*) FROM codes WHERE election_id = ? AND used = 1",
        (election_id,)
    ).fetchone()[0]
    in_person_participants, paper_ballot_count_val, _ = get_round_counts(election_id, current_round)
    postal_voter_count = db.execute(
        "SELECT COUNT(*) FROM postal_votes WHERE election_id = ? AND round_number = ?",
        (election_id, current_round)
    ).fetchone()[0] if _table_exists(db, "postal_votes") else 0
    gap = (in_person_participants or 0) - (used_codes_count + paper_ballot_count_val + postal_voter_count)
    failed_scans = db.execute(
        "SELECT COUNT(*) FROM voter_audit_log WHERE election_id = ? "
        "AND round_number = ? AND result LIKE 'rejected_%'",
        (election_id, current_round)
    ).fetchone()[0]

    reconciliation = {
        "attendees": in_person_participants or 0,
        "online_used": used_codes_count,
        "paper": paper_ballot_count_val,
        "postal": postal_voter_count,
        "gap": gap,
        "failed_scans": failed_scans,
    }
```

Then in the final `return` dict of the function, add:

```python
        "reconciliation": reconciliation,
```

(If `_table_exists` is not present, replace its check with a try/except around the SELECT, or use a known-existing query pattern from elsewhere in the file.)

- [ ] **Step 17.4: Wait until Task 18 to make this test pass.** Reconciliation fields are now in the payload but the template does not yet render them. Commit at the end of Task 18.

---

### Task 18: Reconciliation panel in step_count.html

**Files:**
- Modify: `voting-app/templates/admin/step_count.html`

- [ ] **Step 18.1: Add the panel and the scan button**

Edit `voting-app/templates/admin/step_count.html`. Just after the closing `</form>` for the `paper_ballot_count` form (around line 23), insert:

```jinja
{% set rec = reconciliation %}
<div style="margin: 14px 0; padding: 12px 14px; background: #fafafa;
            border: 1px solid var(--grey); border-radius: 8px;">
    <h3 style="margin: 0 0 10px; font-size: 14px; color: var(--navy);
               text-transform: uppercase; letter-spacing: 0.5px;">Reconciliation</h3>
    <table style="font-size: 14px; line-height: 1.7;">
        <tr><td style="padding-right: 16px;">Attendees:</td><td><strong>{{ rec.attendees }}</strong></td></tr>
        <tr><td style="padding-right: 16px;">Online used:</td><td>{{ rec.online_used }}</td></tr>
        <tr><td style="padding-right: 16px;">Paper ballots:</td><td>{{ rec.paper }}</td></tr>
        <tr><td style="padding-right: 16px;">Postal:</td><td>{{ rec.postal }}</td></tr>
        <tr><td style="padding-right: 16px;">Gap:</td>
            <td>
                {% if rec.gap > 0 %}
                    <span style="color: #555;">{{ rec.gap }} (within attendance)</span>
                {% elif rec.gap == 0 %}
                    <span style="color: #0a7;">Reconciled: every attendee voted.</span>
                {% else %}
                    <span style="color: #c00;"><strong>{{ rec.gap | abs }} more ballots than attendees</strong></span>
                {% endif %}
            </td></tr>
        {% if rec.failed_scans > 0 %}
        <tr><td style="padding-right: 16px;">Failed scan attempts:</td><td>{{ rec.failed_scans }}</td></tr>
        {% endif %}
    </table>
    {% set big_gap = rec.gap > 0 and rec.gap > 2 and rec.gap > (rec.attendees // 10) %}
    {% if big_gap %}
    <p style="margin: 8px 0 0; font-size: 13px; color: #555;">
        Larger gap than expected. Before finalising, consider asking the
        room: "Did anyone try to vote but isn't sure it worked?"
    </p>
    {% endif %}
</div>

{% if reconciliation.gap < 0 %}
<div role="alert" style="margin: 14px 0; padding: 12px 14px;
     background: #ffe6e6; border: 1px solid #c00; border-radius: 8px;">
    <strong>Ballot count exceeds attendance by {{ reconciliation.gap | abs }}.</strong>
    Scan paper ballots to find duplicates.
    <div style="margin-top: 8px;">
        <a href="{{ url_for('admin_scan_ballots', election_id=sidebar_state.election.id) }}"
           class="btn btn-primary btn-small">Scan paper ballots</a>
    </div>
</div>
{% else %}
<div style="margin: 8px 0 14px;">
    <a href="{{ url_for('admin_scan_ballots', election_id=sidebar_state.election.id) }}"
       class="btn btn-outline btn-small">Scan paper ballots</a>
</div>
{% endif %}
```

- [ ] **Step 18.2: Run the reconciliation test, verify it passes**

Run:
```
pytest voting-app/tests/test_app.py::test_step_count_payload_includes_reconciliation_fields -v
```

Expected: PASS.

- [ ] **Step 18.3: Add a `gap < 0` banner test**

Append to `voting-app/tests/test_app.py`:

```python
def test_step_count_shows_red_banner_when_ballots_exceed_attendance(client, db, admin_login):
    info = _seed_count_phase_election(db, used_codes=["KR4T7N", "AB3XY9", "JK5WL6"],
                                       unused_codes=[], paper_ballot_count=50)
    # Force the over-count: 50 paper + 3 used + 0 postal = 53 vs. 50 attendees
    rv = client.get(f"/admin/election/{info['id']}/step/count")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "exceeds attendance" in body
    assert "Scan paper ballots" in body
```

- [ ] **Step 18.4: Run the banner test, verify it passes**

Run:
```
pytest voting-app/tests/test_app.py::test_step_count_shows_red_banner_when_ballots_exceed_attendance -v
```

Expected: PASS.

- [ ] **Step 18.5: Commit**

```
git add voting-app/app.py voting-app/templates/admin/step_count.html voting-app/tests/test_app.py
git commit -m "feat(admin): reconciliation panel + scan button on count step

Renders attendees / online / paper / postal / gap. Three display
states: gap > 0 (within attendance, optional 'larger than expected'
hint when gap > 10% of attendees), gap == 0 (reconciled green),
gap < 0 (red banner with prominent scan-paper-ballots button).
Always shows a smaller scan button outside the banner so the chairman
can run the scanner proactively."
```

---

## Section 6: End-to-end

### Task 19: Double-vote scenario test

**Files:**
- Modify: `voting-app/tests/test_app.py` (or `test_mass_election.py`, whichever fits the existing fixtures)

- [ ] **Step 19.1: Add the e2e test**

Append to `voting-app/tests/test_app.py`:

```python
def test_e2e_double_vote_caught_by_scan(client, db, admin_login, csrf_token):
    """End-to-end: a brother votes online with code X, then a paper
    ballot bearing the same QR is scanned at count. The scan must
    decrement paper_ballot_count and create an audit row.
    """
    info = _seed_count_phase_election(db, used_codes=["KR4T7N"],
                                       unused_codes=[], paper_ballot_count=10)
    eid = info["id"]

    from app import get_db

    # Sanity: starting state.
    rc = get_db().execute(
        "SELECT paper_ballot_count FROM round_counts WHERE election_id = ? AND round_number = 1",
        (eid,)
    ).fetchone()
    assert rc["paper_ballot_count"] == 10

    # Act: scan the same code (simulating the operator finding the
    # paper ballot bearing this voter's QR in the box).
    rv = client.post(
        f"/admin/elections/{eid}/scan-ballot-result",
        json={"code": "KR4T7N"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert rv.status_code == 200
    assert rv.get_json()["result"] == "match"

    # Assert: paper_ballot_count decremented, audit row created.
    rc2 = get_db().execute(
        "SELECT paper_ballot_count FROM round_counts WHERE election_id = ? AND round_number = 1",
        (eid,)
    ).fetchone()
    assert rc2["paper_ballot_count"] == 9

    audit = get_db().execute(
        "SELECT result FROM voter_audit_log "
        "WHERE election_id = ? AND result = 'paper_set_aside_at_count'",
        (eid,)
    ).fetchall()
    assert len(audit) == 1
```

- [ ] **Step 19.2: Run, verify it passes**

Run:
```
pytest voting-app/tests/test_app.py::test_e2e_double_vote_caught_by_scan -v
```

Expected: PASS.

- [ ] **Step 19.3: Commit**

```
git add voting-app/tests/test_app.py
git commit -m "test: e2e double-vote caught by scan and decremented + audited"
```

---

## Section 7: Final verification

### Task 20: Full suite + manual UAT

- [ ] **Step 20.1: Run the full test suite**

Run:
```
pytest voting-app/tests/ -v
```

Expected: all tests PASS, no regressions in unrelated modules.

- [ ] **Step 20.2: End-to-end manual UAT**

1. Reset the dev database: `python voting-app/scripts/reset_app.py` (or similar; check for the actual reset path the project uses).
2. Seed an election with 5 codes via the admin UI. Generate code-slip PDFs and verify the QR is visibly larger (32 mm).
3. Open voting. Vote with two codes from the same phone (simulating husband + wife).
4. On the confirmation page, tap the "?" badge: confirm both codes are listed with timestamps.
5. Re-scan one of the burned QRs. Confirm the page shows "already used" but the "?" badge still lists both codes (the voter can verify their vote is registered).
6. Close voting. Navigate to the count step.
7. Confirm the reconciliation panel appears. Manually enter `paper_ballot_count = 4` (one more than reality of 3 paper-only). Confirm gap is now negative and the red banner appears.
8. Tap "Scan paper ballots". Confirm the camera page opens.
9. Hold each test ballot's QR under the camera in turn. Confirm the two burned codes set aside (red), three unused codes pass (green).
10. Return to the count step. Confirm `paper_ballot_count` has decremented to 2. Reconciliation gap should now be 0 or positive.
11. Check the voter audit log: confirm two `paper_set_aside_at_count` rows exist with the labels "Paper ballot set aside (already voted online)".

- [ ] **Step 20.3: Update CHANGELOG.md**

Add a new section to `CHANGELOG.md` (per global feedback memory: keep CHANGELOG current):

```markdown
## [Unreleased]

### Added
- Phone receipt: each device persists a list of codes voted on it
  (`localStorage`). A "?" badge on voter pages lets a brother confirm
  his vote without panic-dropping a paper ballot after a re-scan.
- Paper-ballot QR scanner on the admin count step. Reads each ballot's
  QR via the device camera; matches against codes already burned
  online; auto-decrements paper_ballot_count and writes a voter-audit
  row when a duplicate is detected.
- Reconciliation panel on the count step showing attendees / online /
  paper / postal / gap. Red banner with prominent scan link when
  ballots exceed attendance.
- Code-slip QR enlarged from 24 mm to 32 mm for reliable count-time
  camera scanning.
```

- [ ] **Step 20.4: Commit the CHANGELOG**

```
git add CHANGELOG.md
git commit -m "docs(changelog): paper scan + phone receipt + 32mm QR"
```

---

## Notes for the implementing engineer

- **Pytest fixtures.** Tests assume `client`, `admin_login`, `db`, and `csrf_token` fixtures already exist in `voting-app/tests/conftest.py` or are defined alongside `test_app.py`. If any are missing, add them following the project's existing pattern (see how `test_app.py` instantiates the Flask test client and admin auth).
- **CSRF.** The endpoint uses CSRF protection via the existing decorator stack (`@admin_required` + global CSRFProtect). Tests must include a valid token; if no fixture exists, fetch one by requesting any admin GET first and reading the `csrf_token` from the response.
- **No em-dashes.** Per the global CLAUDE.md, do not use em-dashes anywhere in code, tests, comments, commit messages, or docs.
- **No new schema.** Every task above reuses existing tables. If a task seems to need a new column, stop and re-read the spec; you've taken a wrong turn.
- **Manual UAT** at Steps 3.2, 5.3, 12.3, 15.2, 20.2 cannot be skipped. Server-side tests do not exercise camera, audio, or localStorage behaviour.
- **Commit boundaries.** One commit per task, as written. The plan deliberately produces small, reviewable commits with green tests at every step.
