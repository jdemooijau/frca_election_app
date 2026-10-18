# Windows Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the election app as a Windows installer that bundles Python, keeps data in `%ProgramData%`, serves voters on port 80 without a port proxy, and helps the operator check the network before printing code slips.

**Architecture:** Three small pure-Python modules (`app_paths.py`, `upgrade_backup.py`, `network_check.py`) carry the testable logic; `app.py` wires them in with minimal edits. A new `launcher.py` replaces `start.bat` for the installed build. PyInstaller (one-folder) freezes it, Inno Setup wraps it, `packaging/build.ps1` drives both. A shell script configures the Flint 2 router.

**Tech Stack:** Python 3.13, Flask 3, waitress 3, pytest 8, PyInstaller 6, Inno Setup 6, OpenWrt `uci`.

**Spec:** [voting-app/docs/superpowers/specs/2026-10-18-windows-installer-design.md](../specs/2026-10-18-windows-installer-design.md)

All paths below are relative to `voting-app/` unless they start with `../`. Run commands from `voting-app/`.

## Global Constraints

- No change to election logic, counting, ballot or PDF output.
- Running from source is unchanged: `start.bat` serves 5000 only; `captive-portal-on.bat` / `captive-portal-off.bat` stay.
- `FRCA_DB_PATH` keeps overriding the database file only.
- New env var `FRCA_DATA_DIR` overrides the data folder.
- Frozen data folder: `%ProgramData%\FRCA Election\data`.
- Installed app binds `0.0.0.0:80` and `0.0.0.0:5000`, waitress 16 threads.
- Default voting URL stays `http://10.0.0.2`.
- Firewall rule name `FRCA Election`, program `FRCA-Election.exe`, TCP 80 and 5000, all profiles, remote `10.0.0.0/24`. No 443 rule, no port proxy.
- Installer name `FRCA-Election-Setup-<version>.exe`; install dir `C:\Program Files\FRCA Election\`.
- Router: LAN `10.0.0.1/24`, laptop reservation `10.0.0.2`; `--captive-portal` adds dnsmasq `/#/10.0.0.2` and DHCP option `114,http://10.0.0.2/api/captive-portal`.
- `scripts/` is not shipped in the installer.
- No em-dashes in any code, comment, doc or commit message.
- Ask the maintainer before the first commit of this plan's work; never push. Every release adds a CHANGELOG entry.
- Full suite must stay green: `python -m pytest -q`.

## Review Focus

1. Data folder path containing spaces (`C:\ProgramData\FRCA Election\data`): every file the app writes must land there. Pinned in Task 1 (`test_frozen_path_with_spaces`) and Task 5 smoke test (temp dir with a space).
2. Laptop with two adapters (home WiFi plus ethernet to the router): the network check must match the voting host against any local address, not the first. Pinned in Task 3 (`test_host_matches_any_address`).
3. Voting URL that is a hostname (`http://church.vote`) or has a port (`http://10.0.0.2:5000`): port is ignored for the match; a hostname gives "cannot check" rather than a false mismatch. Pinned in Task 3 (`test_url_with_port`, `test_hostname_is_unknown`).
4. Data copied in from a source checkout (database present, no `last_version.txt`): a backup must still be taken before migration. Pinned in Task 2 (`test_backup_when_no_version_file`).
5. Port 80 held by a leftover `captive-portal-on.bat` port proxy or IIS: the launcher warns and serves 5000 only; port 5000 taken stops it. Pinned in Task 4 (`test_plan_listen_*`).

---

### Task 1: Data and bundle paths, version constant

**Files:**
- Create: `app_paths.py`, `version.py`
- Modify: `app.py` (the `BASE_DIR`/`DATA_DIR` block under "App configuration"; `load_member_names_from_external(BASE_DIR)` call; `inject_globals`; `admin_setup` render call)
- Modify: `templates/admin/_sidebar.html` (version line at bottom), `templates/admin/setup.html` (data folder line, read-only)
- Test: `tests/test_app_paths.py`

