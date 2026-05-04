# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
