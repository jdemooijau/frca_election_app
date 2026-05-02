# Paper Ballot QR Scanner and Phone Receipt

**Date:** 2026-05-02
**Status:** Draft

## Problem

Two related failure modes exist around the phone-vs-paper interaction.

**Failure A, voter panic.** A brother votes online and sees the "Vote Registered" page. Later he re-scans the QR on his code slip (curiosity, looking for live results, or because his wife is borrowing his phone) and sees "This code has already been used." He misreads this as "my code was wrong, my vote failed" and drops his paper ballot in the box as a fallback. His phone vote and his paper ballot now both count.

**Failure B, undetected double count.** Today the system computes `total_ballots = used_codes + paper_ballot_count + postal_voter_count` (`app.py:1714`) but does not enforce any reconciliation against attendance. The chairman is expected to notice. There is no automated way to find which paper ballot is the duplicate when the totals don't add up.

Both are integrity issues the existing design doesn't close. The existing co-counting helper, manual paper-count entry, and per-office spoilt counts do not address either.

## Solution

Two independent additions, deployed together but not coupled.

**A.** A persistent device-side receipt list, surfaced as a "?" badge in the header of every voter-facing page. It tells the brother (or anyone holding his phone) which codes have already been voted on this device. Reassures in the moment. Storage is `localStorage` only; the server-side change is limited to passing `election_id` and `election_name` into the templates that render the badge.

**B.** A chairman-facing QR-scanner page, accessible from the admin sidebar and surfaced via a non-modal banner on the count screen when reconciliation fails (`online + paper > attendance`). The scanner reads paper-ballot QRs in continuous video mode. When a QR matches a code already burned online, the system flags it as a duplicate, atomically decrements `paper_ballot_count`, and writes an audit-log entry. The physical ballot is set aside by the operator. Re-scan to confirm.

Reconciliation panel + chairman hint also surfaces the symmetric `<` case (more attendees than ballots), but takes no automated action; that case is normal abstention plus possibly some lost votes, and only the chairman can disambiguate by asking the room.

Both parts reuse existing infrastructure: A uses `localStorage`, B reuses `voter_audit` and the existing `paper_ballot_count` field. Zero schema changes.

## Design

### Part A: Phone receipt

#### Storage

`localStorage` key `frcdd_voted` holds a JSON array:

```json
[
  {"code": "KR4T7N", "election_id": 12, "election_name": "FRCDD 2026 Office Bearers", "used_at_iso": "2026-05-02T14:32:11+08:00"},
  {"code": "9MX2QP", "election_id": 12, "election_name": "FRCDD 2026 Office Bearers", "used_at_iso": "2026-05-02T14:34:48+08:00"}
]
```

The array is append-only from the client's perspective. Entries from other elections (different `election_id`) are filtered out at display time but not deleted, so the same device can carry receipts across multiple elections without collision.

#### Write point

`templates/voter/confirmation.html` already renders `used_code` and the page is reached only after `app.py:3080` burns the code. A small inline script appends `{code: used_code, election_id: <id>, election_name: <name>, used_at_iso: <ISO timestamp>}` to `frcdd_voted` if no entry with that `code` already exists (idempotent on reload).

The required values are already passed to the template (`used_code`); `election_id` and `election_name` need to be added to the template context where they are not already present. Timestamp is generated client-side via `new Date().toISOString()`; millisecond accuracy isn't required and avoids a server round trip.

#### Read / display

A new partial `templates/voter/_receipt_badge.html` is included in `templates/base.html`'s header block, adding a small "?" button at top-right. Visible on:

- `/` (welcome / waiting screens, only after at least one entry exists)
- `/v/<code>` (enter-code page)
- `/enter-code`
- `/ballot`
- `/vote-confirmation`

The badge is hidden when `frcdd_voted` is empty or contains no entries for the active election.

Tapping opens a modal panel:

```
Votes cast on this device

Code KR4T7N at 14:32
Code 9MX2QP at 14:34
Code Z7P3WK at 14:36

If you see your code here, your vote is registered. You do not need to cast a paper ballot.

[ Close ]
```

The active-election filter uses the `election_id` injected into the page (already present in `display-data` API responses; see `app.py:1841`). When the active election changes, old entries remain in storage but are filtered out of view.

