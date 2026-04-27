# Admin Manage page — phase-driven flow redesign

Date: 2026-04-21

## Goal

Walk a casual chairman through every step of an election event in
order, from pre-event preparation to declaring the final result, on a
single page. Each step's primary action should be obvious; less-relevant
steps should fold out of the way without disappearing entirely.

## Non-goals

- No new database columns or migrations.
- No change to the underlying voting routes (open/close, paper-tally
  entry, next-round, finalise) — only how they are surfaced.
- No change to the projector/phone display templates beyond what already
  ships.

## Layout

```
[Stepper: 1 — 2 — 3 — 4 — 5]   (current highlighted)

[Phase 1 card]
[Phase 2 card]
[Phase 3 card]
[Phase 4 card]
[Phase 5 card]

▶ Advanced Actions  (collapsed details)
```

The stepper is a compact horizontal strip showing all five phases with
the current one highlighted. Each step is clickable and scrolls to /
expands the matching card.

## Card states

Each of the five phase cards has one of three visual states:

| State    | Visual                                              | Default open?           |
| -------- | --------------------------------------------------- | ----------------------- |
| done     | green tick + one-line summary                       | collapsed (click toggles)|
| active   | full content + primary CTA highlighted              | expanded                |
| pending  | faded title + "Not yet" hint                        | collapsed (click toggles)|

Exactly one card is `active` at any time. The active card's primary
action is the one the chairman is most likely to want next.

## State detection (deterministic)

Inputs (all already available in the route):
- `election.display_phase` (1, 2, 3, or 4)
- `election.voting_open` (0 / 1)
- `election.current_round`
- `election.show_results` (0 / 1)
- `total_ballots_this_round` (digital + paper + postal-this-round)
- `election_complete` (computed: every office has met `original_vacancies`)

Algorithm — top-down, first match wins:

1. `election_complete` OR `display_phase == 4` → **active = 5** (Final)
2. `voting_open == 1` → **active = 3** (Round N voting)
3. `voting_open == 0` AND (`total_ballots_this_round > 0` OR
   `show_results == 1`) → **active = 4** (Round N counting & decide)
4. `display_phase` in (1, 2) → **active = 2** (Opening)
5. otherwise → **active = 1** (Before the meeting)

Per-phase done logic (for the tick + collapsed summary):

- Phase 1 done if `total_codes > 0` (codes exist for the election).
- Phase 2 done if voting has ever been opened (i.e. `current_round > 1`
  OR `display_phase >= 3` OR `total_ballots > 0`).
- Phase 3 done if voting is currently closed AND the current round has
  votes (i.e. we're past it for this round).
- Phase 4 done if a later round has started (`current_round > N`) OR
  the election is complete.
- Phase 5 done is N/A — phase 5 is terminal.

## Phase contents

### Phase 1 — Before the meeting

Active when no voting has started. Done as soon as codes exist (auto-
generated on first visit to the codes page).

Content:
- Code count (e.g. "240 codes generated, 0 used").
- Postal votes count + button to enter / adjust them.
- Buttons: "Open Printer Pack ZIP", "More formats" disclosure with
  individual PDFs.
- One-line "What you should do at this point" hint.

Primary CTA: **Print materials** (links to Printer Pack).

### Phase 2 — Opening the meeting

Active when `display_phase` is 1 or 2 and voting hasn't opened.

Content:
- Mini stepper for the projector display: Welcome → Election Rules →
  Voting (with current highlighted, click to advance).
- "Brothers Present" input + Save button.
- "Open Display" link (`target=_blank`) to the projector page.
- One-line context hint.

Primary CTA: **Next: Open Voting →** (advances projector to phase 3
and opens voting in one click).

### Phase 3 — Round N — Voting in progress

Active when `voting_open == 1`.

Content:
- Big live counters: ballots received, brothers participating, still
  to vote, percentage. Updates via JS to /api/display-data.
- Per-office live tally with Article 6a/6b ticks (already implemented).
- Ballot-anomaly banner when total_ballots > participants.
- "Hide / Show results on projector" toggle.
- "Vote Corrections" disclosure with rollback button (already
  implemented).

Primary CTA: **Close Voting** (red).

### Phase 4 — Round N — Counting & decide

Active when voting closed but the current round still has unresolved
state (votes cast or results visible) and the election isn't complete.

Content (in order):
- Voting method breakdown table (digital / paper / postal totals,
  participation rate with anomaly warning).
- Paper ballot count input + "Enter Paper Votes" button (existing
  paper tally form).
- Per-office results table with elected badges.
- Article 7 explanation paragraph.
- Decision panel:
  - **Start Round N+1**: form with carry-forward checkboxes for
    candidates who weren't elected, "Start Round N+1" button.
  - **Finalise election**: button that switches `display_phase` to 4
    and shows the Phase 5 card.

Primary CTA: depends on chairman's path:
- If paper ballots not yet entered: **Enter Paper Votes**.
- If paper entered but results hidden: **Show Results on Projector**.
- If results visible and runoff needed: **Start Round N+1**.
- If results visible and election complete: handled by phase 5.

### Phase 5 — Final results

Active when `election_complete` is true OR the chairman explicitly
clicked "Show Final Results" (display_phase=4).

Content:
- Elected brothers per office, alphabetical by surname (matches the
  final.html template).
- "Show Final Results on projector" button (sets display_phase=4).
- "Download Election Minutes (DOCX)" button.

Primary CTA: **Show Final Results** (or, if already on phase 4,
**Download Minutes**).

## Stays at the bottom (unchanged)

- **Advanced Actions** disclosure: reset (soft reset, hard reset),
  load demo, etc. Closed by default.

The previous "Reports & Exports" card disappears — minutes moves into
phase 5; no other reports currently exist.

## File scope

- `voting-app/templates/admin/manage.html` — full rewrite of the body
  inside the existing `<div class="container-wide">`. The page header,
  navigation, and CSS dependencies stay.
- `voting-app/app.py` — `admin_election_manage` adds three new context
  variables: `active_phase` (int 1..5), `phase_done` (dict 1..5 -> bool),
  `phase_summary` (dict 1..5 -> short string for collapsed view). No
  route handler changes.

## Out of scope for this change

- Changing how next-round currently resets `display_phase` to 1
  (probably a follow-up: it should land on phase 3 closed so the
  chairman can immediately reopen voting).
- Splitting phase 4 into 4a (count) and 4b (decide). Kept together as
  one card per the design discussion.
