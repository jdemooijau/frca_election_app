# Windows Installer for the Election App: Design

Date: 2026-10-18
Status: draft for review

## Intent

Another FRCA congregation should be able to run elections with this app without
cloning the repo, installing Python, or running batch files as admin by hand.
The person setting it up is as technical as the current maintainer, and uses
the same kit: a Windows laptop wired to a GL.iNet Flint 2 router, laptop fixed
at `10.0.0.2`, no internet.

The aim is to remove the fiddly, easy-to-get-wrong steps, not to hide the
setup behind a wizard for non-technical users.

## Goals

1. A single Windows installer (`FRCA-Election-Setup-<version>.exe`) that
   installs the app with Python and all libraries bundled.
2. The installed app keeps its data (database, secret key, backups, logs,
   member lists) outside the install folder, so upgrading or reinstalling
   never touches it.
3. The installed app listens on ports 80 and 5000 itself, and the installer
   adds the firewall rules for both. No port proxy and no admin-only batch
   files are needed on election night.
4. An admin "Network check" page that tells the operator, before printing
   code slips, whether the laptop's IP matches the voting URL on the slips.
5. A router setup script for the Flint 2 that applies the LAN, DHCP
   reservation and optional DNS wildcard in one step over SSH.
6. The app shows its version, and the installer version matches the git tag
   and the CHANGELOG entry.

## Non-goals

- A Go (or any other) rewrite.
- Mac or Linux installers. `run.sh` and `start.bat` stay for running from
  source.
- Auto-update. Upgrading means downloading and running the new installer.
- Code signing. Windows SmartScreen will warn on first run; SETUP.md explains
  "More info > Run anyway".
- Running the app on the router itself.
- Support for routers other than the Flint 2 (others may work; not tested or
  documented).
- The security hardening already deferred (admin lockout, rate limiting).

## Anti-goals (a failure even if it technically works)

- Any change to election logic, counting, ballot or PDF output.
- An upgrade or uninstall that deletes or replaces an existing database.
- The installed app silently using a different database from the one the
  operator expects.
- The installed app starting while it cannot serve voters on port 80,
  without telling the operator.
- Running from source (`start.bat`, `pytest`) breaking for development.

## Constraints

- Existing pytest suite must still pass from source.
- `scripts/check_display_fit.py` stays the release gate.
- The `FRCA_DB_PATH` override keeps working.
- Every release adds a CHANGELOG entry (existing rule).
- The app currently binds `0.0.0.0:5000` via waitress with 16 threads. The
  installed app binds `0.0.0.0:80` and `0.0.0.0:5000`, 16 threads.
- The default voting URL stays `http://10.0.0.2` (port 80). Today phones
  reach it only because `captive-portal-on.bat` forwards 80 to 5000; the
  installed app replaces that forward by listening on 80 directly (decided
  by the maintainer, 2026-10-18).
- Running from source is unchanged: `start.bat` still serves 5000 only and
  the two `captive-portal-*.bat` files stay for that case.

## Decided design

### 1. Data folder