No tap-to-reveal gate. The Reformed-context threat model is family-sharing, not strangers reading your phone, and gating it adds friction for the very brothers most likely to be reassured by it.

#### Privacy and dataloss

- `localStorage` is per-origin and per-device. A brother who clears site data, switches phones, or uses incognito loses the receipt. That is fine; the receipt is a reassurance, not a record of truth.
- The list shows codes in plain text. A code on its own does not identify the voter (codes are not linked to names in the codes table), and the matching is anonymous. A bystander seeing "Code KR4T7N" cannot tell whose code it is.

### Part B: Count-side QR scanner

#### Prerequisite: enlarge printed QR size

The current code-slip QR is 24 mm (`pdf_generators.py:165`, `qr_size = 24 * mm`). At that size, camera-based scanning works at 5-10 cm but is fussy: focus-hunting, narrow angle tolerance, and a single fold across the QR is enough to fail decoding. For count-time scan throughput on a phone camera, the QR needs to be larger.

Change `qr_size` to **32 mm** in the code-slip drawing path (`draw_code_slip` and the standalone variants in `pdf_generators.py`). At 32 mm the operator can hold the ballot at 15-25 cm without focus issues, fold tolerance roughly doubles per module, and the existing 32 mm Step 2 vertical budget (`pdf_generators.py:86`) accommodates the change without redesigning the slip.

Two affected layouts to verify:

- `generate_ballot_front_pdf` and `draw_code_slip` standalone use: enlarge directly. Plenty of slack in the single-card layout.
- `generate_dual_sided_ballots_pdf` (grid layout, `pdf_generators.py:1033`): the per-cell budget is tighter. Re-check the grid math; if cells overflow at 32 mm, fall back to 30 mm for that layout only or shrink an adjacent label by one font step.

`ERROR_CORRECT_H` (30% recovery) is retained. Do not drop it to gain module density.

This change affects only newly generated PDFs. Ballots already printed for an in-flight election keep their 24 mm QR; the scanner still reads them, just less forgivingly. Plan to regenerate ballots before next election.

#### New routes

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/elections/<id>/scan-ballots` | admin | Render scanner page |
| POST | `/admin/elections/<id>/scan-ballot-result` | admin (CSRF) | Process one scanned QR, return classification JSON |

The page is rendered for an active election only. If voting is still open (`elections.voting_open == 1`) or the election is already finalised (`display_phase == 4`), the scanner refuses to act and shows "Scanning is only available during the count phase."

#### Scanner page (`templates/admin/scan_ballots.html`)

Single-screen layout:

```
┌────────────────────────────────────────┐
│ Scan paper ballots                     │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │                                  │  │
│  │       [ camera viewfinder ]      │  │
│  │                                  │  │
│  └──────────────────────────────────┘  │
│                                        │
│  Scanned: 24                           │
│  Set aside: 2                          │
│                                        │
│  Last result: ✓ Paper-only (KR4T7N)    │
│                                        │
│  [ Done ]                              │
└────────────────────────────────────────┘
```

Camera initialised on page load via `navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}})`. Continuous frame loop:

- If `window.BarcodeDetector` is available with `formats: ['qr_code']`: use it.
- Else: dynamically import `jsQR` (vendored as a single file under `static/vendor/jsqr.min.js`) and run it on each captured frame.

On QR decode, parse the URL pattern `(?:^|/)v/([A-Z0-9]+)$` to extract the code. If the QR doesn't match the pattern, treat it as `unknown` immediately without a server round trip.

Dedup: maintain a JS `Map<code, lastSeenMs>`. On each detection, look up the code; if `(now - lastSeenMs) < 3000`, ignore it. Otherwise update `lastSeenMs` and process. Entries persist for the page session; re-presenting the same ballot after the 3-second window fires again, which is intentional and acts as a deliberate re-scan.

For each non-deduped detection, POST `{code: "KR4T7N"}` to the result endpoint and update the UI on the response.

UI feedback per response class:

| Class | Audio | Visual | UI behaviour |
|---|---|---|---|
| `match` | Long alert tone (~600 ms) | Red flash overlay (1 s) | Counter increments "Set aside". A non-blocking notice "Set aside KR4T7N" stays on screen until tapped or until the next `match` replaces it. Scanning continues underneath; the operator's job is to physically pull that ballot out of the pile. |
| `paper_only` | Short beep (~150 ms) | Green flash overlay (300 ms) | Counter increments "Scanned". No interaction required. |
| `unknown` | Two short beeps | Yellow flash overlay (1 s) | "Unknown QR. Set this ballot aside for the chairman or rescan." Counter does not increment. |

Audio is `Audio` element loading three short embedded data-URI WAVs. Visual flash is a position-fixed semi-transparent overlay.

#### Server endpoint

`POST /admin/elections/<id>/scan-ballot-result`

Body: `{"code": "KR4T7N"}`. Code is normalised via `.upper().strip()` before hashing.

Logic:

```
code_h = hash_code(code)
row = SELECT used FROM codes WHERE election_id = ? AND code_hash = ?
if row is None: return {result: "unknown"}
if row.used == 0: return {result: "paper_only"}
# row.used == 1 → match
BEGIN
  decrement = UPDATE round_counts
              SET paper_ballot_count = paper_ballot_count - 1
              WHERE election_id = ? AND round_number = ?
              AND paper_ballot_count > 0
  if decrement.rowcount == 0:
    return {result: "match", warning: "paper_ballot_count is already 0; nothing to decrement"}
  log_voter_audit(election_id, code, "paper_set_aside_at_count",
                  f"Paper ballot scanned during count, code already burned online; paper_ballot_count decremented")
