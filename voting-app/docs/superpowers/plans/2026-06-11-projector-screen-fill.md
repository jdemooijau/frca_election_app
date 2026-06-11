# Projector Screen-Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all five under-filling projector display screens use the full screen height on sparse content, by scaling content up and centring it.

**Architecture:** Per-template, in-place fixes. Two templates with no scaler (`final.html`, `welcome.html`) get a one-shot JS scaler that sets CSS `zoom` on a content wrapper. Two templates with an existing scaler (`projector.html`, `rules.html`) get tuned caps plus CSS centring. One (`waiting.html`) gets a CSS-only centring fix in `style.css`. All JS is guarded at `innerWidth <= 720` so phone views are untouched.

**Tech Stack:** Flask + Jinja2 templates, vanilla JS, plain CSS. Tests are pytest render-level / static-content assertions (visual correctness is verified by running the app).

Spec: `docs/superpowers/specs/2026-06-11-projector-screen-fill-design.md`

---

## File Structure

- `voting-app/templates/display/final.html` — Task 1 (wrapper + zoom scaler + centre)
- `voting-app/templates/display/projector.html` — Task 2 (cap 2.2->3.0, centre office) + Task 3 (welcome panel sizes)
- `voting-app/templates/display/welcome.html` — Task 4 (wrapper + zoom scaler)
- `voting-app/static/css/style.css` — Task 5 (`.display-waiting` fill+centre)
- `voting-app/templates/display/rules.html` — Task 6 (scaler constants)
- `voting-app/tests/test_display_fill.py` — Create: all tests for this plan

All tests live in one new file `tests/test_display_fill.py`, reusing the `client`, `admin_client`, and `election_with_codes` fixtures from `tests/test_app.py` by importing them.

**Test file preamble** (top of `tests/test_display_fill.py`, created in Task 1, used by all tasks):

```python
"""Render-level guards for the projector screen-fill changes.

These assert the structural hooks (wrappers, scaler functions, tuned
constants) are present in the rendered templates / static CSS. Visual
correctness (does it actually fill the screen) is verified by running the
app at projector resolution, per the spec's manual testing section.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_db
# Reuse fixtures: pytest discovers them via this import.
from tests.test_app import client, admin_client, election_with_codes  # noqa: F401

CSS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "css", "style.css",
)


def _set_phase(election_id, **cols):
    """Directly set election columns (display_phase, voting_open, ...)."""
    assigns = ", ".join(f"{k} = ?" for k in cols)
    with app.app_context():
        db = get_db()
        db.execute(
            f"UPDATE elections SET {assigns} WHERE id = ?",
            (*cols.values(), election_id),
        )
        db.commit()
```

> Note on fixture import: if `from tests.test_app import ...` fails to resolve in the test runner, change it to `from test_app import ...` (the existing suite runs with `tests/` on the path). Confirm in Task 1 Step 2 by running the test and reading the collection error, then use whichever import resolves.

---

## Task 1: final.html — scale-to-fit + vertical centre

**Files:**
- Create: `voting-app/tests/test_display_fill.py`
- Modify: `voting-app/templates/display/final.html`

- [ ] **Step 1: Write the failing test**

Add the preamble above, then:

```python
class TestFinalResultsFill:
    def test_final_results_wraps_and_centers(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, voting_open=0, show_results=0, display_phase=4)
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Content wrapped for zoom-based scale-to-fit:
        assert 'id="final-fit"' in html
        # The one-shot scaler is present:
        assert "fitFinal" in html
        # Vertical centring: the top-anchoring inline style is gone:
        assert "justify-content: flex-start" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestFinalResultsFill -v`
Expected: FAIL — `id="final-fit"` not in html (wrapper not added yet). If it errors on the fixture import instead, fix the import line per the note above, then re-run and confirm it fails on the assertion.

- [ ] **Step 3: Centre the content (edit the inline style)**

In `final.html`, change the `.display-main` opening tag (line ~134):

```html
<div class="display-main" style="justify-content: flex-start;">
```

to:

```html
<div class="display-main" style="justify-content: center;">
```

- [ ] **Step 4: Wrap the content in the zoom target**

Immediately after the changed `<div class="display-main" ...>` line, open the wrapper; close it just before `</div>` of `display-main`. The content to wrap is the `<h1 class="final-title">`, the `<div class="final-subtitle">`, the `<div class="final-offices">`, and the `<p class="final-note">`.