Today `DATA_DIR` is `<app folder>/data`, derived from `__file__`
([app.py:56-57](../../../app.py#L56-L57)). That breaks once frozen: the install
folder is read-only under Program Files and is replaced on upgrade.

New rule, in order:
1. `FRCA_DATA_DIR` environment variable, if set.
2. If running frozen (PyInstaller, `sys.frozen`): `%ProgramData%\FRCA Election\data`.
3. Otherwise (from source): `<app folder>/data`, as today.

`FRCA_DB_PATH` still overrides the database file only. The member-name lookup
(`load_member_names_from_external`, which today is given `BASE_DIR` and
appends `data/`) follows the data folder. The startup print of the database
path stays, and the admin Setup page also shows the data folder path.

Existing source installs (my call): no import feature. Another congregation
starts fresh. Anyone moving from a source checkout copies their `data` folder
into `%ProgramData%\FRCA Election\` by hand; SETUP.md says how. If a source
copy and the installed copy are started at once, the second fails to bind
port 5000 and says so, so the two cannot run side by side by accident.

Backup before upgrade (my call): when the launcher sees that the database was
last opened by a different app version, it copies the database to
`data\backups\frca_election.db.<old version>_<timestamp>` before
`migrate_db` runs. The last-run version is stored in the database itself
(settings key `app_version`), so a database copied in from elsewhere carries
its own version, or none (decided in the final review: a side file in the
data folder could say "same version" for a copied-in database).

Helper scripts (my call): `scripts/` (reset, seed demo, random vote/count,
display fit) are not shipped in the installer. They are developer and test
tools and stay source-only. The in-app demo and reset already cover what an
operator needs.

Read-only bundled files (templates, static, `docs/COUNCIL_PROPOSAL.md`) are
found via the PyInstaller bundle folder when frozen, and `BASE_DIR` as today
from source.

### 2. Launcher

A small entry point (`launcher.py`) that:
- imports the app (which runs `init_db`/`migrate_db` as today),
- prints the version, the data folder and the URLs, as `start.bat` does now,
- checks that ports 80 and 5000 are free before serving,
- opens `http://localhost:5000/admin` in the default browser,
- serves with waitress on `0.0.0.0:80` and `0.0.0.0:5000`, 16 threads.

If port 5000 is taken, it prints which port and stops (another copy is
probably running). If only port 80 is taken (IIS, an old port proxy from
`captive-portal-on.bat`, some VPN tools), it prints a clear warning that
phones using `http://10.0.0.2` will not reach the app, says how to find the
other program (`netstat -ano | findstr :80`) and to run
`captive-portal-off.bat` if it was used before, and carries on serving on
5000 only. The same state shows on the Network check page.

It runs in a visible console window. Closing the window stops the app. This
matches how the app is run today and makes it obvious when it is running.

### 3. Packaging

- PyInstaller in one-folder mode (not one-file). My call: one-file unpacks to
  a temp folder on every start, is slower, and is flagged by antivirus more
  often.
- A pinned build requirements file (exact versions) so builds are repeatable.
  `requirements.txt` stays as it is for development.
- Inno Setup builds the installer from the PyInstaller output.
- A build script (`packaging/build.ps1`) runs: tests, PyInstaller, Inno Setup,
  and leaves the installer in `packaging/dist/`.

### 4. Installer behaviour

- Installs to `C:\Program Files\FRCA Election\`. Needs admin (it already
  needs admin for the firewall rules).
- Creates `%ProgramData%\FRCA Election\data` with modify rights for the Users
  group, so the app can write there without running as admin. Never
  overwrites anything already in it.
- Adds one inbound firewall rule, named `FRCA Election`, for the installed
  program (`FRCA-Election.exe`), TCP ports 80 and 5000, all network
  profiles, remote addresses limited to `10.0.0.0/24` (my call).
  Profile-agnostic because Windows often files the offline Flint 2 network
  as Public; the address limit means the ports are not open to a cafe or
  office network. Removed on uninstall.
- No port 443 rule and no port proxy (maintainer's decision, 2026-10-18).
  Serving plain HTTP on 443 does not help phone captive checks.
- If the old `captive-portal-on.bat` port proxy entries for 80/443 exist,
  the installer removes them, because they would hold port 80 and block the
  app. It says so on its last page.
- Start menu shortcuts:
  - FRCA Election (starts the launcher)
  - Open data folder
- Uninstall removes the program and the firewall rule. It leaves the data
  folder in place and says so.
- Upgrading: running a newer installer over an existing install replaces the
  program files only.

SETUP.md says portproxy rules last "until you reboot". That is wrong (they
are stored in the registry and survive reboots) and gets fixed in the
source-install section.

### 5. Network check page (admin)

A new admin page, linked from Setup, that shows:
- The laptop's IPv4 addresses.
- The host in the configured voting URL (`voting_base_url`, and
  `voting_qr_url` if different), and whether it matches one of the laptop's
  addresses. A mismatch is shown as a clear warning: "Code slips printed now
  will not work on this network."
- Whether the app is serving on port 80 (in the installed app: whether the
  launcher bound it; from source: whether port 80 on this laptop answers
  with this app, i.e. the old port proxy is on). If not, a warning that
  `http://10.0.0.2` will not reach the app.
- A QR code that links to a simple "this phone can reach the app" page at the
  configured voting URL, so the operator can test with a real phone.

It reads only; it changes no settings and needs no admin rights.

### 6. Router setup script (Flint 2)

A shell script in `router/flint2-setup.sh` that the operator copies to the
router and runs over SSH (the Flint 2 runs OpenWrt). Arguments: the laptop's
ethernet MAC address, and an optional flag for the DNS wildcard. It sets:
- LAN to `10.0.0.1/24`,
- a DHCP reservation for the laptop at `10.0.0.2`,
- with the flag (named for the captive portal, e.g. `--captive-portal`):
  the dnsmasq wildcard `/#/10.0.0.2` and DHCP option 114
  (`114,http://10.0.0.2/api/captive-portal`), as SETUP.md Step 5 does by hand
  today (my call: both under one flag, since both exist only for the portal).

The script is safe to run twice (it replaces its own entries rather than
adding duplicates) and prints what it changed.

It does not set the WiFi name, WiFi password or router admin password; the
operator does those in the router admin page as today. My call: a script
over a shared config backup, because a backup would carry our WiFi and admin
credentials and is tied to one firmware version.

### 7. Version

One version constant in the app, shown in the admin footer and printed by the
launcher. The build script reads it to name the installer and refuses to
build if there is no matching CHANGELOG heading.

### 8. Docs

- SETUP.md gains an "Install" section at the top (download, SmartScreen,
  Start menu shortcuts, data folder, upgrade, uninstall) and moves "running
  from source" to a developer section.
- SETUP.md network steps are updated to the 10.0.0.x addresses and the
  router script. The current text still says `192.168.8.100` and
  `church.vote` in places.
- README links to the GitHub Releases page for the installer. The repo
  (`jdemooijau/frca_election_app`) is public. The maintainer builds locally
  and attaches the installer to the release by hand (my call for the first
  release).

## Testing

- pytest from source, unchanged, plus tests for the data-folder rule and the
  network check logic (IP match, URL parsing).
- A smoke test of the built program: start it with `FRCA_DATA_DIR` pointing
  at a temp folder, then fetch `/`, `/admin` and one generated PDF (to prove
  ReportLab and its fonts were bundled), and confirm the database was
  created in the temp folder.
- A manual check on a clean Windows machine (or a fresh Windows user account
  with no Python): install, run, upgrade over the top, uninstall, confirm the
  data survived each step.

## Left to the builder

- Exact PyInstaller spec settings and hidden imports.
- How the launcher detects whether the port proxy is on.
- Layout and wording of the network check page, within the existing admin
  style.
- Whether to add a GitHub Actions job that builds the installer on a tag.
  Not required; a local build is enough for the first release.
- Installer icon and wizard text.
