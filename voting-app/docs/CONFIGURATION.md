# Configuration — First-Time Setup

When a congregation uses this app for the first time, a brief setup wizard runs on first admin login.

## First-Run Setup

1. Start the app: `python app.py`
2. Open `http://localhost:5000/admin`
3. Log in with the default password: `admin`
4. The setup wizard will ask for:

| Setting | Example | Purpose |
|---------|---------|---------|
| **Congregation name** | Free Reformed Church of Armadale | Displayed in page headers, PDFs, attendance register |
| **Short name** | FRCA Armadale | Used in PDF titles and filenames |
| **WiFi SSID** | FRC-Election | Printed on code slips so brothers know which WiFi to connect to |
| **New admin password** | (at least 6 characters) | Replaces the default password — required |

5. Click **Save and Continue**. The app is now configured.

## Changing Settings Later

To change the congregation name or WiFi SSID after initial setup, navigate to `/admin/setup` in the browser. You will need to re-enter a password.

## Environment Variables

These optional environment variables override defaults:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Flask session secret key (auto-generated if not set) |

## Database

The database is a single SQLite file at `data/frca_election.db`. It contains all elections, votes, codes, members, and settings. To start completely fresh, stop the app and delete this file — a new one will be created on next startup.

## What Each Congregation Needs to Provide

Before running an election:

1. **Congregation name** — set during first-run setup
2. **Member list** — exported as CSV from Church Social (or entered manually)
3. **Candidate names** — entered when creating an election
4. **Hardware** — a laptop, a portable WiFi router, and optionally a projector

Everything else is built in.
