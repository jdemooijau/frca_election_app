"""Tests for the installed-app launcher's port handling."""

import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from launcher import plan_listen, port_is_free, port80_report


def test_plan_listen_both_free():
    assert plan_listen(True, True) == ("0.0.0.0:80 0.0.0.0:5000", [])


def test_plan_listen_80_taken():
    listen, messages = plan_listen(False, True)
    assert listen == "0.0.0.0:5000"
    assert "Port 80 is in use" in "\n".join(messages)


def test_port80_report_forwarded_to_this_app():
    text = "\n".join(port80_report(True))
    assert "forwards to this app" in text
    assert "NOT" not in text


def test_port80_report_blocked():
    text = "\n".join(port80_report(False))
    assert "http://10.0.0.2 will NOT reach the app" in text
    assert "netstat -ano | findstr :80" in text
    assert "captive-portal-off.bat" in text


def test_plan_listen_5000_taken():
    listen, messages = plan_listen(True, False)
    assert listen is None
    text = "\n".join(messages)
    assert "Port 5000 is in use" in text
    assert "another copy" in text


def test_plan_listen_both_taken_does_not_start():
    listen, _ = plan_listen(False, False)
    assert listen is None


def test_port_is_free_detects_taken():
    sock = socket.socket()
    sock.bind(("0.0.0.0", 0))
    sock.listen(1)
    try:
        assert port_is_free(sock.getsockname()[1]) is False
    finally:
        sock.close()


def test_port_is_free_on_unused_port():
    sock = socket.socket()
    sock.bind(("0.0.0.0", 0))
    port = sock.getsockname()[1]
    sock.close()
    assert port_is_free(port) is True


def test_main_keeps_window_open_on_startup_error(monkeypatch, capsys):
    import launcher

    def boom():
        raise PermissionError("data folder not writable")

    waited = []
    monkeypatch.setattr(launcher, "_run", boom)
    monkeypatch.setattr(launcher, "_wait_for_enter", lambda: waited.append(True))
    assert launcher.main() == 1
    out = capsys.readouterr().out
    assert "The app could not start" in out
    assert "data folder not writable" in out
    assert waited == [True]
