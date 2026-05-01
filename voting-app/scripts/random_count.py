"""
Simulate paper-ballot counting helpers via the actual HTTP endpoints.

Each simulated helper:
  1. Authenticates by injecting a Flask session cookie signed with the
     server's secret key (same effect as having voted via /vote/submit,
     without needing voting to be open and without burning a code)
  2. POSTs /count/join to register as a counter helper
  3. Taps candidates via POST /count/<sid>/tap as the chairman reads ballots

This exercises the live code path (CSRF, /count/join, the lazy
helper-row-on-first-tap, atomic tally updates) the same way real phones
do, but without the artificial constraint that voting must be open. In
real life voting is typically already CLOSED before paper counting
starts, so the simulator must work in that state too.

Pre-conditions:
  - Server running
  - Election has paper_count_enabled = 1
  - data/.secret_key readable (used to sign session cookies)
  - At least --helpers codes (used or unused) present for this election

Default behaviour with no arguments:
  - 20 helpers, all in perfect agreement (no miscounts)
  - ballot count taken from "still to vote" if voting is open, else from
    --ballots (required when voting is closed)

Optional flags:
  --url URL          server base URL (default: http://localhost:5000)
  --ballots N        number of paper ballots to simulate
  --helpers H        number of helpers to simulate (default: 20)
  --error-rate F     per-tick probability a helper skips the tap (default: 0.0)
  --workers W        concurrent HTTP threads (default: 16)
  --db PATH          SQLite DB path (default: data/frca_election.db)
  --secret-key PATH  path to .secret_key file (default: <db dir>/.secret_key)
  --seed N           random seed for reproducible ballots
"""

import argparse
import os
import random
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required.  Install with:  pip install requests")
    sys.exit(1)

try:
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface
    from itsdangerous import URLSafeTimedSerializer
except ImportError:
    print("ERROR: 'flask' and 'itsdangerous' packages required.")
    sys.exit(1)

import hashlib


def parse_args():
    p = argparse.ArgumentParser(
        description="Simulate paper counting via the live HTTP endpoints."
    )
    p.add_argument("--url", "-u", default="http://localhost:5000")
    p.add_argument("--ballots", "-n", type=int, default=None,
                   help="Number of paper ballots (default: 'still to vote' from /api/display-data, after helpers have voted)")
    p.add_argument("--helpers", "-H", type=int, default=20,
                   help="Number of helpers to simulate (default: 20)")
    p.add_argument("--error-rate", "-e", type=float, default=0.0,
                   help="Per-tick probability a helper skips the tap (default: 0.0)")
    p.add_argument("--workers", "-w", type=int, default=16,
                   help="Concurrent HTTP threads (default: 16)")
    p.add_argument("--pace", "-p", type=float, default=0.15,
                   help="Seconds between taps per helper (default: 0.15 - keeps load realistic)")
    p.add_argument("--db", default="data/frca_election.db")
    p.add_argument("--secret-key", default=None,
                   help="Path to .secret_key file (default: <db dir>/.secret_key)")
    p.add_argument("--seed", "-s", type=int, default=None)
    return p.parse_args()


def load_signers(secret_key_path):
    """Build the two serializers we need:
      - session_ser: signs Flask session cookies (used to inject
        {used_code, election_id, csrf_token} into the helper's session)
      - csrf_ser: signs/loads Flask-WTF csrf_token form values

    Pre-populating both lets the simulator authenticate AND pass CSRF
    in a single POST, no GET round-trip needed.
    """
    if not os.path.exists(secret_key_path):
        print(f"  ERROR  : secret key not found: {secret_key_path}")
        sys.exit(1)
    with open(secret_key_path, "r") as f:
        secret = f.read().strip()
    fake_app = Flask("random_count_sim")
    fake_app.secret_key = secret
    session_ser = SecureCookieSessionInterface().get_signing_serializer(fake_app)
    csrf_ser = URLSafeTimedSerializer(secret, salt="wtf-csrf-token")
    return session_ser, csrf_ser


def weighted_sample(items, weights, k):
    pool = list(zip(items, weights))
    selected = []
    for _ in range(min(k, len(pool))):
        total = sum(w for _, w in pool)
        if total <= 0:
            break
        r = random.uniform(0, total)
        cumsum = 0
        for i, (item, w) in enumerate(pool):
            cumsum += w
            if cumsum >= r:
                selected.append(item)
                pool.pop(i)
                break
    return selected


def preflight(base_url):
    try:
        requests.get(f"{base_url}/", timeout=5)
    except requests.ConnectionError:
        print(f"  ERROR  : Cannot connect to {base_url}")
        sys.exit(1)
    try:
        data = requests.get(f"{base_url}/api/display-data", timeout=5).json()
    except Exception as e:
        print(f"  ERROR  : Cannot read /api/display-data: {e}")
        sys.exit(1)
    if not data.get("active"):
        print("  ERROR  : No active election.")
        sys.exit(1)
    return data


