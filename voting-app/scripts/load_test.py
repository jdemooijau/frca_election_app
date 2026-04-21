"""
Full election mass test: exercises the complete chairman workflow then simulates
concurrent digital voters, postal votes, and paper ballot tallies.

Flow:
  [Admin]  login → enter postal votes → set attendance → display 1→2 (Rules)
           → display 2→3 (Voting — opens voting automatically)
  [Voters] N digital voters cast ballots concurrently
  [Admin]  close voting → set paper ballot count → enter paper vote tallies
           → print final summary

Usage:
    # 1. Seed a demo election (leaves voting closed)
    python scripts/seed_demo.py --codes 100

    # 2. Start the server
    python -m waitress --host=0.0.0.0 --port=5000 app:app

    # 3. Run the mass test
    python scripts/load_test.py                          # defaults
    python scripts/load_test.py --voters 95 --workers 8 # tune concurrency
    python scripts/load_test.py --postal 5 --paper 8    # with postal+paper
    python scripts/load_test.py --url http://10.0.0.5:5000  # remote server
"""

import argparse
import os
import random
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        name_match = re.search(r'<h2 class="ballot-office-title">([^<]+)</h2>', block)
        office_name = name_match.group(1).strip() if name_match else "?"

        max_match = re.search(r'\(select\s+(\d+)\)', block, re.IGNORECASE)
        max_sel = int(max_match.group(1)) if max_match else 1

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


def parse_vote_form_candidates(html, prefix):
    """Parse candidate IDs, names, and max_selections from a postal/paper admin page.

    Returns list of {office_name, max_selections, candidates: [{id (int), name}]}.
    """
    offices = []
    for card in re.split(r'<div class="card"', html)[1:]:
        max_match = re.search(r'data-max="(\d+)"', card)
        max_sel = int(max_match.group(1)) if max_match else 1
        header = re.search(r'<div class="card-header">([^<]+)</div>', card)
        office_name = header.group(1).strip() if header else "?"
        pairs = re.findall(
            rf'<label for="{prefix}_(\d+)">([^<]+)</label>', card
        )
        candidates = [{"id": int(cid), "name": name.strip()} for cid, name in pairs]
        if candidates:
            offices.append({"office_name": office_name, "max_selections": max_sel, "candidates": candidates})
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
# Vote distribution helper (for postal/paper ballots)
# ---------------------------------------------------------------------------

def simulate_offline_votes(offices, n_voters):
    """Simulate n_voters casting up to max_selections votes per office.

    Returns {cand_id (int): count}.
    """
    counts = {}
    for office in offices:
        for c in office["candidates"]:
            counts[c["id"]] = 0
    for _ in range(n_voters):
        for office in offices:
            cands = office["candidates"]
            if not cands:
                continue
            max_sel = office.get("max_selections", 1)
            k = min(random.randint(1, max_sel), len(cands))
            for pick in random.sample(cands, k):
                counts[pick["id"]] += 1
    return counts


# ---------------------------------------------------------------------------
# Admin HTTP helpers
# ---------------------------------------------------------------------------

def _admin_get(session, url):
    """GET url, return (response, csrf_token)."""
    resp = session.get(url, timeout=10)
    return resp, extract_csrf_token(resp.text)


def admin_login(session, base_url, password):
    resp, csrf = _admin_get(session, f"{base_url}/admin/login")
    if not csrf:
        raise RuntimeError("No CSRF token on /admin/login")
    resp = session.post(
        f"{base_url}/admin/login",
        data={"csrf_token": csrf, "password": password},
        allow_redirects=True,
        timeout=10,
    )
    if "Incorrect" in resp.text or "/admin/login" in resp.url:
        raise RuntimeError("Admin login failed — wrong password?")


def get_election_id(session, base_url):
    resp = session.get(f"{base_url}/admin", allow_redirects=True, timeout=10)
    match = re.search(r'/admin/election/(\d+)', resp.text)
    if not match:
        raise RuntimeError("No election found on admin dashboard — run seed_demo first")
    return int(match.group(1))


