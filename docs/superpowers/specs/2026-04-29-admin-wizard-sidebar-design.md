# Admin Wizard with Persistent Progress Sidebar

**Date:** 2026-04-29
**Status:** Draft

## Problem

The admin journey from "create election" through "download minutes" is currently spread across **five separate top-level pages** (Dashboard, Members, Election New, Election Setup, Codes) plus the five-phase Manage page. The admin has to know which page to be on for which task and which "Next" button leads where. Cross-page navigation is via three different mechanisms (top sub-nav tabs, inline "Next: ..." buttons, and Back links to Dashboard), with no single visual indicator of where the admin is in the overall journey or what is left to do.

The existing Manage page already structures election-day work as a 5-phase accordion. That part is broadly fine. The fragmentation is concentrated in the pre-meeting half and at the seams between the two halves.

A second, smaller behavioral problem: when the chairman clicks **Close Round N**, the projector currently auto-reveals vote tallies (`show_results = 1` is set in the same handler). This removes chairman control over the reveal moment.

## Solution

Wrap the entire per-election admin flow in a **persistent left-rail progress sidebar** with three groups (Setup / Round N / Finish). The right pane shows the current step's content. The dashboard (list of elections) stays as a separate top-level page; opening any election lands on its first incomplete step inside the sidebar shell.

The Close Round handler stops auto-revealing results. The projector tally only becomes visible when the admin explicitly clicks **Show Results on Projector**.

## Design

### Step list (12 items per single-round case)

```
SETUP (one-time per election)
  1. Election details        - name, date, max rounds
  2. Members                  - CSV upload, count, attendance register PDF
  3. Offices & Candidates     - per-office cards with vacancies, candidates
  4. Election settings        - paper-count helper, postal votes
  5. Codes & printing         - auto-generated codes, printer pack ZIP

ROUND N (per round, current round visible, prior rounds collapse)
  6. Attendance & postal      - Brothers Present, last-chance postal envelopes
  7. Welcome & Rules          - projector phase advance (Welcome -> Election Rules)
  8. Voting                   - open round, live ballot count, close round
  9. Count & tally            - paper ballots received, per-candidate paper votes
 10. Decide what's next       - Start Round N+1 (carry-forward) OR Show Final Results

FINISH
 11. Final results            - projector switch + Show Final Summary / Vote Details
 12. Minutes & archive        - download DOCX, archive note for `data/frca_election.db`
```

The Round group repeats. With `max_rounds = 2` and Round 1 closed, the sidebar shows the Round 1 group collapsed and the Round 2 group expanded.

### Layout

Two-column shell, applied to every per-election admin page:

```
+-----------------------------+----------------------------------------+
| sidebar (220px)             | main pane                              |
|                             |                                        |
|  Office Bearer Election     |  [Step label tag]                      |
|  20 Oct 2026 - R1 of 2      |  Step heading                          |
|  ----                       |                                        |
|  SETUP                      |  ...step content...                    |
|   [v] Election details      |                                        |
|   [v] Members (42)          |                                        |
|   [v] Offices & Candidates  |                                        |
|   [v] Election settings     |                                        |
|   [v] Codes & printing      |                                        |
|                             |                                        |
|  ROUND 1                    |                                        |
|   [.] Attendance & postal   |                                        |
|       Welcome & Rules       |                                        |
|       Voting                |                                        |
|       Count & tally         |                                        |
|       Decide what's next    |                                        |
|                             |                                        |
|  FINISH                     |                                        |
|       Final results         |                                        |
|       Minutes & archive     |                                        |
+-----------------------------+----------------------------------------+
```

Sidebar is fixed width (220 px) on screens >= 900 px. Below that, it collapses to a horizontal sticky stepper at the top showing only the active group; the admin can tap the group label to expand the full list as a drawer. The app is laptop-first, so the narrow case is a graceful fallback rather than a primary target.

The dashboard (`/admin`) is unchanged in concept (election list + advanced actions) but does not use the sidebar shell. Clicking Manage on a dashboard election routes to the sidebar shell at the election's first incomplete step.

### Step states

Every sidebar item has exactly one of three states:

- **Done** (green tick) - prerequisites met and the step's primary action has been completed at least once. Clickable; revisits the page.
- **Current** (filled navy with gold dot) - the step the admin is on right now, or the step the system would land them on by default if they followed the flow.
- **Locked** (grey, no pointer) - prerequisites not met. Not clickable.

Done steps are always re-visitable. Locked steps are never clickable. There is no "skip ahead" affordance other than completing prerequisites.

### State machine (which steps gate which)