**Interfaces:**
- Produces: `version.__version__: str` (value `"1.4.0"`, maintainer may change at release).
- Produces: `app_paths.resolve_data_dir(environ: Mapping[str,str], frozen: bool, base_dir: str) -> str`
- Produces: `app_paths.resolve_bundle_dir(frozen: bool, meipass: str | None, module_dir: str) -> str`
- Produces: `app.DATA_DIR`, `app.BASE_DIR` (bundle dir), `app.DATA_ROOT` (`os.path.dirname(DATA_DIR)`), template global `app_version`.

- [ ] **Step 1: Write failing tests** in `tests/test_app_paths.py`:

```python
from app_paths import resolve_data_dir, resolve_bundle_dir

def test_env_override_wins():
    assert resolve_data_dir({"FRCA_DATA_DIR": r"D:\x"}, True, r"C:\app") == r"D:\x"

def test_frozen_uses_programdata():
    env = {"ProgramData": r"C:\ProgramData"}
    assert resolve_data_dir(env, True, r"C:\app") == r"C:\ProgramData\FRCA Election\data"

def test_frozen_path_with_spaces():
    env = {"ProgramData": r"C:\Program Data Odd"}
    assert resolve_data_dir(env, True, r"C:\app").endswith(r"Odd\FRCA Election\data")

def test_source_uses_app_folder():
    assert resolve_data_dir({}, False, r"C:\app") == r"C:\app\data"

def test_bundle_dir_frozen_and_source():
    assert resolve_bundle_dir(True, r"C:\b\_internal", r"C:\x") == r"C:\b\_internal"
    assert resolve_bundle_dir(False, None, r"C:\x") == r"C:\x"
```

Use `ntpath.join` inside `app_paths` only if `os.path` breaks these on non-Windows; tests run on Windows, `os.path.join` is fine. When `ProgramData` is missing from the environment, fall back to `C:\ProgramData`.

- [ ] **Step 2: Run** `python -m pytest tests/test_app_paths.py -v`. Expected: FAIL, `ModuleNotFoundError: app_paths`.
- [ ] **Step 3: Implement** both functions in `app_paths.py` and `version.py`.
- [ ] **Step 4: Wire into `app.py`:** `BASE_DIR = resolve_bundle_dir(getattr(sys, "frozen", False), getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__)))`; `DATA_DIR = resolve_data_dir(os.environ, getattr(sys, "frozen", False), <module dir>)` (module dir, not bundle dir, for the source case); `DATA_ROOT = os.path.dirname(DATA_DIR)`. Add `import sys`. Change the startup print to also print `"Data folder: " + DATA_DIR` and the version. Change `load_member_names_from_external(BASE_DIR)` to `load_member_names_from_external(DATA_ROOT)`. Add `"app_version": __version__` to `inject_globals`. Pass `data_dir=DATA_DIR` to `admin/setup.html` and show it as a read-only line near the WiFi/URL fields: `Data folder: {{ data_dir }}`. Add `<div class="wizard-sidebar-version">v{{ app_version }}</div>` before `</aside>` in `_sidebar.html` (small muted text in `static/css/style.css`).
- [ ] **Step 5: Run** `python -m pytest -q`. Expected: all pass (existing suite unaffected; `FRCA_DB_PATH` from `conftest.py` still wins).
- [ ] **Step 6: Commit** `feat(paths): data folder override and frozen-aware paths; show version`.

### Task 2: Backup before upgrade

**Files:**
- Create: `upgrade_backup.py`
- Modify: `app.py` (module-scope startup block, before `init_db()`)
- Test: `tests/test_upgrade_backup.py`

**Interfaces:**
- Consumes: `version.__version__`, `app.DB_PATH`, `app.DATA_DIR`.
- Produces: `upgrade_backup.backup_before_upgrade(db_path: str, data_dir: str, current_version: str, now: datetime) -> str | None` returns the backup path, or `None` if no backup was needed. Version file: `<data_dir>/last_version.txt`. Backup name: `<data_dir>/backups/<db basename>.<old>_<YYYY-MM-DD_HHMMSS>` where `<old>` is the file's content, or `unknown` if the file is missing. Always writes `current_version` to the version file afterwards (also when no db exists).

