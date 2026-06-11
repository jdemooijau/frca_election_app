# Replace the projector Election Rules screen with a Slate screen

Date: 2026-06-11

## Goal

Remove the Election Rules article text from the projector. The congregation
no longer wants the rules (Articles 4, 6, 7, 12) read off the projector. The
phase-2 projector screen becomes a candidate Slate screen: it still shows who
is standing and the vote threshold to be elected, but not the article prose.
The admin walk-through wording that references "Rules" is renamed to match.

## Background

Phase-2 projector screen ([rules.html](../../../templates/display/rules.html))
currently shows two columns: the candidate slate on the left and the Election
Rules articles (7, 6, 12, plus an Article 4 attendance box) on the right, with
an Article 6 vote-threshold line inside the Article 6 block. It has a
scale-to-fit scaler (`autoSizeRules`, `--rules-scale`).

The admin "Welcome & Rules" step ([step_welcome.html](../../../templates/admin/step_welcome.html))
walks the projector through phase 1 (Welcome) and phase 2 (Election Rules)
before Voting. The attendance step ([step_attendance.html](../../../templates/admin/step_attendance.html))
has "Next: Welcome & Rules" buttons.

Display phases: 1 Welcome, 2 Election Rules, 3 Voting, 4 Final. Phase 2 stays;
only its content and label change.

## Non-goals

- No change to the election logic. The Article 6 thresholds that decide who is
  elected (in the app's results code) are untouched.
- Phase-2 display only. Functional article citations stay: Article 13
  (slate-override confirm on the offices step), Article 4 (attendance, still
  shown on the phase-1 Welcome screen), Article 6/8 (final-results wording).
- No change to phases 1, 3, 4 or the voter flow, beyond renaming the phase-2
  label where the admin references it.
- No database, route-path, or API changes (the phase-2 route still renders for
  `display_phase == 2`; only the template file it renders changes).

## Part 1: Projector phase-2 page -> slate.html

Rename `templates/display/rules.html` to `templates/display/slate.html` and
rewrite it as a full-width Slate screen.

- Remove the right-hand Election Rules column entirely: the Article 7
  ("Subsequent Rounds"), Article 6, and Article 12 blocks, and the Article 4
  attendance warning box. Remove the now-unused CSS (`.rules-column`,
  `.article-block`, `.threshold-line`, and the two-column `.rules-layout`
  grid).
- Keep the candidate slate as the whole screen, full width: the existing
  heading ("Slate / Candidate List" in round 1, "Remaining Candidates -
  Round N" in later rounds) and the `.candidate-offices` auto-fit grid of
  offices with their candidate lists.
- Keep the participants strip (brothers present / postal / total) as-is.
- Keep the scale-to-fit scaler, renamed for the new purpose:
  `autoSizeRules` -> `autoSizeSlate`, `--rules-scale` -> `--slate-scale`,
  `.rules-layout` measurement target -> the slate container. Keep the tuned
  constants (0.96 vertical buffer, 2.4 cap, no-wrap horizontal limit, floor 1).
- Update the phase-2 render in [app.py](../../../app.py): the
  `display_phase == 2` branch renders `display/slate.html` instead of
  `display/rules.html`.

## Part 2: Vote threshold (kept, relocated)

The Article 6 two-fifths threshold line moves out of the deleted Article 6
block to a standalone line on the slate screen, phrased plainly without the
"Article 6" label. Rendered only when `participants > 0`:

> **To be elected: at least N votes** (two-fifths of {{ participants }}
> participating)

where N = `(participants * 2 / 5)` rounded up, the same value computed today.
Placed directly under the participants strip (above the slate), centred, so it
reads as a standing fact about this election rather than a rule citation.

## Part 3: Admin interface wording

- [step_welcome.html](../../../templates/admin/step_welcome.html): block title
  and `step_tag` "Welcome & Rules" -> "Welcome & Slate"; `step_heading` "Walk
  the projector through Welcome and Election Rules" -> "Walk the projector
  through Welcome and the Slate"; intro prose "Welcome and Election Rules" ->
  "Welcome and the Slate"; `proj_phases` label `(2, "Election Rules")` ->
  `(2, "Slate")`; button "Next: Election Rules" -> "Next: Slate". The route and
  template filename (`admin_step_welcome` / `step_welcome.html`) stay.
- [step_attendance.html](../../../templates/admin/step_attendance.html): the
  two "Next: Welcome & Rules" labels -> "Next: Welcome & Slate".

## Untouched

- Election logic (Article 6 thresholds deciding elected) in app.py results.
- Article 13 slate-override confirm (step_offices).
- Article 4 attendance requirement (phase-1 Welcome screen and attendance step).
- Article 6/8 final-results appointment wording (final.html).

## Testing

- Update the phase-2 display test: `/display` at `display_phase == 2` renders
  `slate.html` with status 200, contains the slate (an office heading like
  "For Elder") and the threshold line ("To be elected"), and does NOT contain
  the removed article prose ("Subsequent Rounds", "Objections of a formal
  nature") or an "Election Rules" heading.
- Keep a guard that the scaler constants survive the rename (the tuned 0.96 /
  2.4 values, now under `autoSizeSlate`).
- Add an admin-wording guard: the welcome step renders "Welcome & Slate" and
  not "Election Rules".
- Run the full suite; check `test_wizard_sidebar.py` and any other test that
  references the rules phase still passes (update wording assertions if they
  assert the old "Rules" label).
- Manual: project phase 2, confirm the slate fills the screen with the
  threshold line and no article text, and that the admin step reads "Slate".
