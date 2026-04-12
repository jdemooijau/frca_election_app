"""
Load test: simulate voters hitting a running FRCA election server.

Casts votes through the real HTTP flow (/vote -> /ballot -> /submit) so
results appear live on the /display page.  Requires demo mode enabled.

Usage:
    # 1. Seed a demo election with enough codes
    python scripts/seed_demo.py --codes 100

    # 2. Start the server
    python app.py

    # 3. In another terminal, run the load test
    python scripts/load_test.py                        # 95 voters, 0.2s delay
    python scripts/load_test.py --voters 100           # 100 voters
    python scripts/load_test.py --delay 2              # slow — watch /display live
    python scripts/load_test.py --delay 0              # burst mode (no delay)
    python scripts/load_test.py --url http://10.0.0.5:5000  # custom server
"""

import argparse
import random
import re
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required.  Install with:  pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def extract_csrf_token(html):
    """Extract the CSRF token from a rendered page."""
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    return match.group(1) if match else None


def extract_ballot(html):
    """Parse offices, max selections, and candidates from ballot HTML.

    Returns a list of dicts:
        [{"field": "office_1", "max": 2,
          "candidates": [{"id": "3", "name": "Pieter van Rijksen"}, ...]}, ...]
    """
    offices = []
    blocks = re.split(r'<div class="ballot-office">', html)[1:]
    for block in blocks:
        # Office name
        name_match = re.search(r'<h2 class="ballot-office-title">([^<]+)</h2>', block)
        office_name = name_match.group(1).strip() if name_match else "?"

        # Max selections
        max_match = re.search(r'Select up to (\d+)', block)
        max_sel = int(max_match.group(1)) if max_match else 1

        # Candidates: field name, id, display name
        field_ids = re.findall(r'name="(office_\d+)"\s+value="(\d+)"', block)
        names = re.findall(r'class="ballot-option-text">([^<]+)<', block)

        if field_ids:
            field = field_ids[0][0]
            candidates = []
            for i, (_, cid) in enumerate(field_ids):
                cname = names[i].strip() if i < len(names) else f"Candidate {cid}"
                candidates.append({"id": cid, "name": cname})
            offices.append({
                "field": field,
                "max": max_sel,
                "office_name": office_name,
                "candidates": candidates,
            })
    return offices


# ---------------------------------------------------------------------------
# Weighted sampling (without replacement)
# ---------------------------------------------------------------------------

def weighted_sample(items, weights, k):
    """Pick *k* items without replacement, biased by *weights*."""
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
# Voter simulation
# ---------------------------------------------------------------------------

def simulate_voter(base_url, candidate_weights, blank_rate=0.05):
    """Run one voter through the full /vote -> /ballot -> /submit flow.

    *candidate_weights* is a shared dict {candidate_id: float} populated
    on first encounter so that every voter in a run shares the same
    popularity distribution.

    Returns (success: bool, message: str).
    """
    try:
        return _simulate_voter_inner(base_url, candidate_weights, blank_rate)
    except requests.ConnectionError:
        return False, "SERVER_DOWN"
    except requests.Timeout:
        return False, "Timeout"
    except Exception as e:
        return False, f"Error: {e}"


