"""Entry point for the installed (frozen) app: FRCA-Election.exe.

Serves on port 80, so the plain http://10.0.0.2 voting URL works without a
port proxy, and on port 5000 for the admin and anyone using :5000. Running
from source still uses start.bat; this file also runs with
`python launcher.py`.
"""

import socket
import sys
import threading
import webbrowser

VOTER_PORT = 80
ADMIN_PORT = 5000
THREADS = 16
ADMIN_URL = "http://localhost:%d/admin" % ADMIN_PORT


def port_is_free(port):
    """True if nothing else holds TCP port on 0.0.0.0."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def plan_listen(free_80, free_5000):
    """Return (waitress listen string or None to not start, messages)."""
    if not free_5000:
        return None, [
            "Port %d is in use. The app cannot start." % ADMIN_PORT,
            "Probably another copy of the election app is running (installed",
            "or from source). Close it and start again.",
        ]
    if not free_80:
        return "0.0.0.0:%d" % ADMIN_PORT, [
            "Port %d is in use by another program. Checking whether it" % VOTER_PORT,
            "forwards to this app...",
        ]
    return "0.0.0.0:%d 0.0.0.0:%d" % (VOTER_PORT, ADMIN_PORT), []


def port80_report(serves_this_app):
    """Messages once the app is up and port 80 was held by something else.

    The old captive-portal-on.bat port proxy forwards 80 to 5000, so voting
    still works through it; anything else on port 80 blocks voters.
    """
    if serves_this_app:
        return [
            "OK: port 80 forwards to this app (the port proxy from",
            "captive-portal-on.bat). Phones using http://10.0.0.2 will reach it.",
        ]
    return [
        "WARNING: phones using http://10.0.0.2 will NOT reach the app.",
        "Only :%d works. Find the program on port 80 with:" % ADMIN_PORT,
        "  netstat -ano | findstr :80",
        "If you used captive-portal-on.bat before, run captive-portal-off.bat",
        "as Administrator, then restart this app.",
    ]


def _report_port80_later(instance_id):
    import network_check
    for line in port80_report(network_check.port80_serves_this_app(instance_id)):
        print(line)


def _wait_for_enter():
    try:
        input("Press Enter to close.")
    except EOFError:
        pass


def _run():
    import waitress
    import app as app_module

    with app_module.app.app_context():
        voter_url = app_module.get_setting("voting_base_url", "http://10.0.0.2")

    listen, messages = plan_listen(port_is_free(VOTER_PORT), port_is_free(ADMIN_PORT))
    print("=" * 56)
    print("  Admin:  " + ADMIN_URL)
    print("  Voters: " + voter_url)
    print("  Close this window to stop the app.")
    print("=" * 56)
    for line in messages:
        print(line)
    if listen is None:
        _wait_for_enter()
        return 1

    threading.Timer(1.5, webbrowser.open, args=(ADMIN_URL,)).start()
    if not listen.startswith("0.0.0.0:%d " % VOTER_PORT):
        threading.Timer(2.0, _report_port80_later, args=(app_module.INSTANCE_ID,)).start()
    try:
        waitress.serve(app_module.app, listen=listen, threads=THREADS)
    except KeyboardInterrupt:
        pass
    return 0


def main():
    """Run the app; on any startup error keep the window open so the
    operator can read what went wrong."""
    try:
        return _run()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stdout)
        print()
        print("The app could not start. The error is shown above.")
        _wait_for_enter()
        return 1


if __name__ == "__main__":
    sys.exit(main())
