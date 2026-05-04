# UAT Script — Council Dry Run

> **The UAT is conducted at the discretion and responsibility of the church council using this software. The authors provide no warranty, no support, and accept no responsibility for outcomes.**

## Purpose

This script walks the consistory with deacons through a complete dummy election so they can experience the full process and decide whether to approve the app for the real election.

The dry run should take approximately 30-45 minutes.

## Materials Needed

- [ ] Laptop with the app installed and tested
- [ ] WiFi router + ethernet cable + power
- [ ] Projector + HDMI cable
- [ ] Pre-printed code slips for Round 1 (at least 10)
- [ ] Pre-printed code slips for Round 2 (at least 10)
- [ ] Pre-printed paper ballots for Round 1 (at least 5)
- [ ] Pre-printed paper ballots for Round 2 (at least 5)
- [ ] Pens
- [ ] Printed attendance register
- [ ] This script (printed)

## Dummy Candidates

Use generic dummy candidates:

**Office: Elder** — select up to 2
- Candidate A, Candidate B, Candidate C, Candidate D

**Office: Deacon** — select up to 1
- Candidate E, Candidate F, Candidate G

Set these up in the app before the dry run.

---

## Script

### Part 1: Setup (5 minutes)

1. Task team member sets up the laptop and router. Starts the app.
2. Opens the projector display (full-screen).
3. Announces the WiFi network name and password.
4. Council members connect their phones.
5. Verify at least 3-4 phones can reach the voting page.

### Part 2: Round 1 Voting (10 minutes)

1. Hand out Round 1 code slips — one per council member.
2. Give 2-3 members paper ballots instead (to test the paper path).
3. Open voting from the admin panel.
4. Council members enter their codes and vote.
5. Paper voters fill in their ballots.
6. Watch the projector — it shows the vote count increasing.

**Check:** Everyone who voted by phone sees the confirmation page. The projector count matches.

### Part 3: Closing and Counting (5 minutes)

1. Close voting.
2. Collect and count paper ballots manually.
3. Enter paper vote totals in the admin panel.
4. Show results on the projector.

**Check:** Digital + paper totals match expectations.

### Part 4: Second Round (10 minutes)

1. Select 2 candidates per office to carry forward.
2. Start Round 2.
3. Hand out Round 2 code slips and paper ballots.
4. The chairman announces which candidates are still standing.
5. Open voting. Vote again. Close. Count. Show results.

**Check:** Round 2 results displayed. Round 1 results preserved. Round 1 codes no longer work.

### Part 5: Failure Scenarios (10 minutes)

| Scenario | How to test | Expected result |
|----------|-------------|-----------------|
| Invalid code | Type `XXXXXX` | "Invalid code" error message |
| Code used twice | Re-enter a used code | "Your vote has already been registered with this code" error |
| Phone shared | One brother votes, hands phone to next | Fresh code entry page |
| Voting closed | Enter code when voting is closed | "Voting is not currently open" |
| App restarted | Close and reopen the app | All data preserved |
| Max selections | Try to select too many candidates | Server rejects, returns to ballot |

### Part 6: Inspection (5 minutes)

Show the council:

1. The admin results page with full breakdown.
2. The exported results PDF.
3. The database file — a single file the council can inspect.
4. That votes cannot be linked back to codes (by design).

---

## Acceptance Criteria

- [ ] All phones could connect to WiFi and reach the voting page
- [ ] Codes worked correctly — valid accepted, invalid/used rejected
- [ ] Votes were recorded — projector count matched
- [ ] Paper votes added correctly to digital totals
- [ ] Second round worked — new codes, carried-forward candidates, previous results preserved
- [ ] Failure scenarios behaved as expected
- [ ] Projector display was readable from the back of the hall
- [ ] The process was understandable — a brother could vote without assistance
- [ ] Results matched manual counting

## Known Limitations

1. The app is built and administered by brothers in the congregation, not an independent third party.
2. The administrator can see vote counts per candidate, but cannot determine which brother cast which vote.
3. The app requires a laptop, router, and basic technical skill to set up.
4. If anything fails, the fallback is always a full paper ballot election.

---

## Sign-Off

| Name | Role | Approve? | Signature | Date |
|------|------|----------|-----------|------|
| | Chairman | Yes / No | | |
| | Council member | Yes / No | | |
| | Council member | Yes / No | | |
| | Council member | Yes / No | | |

**Decision:** [ ] Approved for use in the next election / [ ] Not approved — reasons noted below

**Notes:**

&nbsp;

&nbsp;