Open (right after the display-main div):
```html
    <div id="final-fit">
```
Close (right before the `</div>` that ends `.display-main`):
```html
    </div>
```

- [ ] **Step 5: Add the scaler to the existing scripts block**

In `final.html`, the `{% block scripts %}` already contains an IIFE with `check()` and `setInterval(check, 5000)`. Add the scaler function and its listeners inside that same IIFE, before the closing `})();`:

```javascript
    function fitFinal() {
        var fit = document.getElementById('final-fit');
        var main = document.querySelector('.display-main');
        if (!fit || !main) return;
        if (window.innerWidth <= 720) { fit.style.zoom = '1'; return; }
        // Reset so we measure natural (unscaled) height.
        fit.style.zoom = '1';
        requestAnimationFrame(function() {
            var available = main.clientHeight;
            var natural = fit.offsetHeight;
            if (natural < 1 || available < 1) return;
            // Fill ~95% of the height; cap 1.9x; never shrink below 1.
            var scale = (available * 0.95) / natural;
            scale = Math.max(1, Math.min(1.9, scale));
            fit.style.zoom = scale.toFixed(3);
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fitFinal);
    } else {
        fitFinal();
    }
    window.addEventListener('resize', fitFinal);
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestFinalResultsFill -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add voting-app/tests/test_display_fill.py voting-app/templates/display/final.html
git commit -m "feat(display): scale-to-fit and centre the Final Results screen"
```

---

## Task 2: projector.html — raise single-office cap + centre office content

**Files:**
- Modify: `voting-app/templates/display/projector.html`
- Test: `voting-app/tests/test_display_fill.py`

- [ ] **Step 1: Write the failing test**

```python
class TestProjectorLiveResultsFill:
    def test_single_office_cap_raised_and_office_centered(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=3)  # phase 3 -> projector.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Single-office scale cap raised 2.2 -> 3.0 (rotating cap stays 3.4):
        assert "3.4 : 3.0" in html
        assert "3.4 : 2.2" not in html
        # Office content is vertically centred within its results cell:
        assert "Vertically centre each office" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestProjectorLiveResultsFill -v`
Expected: FAIL — `3.4 : 3.0` not found (cap still 2.2).

- [ ] **Step 3: Raise the single-office cap**

In `projector.html`, in `autoSizeOffices()` (line ~809), change:

```javascript
            var cap = (grid && grid.classList.contains('rotating')) ? 3.4 : 2.2;
```

to:

```javascript
            var cap = (grid && grid.classList.contains('rotating')) ? 3.4 : 3.0;
```

- [ ] **Step 4: Centre each office's content within its results cell**

In `projector.html`, inside the `<style>` block (after the existing `.display-office h2` rule, around line 26), add:

```css
    /* Vertically centre each office's content within its results cell, so a
       sparse result (one office, a few names) sits in the middle of the
       available height instead of pinned to the top once the auto-scaler
       hits its cap. Applies in both side-by-side and rotating modes. */
    .display-office {
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
```

Then change the rotating-active rule (line ~31) from:

```css
    .display-offices.rotating .display-office.active { display: block; }
```

to:

```css
    .display-offices.rotating .display-office.active {
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
```

> Why this is safe for the scaler: `autoSizeOffices` measures `officeContentHeight` by summing each child's `offsetHeight` + margins. Flex column with `justify-content: center` does not change child heights, so the measurement is unchanged; only the visual position of the block within the cell changes.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestProjectorLiveResultsFill -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add voting-app/templates/display/projector.html voting-app/tests/test_display_fill.py
git commit -m "feat(display): raise live-results single-office cap and centre office content"
```

---

## Task 3: projector.html — enlarge the "Voting will begin shortly" panel

**Files:**
- Modify: `voting-app/templates/display/projector.html`
- Test: `voting-app/tests/test_display_fill.py`

> Scope note: this pre-open panel coexists with the summary panel (0 ballots / 0 participating) below it, so it cannot "own" the screen. The change is limited to enlarging its text so it reads from the back of the church. No layout/visibility change to sibling panels.

- [ ] **Step 1: Write the failing test**

```python
class TestProjectorWelcomePanel:
    def test_prevote_panel_enlarged(self, election_with_codes):
        client = election_with_codes
        # Phase 3 but voting NOT opened and 0 ballots -> the pre-vote panel shows.
        _set_phase(1, display_phase=3, voting_open=0)
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Voting will begin shortly" in html
        assert 'id="prevote-welcome"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestProjectorWelcomePanel -v`
