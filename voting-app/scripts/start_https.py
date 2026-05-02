"""HTTPS launcher for the FRCA Election App, used only when the
chairman needs camera access on his phone for the paper-ballot
scanner.

Phones refuse `getUserMedia()` on plain HTTP origins other than
`localhost`, so the camera viewfinder stays black when the chairman
opens the app over the church-hall WiFi (e.g. `http://192.168.x.x`
or the captive-portal hostname). Serving the same WSGI app over
HTTPS unblocks the camera, at the cost of a one-time browser warning
on each device because the certificate is self-signed.

Usage on Windows:

    voting-app\\start-https.bat

This runs the Flask development server on port 5443 with an
ad-hoc self-signed certificate. The voter-facing port 5000 (Waitress)
is unaffected; both servers can run side-by-side from the same
machine. Voters use the HTTP port; the chairman opens the scanner
page on the HTTPS port, taps "Advanced > Proceed" once, and after
that the camera works.

The development server is single-threaded but is more than adequate
for one chairman scanning ~30 ballots. Do NOT use this launcher for
voter traffic.
"""

import os
import sys

# Make the parent directory (voting-app/) importable so `from app import app`
# resolves regardless of where this script is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402


if __name__ == "__main__":
    print("=" * 60)
    print(" FRCA Election App. HTTPS launcher (chairman scanner only)")
    print(" Voters keep using http://localhost:5000 (started by start.bat).")
    print(" Chairman opens https://<this-machine-ip>:5443/scanner on the")
    print(" phone. Accept the browser warning once per device.")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5443, ssl_context="adhoc",
            threaded=True, debug=False, use_reloader=False)