Steps 1-5 are per-election (Done state survives across rounds). Steps 6-10 are **per-round**: they reset to Locked/Current when a new round begins, and Done means done **for the current round**. Steps 11-12 are terminal.

| Step                  | Prerequisite to be reachable                       | Marked Done when                                           |
|-----------------------|----------------------------------------------------|------------------------------------------------------------|
| 1 Election details    | -                                                  | row exists in `elections` for this id                      |
| 2 Members             | -                                                  | `members` row count > 0                                    |
| 3 Offices & Candidates| 1                                                  | at least one office with at least one candidate            |
| 4 Election settings   | 1                                                  | always (settings have safe defaults; visiting marks done)  |
| 5 Codes & printing    | 3                                                  | `codes` row count > 0 (auto-gen runs on first visit)       |
| 6 Attendance & postal | 5                                                  | `in_person_participants > 0` for the current round         |
| 7 Welcome & Rules     | 6                                                  | for the current round, `display_phase >= 2` has been reached OR voting has been opened |
| 8 Voting              | 7                                                  | the current round has been opened at least once (regardless of current `voting_open`)  |
| 9 Count & tally       | 8 closed                                           | per-candidate paper votes saved for the current round      |
| 10 Decide             | 8 closed                                           | a successor action taken (next round started OR finalised) |
| 11 Final results      | step 10 finalised (display_phase = 4 reached)      | terminal display state reached                             |
| 12 Minutes & archive  | 11                                                 | terminal step; user-controlled                             |

When the admin starts Round N+1 from step 10, steps 6-10 reset for the new round and the Round N group collapses to its summary line. Steps 1-5 stay Done.

Members (step 2) is independent of the election context (member directory is shared). It appears in every election's sidebar as Done if the directory is populated. Editing Members from inside the wizard goes to the existing `/admin/members` page rendered inside the sidebar shell.

The default landing step on shell entry is the lowest-numbered step that is not Done. If all are Done, land on the last Done step.

### Multi-round collapse

The Round group for the current round is always expanded. Prior rounds collapse to a single line:

```
ROUND 1
  Closed - 1 elected   [view]
```

