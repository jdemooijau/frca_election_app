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

### 5. Voting codes and printing

1. Click **Codes & printing** in the wizard sidebar. Codes auto-generate
   the first time you visit after offices are set up - no manual
   generation step. The page shows the freshly minted plaintext codes;
   this is the only time the plaintexts are visible, so print the slips
   before leaving the page.
2. The same step has a **Print & prepare** strip with the **Printer
   Pack ZIP** (recommended) and individual PDFs under **More formats**:
   Code Slips, Paper Ballot, Counter Sheet, Dual-Sided Ballots,
   Dual-Ballot Handout.
3. Print the Printer Pack contents. The dual-sided ballot has a paper
   ballot on one side and a unique code-slip QR on the other.
4. Print the **Attendance Register PDF** from the same step.

> **Codes are reused across rounds** — the same code batch covers
> Round 1, Round 2, etc. Don't regenerate after printing: the
> regeneration form is gated behind typing the election name and the
> admin password to prevent accidental invalidation of printed slips.

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

1. In the admin panel, click **Open** on the election to enter the
   wizard sidebar.
2. Click **Attendance & postal** and enter the **Brothers Present**
   count from the attendance register, then click Save. (The
   paper-ballot count is entered later, on the Count & tally step.)
3. Click **Welcome & Rules** in the sidebar. Walk the projector
   through the phases:
   - **Next: Election Rules ->** (secretary reads Articles 4, 6, 12)
   - Click **Next: Voting ->** to navigate to the Voting step
4. On the Voting step, click **Open Round 1**. The projector switches
   to the live ballot view and shows OPEN at the top with a progress
   bar.

### During Voting

- The projector shows how many votes have been cast.
- The task team helps brothers who need assistance.
- Phones can be shared — the confirmation page redirects to code entry for the next brother.
- Vote counts are hidden on the projector by default.

### Closing Voting

1. On the Voting step, click **Close Round N**. The sidebar advances to
   **Count & tally**. (Closing voting no longer auto-reveals the tally
   on the projector - that is a separate, deliberate action below.)
2. Collect paper ballots. Count manually with at least two brothers.
3. On the Count & tally step, enter the **Paper Ballots Received**
   total and click Save.
4. Click **Enter Paper Votes (per candidate)** and enter the per-
   candidate counts from the counter sheet.

### Viewing Results

1. The Count & tally step shows the per-office results table with
   elected badges, Article 6a/6b ticks, and the office's remaining
   vacancies.
2. Click **Show Results on Projector** to reveal totals to the
   congregation.
3. The consistory with the deacons determines whether to advance to
   another round or finalise.

### Decide what's next

Click **Decide** in the sidebar. The step offers:

- **Start Round N+1** - pick the carry-forward candidates with the
  checkboxes (already-elected ones are auto-disabled). The same code
  batch is reused; no re-printing.
- **Show Final Results** - switches both the projector and the
  voters' phones to the Final Results page.

For each subsequent round the chairman walks the Round group again
(Welcome & Rules -> Voting -> Count & tally -> Decide).

---

## After the Election

### Final results and minutes

When every vacancy is filled (or the council decides to stop), the
**Final results** step (under the **Finish** group in the sidebar)
becomes active. From there:

- **Show Final Results on Projector** — switches the projector and
  phone displays to a clean elected-brothers summary.
- **Download Election Minutes (DOCX)** — narrative minutes with one
  section per round, ready for the secretary to fill in placeholders
  (chairman name, scripture reference, helpers' names, etc.).

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

The app can generate dual-sided ballots — when printed duplex and cut,
each card has a paper ballot on one side and a phone voting code on
the other. This is the recommended format because each brother
receives both options in a single card and can choose which to use.

The dual-sided ballot is included in the **Printer Pack ZIP** (Codes &
printing step -> Print & prepare -> "Printer Pack ZIP"). To get just
the dual-sided PDF, use **More formats -> Dual-Sided Ballots PDF**.

Print on plain A4 with **duplex printing enabled** (long-edge binding),
cut along the dotted lines, then hand one card to each brother at the
attendance register on election day. Each brother chooses which side
to use (phone or paper) and submits only that side.
