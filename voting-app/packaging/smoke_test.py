"""Smoke test for the frozen build: python smoke_test.py <path to FRCA-Election.exe>

Starts the exe against a temp data folder (with a space in its name), then
checks the voter and admin pages, the bundled docs, and that ReportLab can
produce PDFs inside the bundle. Exit code 0 means PASS.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import requests

BASE = "http://127.0.0.1:5000"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(session, path):
    match = CSRF_RE.search(session.get(BASE + path).text)
    assert match, "no CSRF token on " + path
    return match.group(1)


def _wait_until_up(proc, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError("exe exited early with code %s" % proc.returncode)
        try:
            if requests.get(BASE + "/", timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise AssertionError("app did not answer on :5000 within %d s" % seconds)


def run(exe_path):
    root = tempfile.mkdtemp(prefix="frca smoke ")
    data_dir = os.path.join(root, "data dir")
    env = dict(os.environ, FRCA_DATA_DIR=data_dir, BROWSER="echo")
    env.pop("FRCA_DB_PATH", None)
    log_path = os.path.join(root, "exe.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([exe_path], env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL)
    try:
        _wait_until_up(proc)
        s = requests.Session()
        assert s.get(BASE + "/").status_code == 200
        assert s.get(BASE + "/admin/login").status_code == 200

        s.post(BASE + "/admin/login",
               data={"password": "admin", "csrf_token": _csrf(s, "/admin/login")})
        token = _csrf(s, "/admin/election/new")
        s.post(BASE + "/admin/election/new",
               data={"name": "Smoke", "max_rounds": "2", "csrf_token": token})
        for path in ("/admin/election/1/counter-sheet-pdf",
                     "/admin/election/1/results-pdf"):
            resp = s.get(BASE + path)
            assert resp.content[:5] == b"%PDF-", path + " did not return a PDF"
        proposal = s.get(BASE + "/admin/council-proposal")
        assert proposal.status_code == 200 and "<h1" in proposal.text, "council proposal missing"

        for name in ("frca_election.db", "last_version.txt", ".secret_key"):
            assert os.path.exists(os.path.join(data_dir, name)), name + " not in data folder"
        print("PASS")
        return 0
    except AssertionError as exc:
        print("FAIL: %s" % exc)
        log.flush()
        with open(log_path) as f:
            print(f.read()[-3000:])
        return 1
    finally:
        proc.kill()
        proc.wait()
        log.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