Clicking **view** expands the Round 1 group inline (read-only: clicking a sub-step shows that round's data but disables write actions). Future rounds beyond the current one are not shown until the admin reaches "Decide" and starts Round N+1.

### Per-step content

Existing template content moves into the sidebar shell with no functional changes other than the sidebar wrapper and the splits noted below. The renumbering only affects how the chrome presents the work; the routes and form posts remain.

| Sidebar step              | Source template(s)                                 | Notes                                                       |
|---------------------------|----------------------------------------------------|-------------------------------------------------------------|
| 1 Election details        | `election_new.html` (create) + new edit view       | New: an edit form for an existing election (rename, max rounds). Today only create-new exists. |
| 2 Members                 | `members.html`                                     | Unchanged                                                   |
| 3 Offices & Candidates    | `election_setup.html` (offices section)            | Settings disclosure moves out (see step 4)                  |
| 4 Election settings       | `election_setup.html` (settings disclosure section)| Promoted out of disclosure                                  |
| 5 Codes & printing        | `codes.html` + Manage Phase 1 (printing/postal)    | Codes status + printer pack + early postal entry, all here  |
| 6 Attendance & postal     | Manage Phase 2 (steps 1 + 2)                       | Attendance count + last-chance postal                       |
| 7 Welcome & Rules         | Manage Phase 2 (step 3)                            | Projector phase advance only                                |
| 8 Voting                  | Manage Phase 3                                     | Open/Close round, live counts, projector reveal control     |
| 9 Count & tally           | Manage Phase 4 (counting section)                  | Paper ballot count + per-candidate entry                    |
| 10 Decide                 | Manage Phase 4 (decide section)                    | Carry-forward picker OR Show Final Results                  |
| 11 Final results          | Manage Phase 5                                     | Show Final Summary / Vote Details toggle                    |
| 12 Minutes & archive      | Manage Phase 5 (minutes button) + new archive note | Existing minutes button + a paragraph on copying the .db    |

The Round N tally table (currently rendered between Phase 3 and Phase 4 on Manage) appears on both step 8 (Voting, hidden if `show_results = 0`) and step 9 (Count & tally, always visible).

### Behavior change: Close Round no longer auto-reveals

In `admin_toggle_voting` ([app.py:1071-1075](voting-app/app.py#L1071)) the line `show_results = 1` on close is removed. Closing voting only sets `voting_open = 0`. The projector keeps showing the live ballot view with counts hidden until the admin clicks **Show Results on Projector** (step 8 or step 9), or advances the display phase to 4 for the final summary.

This applies symmetrically to step 9 (Count & tally): saving paper-vote totals does **not** flip `show_results`. Reveal stays explicit at all times.

### Routes

The shell renders at a single base route per step:

```
/admin                                     - dashboard (unchanged)
/admin/setup                               - first-time wizard (unchanged)
/admin/members                             - shared member directory (unchanged URL, new chrome)
/admin/election/<id>/step/details          - 1
/admin/election/<id>/step/offices          - 3
/admin/election/<id>/step/settings         - 4
/admin/election/<id>/step/codes            - 5  (absorbs current /codes route)
/admin/election/<id>/step/attendance       - 6
/admin/election/<id>/step/welcome          - 7
/admin/election/<id>/step/voting           - 8
/admin/election/<id>/step/count            - 9  (absorbs /paper-votes link target)
/admin/election/<id>/step/decide           - 10
/admin/election/<id>/step/final            - 11
/admin/election/<id>/step/minutes          - 12
```

Existing routes that handle form posts (`/admin/election/<id>/voting`, `/admin/election/<id>/set-participants`, `/admin/election/<id>/display-phase`, etc.) keep their URLs and continue to redirect back to the sidebar shell. The current `/admin/election/<id>/setup`, `/admin/election/<id>/codes`, `/admin/election/<id>/manage` URLs become permanent 302 redirects to their step equivalents (Manage redirects to the current default step).

Step 2 (Members) routes through the existing shared `/admin/members` page rendered inside the sidebar shell when entered from an election context. The shell knows which election to render the sidebar for via the referrer or a `?election_id=<id>` query param; absent both, the page renders without the sidebar (coming directly from the dashboard).

### Sidebar component

A single Jinja partial (`templates/admin/_sidebar.html`) renders the sidebar from a `sidebar_state` context dict the routes assemble. The dict has the shape:

```python
{
  "election": {"id": ..., "name": ..., "date": ..., "current_round": ..., "max_rounds": ...},
  "current_step": "voting",      # one of the slugs above
  "groups": [
    {"label": "Setup", "items": [
       {"slug": "details",  "label": "Election details",   "state": "done", "url": "..."},
       {"slug": "members",  "label": "Members (42)",       "state": "done", "url": "..."},
       ...
    ]},
    {"label": "Round 1", "collapsed": True, "summary": "Closed - 1 elected", "items": [...]},
    {"label": "Round 2", "items": [
       {"slug": "attendance", "label": "Attendance & postal", "state": "done", "url": "..."},
       {"slug": "voting",     "label": "Voting",              "state": "current", "url": "..."},
       ...
    ]},
    {"label": "Finish", "items": [...]},
  ],
}
```

A helper `compute_sidebar_state(election_id)` in `app.py` builds this dict from the database. Each route calls it once and passes the result into the template.

### Out of scope

- Restyling the dashboard (`/admin`) itself - kept as the existing per-election list with advanced actions.
- Restyling the first-time setup wizard (`/admin/setup`) - that flow is already linear and works.
- Voter-facing screens (`/`, `/displayphone`, `/display`) - this redesign is admin-only.
- Mobile-first layout - laptop is the primary target; the narrow-screen drawer is a graceful fallback only.
- Breaking the existing paper-count co-counting dashboard out of its current side route - it remains a "open in new tab" link from step 8/9.
- Auditing the per-step copy and tone - the spec moves existing content into the new shell; tone polish is a follow-up.

## Migration

No data model changes. Existing elections in `data/frca_election.db` continue to work unchanged. The new routes are additive; the old `/admin/election/<id>/manage` URL becomes a redirect, so any bookmarks or printed instructions that point at it still resolve.

The single behavioral change (Close Round no longer auto-reveals) is a one-line edit in `admin_toggle_voting`. No data migration. If a chairman has muscle memory expecting auto-reveal, the projector will show the closed-but-hidden state and they'll need one extra click to reveal.

The deprecated comment block in `admin_toggle_voting` is updated to describe the new contract.

## Testing

- Existing scenario tests under `voting-app/tests/` continue to pass against the renamed routes via the redirects.
- New test: closing voting does **not** set `show_results = 1`. Confirms the behavior change.
- New test: `compute_sidebar_state` returns the expected step states for each fixture (empty election, mid-setup, round-1-open, round-1-closed-mid-count, finalised).
- Manual UAT: walk a dry run of the existing `UAT_SCRIPT.md` through the new shell. Any step that loses content or breaks a form post is a regression.

## Open questions

- None at spec time. Step 2 (Members) appears in every election's sidebar even though the data is shared across elections; the spec assumes that's fine because it correctly reflects "members are imported, you can advance". Revisit if it confuses dry-run admins.