- [ ] **Step 1: Write failing tests** (use `tmp_path`, a fixed `datetime(2026, 10, 18, 19, 30, 5)`):
  - `test_no_db_no_backup`: no db file -> returns `None`; `last_version.txt` == `"1.4.0"`.
  - `test_same_version_no_backup`: db exists, file says `1.4.0` -> `None`.
  - `test_backup_on_version_change`: file says `1.3.1` -> returns path ending `backups\frca_election.db.1.3.1_2026-10-18_193005`; backup bytes equal db bytes; version file now `1.4.0`.
  - `test_backup_when_no_version_file`: db exists, no file -> name contains `.unknown_`.
- [ ] **Step 2: Run** `python -m pytest tests/test_upgrade_backup.py -v`. Expected: FAIL, module not found.
- [ ] **Step 3: Implement** with `shutil.copy2`. If `<db>-wal` exists, copy it alongside with the same suffix plus `-wal` so a WAL-mode db is not backed up half-written.
- [ ] **Step 4: Wire into `app.py`:** call it at module scope just before `with app.app_context(): init_db()`, and print the backup path when one is made. Skip the call when `FRCA_DB_PATH` is set (tests and scratch runs must not write version files next to the real data).
- [ ] **Step 5: Run** `python -m pytest -q`. Expected: all pass, and `data/last_version.txt` is NOT created by the test run.
- [ ] **Step 6: Commit** `feat(upgrade): back up the database before a new version migrates it`.

### Task 3: Network check page

**Files:**
- Create: `network_check.py`, `templates/admin/network_check.html`, `templates/voter/reach_test.html`
- Modify: `app.py` (new routes after `admin_setup`; `INSTANCE_ID` constant), `templates/admin/setup.html` (link "Check the network")
- Test: `tests/test_network_check.py`

**Interfaces:**
- Produces: `network_check.local_ipv4_addresses() -> list[str]` (all non-loopback IPv4 from `socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)`, sorted, unique).
- Produces: `network_check.url_host(url: str) -> str` (lower-case hostname, no port; `""` if none).
- Produces: `network_check.host_matches(url: str, addresses: list[str]) -> bool | None` (`None` when the host is not a literal IPv4, i.e. cannot check).
- Produces: `network_check.port80_serves_this_app(instance_id: str, timeout: float = 1.0) -> bool` (GET `http://127.0.0.1:80/api/instance`, true only if body equals `instance_id`; any error -> False).
- Produces routes: `GET /admin/network-check` (`@admin_required`, endpoint `admin_network_check`), `GET /reach-test` (public), `GET /api/instance` (public, returns `INSTANCE_ID` as text/plain). `INSTANCE_ID = secrets.token_hex(8)` at module scope.

- [ ] **Step 1: Write failing unit tests:**

```python
def test_url_with_port():
    assert url_host("http://10.0.0.2:5000/v/AB") == "10.0.0.2"

def test_host_matches_any_address():
    assert host_matches("http://10.0.0.2", ["192.168.1.20", "10.0.0.2"]) is True

def test_host_mismatch():
    assert host_matches("http://10.0.0.2", ["192.168.8.100"]) is False

def test_hostname_is_unknown():
    assert host_matches("http://church.vote", ["10.0.0.2"]) is None
```

  Plus route tests using the `client` fixture pattern from `tests/test_captive_portal.py` (log in by setting `session["admin"] = True` via `client.session_transaction()`):
  - `test_instance_route_returns_id`: body == `app_module.INSTANCE_ID`.
  - `test_reach_test_is_public`: 200, contains `"This phone can reach the voting app"`.
  - `test_network_check_mismatch_warning`: monkeypatch `network_check.local_ipv4_addresses` to `["192.168.8.100"]` and `port80_serves_this_app` to `False`; page contains `"Code slips printed now will not work on this network."` and `"http://10.0.0.2 will not reach the app"`.
  - `test_network_check_requires_admin`: not logged in -> redirect to login.
