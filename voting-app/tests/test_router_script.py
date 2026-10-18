"""Tests for router/flint2-setup.sh, run with a fake `uci` that logs calls.

Needs a POSIX sh (Git Bash on Windows); skipped where there is none.
"""

import os
import shutil
import subprocess

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(APP_DIR, "router", "flint2-setup.sh")
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="no POSIX sh available")

MAC = "AA:bb:CC:00:11:22"


def _run(tmp_path, *args):
    bin_dir = tmp_path / "bin"
    initd = tmp_path / "initd"
    bin_dir.mkdir(exist_ok=True)
    initd.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    (bin_dir / "uci").write_text('#!/bin/sh\necho "uci $*" >> "%s"\n' % log.as_posix(), newline="\n")
    for service in ("network", "dnsmasq"):
        (initd / service).write_text('#!/bin/sh\necho "%s $*" >> "%s"\n' % (service, log.as_posix()),
                                     newline="\n")
    env = dict(os.environ, INITD=initd.as_posix(),
               PATH=bin_dir.as_posix() + os.pathsep + os.environ.get("PATH", ""))
    proc = subprocess.run([SH, SCRIPT] + list(args), env=env, capture_output=True, text=True,
                          timeout=30)
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def test_rejects_missing_or_bad_mac(tmp_path):
    for args in ([], ["not-a-mac"], ["AA:BB:CC:00:11"]):
        proc, calls = _run(tmp_path, *args)
        assert proc.returncode == 2
        assert "Usage" in proc.stdout + proc.stderr
        assert calls == []


def test_sets_lan_and_reservation(tmp_path):
    proc, calls = _run(tmp_path, MAC)
    assert proc.returncode == 0, proc.stderr
    assert "uci set network.lan.ipaddr=10.0.0.1" in calls
    assert "uci set network.lan.netmask=255.255.255.0" in calls
    assert "uci set dhcp.frca_laptop=host" in calls
    assert "uci set dhcp.frca_laptop.mac=aa:bb:cc:00:11:22" in calls
    assert "uci set dhcp.frca_laptop.ip=10.0.0.2" in calls
    assert "uci commit" in calls
    assert calls[-2:] == ["network restart", "dnsmasq restart"]


def test_without_flag_removes_captive_portal_entries(tmp_path):
    _, calls = _run(tmp_path, MAC)
    assert "uci del_list dhcp.@dnsmasq[0].address=/#/10.0.0.2" in calls
    assert "uci del_list dhcp.lan.dhcp_option=114,http://10.0.0.2/api/captive-portal" in calls
    assert not any(c.startswith("uci add_list") for c in calls)


def test_captive_portal_flag_replaces_not_duplicates(tmp_path):
    _, calls = _run(tmp_path, MAC, "--captive-portal")
    wildcard = "dhcp.@dnsmasq[0].address=/#/10.0.0.2"
    option = "dhcp.lan.dhcp_option=114,http://10.0.0.2/api/captive-portal"
    for entry in (wildcard, option):
        assert calls.index("uci del_list " + entry) < calls.index("uci add_list " + entry)


def test_rejects_unknown_flag(tmp_path):
    proc, calls = _run(tmp_path, MAC, "--captive")
    assert proc.returncode == 2
    assert calls == []
