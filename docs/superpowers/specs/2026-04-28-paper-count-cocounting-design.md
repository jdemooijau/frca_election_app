# Paper Ballot Co-Counting Helper

**Date:** 2026-04-28
**Status:** Draft

## Problem

When voting closes, the chairman reads each paper ballot aloud and two official counters tally the votes on paper. If one counter mistracks, the totals diverge and the read-out has to be repeated. There's no independent cross-check, and the chairman is the only fast path to a result.

## Solution

A self-service co-counting helper for volunteers in the room. After a digital voter confirms their vote, an opt-in **"Assist with Paper Counting"** button takes them to a tap-to-tally grid on their phone. As the chairman reads ballots aloud, helpers tap surnames; their counts stream to the server. The admin watches a live dashboard that highlights consensus across helpers. When ≥3 helpers agree, the admin sees an unambiguous green total per candidate and can persist the result with one button.

The feature is **opt-in per election**, configured during election setup. When disabled, none of the new UI appears anywhere. When enabled, the helper button surfaces automatically once voting closes for a round.

The "persist" step writes only to new side-tables, leaving the existing paper-vote flow untouched. Future integration (a "prefill from latest count session" button on `paper_votes.html`) is purely additive and out of scope here.

## Design

### Per-election opt-in

New column on `elections`:

```sql
ALTER TABLE elections ADD COLUMN paper_count_enabled INTEGER NOT NULL DEFAULT 0;
```

A checkbox is added to `templates/admin/election_setup.html` near the existing election-level options:

> **Enable paper count helper**
> Volunteers can opt in to co-count paper ballots on their phones during the chairman's read-out.

All paper-count code paths (helper button, dashboard link, session creation, all routes) are gated on `elections.paper_count_enabled = 1`. When 0, the feature is invisible and inert.

### Lifecycle (no explicit start step)

1. Voting closes for a round (existing flow, no change).
2. If `paper_count_enabled = 1`, a `count_sessions` row is auto-created on first read by either the admin dashboard route or the helper-join route, keyed by `(election_id, round_no)`. Lazy creation avoids needing a hook on the close-voting action.
3. Voters still on `voter/confirmation.html` see an **"Assist with Paper Counting"** button (visible only when paper-count is enabled, voting is closed for the current round, and the session is not yet `persisted`).
4. Tapping the button calls `POST /count/join`. The server reads the burned `used_code` from the voter's session, finds-or-creates the `count_sessions` row, finds-or-creates a `count_session_helpers` row keyed by `(session_id, voter_code)`, and redirects to `/count/<session_id>`.
5. Helpers tap surname rows to +1 and the small red `−1` pill to -1. Each tap POSTs immediately and persists.
6. Admin opens the dashboard at `/admin/election/<id>/count/<round>` from a "Paper Count Dashboard" link on `manage.html` (link only appears when feature enabled and voting closed for current round).
7. Dashboard polls `GET /admin/election/<id>/count/<round>/state` every 1s, re-rendering per-candidate rows.
8. Admin presses **"Persist Paper Ballot Count"** → confirmation modal lists the agreed totals → on confirm, `count_sessions.persisted_at` and `persisted_by_admin_id` are set, helpers' devices transition to the 'Thanks' screen on their next heartbeat.

### Counter identity

The helper's identity is the burned voter code from their session. Display name on both helper page and admin dashboard is the **last 6 characters** of the code, e.g. `Counter ABCDEF`. Helpers are anonymous to each other and to the admin in the strict identity sense, but unique enough to call out individually if needed ("ABCDEF, can you check Smith?").

### Helper UI (`templates/voter/count_helper.html`)

Constraints: single landscape phone screen, no scrolling, no pagination, surname-only buttons.

**Helpers do not see their own running counts.** This is deliberate - a helper who sees their tally may second-guess and re-tap; we want them to be a pure ear-and-tap worker. Cross-correlation is the admin's job.

Layout:

```
Counter ABCDEF                                                                    [Done]
─────────────────────────────────────────────────────────────────────────────────────────
ELDERS                                          DEACONS
┌─────────────────────────┐                    ┌─────────────────────────┐
│ Smith               −1  │                    │ White               −1  │
│ Jones               −1  │                    │ Black               −1  │
│ Brown               −1  │                    │ Green               −1  │
│ ...                     │                    │ ...                     │
└─────────────────────────┘                    └─────────────────────────┘
```