def _simulate_voter_inner(base_url, candidate_weights, blank_rate):
    s = requests.Session()

    # 1. GET the enter-code page (pick up session cookie + CSRF token)
    resp = s.get(f"{base_url}/", timeout=10)
    csrf = extract_csrf_token(resp.text)
    if not csrf:
        return False, "No CSRF on enter-code page"

    # 2. POST /vote with a blank code — demo mode auto-assigns an unused code
    resp = s.post(
        f"{base_url}/vote",
        data={"csrf_token": csrf, "code": ""},
        allow_redirects=True,
        timeout=10,
    )
    if "/ballot" not in resp.url:
        if "All demo codes have been used" in resp.text:
            return False, "OUT_OF_CODES"
        if "valid 6-character code" in resp.text:
            return False, "NOT_DEMO_MODE"
        return False, "Not redirected to ballot"

    # 3. Parse the ballot
    csrf = extract_csrf_token(resp.text)
    offices = extract_ballot(resp.text)
    if not offices or not csrf:
        return False, "Could not parse ballot"

    # Assign popularity weights to any candidates we haven't seen yet
    for office in offices:
        for cand in office["candidates"]:
            if cand["id"] not in candidate_weights:
                candidate_weights[cand["id"]] = random.uniform(0.2, 1.0)

    # 4. Build vote selections
    form_data = [("csrf_token", csrf), ("confirm_partial", "1")]

    for office in offices:
        # Small chance of a blank vote for this office
        if random.random() < blank_rate:
            continue

        max_sel = office["max"]
        cand_ids = [c["id"] for c in office["candidates"]]
        weights = [candidate_weights[cid] for cid in cand_ids]

        # 85 % of voters use all their selections, 15 % under-select
        count = max_sel if random.random() < 0.85 else random.randint(1, max_sel)
        selected = weighted_sample(cand_ids, weights, count)

        for cid in selected:
            form_data.append((office["field"], cid))

    # 5. Submit the ballot
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
# Progress bar
# ---------------------------------------------------------------------------

BAR_WIDTH = 30


def progress_line(current, total, failed, elapsed):
    """Return a single-line progress string."""
    pct = current / total if total else 0
    filled = int(BAR_WIDTH * pct)
    bar = "\u2588" * filled + "\u2591" * (BAR_WIDTH - filled)
    rate = current / elapsed if elapsed > 0 else 0
    return f"\r  [{current:>{len(str(total))}}/{total}] {bar} {pct:5.1%}  {rate:.1f} v/s  ({failed} failed)"


# ---------------------------------------------------------------------------
# Results summary
# ---------------------------------------------------------------------------

