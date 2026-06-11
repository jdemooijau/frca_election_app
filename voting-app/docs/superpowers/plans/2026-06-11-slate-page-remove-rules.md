# Slate Page (remove Election Rules) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the projector phase-2 "Election Rules" screen with a full-width candidate Slate screen (display wording "Candidates") that keeps the vote threshold, and rename the admin walk-through wording from "Rules" to "Candidates".

**Architecture:** Rename `display/rules.html` to `display/slate.html`, drop the Election Rules column, keep the candidate slate full-width plus a standalone threshold line, and rename the scaler identifiers to `slate`. Update the phase-2 render in app.py and the admin step wording. Display text says "Candidates"; technical identifiers stay "slate".

**Tech Stack:** Flask + Jinja2 templates, vanilla JS, plain CSS. Tests are pytest render-level assertions.

Spec: `docs/superpowers/specs/2026-06-11-slate-page-remove-rules-design.md`

---

## File Structure

- Rename + rewrite: `voting-app/templates/display/rules.html` -> `voting-app/templates/display/slate.html`
- Modify: `voting-app/app.py` (phase-2 render line ~4847)
- Modify: `voting-app/templates/admin/step_welcome.html` (wording)
- Modify: `voting-app/templates/admin/step_attendance.html` (two button labels)
- Modify tests: `voting-app/tests/test_display_fill.py` (TestRulesScreenFill), `voting-app/tests/test_wizard_sidebar.py:207`

---

## Task 1: Projector phase-2 -> Candidates slate (slate.html)

**Files:**
- Rename: `voting-app/templates/display/rules.html` -> `voting-app/templates/display/slate.html`
- Modify: `voting-app/app.py` (render line ~4847)
- Test: `voting-app/tests/test_display_fill.py`

- [ ] **Step 1: Update the failing test**

In `tests/test_display_fill.py`, replace the whole `TestRulesScreenFill` class with:

```python
class TestSlateScreen:
    def test_phase2_renders_candidate_slate_not_rules(self, election_with_codes):
        client = election_with_codes
        _set_phase(1, display_phase=2)  # phase 2 -> slate.html
        resp = client.get("/display")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Candidate slate is shown (an office heading) with the vote threshold.
        assert "For Elder" in html
        assert "To be elected" in html
        # Election Rules article prose is gone.
        assert "Election Rules" not in html
        assert "Subsequent Rounds" not in html
        assert "Objections of a formal nature" not in html
        # Scale-to-fit scaler survives the rename with its tuned constants.
        assert "autoSizeSlate" in html
        assert "* 0.96)" in html
        assert "hScale, 2.4)" in html
```

> Note: `election_with_codes` creates one office named "Elder", so "For Elder"
> is present in the slate. The fixture leaves `display_phase` at 1; `_set_phase`
> sets it to 2.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestSlateScreen -v`
Expected: FAIL. `slate.html` does not exist yet, so phase 2 still renders the old rules page (contains "Election Rules"); `autoSizeSlate` not found.

- [ ] **Step 3: Rename the template file**

Run: `cd voting-app && git mv templates/display/rules.html templates/display/slate.html`

- [ ] **Step 4: Replace the template contents**

Overwrite `voting-app/templates/display/slate.html` with exactly:

```html
{% extends "base.html" %}
{% block title %}Display - Candidates{% endblock %}
{% block body_class %}display-body{% endblock %}