- [ ] **Step 2: Run** `python -m pytest tests/test_network_check.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `network_check.py` and the routes. The page lists: local addresses; `voting_base_url` and `voting_qr_url` (second only if different) each with match / mismatch / "hostname, cannot check"; port 80 status; a QR (reuse `_generate_qr_image`) for `voting_qr_url.rstrip("/") + "/reach-test"`. Exact copy for the two warnings is in the tests above. Extend the admin base template; match existing admin style.
- [ ] **Step 4: Run** `python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Manual check** from source: `start.bat`, open `/admin/network-check`, confirm addresses list and that port 80 shows "not serving" unless `captive-portal-on.bat` was run.
- [ ] **Step 6: Commit** `feat(admin): network check page and phone reach test`.

### Task 4: Launcher

**Files:**
- Create: `launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `app.app`, `app.DATA_DIR`, `version.__version__`.
- Produces: `launcher.port_is_free(port: int) -> bool` (try `socket.bind(("0.0.0.0", port))` with `SO_EXCLUSIVEADDRUSE` on Windows; close; True on success).
- Produces: `launcher.plan_listen(free_80: bool, free_5000: bool) -> tuple[str | None, list[str]]` returns the waitress `listen` string (or `None` = do not start) and the messages to print.
- Produces: `launcher.main() -> int` entry point.

- [ ] **Step 1: Write failing tests:**
  - `test_plan_listen_both_free`: `("0.0.0.0:80 0.0.0.0:5000", [])`.
  - `test_plan_listen_80_taken`: listen `"0.0.0.0:5000"`; messages mention `http://10.0.0.2`, `netstat -ano | findstr :80` and `captive-portal-off.bat`.
  - `test_plan_listen_5000_taken`: listen `None`; message says port 5000 is in use and another copy may be running.
  - `test_port_is_free_detects_taken`: bind a socket to an ephemeral port in the test, assert `port_is_free(that_port) is False`.
- [ ] **Step 2: Run** `python -m pytest tests/test_launcher.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `main()`: import `app` (triggers backup/migrate), print version, data folder, admin URL `http://localhost:5000/admin`, voter URL from `voting_base_url`; check ports; print messages; if listen is `None`, wait for Enter and return 1; else open the browser with `webbrowser.open` on a 1.5 s `threading.Timer` and call `waitress.serve(app, listen=listen, threads=16)`. Import `app` inside `main()` so tests of `plan_listen` do not trigger app startup.
- [ ] **Step 4: Run** `python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Manual check:** `python launcher.py` from a normal (non-admin) prompt. Expected: both ports bind, browser opens, `http://localhost/` serves the voter page. Then run `captive-portal-on.bat`, start again, confirm the port 80 warning and that 5000 still works; run `captive-portal-off.bat`.
- [ ] **Step 6: Commit** `feat(launcher): serve on 80 and 5000 with clear port messages`.

### Task 5: Freeze with PyInstaller, smoke test, build script

**Files:**
- Create: `packaging/requirements-build.txt` (exact `==` pins of the versions in the current venv for every `requirements.txt` package except pytest, plus `pyinstaller`), `packaging/frca_election.spec`, `packaging/smoke_test.py`, `packaging/build.ps1`
- Modify: `../.gitignore` (`voting-app/packaging/build/`, `voting-app/packaging/dist/`)

**Interfaces:**
- Consumes: `launcher.main`, `version.__version__`.
- Produces: `packaging/dist/FRCA-Election/FRCA-Election.exe` (one-folder, console), consumed by Task 6.
- Produces: `packaging/smoke_test.py <exe path>` exit code 0 on pass.

