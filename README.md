# FRCA Election App

A self-contained offline voting app for office bearer elections in Free Reformed Churches of Australia. Designed to run on a single laptop in the church hall with a local WiFi router — no internet required.

## Before You Start

**New here?** See [where_to_start.md](where_to_start.md) for a signpost to the right document based on your role (council member, technical volunteer, election-day admin, demo presenter, or developer).

This software was built for a specific congregation and is shared freely in the hope that others find it useful. It is provided as-is under the MIT License, without warranty of any kind.

A few things to keep in mind:

- **This is not a commercial product.** There is no help desk, no guaranteed support, and no service-level agreement. That said, the author welcomes feedback and will consider suggestions, bug reports, and feature requests — though without any commitment to act on them.
- **You are responsible for your own use.** Before relying on this software for a real election, please test it thoroughly in your own environment and verify that it meets your congregation's needs and correctly implements your election rules.
- **Elections are serious.** The responsibility for running an election correctly rests with the church council — not with the authors of any tool used in the process.

This software works best when your congregation has someone who is comfortable with Python, basic networking, and the command line, and who is willing to set things up, run a few dry runs, and be on hand on election day.

If you would prefer a fully supported solution, consider a commercial voting platform such as ElectionBuddy, or continue with traditional paper ballots — both are perfectly good options.

## What is this?

This app lets brothers cast ballots on their phones over a local WiFi network during congregational elections for elders and deacons. It runs on a single laptop — no internet connection required. Paper ballots remain available as a fallback at all times.

Any FRCA congregation can clone this repository, run the setup wizard, and be ready for an election.

## Quick start

**Prerequisites:** Python 3.11 or later.

First, install dependencies:

```bash
cd frca_election_app/voting-app
pip install -r requirements.txt
```

Then start the app using the launcher for your platform:

**Windows (Command Prompt):**
```cmd
start.bat
```

**Windows (PowerShell):**
```powershell
.\start.bat
```

**Linux / macOS:**
```bash
./run.sh
```

The launcher starts the waitress production server on port 5000 and opens the admin page in your browser. Do not run `python app.py` directly — it will print a reminder and exit.

Replace `frca_election_app` with whatever you named the folder when you cloned the repository.

The app runs on `http://localhost:5000`.

- **Admin panel:** `http://localhost:5000/admin`
- **Voter page:** `http://localhost:5000/`
- **Projector display:** `http://localhost:5000/display`

On first login, the setup wizard collects your congregation name, WiFi SSID, and a new admin password. The default password is `admin`.

## How it works

1. An administrator creates an election, enters candidate names for elder and deacon, and generates one-time voting codes for all rounds.
2. Codes are printed on slips and handed out at the door alongside paper ballots. Brothers sign the attendance register.
3. Brothers enter their code on their phone, select candidates, and submit.
4. Each code can only be used once. Votes are recorded anonymously — there is no link between a code and the vote it cast.
5. Paper ballot totals are entered manually at count time and added to the digital totals.
6. Results are displayed on a projector with full Article 6 threshold transparency. If a second round is needed, selected candidates carry forward with the pre-printed Round 2 codes.

## Election rules compliance

The app implements the Rules for the Election of Office Bearers (Articles 1-13) as used in FRCA congregations:

- **Article 2** — Slate size validation (twice the number of vacancies), with Article 13 override
- **Article 6** — Threshold calculations: both 6a (more than half the valid votes divided by vacancies) and 6b (at least two-fifths of participants, fractions rounded up) displayed transparently with per-candidate pass/fail
- **Article 7** — Partial ballots valid (with under-selection warning), over-selection blocked server-side, vacancies and max_selections auto-updated for subsequent rounds
- **Article 10** — Retiring office bearer flag on candidates
- **Postal votes** — Aggregate postal vote entry (round 1 only), included in threshold calculations
- **Paper ballots** — Per-candidate paper vote entry with validation against ballot count, printable counter sheets for dual-counter verification
- **Multi-round** — Automatic carry-forward of candidates, per-round participant and ballot tracking, vacancies reduced as candidates are elected
- **Display** — Projector shows elected candidates (names only when counts hidden, full breakdown when shown), blank votes, totals with verification tick/cross, ballot method breakdown
- **Reset** — Soft reset (clear round, restore codes) and hard reset (start over) with confirmation
- **QR codes** — Each code slip has a QR code linking directly to the voting page with the code pre-filled

Full rules text: [ELECTION_RULES.md](voting-app/docs/ELECTION_RULES.md)

## Project layout

```
voting-app/
├── app.py                  # Flask application
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS (all bundled, no CDNs)
├── data/                   # SQLite database (gitignored)
├── tests/                  # 58 unit tests + 76 scenario mass tests
├── docs/
│   ├── README.md           # Detailed documentation
│   ├── SETUP.md            # Hardware and network setup
│   ├── ADMIN_GUIDE.md      # How to run an election
│   ├── CONFIGURATION.md    # First-time congregation setup
│   ├── UAT_SCRIPT.md       # Council dry-run script
│   ├── SECURITY.md         # Security and anonymity model
│   ├── FAILSAFE.md         # What to do when things go wrong
│   ├── COMPATIBILITY_TEST.md # Device testing checklist
│   ├── ELECTION_RULES.md   # Full text of Articles 1-13
│   └── CHURCH_ORDER_NOTES.md # Alignment with FRCA Church Order
├── requirements.txt
├── LICENSE
└── .gitignore
```

## Technology

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+, Flask |
| Database | SQLite (single file) |
| PDF generation | ReportLab |
| Production server | gunicorn |
| Frontend | HTML/CSS, mobile-first, no JavaScript in voter flow |

Everything is self-contained. No CDNs, no internet dependencies, no external services. The voter flow works with JavaScript completely disabled — pure HTML forms on every phone from 2016 onwards.

## License

MIT License. See [LICENSE](voting-app/LICENSE).

Built for office bearer elections in Free Reformed Churches of Australia. Released under the MIT License in the hope that it may serve any FRCA congregation — and any other organisation with similar needs.
