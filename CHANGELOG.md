# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