- [ ] **Step 1: Write the spec file.** Entry `../launcher.py`; `name="FRCA-Election"`; `console=True`; one-folder (`exclude_binaries=True` + `COLLECT`); datas: `templates`, `static`, `docs/COUNCIL_PROPOSAL.md` (to `docs/`); `collect_data_files("reportlab")` so its fonts ship; exclude `pytest`, `tkinter`.
- [ ] **Step 2: Write `smoke_test.py`.** Creates a temp dir whose name contains a space, sets `FRCA_DATA_DIR` to it, starts the exe as a subprocess, polls `http://127.0.0.1:5000/` up to 30 s, then asserts: `/` returns 200; `/admin/login` returns 200; one PDF endpoint that needs no login returns `%PDF` bytes (if every PDF route needs admin, log in with the default password `admin` first, using a session and the CSRF token from the login form); `frca_election.db` and `last_version.txt` exist in the temp dir. Kills the process and removes the temp dir in `finally`. Uses only the standard library plus `requests`.
- [ ] **Step 3: Write `build.ps1`.** Steps, stop on first failure: read `__version__` from `version.py`; fail with a clear message if `../CHANGELOG.md` has no `## [<version>]` heading; `python -m pytest -q`; `python scripts/check_display_fit.py` (release gate); create/refresh `packaging/.venv-build` from `requirements-build.txt`; `pyinstaller packaging/frca_election.spec --distpath packaging/dist --workpath packaging/build --noconfirm`; `python packaging/smoke_test.py packaging/dist/FRCA-Election/FRCA-Election.exe`; then `ISCC.exe /DAppVersion=<version> packaging/installer.iss` if the `.iss` exists (Task 6), else stop after the smoke test. Accept `-SkipChangelogCheck` for dev builds.
- [ ] **Step 4: Run** `powershell -File packaging/build.ps1 -SkipChangelogCheck`. Expected: tests pass, exe built, smoke test prints PASS. Fix hidden imports or missing data files until it does.
- [ ] **Step 5: Commit** `build: PyInstaller one-folder build with smoke test`.

### Task 6: Inno Setup installer

**Files:**
- Create: `packaging/installer.iss`

**Interfaces:**
- Consumes: `packaging/dist/FRCA-Election/` from Task 5; `/DAppVersion` from `build.ps1`.
- Produces: `packaging/dist/FRCA-Election-Setup-<version>.exe`.

- [ ] **Step 1: Write `installer.iss`:**
  - Fixed `AppId` GUID (generate once, never change); `AppName=FRCA Election`; `DefaultDirName={autopf}\FRCA Election`; `PrivilegesRequired=admin`; `OutputBaseFilename=FRCA-Election-Setup-{#AppVersion}`.
  - `[Dirs]`: `{commonappdata}\FRCA Election\data` with `Permissions: users-modify`; `uninsneveruninstall` flag.
  - `[Files]`: the whole dist folder, `recursesubdirs`.
  - `[Icons]`: `FRCA Election` -> exe; `Open data folder` -> `{commonappdata}\FRCA Election\data`.
  - `[Run]` (hidden, `runhidden`), in order: `netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0`; same for 443; `netsh advfirewall firewall delete rule name="FRCA Election"`; `netsh advfirewall firewall add rule name="FRCA Election" dir=in action=allow program="{app}\FRCA-Election.exe" protocol=TCP localport=80,5000 remoteip=10.0.0.0/24 profile=any`. Deletes may fail when nothing exists; that is fine.
  - `[UninstallRun]`: delete the `FRCA Election` firewall rule.
  - Last wizard page text: the data folder path, that uninstall keeps it, and (only if a port proxy delete succeeded, checked in `[Code]` via `Exec` result) that old port forwarding from `captive-portal-on.bat` was removed.
- [ ] **Step 2: Run** `powershell -File packaging/build.ps1 -SkipChangelogCheck`. Expected: installer exe in `packaging/dist/`.
- [ ] **Step 3: Manual check on a Windows user account with no Python on PATH:** install; Start menu "FRCA Election" starts and serves `http://localhost/` and `:5000`; `netsh advfirewall firewall show rule name="FRCA Election"` shows ports 80,5000 and remote 10.0.0.0/24; create an election; reinstall the same installer over the top and confirm the election is still there and a backup appeared only if the version changed; uninstall and confirm the data folder and db remain and the firewall rule is gone.
- [ ] **Step 4: Commit** `build: Inno Setup installer with firewall rule and data folder`.

