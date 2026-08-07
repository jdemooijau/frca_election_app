# Design: Support 10 Elder + 8 Deacon Candidates (Ballots, Screens, Demo DB)

Date: 2026-08-07
Status: Approved (chairman/developer: Jan de Mooij)

## Goal

The app must handle a slate of up to 10 elder candidates and up to 8 deacon
candidates cleanly on every surface: paper ballot PDFs, the projector
display screens, and the demo database. The demo election seeds this
maximum so every rehearsal exercises the worst case. No new hard limit is
introduced anywhere; 10/8 is a verification target, not an enforced cap.

## What was verified before this design (evidence)

A throwaway server (scratch db, monkeypatched `DB_PATH`, port 5001) was
seeded with 10 elder + 8 deacon candidates and screenshotted with
Playwright at 1920x1080 and 1280x720:

| Surface | 1080p | 720p | Verdict |
|---|---|---|---|
| Projector, voting open live tally | fits | not tested (rotation + two-col scale) | OK |
| Projector, closed round + results | fits (tight) | **Total row clips off bottom** | FIX |
| Projector, round-2 instructions with Option B valid names (6+4 runoff) | fits | not tested | OK |
| Candidates slate (phase 2) | **overflows, last rows clipped** | **only 3 of 10 names visible** | FIX |
| Paper ballot PDF, 6-per-A4 grid | clean, readable | n/a | OK, no change |
| Dual-sided ballot card front | clean, readable | n/a | OK, no change |

The paper ballot generators already scale dynamically
(`generate_paper_ballot_pdf`, `_draw_ballot_card`) and need no code change.
The admin UI has no cap on candidates per office; real elections can
already enter 10/8.

## Change 1: Demo data at 10 elder / 8 deacon, vacancies 5 / 4

Three places currently hardcode the 6+4 shape:

1. `scripts/seed_demo.py` (`_create_demo_election`):
   - Generate 18 names (`generate_demo_names(count=18, ...)`).
   - Elder office: vacancies 5, max_selections 5, candidates `names[:10]`.
   - Deacon office: vacancies 4, max_selections 4, candidates `names[10:18]`.
   - Update comments and the summary print line.
2. `app.py` (`admin_load_sample_offices`): identical split and counts
   (including `original_vacancies`), update the flash message.
3. `demo_names.py`:
   - Extend `FALLBACK_ELDER_CANDIDATES` to 10 and
     `FALLBACK_DEACON_CANDIDATES` to 8. Convention unchanged:
     Australian-sounding first names (the existing `FIRST_NAMES` style)
     paired with INVENTED Dutch-ish surnames (mashups like "Brouwerhof",
     never real surnames), so fallback names cannot collide with real
     families.
   - Pool mode needs no change: ~60 real Dutch surnames minus member
     surnames still comfortably yields 18 unique names. Pool mode pairs
     each surname with a random Australian first name; that convention is
     already correct.

## Change 2: Candidates slate screen fits (Option B, chosen)

Defect: `templates/display/slate.html` auto-scaler clamps
`scale = Math.max(1, scale)`; the slate can grow but never shrink, so a
10-name office overflows the viewport and the projector shows clipped
names (nobody scrolls a projector).

Fix, two parts:

1. **Two-column name lists**: when an office has 6 or more candidates,
   flow its `.candidate-list` into two columns (CSS `column-count: 2`,
   `break-inside: avoid` on `li`), mirroring the projector's existing
   two-col treatment. Ten names become 5 rows; text stays large.
2. **Shrink floor as safety net**: change the clamp floor from 1 to 0.6 so
   pathological cases (very long names, tiny beamer resolution) shrink to
   fit instead of clipping. The 2.4 growth cap stays.

The page keeps its scroll-instead-of-clip body override as a last resort.

## Change 3: Projector closed-results screen fits at 720p

Defect: with 10 candidates plus Blank votes / Spoilt / Total rows, the
closed-round results view clips the bottom rows at 1280x720 even though
`autoSizeOffices()` ran. Suspected causes (confirm during implementation):
the 0.6 scale floor is too high once the fixed-size summary strip
(64px numbers, 48px progress bar) and runoff banner take their share, or
`resultsContainer.clientHeight` measures more than the visible area.

Fix: diagnose the actual limiting factor, then make the office content
always fit. Expected shape of the fix: lower the primary floor to about
0.45, and let the wrap-aware correction pass shrink below the floor
rather than clip. Do not scale down the summary strip (chairman wants the
ballots-received numbers readable); only the office lists scale.

## Change 4: Verification and tests

- `scripts/test_ballot_layouts.py`: add a `08_2offices_10plus8` scenario
  (10 elder + 8 deacon, worst-case long name included) so the PDF range
  matches the new maximum.
- Grep tests for baked-in 6+4 demo assumptions (`test_app.py`,
  `test_mass_election.py`, `test_display_fill.py`,
  `test_rules_compliance.py`) and update any that assert the old shape.
- Acceptance check: re-run the scratch screenshot harness (real
  `generate_demo_names()` output this time) at 1920x1080 AND 1280x720
  across all five projector states; every name row, ELECTED badge, and
  the Total row must be fully visible. Ballot PDFs re-rendered at 10+8
  and eyeballed.

## Out of scope

- No enforced maximum candidate count.
- No changes to counter sheet, results PDF, voter phone ballot (all grow
  or paginate naturally).
- No change to vote-counting or runoff rules.