def print_results(base_url):
    """Fetch /api/display-data and print vote tallies."""
    try:
        resp = requests.get(f"{base_url}/api/display-data", timeout=5)
        data = resp.json()
    except Exception:
        return

    if not data.get("active"):
        return

    print(f"\n  Election : {data.get('election_name', '?')}")
    print(f"  Round    : {data.get('current_round', '?')}")
    print(f"  Digital  : {data.get('used_codes', 0)} ballots")
    print(f"  Paper    : {data.get('paper_ballot_count', 0)} ballots")
    print(f"  Postal   : {data.get('postal_voter_count', 0)} ballots")
    print(f"  Total    : {data.get('total_ballots', 0)} ballots")

    results = data.get("results", [])
    if results:
        print()
        for office in results:
            print(f"  --- {office['office_name']} ---")
            for c in sorted(office.get("candidates", []), key=lambda x: x.get("total", 0), reverse=True):
                mark = " *" if c.get("elected") else ""
                print(f"    {c['name']:<30s}  {c.get('total', 0):>4} votes{mark}")
    else:
        print("\n  (Results not yet visible — toggle Show Results in admin to see tallies)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Load-test an FRCA election server by simulating voters",
    )
    parser.add_argument(
        "--voters", "-n", type=int, default=95,
        help="Number of voters to simulate (default: 95)",
    )
    parser.add_argument(
        "--delay", "-d", type=float, default=0.2,
        help="Seconds between votes — 0 for burst mode (default: 0.2)",
    )
    parser.add_argument(
        "--url", "-u", default="http://localhost:5000",
        help="Base URL of the running server (default: http://localhost:5000)",
    )
    parser.add_argument(
        "--blank-rate", "-b", type=float, default=0.05,
        help="Probability of a blank vote per office (default: 0.05)",
    )
    parser.add_argument(
        "--seed", "-s", type=int, default=None,
        help="Random seed for reproducible vote distributions",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    base_url = args.url.rstrip("/")

    # --- Pre-flight checks ---------------------------------------------------

    print(f"\n  Server : {base_url}")
    try:
        resp = requests.get(f"{base_url}/", timeout=5)
    except requests.ConnectionError:
        print(f"  ERROR  : Cannot connect to {base_url}")
        print("           Start the server first:  python app.py")
        sys.exit(1)

    # Check demo mode via the enter-code page (it shows "Demo mode:" hint)
    is_demo = 'demo mode' in resp.text.lower() or 'pattern="[A-Za-z0-9]{0,6}"' in resp.text
    if not is_demo:
        print("  ERROR  : Server is NOT in demo mode.")
        print("           This script requires demo mode (blank codes are auto-assigned).")
        print("           Seed a demo first:  python scripts/seed_demo.py --codes 100")
        sys.exit(1)

    # Check voting is open
    if "Voting is not currently open" in resp.text:
        print("  ERROR  : Voting is not open. Open voting from the admin panel first.")
        sys.exit(1)

    print(f"  Mode   : DEMO")
    print(f"  Voters : {args.voters}")
    print(f"  Delay  : {args.delay}s between votes")
    print(f"  Blank  : {args.blank_rate * 100:.0f}% chance per office")
    if args.seed is not None:
        print(f"  Seed   : {args.seed}")

    # --- Cast votes -----------------------------------------------------------

    candidate_weights = {}  # shared across all voters, populated lazily
    success_count = 0
    fail_count = 0
    total = args.voters

    print()
    start = time.time()

    for i in range(1, total + 1):
        if i > 1 and args.delay > 0:
            time.sleep(args.delay)

        ok, msg = simulate_voter(base_url, candidate_weights, args.blank_rate)
        if ok:
            success_count += 1
        else:
            fail_count += 1
            if msg == "OUT_OF_CODES":
                elapsed = time.time() - start
                sys.stdout.write(progress_line(i, total, fail_count, elapsed))
                print(f"\n\n  Ran out of demo codes after {success_count} votes.")
                print("  Generate more:  python scripts/seed_demo.py --codes <N>")
                break
            if msg == "SERVER_DOWN":
                elapsed = time.time() - start
                sys.stdout.write(progress_line(i, total, fail_count, elapsed))
                print(f"\n\n  Server stopped responding after {success_count} votes.")
                print("  The server may have crashed — check its console output.")
                break
            if msg == "NOT_DEMO_MODE":
                elapsed = time.time() - start
                sys.stdout.write(progress_line(i, total, fail_count, elapsed))
                print("\n\n  Server is not in demo mode — blank codes are rejected.")
                print("  Seed a demo first:  python scripts/seed_demo.py --codes 100")
                break

        elapsed = time.time() - start
        sys.stdout.write(progress_line(i, total, fail_count, elapsed))
        sys.stdout.flush()

    elapsed = time.time() - start

    # --- Summary --------------------------------------------------------------

    print(f"\n\n  Done in {elapsed:.1f}s")
    print(f"  Success : {success_count}")
    print(f"  Failed  : {fail_count}")
    if elapsed > 0:
        print(f"  Rate    : {success_count / elapsed:.1f} votes/sec")

    # Show candidate weight distribution used for this run
    if candidate_weights:
        print("\n  Popularity weights used this run:")
        # We need the ballot structure to map IDs to names — do one more fetch
        try:
            s = requests.Session()
            resp = s.get(f"{base_url}/", timeout=5)
            csrf = extract_csrf_token(resp.text)
            if csrf:
                resp = s.get(f"{base_url}/ballot", timeout=5)
                offices = extract_ballot(resp.text)
                id_to_name = {}
                for office in offices:
                    for c in office["candidates"]:
                        id_to_name[c["id"]] = c["name"]
                # If we couldn't get names from a ballot, just skip the names
                if not id_to_name:
                    raise ValueError("no names")
        except Exception:
            id_to_name = {}

        for cid, w in sorted(candidate_weights.items(), key=lambda x: -x[1]):
            name = id_to_name.get(cid, f"Candidate {cid}")
            bar = "\u2588" * int(w * 20)
            print(f"    {name:<30s}  {w:.2f}  {bar}")

    # Show final tallies from the display API
    print_results(base_url)
    print(f"\n  View live: {base_url}/display\n")


if __name__ == "__main__":
    main()