def admin_enter_postal_votes(session, base_url, election_id, postal_count):
    resp, csrf = _admin_get(
        session, f"{base_url}/admin/election/{election_id}/postal-votes"
    )
    offices = parse_vote_form_candidates(resp.text, "postal")
    if not offices:
        return False, "Could not parse candidates from postal-votes page"

    vote_counts = simulate_offline_votes(offices, postal_count)
    form_data = {"csrf_token": csrf, "postal_voter_count": postal_count}
    for cid, count in vote_counts.items():
        form_data[f"postal_{cid}"] = count

    resp = session.post(
        f"{base_url}/admin/election/{election_id}/postal-votes",
        data=form_data,
        allow_redirects=True,
        timeout=10,
    )
    return "saved" in resp.text.lower(), ""


def admin_set_participants(session, base_url, election_id, participants):
    _, csrf = _admin_get(
        session, f"{base_url}/admin/election/{election_id}/manage"
    )
    session.post(
        f"{base_url}/admin/election/{election_id}/participants",
        data={"csrf_token": csrf, "participants": participants},
        allow_redirects=True,
        timeout=10,
    )


def admin_advance_phase(session, base_url, election_id):
    _, csrf = _admin_get(
        session, f"{base_url}/admin/election/{election_id}/manage"
    )
    session.post(
        f"{base_url}/admin/election/{election_id}/display-phase",
        data={"csrf_token": csrf, "direction": "next"},
        allow_redirects=True,
        timeout=10,
    )


def admin_close_voting(session, base_url, election_id):
    _, csrf = _admin_get(
        session, f"{base_url}/admin/election/{election_id}/manage"
    )
    session.post(
        f"{base_url}/admin/election/{election_id}/voting",
        data={"csrf_token": csrf},
        allow_redirects=True,
        timeout=10,
    )


def admin_enter_paper_votes(session, base_url, election_id, paper_count):
    # Set the ballot count on the participants endpoint first
    _, csrf = _admin_get(
        session, f"{base_url}/admin/election/{election_id}/manage"
    )
    session.post(
        f"{base_url}/admin/election/{election_id}/participants",
        data={"csrf_token": csrf, "paper_ballot_count": paper_count},
        allow_redirects=True,
        timeout=10,
    )

    # Enter per-candidate tallies
    resp, csrf = _admin_get(
        session, f"{base_url}/admin/election/{election_id}/paper-votes"
    )
    offices = parse_vote_form_candidates(resp.text, "paper")
    if not offices:
        return False, "Could not parse candidates from paper-votes page"

    vote_counts = simulate_offline_votes(offices, paper_count)
    form_data = {"csrf_token": csrf}
    for cid, count in vote_counts.items():
        form_data[f"paper_{cid}"] = count

    resp = session.post(
        f"{base_url}/admin/election/{election_id}/paper-votes",
        data=form_data,
        allow_redirects=True,
        timeout=10,
    )
    return "saved" in resp.text.lower(), ""


# ---------------------------------------------------------------------------
# Voter simulation
# ---------------------------------------------------------------------------

def simulate_voter(base_url, candidate_weights, weights_lock, blank_rate=0.05):
    """Run one voter through the full /vote -> /ballot -> /submit flow."""
    try:
        return _simulate_voter_inner(base_url, candidate_weights, weights_lock, blank_rate)
    except requests.ConnectionError:
        return False, "SERVER_DOWN"
    except requests.Timeout:
        return False, "Timeout"
    except Exception as e:
        return False, f"Error: {e}"