- Header: small font, just `Counter ABCDEF`. No round number, no title.
- Each candidate row spans full column width. The whole row is the +1 hit zone; on the right is a small **`−1`** pill (literal text `−1`, not a circle-minus icon) which decrements the helper's count for that candidate by exactly one. The `−1` text is deliberate - a circled-minus or trash glyph could read as "delete all of my Smith taps", which is not what it does. Tap handler uses `event.stopPropagation()` so a `−1` tap doesn't also fire +1.
- **No count number is shown** anywhere on the row. Tap feedback is visual only: a brief 150ms highlight pulse on the row to confirm the tap registered. If the POST fails, a small red dot appears in the row corner.
- The `−1` pill is for immediate self-correction (helper realises they tapped the wrong surname and backs it out before moving on) - the helper doesn't need to see the count to know "I just made a mistake". Each tap on `−1` is exactly one decrement, never a wipe.
- Two columns in landscape, one column in portrait if needed (but 14-20 buttons in landscape is the design target).
- Bottom-right "Done" toggle: helper marks themselves as finished. **Toggling to Done immediately replaces the page with the 'Thanks' screen** (see below). The helper can no longer tap, but their counts are kept and flow into consensus.

#### End-state screens

The helper page transitions into one of two terminal screens:

- **'Thanks' screen** - shown when:
  - The helper marks themselves Done (self-triggered), OR
  - The admin persists the session (server-pushed via polling).
  - Content: large checkmark, `Thanks for helping count.` and a link back to `voter_enter_code` for the next round (if applicable).
- **'Session cancelled' screen** - shown when:
  - The admin cancels the session.
  - Content: `Counting was cancelled.` plus the same back link.

