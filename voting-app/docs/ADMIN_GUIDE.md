# Admin Guide — How to Run an Election

> **Before following these instructions, please read the disclaimer in the main README. You are fully responsible for the correct setup and operation of this software.**

This guide walks the task team through running a complete office bearer election, from preparation days before to archiving results after.

## Before Election Day

### 1. First-Time Setup

If this is the first time using the app, run through the setup wizard:

1. Start the app: `python app.py`
2. Open `http://localhost:5000/admin`, log in with `admin`
3. Complete the setup wizard (congregation name, WiFi name, new password)

See [CONFIGURATION.md](CONFIGURATION.md) for details.

### 2. Import Members

1. Export the male confessing members from Church Social as a CSV.
2. In the admin panel, click **Members** > upload the CSV.
3. This gives you the attendance register and candidate autocomplete.

### 3. Create the Election

1. Click **+ New Election**.
2. Name it (e.g. "Office Bearer Election").
3. Set **Maximum Rounds** (typically 2).

### 4. Add Offices and Candidates

1. On the election setup page, click **Add Office**.
2. Enter "Elder", set maximum selections (e.g. 2 for 2 vacancies).
3. Use the autocomplete to search and select candidates from the member list.
4. Repeat for "Deacon".

### 5. Generate Codes and Print

1. Go to the **Codes** tab.
2. Click **Generate Codes for All Rounds** (count defaults to member count + 10).
3. Download the **Code Slips PDF** and **Paper Ballot PDF** for each round.
4. Print and cut the code slips. Sort into envelopes labelled "Round 1" and "Round 2".
5. Print paper ballots for each round.
6. Print the **Attendance Register** from the Members page.

### 6. Test the Setup

Follow [SETUP.md](SETUP.md) to test with the router and a few phones.

---

## On Election Day

### At the Door

1. As brothers arrive, have them sign the **attendance register**.
2. Ask: "Phone or paper?"
3. **Phone**: hand out one code slip from the Round 1 envelope.
4. **Paper**: hand out a Round 1 paper ballot and a pen.
5. Do not hand out Round 2 materials yet.

### Opening Voting

1. In the admin panel, go to **Manage** for the election.
2. Click **Open Voting**.
3. The projector shows "OPEN" and a progress bar.

### During Voting

- The projector shows how many votes have been cast.
- The task team helps brothers who need assistance.
- Phones can be shared — the confirmation page redirects to code entry for the next brother.
- Vote counts are hidden on the projector by default.

### Closing Voting

1. Click **Close Voting** when all brothers have voted.
2. Collect paper ballots. Count manually with at least two brothers.
3. Enter paper vote totals in the admin panel.

### Viewing Results

1. The **Manage** page shows full results (digital + paper).
2. Click **Show Results on Projector** to display results to the congregation.
3. The consistory with the deacons determines whether the threshold has been met per the congregation's election rules.

### Second Round

If a second round is needed:

1. Select the candidates to carry forward.
2. Click **Start Round 2**.
3. Hand out Round 2 code slips and paper ballots.
4. The chairman announces which candidates are still standing (Round 2 paper ballots list all candidates).
5. Open voting, vote, close, count, show results — same process.

---

## After the Election

### Export Results

Click **Export Results PDF** for a printable record for the consistory with the deacons.

### Archive

The database file is at `data/frca_election.db`. Copy it to a safe location for the congregation's records.

### Next Election

Create a new election in the same database, or delete the database file to start fresh.

---

## Quick Reference

| Action | Where |
|--------|-------|
| Admin panel | `http://localhost:5000/admin` |
| Voter page | `http://<laptop-ip>:5000` |
| Projector display | `http://localhost:5000/display` |
| Default admin password | `admin` (must be changed on first login) |
| Database file | `data/frca_election.db` |

### Dual-Sided Ballots

The app can generate dual-sided ballots — when printed duplex and cut, each
card has a paper ballot on one side and a phone voting code on the other.
This is the recommended format because each brother receives both options
in a single card and can choose which to use.

To generate:

1. Generate codes for the election (Codes page)
2. Click **"Download Dual-Sided Ballots PDF"**
3. Print on plain A4 paper with **duplex printing enabled** (long-edge
   binding)
4. Cut the printed sheets along the dotted lines
5. Each card now has a paper ballot on one side and a code slip on the other
6. Hand one card to each brother at the attendance register on election day

Each brother chooses which side to use (phone or paper) and submits only
that side.