COMMIT
return {result: "match"}
```

The decrement targets the **current round**, read from `elections.current_round`. Atomicity is enforced by SQLite's per-statement transactionality; the `paper_ballot_count > 0` guard prevents going negative if the chairman somehow scans more matches than the entered paper count.

The `warning` path (decrement-of-zero) tells the operator something is mathematically off without crashing the scan flow.

#### Audit log integration

A new `reason` value `paper_set_aside_at_count` is added (the `reason` column is already free-form `TEXT`, so no schema change needed). Wherever the codebase translates audit reasons into human-readable labels (locate by searching for `rejected_already_used`, which is where the existing reason-label cluster lives), add the new label "Paper ballot set aside (already voted online)." Update `templates/admin/voter_log.html` if it maps reasons inline.

#### Count screen integration

`templates/admin/step_count.html` (and any other surface where `paper_ballot_count` is set) gets a new reconciliation panel:

```
Reconciliation
──────────────────────────────
Attendees:        50
Online used:      28
Paper ballots:    18
Postal:            0
Gap:               4 (within attendance)
```

Computation:

```
gap = participants - (used_codes + paper_ballot_count + postal_voter_count)
```

Three display modes:

- `gap > 0`: "Gap: N (within attendance)" in neutral colour. If `gap > max(2, ceil(0.10 * participants))`, append a chairman hint: "Larger gap than expected. Before finalising, consider asking the room: 'Did anyone try to vote but isn't sure it worked?'"
- `gap == 0`: "Reconciled: every attendee voted." in green.
- `gap < 0`: red banner, non-modal: "Ballot count exceeds attendance by N. Scan paper ballots to find duplicates." with a link to `/admin/elections/<id>/scan-ballots`. The banner is dismissible but reappears on reload as long as the condition holds.

Audit panel also exposes a count of `voter_audit` rows where `reason LIKE 'rejected_%'` for the current round, labelled "Failed scan attempts: N". A high N + a large positive gap is the classic "scan-trouble" signal.

#### Sidebar link

`templates/admin/_sidebar.html` gains a "Scan paper ballots" link. Visible when the count phase is reachable: `voting_open == 0 AND display_phase IN (3)` for the round whose voting has just closed but not yet been finalised, mirroring the gating used by the existing paper-count helper (cross-check with the `2026-04-21-manage-page-phase-flow-design.md` mapping where `active = 4` is the counting state). When the election is finalised (`display_phase == 4`) or voting is still open, the link is hidden.

### Reuse of existing primitives

- `hash_code(code)` for QR-to-DB lookup.
- `log_voter_audit(...)` for set-aside entries.
- `get_round_counts` / `set_round_counts` for `paper_ballot_count` reads, but the decrement uses a direct SQL `UPDATE ... WHERE paper_ballot_count > 0` to keep it atomic.
- `current_round` from the `elections` row.
- Existing CSRF token handling on POST.
- Existing admin-auth decorator on all new admin routes.

## Non-goals

- **CV tickbox counting.** Separate exploration; standalone prompt already produced.
- **Hardware barcode scanner support as a feature.** A USB or Bluetooth scanner that emulates a keyboard will type the QR contents into a focused `<input>` if one is present, so the scanner page can support hardware out of the box without dedicated code (a hidden text input that listens for `Enter` and POSTs the same way). This is enabled, not designed.
- **Cross-round scanning.** The endpoint scopes everything to `current_round`. Scanning a ballot from a previous round during a new round is operator error and produces `paper_only` (because codes are un-burned between rounds, `app.py:2406`). Acceptable.
- **Forcing a re-vote when `gap < 0` or chairman-side automation.** The system surfaces, the chairman acts.
- **Replacing the existing co-counting flow.** The scanner runs before or alongside; co-counting is unchanged.
- **Scan-session resume / multi-operator coordination.** One operator, ~30 ballots, one session. Not worth the schema.
- **A receipt-list "share / send to chairman" feature.** The receipt is for the voter only.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `BarcodeDetector` unavailable on operator's phone | `jsQR` fallback bundled, tested on iOS Safari < 17 and old Android. |
| Camera focus fails under hall lighting | Operator can hold the ballot at varying distance; QR error correction H is forgiving. Browser-camera fallback is already an acknowledged ergonomic tradeoff vs. hardware scanner. |
| Operator scans the same ballot twice quickly | 3-second dedup window. |
| Two operators on two phones scanning concurrently | Server endpoint is atomic per request; double-scan of the same code by two operators would still only decrement once (the second hits `used` = 1 and would re-fire `match`, but the `paper_ballot_count > 0` guard prevents over-decrement). Audit log records both events, which is correct for transparency. |
| Voter clears site data, loses receipt, panics anyway | Receipt is best-effort. Reconciliation in B is the actual integrity safeguard. |
| Operator scans a malicious QR (someone printed a fake) | Hash lookup against this election's codes table; unknown QRs return `unknown`, not `match`. Fake QRs cannot inject set-aside actions. |
| `paper_ballot_count` is 0 when a match is scanned (chairman hasn't entered it yet) | Endpoint returns `match` with `warning` payload; UI shows the warning text but doesn't crash. Chairman fixes the entered count and continues. |

## Test approach

- **A**: Jest-style or Playwright assertions on the receipt panel: write to localStorage, render template, assert badge appears; assert filter by `election_id`; assert idempotent append on confirmation reload.
- **B server**: Pytest in `tests/test_paper_scan.py`:
  - `match` path decrements `paper_ballot_count` and writes audit row.
  - `paper_only` path is a no-op.
  - `unknown` path is a no-op.
  - Decrement is atomic and clamps at 0.
  - Endpoint requires admin auth and CSRF.
  - Endpoint is locked while voting is open and after finalisation.
- **B client**: manual UAT script entry: "scan a known-burned QR from the camera, confirm red flash + decrement"; "scan an unused QR, confirm green flash"; "scan a random QR string, confirm yellow flash"; "scan twice within 3s, confirm second is ignored."
- **Reconciliation panel**: pytest snapshot of the three display modes.
- **End-to-end sanity**: extend `tests/test_app.py` (or `test_mass_election.py`) with a "double vote" scenario: voter X votes online, then a paper ballot with X's QR is scanned, assert `paper_ballot_count` decrements and audit row exists.
- **PDF layout regression**: extend `tests/test_pdf_generators.py` with a snapshot or page-count assertion confirming the 32 mm QR change does not overflow any ballot or slip layout. Visual verification by generating a sample card and confirming the QR fits the Step 2 envelope.

## Open questions

None blocking. The "should the receipt show election name" question is resolved (yes, for cross-election clarity). The "what about hardware scanner" question is resolved (works for free if the scanner page has a focused input; not designed for explicitly).
