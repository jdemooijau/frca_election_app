# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project will adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once API surfaces stabilise.

## [1.0.0] — 2026-04-27

Initial public release.

### What's in 1.0.0

**Core election workflow:**
- Multi-round congregational election for elders and deacons.
- Per-round attendance, postal, and paper-ballot tracking.
- Digital voter flow over local WiFi (no internet required).
- One-time voting codes with QR code links.
- Anonymous vote recording (no link between code and vote).
- Paper ballots always available as fallback.
- Projector display with live tallies, Article 6 threshold transparency, and elected-status badges.
- Phone display for the chairman.
- Admin minutes DOCX export for the secretary.

**Election rules implementation (FRCA Articles 1–13):**
- Article 2: slate-size validation with Article 13 override.
- Article 6a: **Reading A** of "valid votes cast" — per-office sum of candidate ticks. Blank and spoilt ballots excluded from the threshold denominator. Council-confirmed; full provenance in [`voting-app/docs/ELECTION_RULES.md`](voting-app/docs/ELECTION_RULES.md).
- Article 6b: `ceil(participants × 2/5)` participation floor.
- Article 7: spoilt-ballot tracking per office; partial ballots accepted; over-voting blocked at the UI.
- Article 10: retiring-officer flag on candidates.
- Article 11: interim-election mode.

**Testing and tooling:**
- pytest suite covering rules compliance, voter flow, demo mode, mass-election scenarios, and PDF generation.
- `scripts/random_vote.py` for dry-run / load test against an open election.
- `scripts/seed_demo.py` for one-command demo setup (110 codes, attendance pre-set).

**Documentation for forks:**
- [`voting-app/docs/ELECTION_RULES.md`](voting-app/docs/ELECTION_RULES.md) presents each Election Rules article verbatim, alongside the app's interpretation and decision provenance.
- Rule arithmetic isolated in [`voting-app/election_rules.py`](voting-app/election_rules.py) so a forking congregation has one file to audit and change.
- README front-loads the "verify against your own Election Rules" disclaimer.
- Permissive MIT license (LICENSE at repo root).

### Known issues

- `tests/test_demo_mode.py::test_demo_mode_handles_exhausted_code_pool` fails on a pre-existing assertion about exact error wording. Tracked separately; does not affect election correctness.