def _simulate_voter_inner(base_url, candidate_weights, weights_lock, blank_rate):
    s = requests.Session()

    # 1. GET enter-code page (CSRF + session cookie)
    resp = s.get(f"{base_url}/", timeout=10)
    csrf = extract_csrf_token(resp.text)
    if not csrf:
        return False, "No CSRF on enter-code page"

    # 2. POST /vote with blank code — demo mode auto-assigns an unused code
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

    # Assign popularity weights to new candidates (thread-safe)
    with weights_lock:
        for office in offices:
            for cand in office["candidates"]:
                if cand["id"] not in candidate_weights:
                    candidate_weights[cand["id"]] = random.uniform(0.2, 1.0)

    # 4. Build vote selections
    form_data = [("csrf_token", csrf), ("confirm_partial", "1")]

    for office in offices:
        if random.random() < blank_rate:
            continue
        max_sel = office["max"]
        cand_ids = [c["id"] for c in office["candidates"]]
        with weights_lock:
            weights = [candidate_weights.get(cid, 0.5) for cid in cand_ids]

        count = max_sel if random.random() < 0.85 else random.randint(1, max_sel)
        selected = weighted_sample(cand_ids, weights, count)
        for cid in selected:
            form_data.append((office["field"], cid))

    # 5. Submit
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
    pct = current / total if total else 0
    filled = int(BAR_WIDTH * pct)
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    rate = current / elapsed if elapsed > 0 else 0
    return (
        f"\r  [{current:>{len(str(total))}}/{total}] {bar} "
        f"{pct:5.1%}  {rate:.1f} v/s  ({failed} failed)"
    )


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
            for c in sorted(
                office.get("candidates", []),
                key=lambda x: x.get("total", 0),
                reverse=True,
            ):
                mark = " *" if c.get("elected") else ""
                print(
                    f"    {c['name']:<30s}  {c.get('total', 0):>4} votes{mark}"
                )
    else:
        print("\n  (Enable 'Show Results' in admin to see tallies)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Full election mass test — admin flow + concurrent voters + paper/postal"
    )
    parser.add_argument(
        "--voters", "-n", type=int, default=95,
        help="Digital voters to simulate (default: 95)",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=8,
        help="Concurrent voter threads (default: 8)",
    )
    parser.add_argument(
        "--postal", type=int, default=5,
        help="Postal voters to simulate (default: 5)",
    )
    parser.add_argument(
        "--paper", type=int, default=8,
        help="Paper ballot count (default: 8)",
    )
    parser.add_argument(
        "--blank-rate", "-b", type=float, default=0.05,
        help="Probability of a blank vote per office (default: 0.05)",
    )
    parser.add_argument(
        "--seed", "-s", type=int, default=None,
        help="Random seed for reproducible vote distributions",
    )
    parser.add_argument(
        "--url", "-u", default="http://localhost:5000",
        help="Base URL of the running server (default: http://localhost:5000)",
    )
    parser.add_argument(
        "--admin-password",
        default=os.environ.get("FRCA_ADMIN_PASSWORD", "admin"),
        help="Admin password (env: FRCA_ADMIN_PASSWORD, default: admin)",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    base_url = args.url.rstrip("/")

    # --- Server reachability check -------------------------------------------
    print(f"\n  Server  : {base_url}")
    try:
        requests.get(f"{base_url}/", timeout=5)
    except requests.ConnectionError:
        print(f"  ERROR   : Cannot connect to {base_url}")
        print("            Start the server first:  python app.py")
        sys.exit(1)

    # =========================================================================
    # PHASE 1 — Admin setup
    # =========================================================================
    print("\n  ┌─ Admin setup ──────────────────────────────────────────────┐")

    admin_session = requests.Session()
    print("  │  Logging in as admin...")
    try:
        admin_login(admin_session, base_url, args.admin_password)
    except RuntimeError as e:
        print(f"  │  ERROR: {e}")
        sys.exit(1)

    election_id = get_election_id(admin_session, base_url)
    print(f"  │  Election ID  : {election_id}")

    if args.postal > 0:
        print(f"  │  Postal votes : {args.postal} voters → entering tallies...")
        ok, msg = admin_enter_postal_votes(
            admin_session, base_url, election_id, args.postal
        )
        status = "saved" if ok else f"WARNING — {msg}"
        print(f"  │                 {status}")

    in_person = args.voters + args.paper
    print(f"  │  Attendance   : {in_person} ({args.voters} digital + {args.paper} paper + {args.postal} postal)")
    admin_set_participants(admin_session, base_url, election_id, in_person)

    print("  │  Display      : Welcome → Election Rules  (phase 1→2)")
    admin_advance_phase(admin_session, base_url, election_id)

    print("  │  Display      : Election Rules → Voting   (phase 2→3, opens voting)")
    admin_advance_phase(admin_session, base_url, election_id)

    # Verify
    try:
        data = requests.get(f"{base_url}/api/display-data", timeout=5).json()
    except Exception:
        data = {}
    if not data.get("voting_open"):
        print("  │  ERROR: voting did not open — check server logs")
        sys.exit(1)
    print(f"  │  Voting       : OPEN  (display phase {data.get('display_phase')})")
    print("  └────────────────────────────────────────────────────────────┘")

    # =========================================================================
    # PHASE 2 — Digital voting (concurrent)
    # =========================================================================
    print(
        f"\n  ┌─ Digital voting: {args.voters} voters, {args.workers} workers ─────────────────────┐"
    )

    candidate_weights = {}
    weights_lock = threading.Lock()
    counter = [0, 0]  # [success, fail]
    aborted = [False]
    start = time.time()

    futures_list = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures_list = [
            executor.submit(
                simulate_voter, base_url, candidate_weights, weights_lock, args.blank_rate
            )
            for _ in range(args.voters)
        ]
        for future in as_completed(futures_list):
            ok, msg = future.result()
            if ok:
                counter[0] += 1
            else:
                counter[1] += 1
                if msg == "OUT_OF_CODES":
                    print(f"\n  │  Ran out of demo codes after {counter[0]} votes.")
                    aborted[0] = True
                    break
                if msg == "SERVER_DOWN":
                    print(f"\n  │  Server went down after {counter[0]} votes.")
                    aborted[0] = True
                    break
            elapsed = time.time() - start
            sys.stdout.write(
                "  │  " + progress_line(sum(counter), args.voters, counter[1], elapsed)
            )
            sys.stdout.flush()

    elapsed = time.time() - start
    print(f"\n  │  Done in {elapsed:.1f}s  —  {counter[0]} OK / {counter[1]} failed  ({counter[0]/elapsed:.1f} v/s)")
    print("  └────────────────────────────────────────────────────────────┘")

    # =========================================================================
    # PHASE 3 — Admin close + paper votes
    # =========================================================================
    print("\n  ┌─ Admin close ──────────────────────────────────────────────┐")

    print("  │  Closing voting...")
    admin_close_voting(admin_session, base_url, election_id)

    if args.paper > 0:
        print(f"  │  Paper votes  : {args.paper} ballots → entering tallies...")
        ok, msg = admin_enter_paper_votes(
            admin_session, base_url, election_id, args.paper
        )
        status = "saved" if ok else f"WARNING — {msg}"
        print(f"  │                 {status}")

    print("  └────────────────────────────────────────────────────────────┘")

    # =========================================================================
    # Final summary
    # =========================================================================
    print_results(base_url)

    # Candidate popularity weights
    if candidate_weights:
        print("\n  Popularity weights used this run:")
        id_to_name = {}
        try:
            s = requests.Session()
            resp = s.get(f"{base_url}/", timeout=5)
            csrf = extract_csrf_token(resp.text)
            if csrf:
                resp = s.post(
                    f"{base_url}/vote",
                    data={"csrf_token": csrf, "code": ""},
                    allow_redirects=True,
                    timeout=5,
                )
                offices = extract_ballot(resp.text)
                id_to_name = {
                    c["id"]: c["name"]
                    for o in offices for c in o["candidates"]
                }
        except Exception:
            pass

        for cid, w in sorted(candidate_weights.items(), key=lambda x: -x[1]):
            name = id_to_name.get(cid, f"Candidate {cid}")
            bar = "█" * int(w * 20)
            print(f"    {name:<30s}  {w:.2f}  {bar}")

    print(f"\n  View live: {base_url}/display\n")


if __name__ == "__main__":
    main()
