# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- `7_wifi_handout.pdf` (the 10-copy WiFi-join sheet) is no longer
  produced or included in the printer pack. Its role is taken over
  by the per-voter duplex handout (front: how-to-vote, back: FAQ).
  The supporting helpers `generate_wifi_handout_pdf`,
  `_wifi_qr_payload`, and `_draw_wifi_icon` are deleted.
- `docs/DOUBLE_VOTING_SAFEGUARDS.md` deleted in favour of the FAQ
  on the back of `how_to_vote_card.html` (single source of truth
  for voter-facing safeguard wording; print and email use the same
  rendered PDF).

### Changed

- Step 1 numbered circle on the code slip moved 3 mm down so it no
  longer crowds the "Vote with phone" header rule.
- Voting card back simplified to a single QR after UAT (David, Matt)
  showed the two-QR design (WiFi join + voting) confused voters who
  would not read the step labels and just scanned whichever QR they
  saw first. Step 1 is now a text-only line ("Connect to WiFi:
  ChurchVote / No password needed") next to a numbered circle. Step
  2 keeps the voting QR (back up to 36 mm) plus a vertical divider
  with an "If QR fails" hint and the manual fallback text. The
  numbered step circles are bigger (5 mm radius, 16 pt) and styled
  black-on-white (white fill, black ring, black digit) so they read
  as numbered steps rather than a generic icon. The standalone
  `7_wifi_handout.pdf` continues to provide a WiFi-join QR at the
  sign-in table for the convenience use case.

### Added

- Welcome display labels bumped from 26 px to 36 px and the Step 2
  label changed from "Type" to "Scan the QR or type" so the line
  reads as one instruction across the value: "scan the QR or type
  church.vote (or http://10.0.0.2) into your browser".
- `docs/how_to_vote_card.html` is now a duplex A4 voter handout.
  Front: how to vote on paper or on the phone (refreshed wording,
  including a clear "tear up the card" Step 4). Back: a
  "How is this kept honest?" FAQ in five short paragraphs covering
  single-use codes, paper-vs-phone reconciliation, anonymity, paper
  fallback, and the audit trail. Designed to be emailed to members
  ahead of the meeting AND printed (one duplex copy per voter) for
  the sign-in table on the day. The rendered `how_to_vote_card.pdf`
  is included in the printer pack as `7_voter_handout.pdf`.

### Fixed

- Voter session is now round-aware: `voted_round` is recorded
  alongside `used_code` / `election_id` when a code is accepted,
  and the bare URL (`/`) only treats the session as "voted in the
  active election" when `voted_round` matches the election's
  `current_round`. Previously, after voting in round 1 and round 2
  opening, hitting `/` on the same phone rendered the live phone
  display as if the round-1 vote still counted, instead of the
  code-entry form for the new round-2 code. Stale session keys
  from a previous round are now cleared on the next visit so the
  entry form renders.

### Added

- Printer pack now includes a `7_wifi_handout.pdf` (10 identical A4
  copies) headed with a WiFi icon, "Prepare your wifi connection",
  a prominent oversized "(optional)" line, and "scan both codes:".
  Two stacked numbered QRs follow: (1) the standard `WIFI:` payload
  (iOS Camera / Android 10+ recognise it as a "Join Network" prompt)
  with the SSID printed beneath, and (2) the bare voting URL so
  voters can confirm the page loads end-to-end, with the URL printed
  beneath. The 10-copy stack is intended to be passed down the pews
  so members can prepare their phones while waiting for ballots. The
  previous AV-team handout becomes `8_av_instructions.pdf`.
  (#wifi-qr-handout)
- Read-only round-results page for any closed prior round, reachable
  by clicking the collapsed "Round N - Closed - X elected" entry in
  the wizard sidebar. The page reuses the count-step tally partial
  to render that round's per-candidate digital/paper/postal totals,
  Article 6a/6b thresholds (calculated against the round's actual
  participants and the vacancies that were open at the start of that
  round), and an ELECTED badge on candidates whose `elected_round`
  matches. No action buttons; round 1 always shows every candidate,
  later rounds show only those who received votes that round or were
  elected that round.

### Changed

- Voter audit log's repeat-offenders banner no longer flags multiple
  `code_accepted` events for the same code. Voters routinely test-scan
  the voting QR at the sign-in table before voting (the Step 1 / Step
  2 card layout makes this part of the workflow), so the old detector
  produced false positives on every voter who pre-tested. The banner
  now only fires on more than one `vote_submitted` for the same code,
  which the burn-on-submit DB logic should make impossible (so seeing
  it means a genuine integrity bug). Heading reworded from "Codes with
  repeated events" to "Possible double vote".
- Voter confirmation page (`/vote-confirmation`) now shows a prominent
  amber "Tear up your paper ballot / Do not submit it. Your phone vote
  is the one counted." warning between the success heading and the
  code box, closing the only remaining accidental-double-count path.
- Voting card reworked end-to-end:
  - Header text changed from "Vote Digitally" to "Vote with phone".
  - Warning strip on both sides changed from "if you voted digitally"
    to "if you voted with your phone" (paper-ballot front + code
    slip back).
  - Code slip back is now a two-column layout: both QRs on the left
    at the same 30 mm size (Step 1 = WiFi, Step 2 = voting), step
    circles to their left; vertical divider; right column carries
    Step 1's "Connect to [WiFi icon]" header, the SSID on its own
    line in bold, the password line, and Step 2's "Type ... and
    enter this code:" fallback with the code in big mono.
  - The horizontal OR pill is replaced with a vertical "If QR fails"
    hint running bottom-to-top along the divider, centred on the
    voting QR.
  - The redundant "Scan QR code with your phone camera" preamble is
    dropped (modern users know how QR works).
  - Card fills the A4 grid budget (88 mm) so 6 slips per page no
    longer leave the bottom of the sheet empty.
  - Voting QR is 30 mm (down from 36 mm; below the original 32 mm
    count-time spec floor but well above the 24 mm panic threshold).
    Confirm count-time scanning still holds in practice.
  Affects every printer-pack output that renders the card back.
- Final-results projector view (phase 4 with details) now renders
  prior-round winners in a separate "Previously elected" strip at the
  top of each office card (with a R1/R2 round badge and their
  winning-round vote total). Previously these brothers were merged
  into the current-round candidate list, which mixed totals from
  different rounds with the current round's threshold checks and
  Blank/Spoilt/Total summary. The current-round candidate list,
  Article 6a/6b lines, and the Total checkmark are now strictly
  current-round-only; the prior winners are still visible for context
  but cannot be confused with current-round arithmetic. The clean
  Final Summary view (`final.html`, no counts) remains the canonical
  merged "who was elected" screen.
- Wizard sidebar's collapsed prior-round entry is now a clickable
  link (with hover state and a chevron) instead of static italic
  text.

### Fixed

- Projector display in rounds > 1 no longer shows "Voting will begin
  shortly" overlaid on the closed-round results. Two compounding
  issues were fixed:
  - The count step now derives `round_counts.paper_ballot_count`
    from the saved per-office tallies (`ceil(marks / max_selections)
    + spoilt`, max across offices) when attendance was skipped, so
    `total_ballots` reflects what was actually counted. Only fills
    in when the count is missing, so an explicit attendance entry
    (and its tally validation) is preserved.
  - The pre-vote welcome panel in `projector.html` now also requires
    `display_phase != 4`. Defence in depth so the banner cannot
    appear on the Final-results screen even if `total_ballots` were
    somehow zero.

## [1.3.1] - 2026-05-02

### Fixed

- Reconciliation panel on the admin count step now uses the
  per-round digital ballot count instead of the cumulative
  `codes.used = 1` total. In round 2+ the cumulative count summed
  burned codes from prior rounds, inflating the Online used cell and
  producing spurious "more ballots than attendees" gaps.
- Voter-log repeat-offender row now states which event repeated
  (`code_accepted` vs `vote_submitted`) and passes that result
  through to the View entries link, so the drill-down matches the
  row instead of mixing event types.
- Code-slip layout vertical balance restored after the 36 mm QR
  enlargement: header height +1 mm, OR-pill anchor lifted 1 mm to
  preserve clearance.

### Removed

- Duplicate "Generated Codes" on-screen list on the Codes step. The
  Code Slips PDF printed from the same page is the canonical artifact
  for distributing codes; the redundant monospace list added clutter
  without new information.

## [1.3.0] - 2026-05-02

### Added

- Paper-ballot QR scanner page on the admin count step. Reads each
  ballot's QR via the device camera (continuous video, browser
  `BarcodeDetector` with vendored `jsQR` fallback). When a scanned QR
  matches a code already burned online, the scanner flags the
  match, atomically decrements `paper_ballot_count` for the current
  round, and writes a `paper_set_aside_at_count` audit-log row. Visual
  flash and audible beep distinguish match / paper-only / unknown
  results. Mute toggle supported.
- Reconciliation panel on the count step showing attendees, online
  used, paper, postal, and the gap. Three display states: gap > 0
  (within attendance, optional "larger than expected" hint when gap
  exceeds 10% of attendees), gap == 0 (reconciled green), gap < 0
  (red banner with prominent scan-paper-ballots button). A smaller
  scan-paper-ballots button is always present so the chairman can run
  the scanner proactively.
- Audit-log labels: `RESULT_LABELS` mapping renders all known voter
  audit reasons as human-readable strings on the admin voter-log page,
  including the new "Paper ballot set aside (already voted online)"
  label.

### Changed

- Code-slip QR enlarged from 24 mm to 32 mm. The smaller QR forced
  phone cameras to focus at 5-10 cm with narrow angle tolerance,
  making count-time triage scanning fussy. The larger QR roughly
  doubles fold tolerance per module and lets the operator hold a
  ballot at 15-25 cm without focus hunting.

## [1.2.1] - 2026-05-01

First real release. Self-contained offline voting app for office bearer
elections in Free Reformed Churches of Australia.

### Added

- Persistent left-rail wizard sidebar covering 12 steps grouped Setup,
  Round 1..N, Finish (Election details, Members, Offices & Candidates,
  Election settings, Codes & printing, Attendance & postal, Welcome &
  Rules, Voting, Count & tally, Decide, Final results, Minutes &
  archive). Each step is its own page; sidebar marks each as Done,
  Current, Available, or Locked.
- Multi-round elections with chairman-driven candidate carry-forward,
  Article 6a/6b threshold enforcement, and Article 7 spoilt-ballot
  handling.
- Paper, postal, and digital votes counted together. Voter audit log
  records every code attempt with colour-coded result pills.
- Optional paper-count co-counting helper: volunteers tap on phones
  while the chairman reads ballots aloud, with consensus calculation
  and a development HTTP simulator (`scripts/random_count.py`).
- Captive-portal style landing for visitors; foreign-host redirects to
  the canonical `church.vote` host; no-cache headers throughout.
- Final Results projector aggregates winners across rounds with each
  candidate's winning-round vote totals.
- Phones on `/`, `/vote`, `/vote/ballot`, and `/vote/confirmation`
  auto-redirect to `/displayphone` when the chairman finalises the
  election (display_phase = 4).
- DOCX minutes export with round-by-round narrative; Printer Pack ZIP
  bundling attendance register, dual-sided ballots, code slips, and
  counter sheet.
- `random_count.py` simulator authenticates via signed Flask session
  cookies, so it works whether voting is open or closed.

### Changed

- Closing voting no longer auto-reveals tallies on the projector. The
  chairman explicitly clicks Show Results on Projector. ELECTED badges
  and the runoff banner are gated on the same flag, so the audience
  never sees premature conclusions.
- Decide step navigates to Final results without flipping the
  projector; Final results step owns the explicit Show-on-Projector
  click and the toggle between Final Summary and Vote Details.
- Sidebar wizard replaces the prior Manage / Codes / Offices tab
  layout. Dashboard exposes a single "Open" button per election.

### Tests

- 237 / 237 passing.

### Compliance

The implementation encodes one congregation's interpretation of the
FRCA Election Rules. See [`voting-app/docs/ELECTION_RULES.md`](voting-app/docs/ELECTION_RULES.md)
for the article-by-article reading. Other congregations should fork
and adjust [`voting-app/election_rules.py`](voting-app/election_rules.py)
before running a real election.

### Historical

Earlier development snapshots remain reachable as tags `v1.0.0`,
`v1.1.0`, and `v1.2.0`. They point into orphaned history kept alive by
the tags themselves; they are not part of the squashed `main`.