Once a helper is in either terminal screen, they cannot rejoin the same session even if they navigate back (the helper row's `marked_done_at` or session status guards `/count/<session_id>/tap`, which returns 403).

### Admin dashboard (`templates/admin/count.html`)

Path: `/admin/election/<id>/count/<round_no>`

```
Paper Count - Round 1                                                  [Cancel session]
N helpers joined · M done

[ banner ]   ✓ ALL CANDIDATES AGREE (3 of 3 helpers, all marked done)
                                                                      [Persist Paper Ballot Count]
─────────────────────────────────────────────────────────────────────────────────────
ELDERS
                          ABCDEF   GHIJKL   MNOPQR    Consensus
  Smith                       7        7        7    ✓ 7
  Jones                       6        6        6    ✓ 6
  Brown                       5        5        4    ✗ Mismatch (MNOPQR: 4)
  ...

DEACONS
  ...
```

- Banner colour (computed over **active, non-disregarded** helpers):
  - Green: every candidate has consensus AND every active helper has marked done AND ≥3 active helpers.
  - Amber: every candidate has consensus but not all active helpers are done, OR fewer than 3 active helpers.
  - Red: at least one candidate has a mismatch.
  - Grey: 0 active helpers (only idle and/or disregarded helpers present).
- "Persist Paper Ballot Count" button:
  - Always visible.
  - Disabled (greyed) only if 0 helpers have any tallies recorded.
  - On click: confirmation modal `Persist these totals: Smith=7, Jones=6, Brown=5, White=4, ...? This cannot be undone.`
  - Persist value resolution per candidate:
    - ≥3 reporting helpers all agree → consensus value, source `consensus`.
    - ≥3 reporting helpers, mismatch → modal shows `Mismatch on Brown - pick a value:` with a small input pre-filled with the most-common value. Admin types the agreed value and confirms. Source `admin_override`.
    - 1 or 2 reporting helpers → modal shows `Only N helper(s) reporting on Brown - pick a value:` with the same input control, pre-filled with the highest count. Admin confirms or edits. Source `admin_override`.
    - 0 reporting helpers for a candidate (everyone idle on that row) → modal pre-fills 0; admin confirms or edits. Source `admin_override`.
- "Cancel session" button: confirmation modal, then sets `count_sessions.status = 'cancelled'`. Helper devices show "Session cancelled". No totals written.

### Consensus logic (advisory)

Per candidate, given the current set of helpers' counts:

| Active, non-disregarded helpers reporting | Counts | Consensus state |
|---|---|---|
| 0 | - | Hidden / no row data |
| 1 or 2 | any | Show counts, no consensus claim, "—" in consensus column |
| ≥3 | all equal | ✓ green, value shown |
| ≥3 | not all equal | ✗ red, mismatch shown with offender's short_id(s) |

A helper "reports" once they have made any tap (any +1 or -1, even if final count is 0). Helpers fall into one of three states for consensus purposes:

- **Idle** - joined but never tapped. Excluded from consensus and from the "all done" check. An idle helper who walked away never blocks a green banner.
- **Active** - tapping along, included in consensus.
- **Disregarded** - explicitly excluded by the admin (see below). Their column stays visible on the dashboard, greyed out, but their counts no longer feed consensus or the "all done" check.

#### Disregarding an out-of-sync helper

A counter who has lost track of the read-out (off by miles, double-tapping, half-asleep) would otherwise prevent consensus across the room. The admin can excise them with one click:

- Each helper column on the admin dashboard has a small **"Disregard"** button in its header. Clicking it sets a `disregarded_at` timestamp on the helper row. Consensus immediately recalculates excluding that helper.
- A disregarded helper's column is greyed out but still visible (so the admin can see why they were excluded). A small **"Restore"** button replaces "Disregard" - admin can revert the decision.
- The dashboard also auto-**flags** helpers who appear out of sync, so the admin doesn't have to spot it manually:
  - **Flag rule:** when ≥3 active helpers exist, any helper whose count differs from the modal value on **>30% of candidates that have a mode** is marked with a small amber `⚠ out of sync` chip in their column header. This is a visual warning only - no automatic exclusion. Admin still has to click Disregard.
- Auto-disregard is **deliberately not** implemented. If three helpers are wrong and one is right, auto-exclusion would discard the truth. The admin holds the final call.

The auto-flag and disregard mechanics are why the consensus rule reads "≥3 **active, non-disregarded** helpers all equal" rather than just "≥3 helpers all equal".

Top banner state derives from the per-candidate states plus the "marked done" count over **active, non-disregarded** helpers only.

### Data model

Four new tables. None of `elections`, `votes`, `paper_votes`, `codes`, `offices`, `candidates` are modified beyond the one new column on `elections`.

```sql
CREATE TABLE count_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id INTEGER NOT NULL,
    round_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'persisted' | 'cancelled'
    started_at TEXT NOT NULL,
    persisted_at TEXT,
    persisted_by_admin_id INTEGER,
    cancelled_at TEXT,
    UNIQUE(election_id, round_no),
    FOREIGN KEY (election_id) REFERENCES elections(id)
);

CREATE TABLE count_session_helpers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    voter_code TEXT NOT NULL,
    short_id TEXT NOT NULL,            -- last 6 chars of voter_code, uppercase
    joined_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    marked_done_at TEXT,
    disregarded_at TEXT,               -- non-NULL = admin excluded from consensus
    UNIQUE(session_id, voter_code),
    FOREIGN KEY (session_id) REFERENCES count_sessions(id)
);

CREATE TABLE count_session_tallies (
    session_id INTEGER NOT NULL,
    helper_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, helper_id, candidate_id),
    FOREIGN KEY (session_id) REFERENCES count_sessions(id),
    FOREIGN KEY (helper_id) REFERENCES count_session_helpers(id),
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
);
```

Persisted totals are derivable from `count_session_tallies` filtered to the per-candidate consensus value at persist time, plus an optional admin-typed override for mismatched candidates. The admin's chosen final value per candidate is captured in a small `count_session_results` table:

```sql
CREATE TABLE count_session_results (
    session_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    final_count INTEGER NOT NULL,
    source TEXT NOT NULL,              -- 'consensus' | 'admin_override'
    PRIMARY KEY (session_id, candidate_id),
    FOREIGN KEY (session_id) REFERENCES count_sessions(id),
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
);
```

Migration in `_migrate_db_on()`: add the `paper_count_enabled` column on `elections`, then `CREATE TABLE IF NOT EXISTS` for all four new tables.

### Routes

All new routes; no existing routes modified except the small additions noted in "Files changed".

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/election/<id>/count/<round>` | Admin dashboard (HTML) |
| GET | `/admin/election/<id>/count/<round>/state` | JSON for polling: helpers, per-candidate counts, consensus state, banner state |
| POST | `/admin/election/<id>/count/<round>/persist` | Body: `{ candidate_id: final_count, ... }` for any admin overrides. Writes `count_session_results`, sets `status='persisted'`. |
| POST | `/admin/election/<id>/count/<round>/cancel` | Sets `status='cancelled'`. |
| POST | `/admin/election/<id>/count/<round>/disregard` | Body: `{ helper_id, disregard: true\|false }`. Sets/clears `disregarded_at` on the helper row. |
| POST | `/count/join` | Reads burned voter code from session, finds-or-creates session and helper rows, redirects to `/count/<session_id>`. |
| GET | `/count/<session_id>` | Helper grid (HTML). 404 if helper row not found in session for this voter code. |
| POST | `/count/<session_id>/tap` | Body: `{ candidate_id, delta }` (delta = +1 or -1). Updates the helper's tally. Returns 200 OK on success (no count in response - helpers don't see counts). Server clamps to ≥0. Returns 403 if helper is already marked done or session is not `active`. |
| POST | `/count/<session_id>/done` | Sets `marked_done_at`. One-way: a helper cannot un-mark themselves Done. Returns 200 OK; client transitions to the 'Thanks' screen. |
| GET | `/count/<session_id>/heartbeat` | Updates `last_seen_at`. Helper page calls every 5s. Response: `{ session_status, helper_done }` so the helper page can transition to the right end-state screen if the session is persisted/cancelled. |

All admin routes use `@admin_required`. All `/count/...` routes require `session.get('used_code')` (the burned voter code) and verify it matches a helper row in the requested session.

### UI integration points (existing files)

1. **`templates/admin/election_setup.html`** - add the **Enable paper count helper** checkbox bound to `elections.paper_count_enabled`. POST handler in `admin_election_setup` updates the column.
2. **`templates/admin/manage.html`** - when `paper_count_enabled = 1` and current round's voting is closed, show a **"Paper Count Dashboard"** link in the post-close panel (alongside existing "Close Voting" / "Next Round" controls). Link is `url_for('admin_count_dashboard', election_id=..., round_no=...)`.
3. **`templates/voter/confirmation.html`** - when `paper_count_enabled = 1` and the current round's voting is closed and no session for that round is `persisted` or `cancelled`, show a small button:
   ```html
   <form method="POST" action="{{ url_for('count_join') }}">
     <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
     <button class="btn btn-outline btn-small">Assist with Paper Counting</button>
   </form>
   ```
   Visible only when feature enabled, current round's voting is closed, and session is not `persisted` or `cancelled`.

### Audit log events

Reuse existing `audit_log` infrastructure:

- `paper_count_helper_joined` - payload: helper short_id
- `paper_count_helper_disregarded` - payload: helper short_id, set or cleared
- `paper_count_persisted` - payload: per-candidate totals + which were `admin_override`, plus list of disregarded helpers
- `paper_count_cancelled` - payload: helper count at cancel time

Helper taps and "done" toggles do **not** generate audit log entries (would be too chatty).

### Polling and concurrency

- Helper page POSTs each tap immediately. The server applies the increment atomically and returns 200 OK. The helper UI shows only a brief tap-flash; no count is displayed, so there's nothing for the helper to "verify" against the response. If the POST fails, a small red dot appears in the row corner and the next successful tap clears it.
- Helper heartbeat every 5s pings `/count/<session_id>/heartbeat` to update `last_seen_at` AND to detect terminal state. The heartbeat response includes `{ session_status, helper_done }` - if the session has been persisted/cancelled or the helper has been marked done elsewhere, the helper page transitions to the appropriate end-state screen on the next heartbeat.
- Admin dashboard treats `last_seen_at > 30s ago` as "stale" (greyed-out column with a small `(stale)` tag).
- Admin polls every 1s. Polling is paused when the persist confirmation modal is open (so the totals shown in the modal don't shift mid-confirmation).
- Server-side increments are atomic (`UPDATE count_session_tallies SET count = count + ? ...`). Two helpers tapping at the same instant on different rows → no contention. A single helper double-tapping is idempotent at the row level (each tap is one increment).

### Soft-reset, hard-reset, advance-round behaviour

- **`admin_soft_reset`** (round redo): if a count session exists for the current round, set its `status='cancelled'` and notify helpers via the existing reset flow. A new session can be created when voting closes again.
- **`admin_hard_reset`**: cancel all count sessions for the election. This happens implicitly because hard-reset already wipes most state - extend it to also delete `count_sessions`, `count_session_helpers`, `count_session_tallies`, `count_session_results` rows for the election.
- **`admin_next_round`**: previous round's session is left in whatever state it ended in (typically `persisted`). It becomes read-only - the dashboard route still works for audit, but join/tap/done/persist all reject with `400` if status is not `active`.

### What is explicitly out of scope

- No prefill of `paper_votes.html` from the persisted totals. Future integration is documented but not built.
- No tally per ballot (counters keep continuous running totals only - decided in brainstorm Q1).
- No real-time push (websockets/SSE). Polling is sufficient for ≤10 helpers and a single admin dashboard.
- No identity verification for helpers beyond holding a burned code (any voter who voted can help; non-voters cannot).
- No counter-of-counters (no meta-helpers tracking the helpers).

## Files changed

1. **`app.py`** - eight new route handlers, helper functions for consensus calculation, lazy session creation, migration of new column + tables.
2. **`templates/admin/election_setup.html`** - new checkbox.
3. **`templates/admin/manage.html`** - new "Paper Count Dashboard" link gated on feature flag and round state.
4. **`templates/admin/count.html`** - NEW dashboard with polling JS.
5. **`templates/voter/confirmation.html`** - new "Assist with Paper Counting" button.
6. **`templates/voter/count_helper.html`** - NEW helper grid with tap JS and heartbeat.
7. **`static/css/style.css`** - count UI styles (compact button rows, two-column landscape grid, consensus badges).

## Manual test plan

1. Create election, enable "Paper count helper" in setup. Add 8 elder candidates + 6 deacon candidates. Generate codes, attendance, etc.
2. Cast 5 digital votes + put 8 paper ballots aside. Close voting.
3. From three different phones still on `confirmation.html`, tap "Assist with Paper Counting". Verify each lands on the helper grid showing all 14 candidates in two columns, no scroll in landscape, **no counts shown next to surnames**.
4. Verify each phone's header shows `Counter XXXXXX` (last 6 chars of that phone's burned code).
5. Open admin dashboard. Verify three helper columns appear, all zeros.
6. Tap candidates on each phone identically (e.g., all three tap "Smith" twice). Verify admin dashboard shows `2, 2, 2` and green ✓ consensus on Smith. Verify the helper screens show only a brief flash on each tap, no count.
7. Tap "Smith" once more on only one phone. Verify mismatch indicator appears with offender's short_id.
8. Use the `−1` pill on that phone to back out the extra tap. Verify consensus restored.
8a. On a fourth phone, tap candidates wildly out of sync (e.g., tap Smith 15 times while others tap 7). Verify the column header shows the amber `⚠ out of sync` chip after a few divergent taps.
8b. Click "Disregard" on that fourth helper's column. Verify consensus banner returns to green based on the other three. Verify the column is greyed out but visible. Click "Restore" - verify mismatch returns.
8c. Disregard the fourth helper again before persist. Verify `paper_count_persisted` audit payload includes the disregarded helper's short_id.
9. Mark one phone as "Done". Verify that phone immediately replaces with the 'Thanks' screen and can no longer tap (server should return 403 if the helper sends another tap). Verify its counts are still in the consensus on the dashboard.
9a. Mark the remaining two phones "Done". Verify all three are on the 'Thanks' screen and the dashboard banner is green.
10. Press "Persist Paper Ballot Count". Verify modal lists totals. Confirm. Verify `count_sessions.status='persisted'`, `count_session_results` populated.
11. Verify `paper_votes`, `votes`, `codes` tables are unchanged (compare row counts before/after).
12. Try to `POST /count/<sid>/tap` after persist - verify 400.
13. New election with `paper_count_enabled=0`: confirm the helper button does NOT appear on confirmation page, the dashboard link does NOT appear on manage page, and `/admin/election/<id>/count/1` returns 404.
14. Soft-reset mid-count: verify session goes to `cancelled`, helpers see "Session cancelled".
15. Hard-reset: verify all four count tables are cleared for that election.
16. Round 1 persisted, advance to round 2: verify a new session is created for round 2 when voting for that round closes; round 1's dashboard remains viewable but read-only.

## Future integration (NOT in this spec)

When ready, a small follow-up adds a "Prefill from latest count session" button to `paper_votes.html`. It reads `count_session_results` for the current round and pre-fills the form. This requires no schema changes and no changes to the routes built in this spec.
