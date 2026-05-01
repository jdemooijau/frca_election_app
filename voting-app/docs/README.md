# FRCA Election App

A self-contained offline voting app for office bearer elections in Free Reformed Churches of Australia. Designed to run on a single laptop in the church hall with a local WiFi router — no internet required.

## Important — Read Before Using

**No warranty. No responsibility. No support.**

This software is provided as-is, with absolutely no warranty of any kind. It was built for a specific congregation's needs and is shared in the hope that it may be useful to others. However:

- **The authors accept no responsibility** for any consequences of using this software, including but not limited to: incorrect vote counts, failed elections, disputed outcomes, data loss, hardware damage, or any other issue that may arise from its use.
- **The authors provide no support.** No help desk, no email support, no guaranteed response to issues, no installation assistance, no troubleshooting, no custom changes. If you use this software, you are on your own.
- **You are fully responsible** for verifying that this software meets your congregation's needs, that it correctly implements your election rules, and that it operates correctly in your specific environment. Do not trust this software with a real election until you have thoroughly tested it yourself.

**If you cannot implement, run, and troubleshoot this software yourself, do not use it.** This is not a product. It is source code shared in good faith, nothing more. A real election is a serious matter and the responsibility for running it correctly belongs entirely with the church council that uses this tool — not with the authors of the tool.

If you are not comfortable with installing Python, running a Flask web application, configuring a local WiFi router, reading the source code, and taking full responsibility for the outcome — **then this software is not for you.** Use a commercial voting platform such as ElectionBuddy instead, or continue with traditional paper ballots.

## Who This Is For

This software is for congregations that have at least one member with the following:

- **Technical skill.** Comfortable with Python, Flask, SQLite, the command line, and basic networking. Able to read and understand the source code.
- **Willingness to take responsibility.** Prepared to be the one who installs, configures, tests, and runs the software — and the one who troubleshoots if something goes wrong on election day.
- **Time to test thoroughly.** Willing to conduct multiple dry runs before using it for a real election, including a full dress rehearsal with the church council.
- **Hardware access.** A laptop, a local WiFi router, and the ability to set both up in the church hall.

If your congregation does not have someone like this, **please do not use this software.** Use ElectionBuddy (a commercial platform with proper support) or stay with paper ballots.

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
6. Results are displayed on a projector. If a second round is needed, selected candidates carry forward with the pre-printed Round 2 codes.

## Project layout

```
voting-app/
├── app.py                  # Flask application
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS (all bundled, no CDNs)
├── data/                   # SQLite database (gitignored)
├── tests/                  # pytest test suite
├── docs/
│   ├── README.md           # This file
│   ├── SETUP.md            # Hardware and network setup
│   ├── ADMIN_GUIDE.md      # How to run an election
│   ├── CONFIGURATION.md    # First-time congregation setup
│   ├── UAT_SCRIPT.md       # Council dry-run script
│   ├── SECURITY.md         # Security and anonymity model
│   ├── FAILSAFE.md         # What to do when things go wrong
│   ├── COMPATIBILITY_TEST.md # Device testing checklist
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
| Frontend | HTML/CSS, mobile-first, no JavaScript frameworks |

Everything is self-contained. No CDNs, no internet dependencies, no external services.

## Documentation

| Document | Audience | Purpose |
|----------|----------|---------|
| [CONFIGURATION.md](CONFIGURATION.md) | Administrator | First-time setup for your congregation |
| [SETUP.md](SETUP.md) | Task team | Hardware and network setup at church |
| [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Task team | How to run an election end to end |
| [UAT_SCRIPT.md](UAT_SCRIPT.md) | Consistory with deacons | Step-by-step dry-run script |
| [SECURITY.md](SECURITY.md) | Consistory with deacons | Security model and anonymity guarantees |
| [FAILSAFE.md](FAILSAFE.md) | Task team | What to do when things go wrong |
| [COMPATIBILITY_TEST.md](COMPATIBILITY_TEST.md) | Task team | Device testing checklist |
| [CHURCH_ORDER_NOTES.md](CHURCH_ORDER_NOTES.md) | Consistory with deacons | Alignment with Church Order Article 3 |

## License

Built for office bearer elections in Free Reformed Churches of Australia. Released under the MIT License in the hope that it may serve any FRCA congregation — and any other organisation with similar needs.