{% block head %}
<meta http-equiv="refresh" content="5">
<style>
    /* Override display-body 100vh/overflow:hidden so the slate can flow and
       the page scrolls instead of an inner column producing a scrollbar. */
    body.display-body {
        height: auto;
        overflow: visible;
    }
    body.display-body .display-main {
        overflow: visible;
    }
    :root { --slate-scale: 1; }

    /* Bigger topbar title on the slate page (scoped) */
    body.display-body .display-topbar { padding: 18px 32px; }
    body.display-body .display-title { font-size: 40px; }

    /* Participation strip: fixed size so the layout top does not move when
       the slate scales. */
    .participants-strip {
        display: flex;
        gap: 56px;
        justify-content: center;
        align-items: baseline;
        padding: 16px 24px;
        background: var(--grey-light);
        border-bottom: 2px solid var(--gold);
        font-size: 32px;
        flex-wrap: wrap;
    }
    .participants-strip strong { font-size: 48px; }
    .participants-strip .pstrip-num-navy { color: var(--navy); }
    .participants-strip .pstrip-num-gold { color: var(--gold); }
    .participants-strip .pstrip-label { color: #555; }

    /* Standalone vote-threshold line (was inside the Article 6 block). Fixed
       size, not scaled, so it stays put above the slate. */
    .slate-threshold {
        text-align: center;
        font-size: 30px;
        color: var(--navy);
        margin: 18px 0 6px;
    }
    .slate-threshold strong { color: var(--gold); }

    .slate-heading {
        font-size: calc(34px * var(--slate-scale));
        color: var(--navy);
        margin: calc(8px * var(--slate-scale)) 0 calc(14px * var(--slate-scale));
        padding-bottom: calc(8px * var(--slate-scale));
        border-bottom: 3px solid var(--gold);
    }
    .candidate-offices {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: calc(40px * var(--slate-scale));
    }
    .candidate-office {
        margin-bottom: calc(24px * var(--slate-scale));
    }
    .candidate-office h3 {
        font-size: calc(40px * var(--slate-scale));
        color: var(--gold);
        margin-bottom: calc(14px * var(--slate-scale));
    }
    /* Scale the inline-styled pill / "all vacancies filled" sub-elements so
       they stay in proportion with the heading. */
    .candidate-office h3 > span {
        font-size: calc(24px * var(--slate-scale)) !important;
    }
    .candidate-list {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .candidate-list li {
        font-size: calc(34px * var(--slate-scale));
        padding: calc(12px * var(--slate-scale)) calc(16px * var(--slate-scale));
        border-bottom: 1px solid var(--grey);
        color: var(--navy);
    }
    .candidate-list li:last-child {
        border-bottom: none;
    }
</style>
{% endblock %}

{% block content %}
<div class="display-topbar">
    <span class="display-title">{{ election.name }}</span>
    {% if election.current_round > 1 %}
    <span class="round-badge">Round {{ election.current_round }}</span>
    {% endif %}
</div>

{% if (in_person_participants or 0) > 0 or (postal_voter_count or 0) > 0 %}
<div class="participants-strip">
    <span><strong class="pstrip-num-navy">{{ in_person_participants or 0 }}</strong>
          <span class="pstrip-label">brother{{ '' if in_person_participants == 1 else 's' }} present</span></span>
    <span><strong class="pstrip-num-navy">{{ postal_voter_count or 0 }}</strong>
          <span class="pstrip-label">postal vote{{ '' if postal_voter_count == 1 else 's' }}</span></span>
    <span><strong class="pstrip-num-gold">{{ (in_person_participants or 0) + (postal_voter_count or 0) }}</strong>
          <span class="pstrip-label">total participating</span></span>
</div>
{% endif %}

<div class="display-main">
    {% if participants > 0 %}
    <div class="slate-threshold">
        To be elected: <strong>at least {{ (participants * 2 / 5) | round(0, 'ceil') | int }} votes</strong>
        (two-fifths of {{ participants }} participating)
    </div>
    {% endif %}

    <div class="slate-body">
        {% if election.current_round > 1 %}
        <h2 class="slate-heading">Remaining Candidates - Round {{ election.current_round }}</h2>
        {% else %}
        <h2 class="slate-heading">Candidates</h2>
        {% endif %}
        <div class="candidate-offices">
        {% for item in results %}
        <div class="candidate-office">
            <h3>
                For {{ item.office_name }}
                {% if item.max_selections > 0 %}
                <span style="display: block; width: fit-content; margin-top: 6px; padding: 4px 14px;
                             background: var(--gold); color: var(--navy);
                             border-radius: 999px; font-size: 24px; font-weight: 700;
                             letter-spacing: 0.3px;">
                    Select {{ item.max_selections }} name{{ '' if item.max_selections == 1 else 's' }}
                </span>
                {% else %}
                <span style="display: block; margin-top: 6px; font-size: 24px; font-weight: 400; color: #666;">
                    all vacancies filled
                </span>
                {% endif %}
            </h3>
            {% if item.candidates %}
            <ul class="candidate-list">
                {% for cand in item.candidates %}
                <li>Br. {{ cand.name }}</li>
                {% endfor %}
            </ul>
            {% endif %}
        </div>
        {% endfor %}
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
(function() {
    // Largest scale at which every candidate-name LI still fits on one line
    // in its column. Both the text and the padding scale with --slate-scale.
    function maxScaleForNoWrap(layout) {
        var lis = layout.querySelectorAll('.candidate-list li');
        if (!lis.length) return Infinity;
        var minScale = Infinity;
        for (var i = 0; i < lis.length; i++) {
            var li = lis[i];
            var textNode = null;
            for (var j = 0; j < li.childNodes.length; j++) {
                if (li.childNodes[j].nodeType === 3 &&
                    li.childNodes[j].nodeValue.trim().length > 0) {
                    textNode = li.childNodes[j];
                    break;
                }
            }
            if (!textNode) continue;
            var origWS = li.style.whiteSpace;
            li.style.whiteSpace = 'nowrap';
            var range = document.createRange();
            range.selectNode(textNode);
            var textWidth = range.getBoundingClientRect().width;
            li.style.whiteSpace = origWS;
            var cs = window.getComputedStyle(li);
            var padH = parseFloat(cs.paddingLeft || 0) +
                       parseFloat(cs.paddingRight || 0);
            var availW = li.clientWidth;
            var denom = textWidth + padH;
            if (availW > 0 && denom > 0) {
                var s = availW / denom;
                if (s < minScale) minScale = s;
            }
        }
        return minScale;
    }

    function autoSizeSlate() {
        var root = document.documentElement;
        if (window.innerWidth <= 720) {
            root.style.setProperty('--slate-scale', '1');
            return;
        }
        var layout = document.querySelector('.slate-body');
        if (!layout) {
            root.style.setProperty('--slate-scale', '1');
            return;
        }
        root.style.setProperty('--slate-scale', '1');
        requestAnimationFrame(function() {
            var rect = layout.getBoundingClientRect();
            var available = window.innerHeight - rect.top - 16;
            var natural = layout.scrollHeight;
            if (natural < 1 || available < 1) return;
            var vScale = (available * 0.96) / natural;
            var hScale = maxScaleForNoWrap(layout) * 0.98;
            var scale = Math.min(vScale, hScale, 2.4);
            scale = Math.max(1, scale);
            root.style.setProperty('--slate-scale', scale.toFixed(3));
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoSizeSlate);
    } else {
        autoSizeSlate();
    }
    window.addEventListener('resize', autoSizeSlate);
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Point the phase-2 route at the new template**

In `voting-app/app.py` (line ~4847), change:

```python
        return render_template("display/rules.html", **ctx)
```

to:

```python
        return render_template("display/slate.html", **ctx)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py::TestSlateScreen -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add voting-app/templates/display/slate.html voting-app/app.py voting-app/tests/test_display_fill.py
git commit -m "feat(display): replace phase-2 Election Rules with a Candidates slate screen"
```

---

## Task 2: Admin wording (Rules -> Candidates)

**Files:**
- Modify: `voting-app/templates/admin/step_welcome.html`
- Modify: `voting-app/templates/admin/step_attendance.html`
- Test: `voting-app/tests/test_wizard_sidebar.py`

- [ ] **Step 1: Update the failing test**

In `tests/test_wizard_sidebar.py` line ~207, change:

```python
    assert "Welcome" in body or "Election Rules" in body
```

to:

```python
    assert "Welcome" in body and "Candidates" in body
    assert "Election Rules" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v -k welcome`
Expected: FAIL. the welcome step still says "Election Rules", not "Candidates".

> If `-k welcome` selects no test, run the whole file: `python -m pytest tests/test_wizard_sidebar.py -v` and confirm the assertion at line ~207 fails.

- [ ] **Step 3: Update step_welcome.html wording**

In `voting-app/templates/admin/step_welcome.html`, make these exact replacements:

- Line 2: `{% block title %}Welcome &amp; Rules - {{ sidebar_state.election.name }}{% endblock %}`
  -> `{% block title %}Welcome &amp; Candidates - {{ sidebar_state.election.name }}{% endblock %}`
- Line 3: `{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Welcome &amp; Rules{% endblock %}`
  -> `{% block step_tag %}Round {{ sidebar_state.election.current_round }} - Welcome &amp; Candidates{% endblock %}`
- Line 4: `{% block step_heading %}Walk the projector through Welcome and Election Rules{% endblock %}`
  -> `{% block step_heading %}Walk the projector through Welcome and Candidates{% endblock %}`
- Lines 7-10 intro `<p>`: change `Walk the projector through <strong>Welcome</strong> and <strong>Election Rules</strong>`
  -> `Walk the projector through <strong>Welcome</strong> and <strong>Candidates</strong>`
- Line 13: `{% set proj_phases = [(1, "Welcome"), (2, "Election Rules")] %}`
  -> `{% set proj_phases = [(1, "Welcome"), (2, "Candidates")] %}`
- Line 36: `<button type="submit" class="btn btn-gold">Next: Election Rules &rarr;</button>`
  -> `<button type="submit" class="btn btn-gold">Next: Candidates &rarr;</button>`

- [ ] **Step 4: Update step_attendance.html wording**

In `voting-app/templates/admin/step_attendance.html`, change both occurrences of
`Next: Welcome &amp; Rules &rarr;` to `Next: Welcome &amp; Candidates &rarr;`
(lines ~93 and ~97).

Run to confirm both are changed:
`cd voting-app && grep -n "Welcome &amp; Rules" templates/admin/step_attendance.html` should print nothing.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd voting-app && python -m pytest tests/test_wizard_sidebar.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add voting-app/templates/admin/step_welcome.html voting-app/templates/admin/step_attendance.html voting-app/tests/test_wizard_sidebar.py
git commit -m "feat(admin): rename Welcome & Rules step wording to Welcome & Candidates"
```

---

## Task 3: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the display and sidebar tests**

Run: `cd voting-app && python -m pytest tests/test_display_fill.py tests/test_wizard_sidebar.py -v`
Expected: all PASS.

- [ ] **Step 2: Run the entire suite**

Run: `cd voting-app && python -m pytest -q`
Expected: all PASS. In particular `test_captive_portal.py` (uses `display_phase=2` for the voter wait page, unaffected by the projector template rename) and `test_rules_compliance.py` (tests the election logic / Article thresholds, untouched) must still pass.

- [ ] **Step 3: Confirm no stale references**

Run: `cd voting-app && grep -rn "display/rules.html\|Election Rules" app.py templates/`
Expected: no matches (the projector no longer renders rules.html or shows "Election Rules"). Functional `Article N` citations elsewhere are expected to remain and are out of scope.

- [ ] **Step 4: Manual verification (run the app)**

Project phase 2 at 1920x1080: confirm the screen shows the candidate slate full-width with the "To be elected: at least N votes" line and no article text, and that the admin step reads "Welcome & Candidates". Re-check at phone width that the `<= 720` guard holds.