Expected: FAIL — `id="prevote-welcome"` not present.

- [ ] **Step 3: Add the id and enlarge the panel text**

In `projector.html` (lines ~213-226), the panel currently begins:

```html
    <div style="text-align: center; padding: 40px 0;">
        <h2 style="font-size: 32px; color: var(--navy); margin-bottom: 16px;">Voting will begin shortly</h2>
        <p style="font-size: 20px; color: #666; margin-bottom: 24px;">
            Please connect to the WiFi and have your voting code ready.
        </p>
```

Replace those three lines (the wrapper div, the h2, and the opening of the p) with:

```html
    <div id="prevote-welcome" style="text-align: center; padding: 64px 0;">
        <h2 style="font-size: 56px; color: var(--navy); margin-bottom: 24px;">Voting will begin shortly</h2>
        <p style="font-size: 32px; color: #666; margin-bottom: 32px;">
            Please connect to the WiFi and have your voting code ready.
        </p>
```

Then in the WiFi box inside the same panel, bump the two `font-size: 20px` values to `font-size: 32px`:

```html
            <p style="font-size: 32px; color: var(--navy); margin-bottom: 4px;"><strong>WiFi:</strong> {{ wifi_ssid }}</p>
            {% if wifi_password %}
            <p style="font-size: 32px; color: var(--navy);"><strong>Password:</strong> {{ wifi_password }}</p>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestProjectorWelcomePanel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add voting-app/templates/display/projector.html voting-app/tests/test_display_fill.py
git commit -m "feat(display): enlarge the pre-vote 'Voting will begin shortly' panel"
```

---

## Task 4: welcome.html — scale-to-fit (zoom wrapper)

**Files:**
- Modify: `voting-app/templates/display/welcome.html`
- Test: `voting-app/tests/test_display_fill.py`

- [ ] **Step 1: Write the failing test**

```python
class TestWelcomeScreenFill:
    def test_welcome_wraps_and_scales(self, election_with_codes):
        client = election_with_codes  # display_phase defaults to 1 -> welcome.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'id="welcome-fit"' in html
        assert "fitWelcome" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestWelcomeScreenFill -v`
Expected: FAIL — `id="welcome-fit"` not present. (If it 500s, check that `/display` at phase 1 renders welcome.html with `congregation_name` available; the existing app provides it. Resolve before continuing.)

- [ ] **Step 3: Wrap the content in the zoom target**

In `welcome.html`, the content lives directly inside:

```html
<div class="display-main" style="justify-content: center; align-items: center; text-align: center;">
```

Immediately after that opening tag, add:
```html
    <div id="welcome-fit">
```
And immediately before the `</div>` that closes `.display-main` (the last line before `{% endblock %}`), add the matching close:
```html
    </div>
```

> Do not set a width on the wrapper. With the parent's `align-items: center`, the wrapper shrinks to its content and stays horizontally centred; `text-align: center` (inherited) keeps the inner blocks centred. `zoom` then scales the whole wrapper while the flex parent keeps it centred.

- [ ] **Step 4: Add a scripts block with the scaler**

`welcome.html` has no `{% block scripts %}` today. Add one at the end of the file (after `{% endblock %}` for content):

```html
{% block scripts %}
<script>
(function() {
    function fitWelcome() {
        var fit = document.getElementById('welcome-fit');
        var main = document.querySelector('.display-main');
        if (!fit || !main) return;
        if (window.innerWidth <= 720) { fit.style.zoom = '1'; return; }
        fit.style.zoom = '1';
        requestAnimationFrame(function() {
            var available = main.clientHeight;
            var natural = fit.offsetHeight;
            if (natural < 1 || available < 1) return;
            // Cap 1.6x; never shrink below 1 (round-1 content is already large).
            var scale = (available * 0.95) / natural;
            scale = Math.max(1, Math.min(1.6, scale));
            fit.style.zoom = scale.toFixed(3);
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fitWelcome);
    } else {
        fitWelcome();
    }
    window.addEventListener('resize', fitWelcome);
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestWelcomeScreenFill -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add voting-app/templates/display/welcome.html voting-app/tests/test_display_fill.py
git commit -m "feat(display): scale-to-fit the congregation welcome screen"
```

---

## Task 5: waiting.html — fill + centre (CSS only)

