"""
Cast random ballots for every unused voting code in the active election.

Default behaviour with no arguments:
  - reads data/frca_election.db (relative to the voting-app dir)
  - finds the active election + its unused plaintext codes
  - casts one random ballot per unused code against http://localhost:5000
  - prints a tally summary

Pre-conditions: the server is running and voting is open (display phase 3).
The script does not log in as admin or change election state.

Optional flags:
  --url URL          server base URL (default: http://localhost:5000)
  --workers N        concurrent voter threads (default: 8)
  --db PATH          SQLite DB path (default: data/frca_election.db)
  --seed N           random seed for reproducible vote distributions
  --blank-rate F     probability of a blank vote per office (default: 0.05)
"""

import argparse
import os
import queue
import random
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required.  Install with:  pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Cast random ballots for every unused code in the active election.",
    )
    p.add_argument("--url", "-u", default="http://localhost:5000",
                   help="Server base URL (default: http://localhost:5000)")
    p.add_argument("--workers", "-w", type=int, default=8,
                   help="Concurrent voter threads (default: 8)")
    p.add_argument("--db", default="data/frca_election.db",
                   help="SQLite DB path (default: data/frca_election.db)")
    p.add_argument("--seed", "-s", type=int, default=None,
                   help="Random seed for reproducible vote distributions")
    p.add_argument("--blank-rate", "-b", type=float, default=0.05,
                   help="Probability of a blank vote per office (default: 0.05)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def extract_csrf_token(html):
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    return match.group(1) if match else None


def extract_ballot(html):
    offices = []
    blocks = re.split(r'<div class="ballot-office">', html)[1:]
    for block in blocks:
        max_match = re.search(r'\(select\s+(\d+)\)', block, re.IGNORECASE)
        max_sel = int(max_match.group(1)) if max_match else 1

        field_ids = re.findall(r'name="(office_\d+)"\s+value="(\d+)"', block)
        if field_ids:
            field = field_ids[0][0]
            cand_ids = [cid for _, cid in field_ids]
            offices.append({"field": field, "max": max_sel, "cand_ids": cand_ids})
    return offices


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


# ---------------------------------------------------------------------------
# Code source
# ---------------------------------------------------------------------------

def load_unused_codes(db_path):
    if not os.path.exists(db_path):
        print(f"  ERROR   : DB file not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        eid_row = conn.execute(
            "SELECT id FROM elections ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if eid_row is None:
            print(f"  ERROR   : No election found in {db_path}")
            sys.exit(1)
        rows = conn.execute(
            "SELECT plaintext FROM codes WHERE election_id = ? AND used = 0 "
            "AND plaintext != '' ORDER BY id",
            (eid_row["id"],),
        ).fetchall()
    finally:
        conn.close()

    codes = [r["plaintext"] for r in rows]
    if not codes:
        print(f"  ERROR   : No unused codes in {db_path}")
        sys.exit(1)
    return codes


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight(base_url):
    try:
        requests.get(f"{base_url}/", timeout=5)
    except requests.ConnectionError:
        print(f"  ERROR   : Cannot connect to {base_url}")
        print("            Start the server first.")
        sys.exit(1)

    try:
        data = requests.get(f"{base_url}/api/display-data", timeout=5).json()
    except Exception as e:
        print(f"  ERROR   : Cannot read /api/display-data: {e}")
        sys.exit(1)

    if not data.get("active"):
        print("  ERROR   : No active election.")
        sys.exit(1)
    if not data.get("voting_open"):
        print("  ERROR   : Voting is not open.")
        print("            Advance the projector display to phase 3 (Voting) in admin.")
        sys.exit(1)
    print(f"  Voting  : OPEN (display phase {data.get('display_phase')})")
    return data


def expected_digital_voters(display_data):
    """Compute how many additional digital ballots are still expected.

    Returns None if chairman has not set attendance (caller should fall back
    to "use every unused code"). Subtracts digital ballots already cast so the
    script tops up the room rather than filling on top of existing votes.
    """
    participants = display_data.get("participants") or 0
    if participants <= 0:
        return None
    postal = display_data.get("postal_voter_count") or 0
    paper = display_data.get("paper_ballot_count") or 0
    already = display_data.get("used_codes") or 0
    return max(0, participants - postal - paper - already)


# ---------------------------------------------------------------------------
# Voter simulation
# ---------------------------------------------------------------------------

def simulate_voter(base_url, code, candidate_weights, weights_lock, blank_rate):
    try:
        return _simulate_voter_inner(base_url, code, candidate_weights, weights_lock, blank_rate)
    except requests.ConnectionError:
        return False, "SERVER_DOWN"
    except requests.Timeout:
        return False, "Timeout"
    except Exception as e:
        return False, f"Error: {e}"


def _simulate_voter_inner(base_url, code, candidate_weights, weights_lock, blank_rate):
    s = requests.Session()

    resp = s.get(f"{base_url}/", timeout=10)
    csrf = extract_csrf_token(resp.text)
    if not csrf:
        return False, "No CSRF on enter-code page"

    resp = s.post(
        f"{base_url}/vote",
        data={"csrf_token": csrf, "code": code},
        allow_redirects=True,
        timeout=10,
    )
    if "/ballot" not in resp.url:
        if "valid 6-character code" in resp.text:
            return False, f"Invalid code: {code}"
        if "already been used" in resp.text.lower():
            return False, f"Already-used code: {code}"
        return False, "Not redirected to ballot"

    csrf = extract_csrf_token(resp.text)
    offices = extract_ballot(resp.text)
    if not offices or not csrf:
        return False, "Could not parse ballot"

    with weights_lock:
        for office in offices:
            for cid in office["cand_ids"]:
                if cid not in candidate_weights:
                    candidate_weights[cid] = random.uniform(0.2, 1.0)

    form_data = [("csrf_token", csrf), ("confirm_partial", "1")]
    for office in offices:
        if random.random() < blank_rate:
            continue
        max_sel = office["max"]
        cand_ids = office["cand_ids"]
        with weights_lock:
            weights = [candidate_weights.get(cid, 0.5) for cid in cand_ids]
        count = max_sel if random.random() < 0.85 else random.randint(1, max_sel)
        selected = weighted_sample(cand_ids, weights, count)
        for cid in selected:
            form_data.append((office["field"], cid))

    resp = s.post(
        f"{base_url}/submit",
        data=form_data,
        allow_redirects=True,
        timeout=10,
    )
    if "/confirmation" in resp.url:
        return True, "OK"
    return False, "Submit did not reach confirmation"


# ---------------------------------------------------------------------------
# Progress + summary
# ---------------------------------------------------------------------------

BAR_WIDTH = 30


def progress_line(current, total, failed, elapsed):
    pct = current / total if total else 0
    filled = int(BAR_WIDTH * pct)
    bar = "#" * filled + "." * (BAR_WIDTH - filled)
    rate = current / elapsed if elapsed > 0 else 0
    return (
        f"\r  [{current:>{len(str(total))}}/{total}] {bar} "
        f"{pct:5.1%}  {rate:.1f} v/s  ({failed} failed)"
    )


def print_results(base_url):
    try:
        data = requests.get(f"{base_url}/api/display-data", timeout=5).json()
    except Exception:
        return
    if not data.get("active"):
        return

    print(f"\n  Election : {data.get('election_name', '?')}")
    print(f"  Round    : {data.get('current_round', '?')}")
    print(f"  Digital  : {data.get('used_codes', 0)} ballots")
    print(f"  Total    : {data.get('total_ballots', 0)} ballots")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    base_url = args.url.rstrip("/")
    print(f"\n  Server  : {base_url}")

    display_data = preflight(base_url)

    codes = load_unused_codes(args.db)
    expected = expected_digital_voters(display_data)

    if expected is None:
        cast_count = len(codes)
        print(f"  Codes   : {len(codes)} unused (no attendance set — will cast all)")
    elif expected >= len(codes):
        cast_count = len(codes)
        print(f"  Codes   : {len(codes)} unused, expected {expected} digital voters — will cast all")
    else:
        cast_count = expected
        print(f"  Codes   : {len(codes)} unused, but only {expected} digital voters expected — will cast {expected}")

    if cast_count == 0:
        print("  Nothing to cast.")
        return

    codes_q = queue.Queue()
    for c in codes[:cast_count]:
        codes_q.put(c)

    print(f"  Workers : {args.workers}")

    candidate_weights = {}
    weights_lock = threading.Lock()
    counter = [0, 0]
    start = time.time()
    fail_reasons = {}
    total = cast_count

    def take_code():
        try:
            return codes_q.get_nowait()
        except queue.Empty:
            return None

    def voter_task():
        c = take_code()
        if c is None:
            return False, "NO_MORE_CODES"
        return simulate_voter(base_url, c, candidate_weights, weights_lock, args.blank_rate)

    print()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(voter_task) for _ in range(total)]
        for future in as_completed(futures):
            ok, msg = future.result()
            if ok:
                counter[0] += 1
            else:
                counter[1] += 1
                fail_reasons[msg] = fail_reasons.get(msg, 0) + 1
            elapsed = time.time() - start
            sys.stdout.write(progress_line(sum(counter), total, counter[1], elapsed))
            sys.stdout.flush()

    elapsed = time.time() - start
    print()
    rate = counter[0] / elapsed if elapsed > 0 else 0
    print(f"\n  Done in {elapsed:.1f}s  -  {counter[0]} OK / {counter[1]} failed  ({rate:.1f} v/s)")

    if fail_reasons:
        print("\n  Failure reasons:")
        for reason, n in sorted(fail_reasons.items(), key=lambda kv: -kv[1]):
            print(f"    {n:>4}  {reason}")

    print_results(base_url)
    print(f"\n  View live: {base_url}/display\n")


if __name__ == "__main__":
    main()