### Task 7: Flint 2 router script

**Files:**
- Create: `router/flint2-setup.sh`

**Interfaces:**
- Usage: `sh flint2-setup.sh <laptop-mac> [--captive-portal]`.

- [ ] **Step 1: Write the script** (POSIX `sh`, OpenWrt `uci`). Validate the MAC (`xx:xx:xx:xx:xx:xx`, case-insensitive) or exit 2 with usage. Set `network.lan.ipaddr=10.0.0.1`, `network.lan.netmask=255.255.255.0`. Use a named host section `dhcp.frca_laptop` (`uci set dhcp.frca_laptop=host`, `.name=frca-laptop`, `.mac=<mac>`, `.ip=10.0.0.2`) so rerunning replaces it. With `--captive-portal`: `uci del_list` then `uci add_list` for `dhcp.@dnsmasq[0].address='/#/10.0.0.2'` and `dhcp.lan.dhcp_option='114,http://10.0.0.2/api/captive-portal'`. Without it: `del_list` both (so rerunning without the flag turns the portal off). Print each change, `uci commit`, then tell the operator the router will move to `10.0.0.1` and restart network and dnsmasq (`/etc/init.d/network restart`, `/etc/init.d/dnsmasq restart`) last, because the SSH session drops.
- [ ] **Step 2: Syntax check:** `sh -n router/flint2-setup.sh` (Git Bash). Expected: no output. Run `shellcheck` if installed.
- [ ] **Step 3: Manual check on the Flint 2:** copy with `scp`, run with and without `--captive-portal`, run twice, confirm with `uci show dhcp | grep -E "frca|114|/#/"` that there are no duplicates. Then confirm the laptop gets `10.0.0.2`.
- [ ] **Step 4: Commit** `feat(router): Flint 2 setup script for LAN, reservation and captive portal`.

### Task 8: Docs and changelog

**Files:**
- Modify: `docs/SETUP.md`, `../README.md`, `../CHANGELOG.md`

- [ ] **Step 1: SETUP.md.** New top section "Install (recommended)": download from GitHub Releases (`https://github.com/jdemooijau/frca_election_app/releases`), SmartScreen "More info > Run anyway", Start menu shortcuts, data folder `C:\ProgramData\FRCA Election\data`, upgrade (run the new installer; automatic backup), uninstall (data kept), moving from a source copy (copy the `data` folder in, with the app closed). Router section rewritten around `router/flint2-setup.sh` and `10.0.0.1` / `10.0.0.2`; replace the remaining `192.168.8.100` and `church.vote` instructions. Network check page: run it before printing slips. Move "running from source" to a "For developers" section; there, fix the claim that port proxy rules last "until you reboot" (they survive reboots; run `captive-portal-off.bat`).
- [ ] **Step 2: README.md.** Quick start points to the installer and Releases page first; source instructions follow.
- [ ] **Step 3: CHANGELOG.md.** Under `[Unreleased]` add `Added` entries (installer, data folder and `FRCA_DATA_DIR`, upgrade backup, network check page, launcher on port 80, router script) and a `Fixed` entry for the SETUP.md reboot claim.
- [ ] **Step 4: Check** `grep -rn "192.168.8.100\|until you reboot" docs/SETUP.md ../README.md`. Expected: no hits outside a clearly marked "older setups" note, if one is kept.
- [ ] **Step 5: Commit** `docs: installer setup, router script and network check`.

## Release (maintainer, after all tasks)

Rename `[Unreleased]` to `[1.4.0] - <date>` (or the chosen version, matching `version.py`), run `packaging/build.ps1` without `-SkipChangelogCheck`, tag, create the GitHub release and attach the installer.