**Files:**
- Modify: `voting-app/static/css/style.css`
- Test: `voting-app/tests/test_display_fill.py`

- [ ] **Step 1: Write the failing test**

```python
class TestWaitingScreenFill:
    def test_waiting_block_fills_and_centers(self):
        with open(CSS_PATH, encoding="utf-8") as f:
            css = f.read()
        idx = css.find(".display-waiting {")
        assert idx != -1
        block = css[idx:idx + 320]
        assert "flex: 1" in block
        assert "justify-content: center" in block
        assert "align-items: center" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestWaitingScreenFill -v`
Expected: FAIL — `flex: 1` not in the `.display-waiting` block.

- [ ] **Step 3: Update the `.display-waiting` rule**

In `style.css` (line ~864), replace:

```css
.display-waiting {
    text-align: center;
    padding: 100px 40px;
    font-size: 36px;
    color: var(--grey-dark);
}
```

with:

```css
.display-waiting {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 40px;
    font-size: 36px;
    color: var(--grey-dark);
}
```

> `.display-waiting` is the only child of `body.display-body` in `waiting.html` (no topbar, no `.display-main`). `body.display-body` is a `height: 100vh` flex column, so `flex: 1` makes the block fill the viewport and the centring rules balance the content vertically.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestWaitingScreenFill -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add voting-app/static/css/style.css voting-app/tests/test_display_fill.py
git commit -m "feat(display): fill and centre the no-active-election waiting screen"
```

---

## Task 6: rules.html — tune the existing scaler

**Files:**
- Modify: `voting-app/templates/display/rules.html`
- Test: `voting-app/tests/test_display_fill.py`

- [ ] **Step 1: Write the failing test**

```python
class TestRulesScreenFill:
    def test_rules_scaler_constants_tuned(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=2)  # phase 2 -> rules.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Vertical buffer raised 0.94 -> 0.96:
        assert "* 0.96)" in html
        assert "* 0.94)" not in html
        # Cap raised 2.0 -> 2.4:
        assert "hScale, 2.4)" in html
        assert "hScale, 2.0)" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestRulesScreenFill -v`
Expected: FAIL — `* 0.96)` not present (still 0.94).

- [ ] **Step 3: Raise the vertical buffer**

In `rules.html`, in `autoSizeRules()` (line ~291), change:

```javascript
            var vScale = (available * 0.94) / natural;
```

to:

```javascript
            var vScale = (available * 0.96) / natural;
```

- [ ] **Step 4: Raise the cap**

In the same function (line ~296), change:

```javascript
            var scale = Math.min(vScale, hScale, 2.0);
```

to:

```javascript
            var scale = Math.min(vScale, hScale, 2.4);
```

> The horizontal no-wrap constraint (`hScale`) and the `scale = Math.max(1, scale)` floor are unchanged, so long candidate names still cannot wrap and content is never shrunk. This only lets sparse, short-name slates grow a little more.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestRulesScreenFill -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add voting-app/templates/display/rules.html voting-app/tests/test_display_fill.py
git commit -m "feat(display): tune rules-screen scaler to fill more on small slates"
```

---

## Task 7: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the new test file**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py -v`
Expected: all classes PASS.

- [ ] **Step 2: Run the entire suite to confirm no regressions**

Run: `cd voting-app && python -m pytest -q`
Expected: all pre-existing tests still PASS (no display/template tests broken by the markup changes).

- [ ] **Step 3: Manual visual verification (run the app)**

Start the app and open `/display` in a Chromium-based browser at 1920x1080. Drive an election through the phases (or set `display_phase` directly in a scratch DB) and confirm each screen fills and nothing clips:
- Phase 1 welcome (round 1 content-heavy, and a round-2 sparse case).
- Phase 2 rules (a short slate and a long-name slate — confirm no name wraps).
- Phase 3 pre-open ("Voting will begin shortly" enlarged) and live results (1 office / 1-2 candidates; many offices rotating).
- Phase 4 Final Results (1 office / 1 name; several offices; the no-appointments case).
- No-active-election waiting screen.
- Re-check each at a phone-width window (<= 720px) to confirm the guards hold and mobile layouts are unchanged.

- [ ] **Step 4: Report results**

Report: test counts (passed/failed), and the manual verification outcome per screen. If any screen still under-fills or clips, note it for a follow-up tuning pass (cap values are the likely lever).
```
