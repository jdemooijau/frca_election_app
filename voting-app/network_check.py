"""Read-only checks behind the admin Network check page.

They answer the questions that decide whether printed code slips will work:
does this laptop have the address the voting URL points at, and is the app
answering on port 80 (the port a plain http://10.0.0.2 URL uses)?
"""

import socket
import urllib.request
from urllib.parse import urlparse

PROBE_PORT = 80


def local_ipv4_addresses():
    """All non-loopback IPv4 addresses of this machine, sorted, unique."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except socket.gaierror:
        return []
    addresses = {info[4][0] for info in infos}
    return sorted(a for a in addresses if not a.startswith("127."))


def url_host(url):
    """Lower-case hostname of url, without port; empty if none."""
    return (urlparse(url).hostname or "").lower()


def _is_ipv4(host):
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def host_matches(url, addresses):
    """True/False when url's host is a literal IPv4 that is/is not one of
    addresses; None when it is a hostname, which cannot be checked here."""
    host = url_host(url)
    if not _is_ipv4(host):
        return None
    return host in addresses


def port80_serves_this_app(instance_id, timeout=1.0):
    """True only if port 80 on this machine answers /api/instance with
    instance_id, i.e. it is this running app and not something else."""
    url = "http://127.0.0.1:%d/api/instance" % PROBE_PORT
    # No proxy: a work-laptop proxy setting would otherwise be used even for
    # 127.0.0.1 and make a working port 80 look dead.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace").strip() == instance_id
    except Exception:
        return False
