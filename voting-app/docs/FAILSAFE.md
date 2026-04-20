# Failsafe — When Things Go Wrong

## The Standing Rule

**If in doubt, hand out paper ballots and start the election over on paper.**

Paper ballots and the attendance register are always physically in the room. The app is a convenience, not a requirement.

---

## Decision Tree

### WiFi fails

1. Check the router is powered on.
2. Restart the router (unplug, wait 10 seconds, plug back in, wait 60 seconds).
3. If still broken: **switch to paper ballots for all voters**.

### Laptop crashes or freezes

1. Restart the laptop.
2. Restart the app: `python app.py`
3. **All data is preserved** — the database survives restarts.
4. If the laptop won't restart: **switch to paper ballots from scratch**.

### App crashes

1. Note the error (take a photo).
2. Stop (Ctrl+C) and restart: `python app.py`
3. The database is unaffected. Resume voting.
4. If the app won't restart: **switch to paper ballots**.

### Power outage

1. If the laptop has battery, it keeps running. Check the router.
2. If everything lost power, restart when power returns.
3. If power won't return: **complete the election on paper**.

### A brother's phone won't load the page

1. Check they're connected to the election WiFi (not mobile data).
2. Try the URL again.
3. Try a different browser.
4. If it still doesn't work: give them a **paper ballot**.

### A code doesn't work

1. Check the brother is typing it correctly (6 characters, uppercase).
2. Check voting is open.
3. If the code was already used: the brother must use a paper ballot.
4. If genuinely invalid: give a paper ballot and investigate later.

### Someone voted for the wrong candidate

Votes cannot be undone. This is the same as crossing the wrong box on a paper ballot.

### Need to start the entire election over

1. Stop the app (Ctrl+C).
2. Delete the database file: `data/frca_election.db`
3. Restart the app: `python app.py`
4. New code slips will be needed — the old ones are tied to the deleted database.
5. If no new code slips: **run the entire election on paper**.

---

## Recovering the Database

The database is a single file: `data/frca_election.db`

- Can be copied or backed up like any file.
- Can be inspected with [DB Browser for SQLite](https://sqlitebrowser.org/).
- The app does not need to be stopped to copy the file.

---

## Who to Call

Update this table with your congregation's task team:

| Person | Role | Contact |
|--------|------|---------|
| | Task team lead | |
| | Technical support | |
| | Backup | |

---

## Summary

| Situation | Action |
|-----------|--------|
| Minor issue | Troubleshoot, then resume |
| Major failure | Switch to paper ballots immediately |
| Any doubt about integrity | Switch to paper ballots |
| Partial results from a crash | Do not use — start over on paper |

**The election is more important than the app. If the app fails, the election continues on paper.**