def load_db_info(db_path):
    if not os.path.exists(db_path):
        print(f"  ERROR  : DB file not found: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    election = conn.execute(
        "SELECT * FROM elections ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not election:
        print("  ERROR  : No election found.")
        sys.exit(1)
    if not election["paper_count_enabled"]:
        print("  ERROR  : paper_count_enabled is 0 on this election.")
        sys.exit(1)
    # The simulator no longer burns codes (auth is via injected session
    # cookie), so any plaintext code from this election is fine. Prefer
    # used codes when available because they correspond to brothers who
    # actually voted, matching reality more closely.
    codes = conn.execute(
        "SELECT plaintext FROM codes WHERE election_id = ? "
        "AND plaintext != '' ORDER BY used DESC, id",
        (election["id"],),
    ).fetchall()
    cand_rows = conn.execute(
        "SELECT c.id AS cid, c.office_id, o.max_selections, o.sort_order "
        "FROM candidates c JOIN offices o ON c.office_id = o.id "
        "WHERE o.election_id = ? AND c.active = 1 "
        "ORDER BY o.sort_order, c.id",
        (election["id"],),
    ).fetchall()
    conn.close()
    by_office = {}
    for r in cand_rows:
        if r["office_id"] not in by_office:
            by_office[r["office_id"]] = {
                "max": r["max_selections"],
                "sort": r["sort_order"],
                "cand_ids": [],
            }
        by_office[r["office_id"]]["cand_ids"].append(r["cid"])
    offices = sorted(by_office.values(), key=lambda o: o["sort"])
    return {
        "election": dict(election),
        "codes": [r["plaintext"] for r in codes],
        "offices": offices,
    }


def setup_helper(base_url, code, election_id, session_ser, csrf_ser):
    """Authenticate via direct session-cookie injection, then POST /count/join.
    Returns ((http_session, count_session_id), "OK") or (None, reason)."""
    s = requests.Session()
    try:
        # Generate a raw CSRF token (random hex), pre-populate it in the
        # session under the key Flask-WTF expects ('csrf_token'), and sign
        # it with the wtf-csrf-token salt to produce the matching form
        # value. /count/join's CSRF check then passes without needing a
        # prior GET to bootstrap a token in the session.
        raw_csrf = hashlib.sha1(os.urandom(64)).hexdigest()
        cookie_value = session_ser.dumps({
            "used_code": code,
            "election_id": election_id,
            "csrf_token": raw_csrf,
        })
        s.cookies.set("session", cookie_value)
        signed_csrf = csrf_ser.dumps(raw_csrf)

        resp = s.post(
            f"{base_url}/count/join",
            data={"csrf_token": signed_csrf},
            allow_redirects=True, timeout=10,
        )
        m = re.search(r"/count/(\d+)$", resp.url)
        if not m:
            body = (resp.text or "")[:160].replace("\n", " ")
            return None, (f"join did not redirect to /count/<sid> "
                          f"(status {resp.status_code}, body: {body!r})")
        return (s, int(m.group(1))), "OK"
    except requests.ConnectionError:
        return None, "SERVER_DOWN"
    except requests.Timeout:
        return None, "Timeout"
    except Exception as e:
        return None, f"Error: {e}"


def helper_tap(s, base_url, session_id, candidate_id):
    try:
        r = s.post(
            f"{base_url}/count/{session_id}/tap",
            json={"candidate_id": candidate_id, "delta": 1},
            timeout=10,
        )
        return r.status_code == 200, r.status_code
    except Exception as e:
        return False, str(e)


def helper_tap_ballot(s, base_url, session_id, ticks, error_rate, pace):
    """Tap each tick for one helper, sequentially - requests.Session is not
    thread-safe so we never let two threads share one helper's Session.
    Sleeps `pace` seconds between taps to mimic human cadence and keep the
    server responsive for real voters running concurrently."""
    okays = 0
    fails = 0
    misses = 0
    for i, cid in enumerate(ticks):
        if i > 0 and pace > 0:
            # Jitter +/- 30% so all helpers don't fire in lockstep.
            time.sleep(pace * random.uniform(0.7, 1.3))
        if random.random() < error_rate:
            misses += 1
            continue
        ok, _ = helper_tap(s, base_url, session_id, cid)
        if ok:
            okays += 1
        else:
            fails += 1
    return okays, fails, misses


def main():
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    base_url = args.url.rstrip("/")
    print(f"\n  Server  : {base_url}")
    preflight(base_url)
    info = load_db_info(args.db)

    secret_key_path = args.secret_key or os.path.join(
        os.path.dirname(os.path.abspath(args.db)), ".secret_key"
    )
    session_ser, csrf_ser = load_signers(secret_key_path)

    available = info["codes"]
    if len(available) < args.helpers:
        print(f"  ERROR  : Only {len(available)} codes for this election; need {args.helpers}")
        sys.exit(1)
    helper_codes = available[:args.helpers]
    election_id = info["election"]["id"]

    print(f"  Election: {info['election']['name']}")
    print(f"  Helpers : {args.helpers} (auth via injected session cookies, no codes burned)")
    print(f"  Error   : {args.error_rate:.1%} per tick per helper")
    print(f"  Pace    : {args.pace * 1000:.0f}ms between taps per helper (+/- 30% jitter)")
    print(f"  Workers : {args.workers}")
    print()

    # Phase 1 - set up helpers (cookie inject + join) in parallel
    print("  Setting up helpers (session inject + count/join)...")
    t0 = time.time()
    helpers = []
    setup_failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [
            ex.submit(setup_helper, base_url, code, election_id, session_ser, csrf_ser)
            for code in helper_codes
        ]
        for fut in as_completed(futures):
            res, msg = fut.result()
            if res is None:
                setup_failed += 1
                print(f"    helper failed: {msg}")
            else:
                helpers.append(res)
    print(f"  Helpers ready: {len(helpers)}  ({setup_failed} failed)  in {time.time()-t0:.1f}s")
    if not helpers:
        print("  ERROR  : No helpers ready, aborting.")
        sys.exit(1)

    # Determine ballot count. With voting open we estimate from
    # "still to vote"; with voting closed we use the actual
    # paper_ballot_count the chairman entered on the Count & tally step.
    if args.ballots is not None:
        ballots = args.ballots
        print(f"  Ballots : {ballots} (from --ballots)")
    else:
        try:
            data = requests.get(f"{base_url}/api/display-data", timeout=5).json()
        except Exception as e:
            print(f"  ERROR  : Cannot read /api/display-data: {e}")
            sys.exit(1)
        if data.get("voting_open"):
            participants = data.get("participants") or 0
            used = data.get("used_codes") or 0
            paper = data.get("paper_ballot_count") or 0
            postal = data.get("postal_voter_count") or 0
            ballots = max(0, participants - used - paper - postal)
            print(f"  Ballots : {ballots} (still to vote: "
                  f"{participants} - {used} digital - {paper} paper - {postal} postal)")
        else:
            ballots = data.get("paper_ballot_count") or 0
            print(f"  Ballots : {ballots} (paper_ballot_count from admin)")
    if ballots <= 0:
        print("  Nothing to simulate. Use --ballots N to force a count.")
        sys.exit(0)

    # Generate per-candidate weights for realistic ballot distributions
    weights = {}
    for o in info["offices"]:
        for cid in o["cand_ids"]:
            weights[cid] = random.uniform(0.2, 1.0)

    # Phase 2 - simulate ballots being read aloud. One thread per helper
    # (parallel across helpers, sequential within a helper's Session).
    print(f"\n  Reading {ballots} paper ballots...")
    t0 = time.time()
    total_taps = 0
    total_skipped = 0
    failed_taps = 0
    for b in range(ballots):
        ticks = []
        for o in info["offices"]:
            cand_ids = o["cand_ids"]
            if not cand_ids:
                continue
            n = o["max"] if random.random() < 0.95 else random.randint(1, o["max"])
            ticks.extend(weighted_sample(cand_ids, [weights[c] for c in cand_ids], n))

        with ThreadPoolExecutor(max_workers=min(args.workers, len(helpers))) as ex:
            futures = [
                ex.submit(helper_tap_ballot, s, base_url, sid, ticks,
                          args.error_rate, args.pace)
                for s, sid in helpers
            ]
            for fut in as_completed(futures):
                ok, fail, miss = fut.result()
                total_taps += ok
                failed_taps += fail
                total_skipped += miss

        if (b + 1) % 5 == 0 or b == ballots - 1:
            elapsed = time.time() - t0
            rate = (b + 1) / elapsed if elapsed > 0 else 0
            print(f"    {b+1}/{ballots} ballots  ({rate:.1f} b/s, {total_taps} taps, {failed_taps} failed)")

    elapsed = time.time() - t0
    print(f"\n  Done    : {ballots} ballots, {total_taps} taps OK, "
          f"{total_skipped} miscounted, {failed_taps} failed  in {elapsed:.1f}s")
    print(f"  View    : {base_url}/admin/election/{info['election']['id']}"
          f"/count/{info['election']['current_round']}")


if __name__ == "__main__":
    main()
