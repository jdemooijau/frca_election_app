# Security and Anonymity Model

This document explains how the app protects vote secrecy, prevents fraud, and where its honest limitations lie.

## Threat Model

In a church election context, the threats are modest:

- **Curious brother** — wants to know how someone else voted
- **Double voter** — tries to vote more than once
- **Code guesser** — tries to manufacture a valid code
- **Administrator** — has access to the laptop and database

The app is designed for a trusted community of brothers voting in a church hall, not for adversarial environments.

## How Anonymity is Preserved

### The separation between codes and votes

1. A brother receives a **code slip** at the door. The attendance register records that he was present, but **not which code he received**. Code slips are handed out from a shuffled stack.

2. The brother enters the code on his phone. The app checks the code against a **hashed** version stored in the database (the plaintext code is never stored).

3. When the brother submits his ballot, the app performs an **atomic transaction**:
   - The code is marked as "used" (burned).
   - The vote is recorded in a separate table.
   - There is **no foreign key, no column, and no field** connecting the vote record to the code record.

4. After the transaction, it is **impossible** — even with full database access — to determine which code cast which vote.

## How Double Voting is Prevented

1. Each code is unique and can only be used once.
2. When a vote is submitted, the code is burned in the same database transaction.
3. The burn uses an atomic `UPDATE ... WHERE used = 0` — even if two requests arrive simultaneously, only one succeeds.

## How Code Guessing is Prevented

- **Code entropy**: 6 characters from a 28-character set = 482 million possible codes. With ~100 valid codes, the chance of guessing one is ~1 in 4.8 million per attempt.
- **Rate limiting**: 5 attempts per minute per IP address.
- **Hashing**: Codes are stored as SHA-256 hashes. Even with database access, unused codes cannot be read.

## What the Council Can Verify

By inspecting the database file (`data/frca_election.db`) with any SQLite browser:

1. Total codes generated matches the number of slips printed.
2. Total codes used matches the number of digital voters.
3. No link exists between the `codes` and `votes` tables.
4. Paper vote entries match the manually counted paper ballots.
5. Candidate totals (digital + paper) match the displayed results.

## What the Council CANNOT Do

**Link a vote to a brother** — this is by design. Even with full access to the database, the laptop, and the attendance register, it is not possible to determine how any individual voted.

## Honest Limitations

### 1. The administrator is a brother in the congregation

Unlike a commercial service, there is no independent third party. The council must decide if this is acceptable.

**Mitigation:** The code is open source and inspectable. The database is auditable. The task team includes multiple brothers.

### 2. The admin can see vote counts

The admin can see real-time counts per candidate, but not who voted for whom.

**Mitigation:** Paper ballot counting should be done by at least two brothers independently.

### 3. Network traffic is unencrypted

The app runs over HTTP on a local WiFi network. In theory, someone with network sniffing tools could see codes being submitted. In practice, codes are one-time use and the WiFi is only active during the election.

### 4. Timestamp correlation

While there is no direct link between codes and votes, timestamps on both tables could theoretically be correlated if someone voted in isolation. With 30+ brothers voting in a short window, this is not a realistic attack.

## CSRF Protection

All forms are protected with CSRF tokens (via Flask-WTF), preventing cross-site request forgery.

## Summary

| Property | Status |
|----------|--------|
| Vote anonymity | Strong — no link between code and vote |
| Double voting prevention | Strong — atomic code burn |
| Code guessing prevention | Strong — entropy + rate limiting |
| Tampering detection | Moderate — inspectable database, task team oversight |
| Independent verification | Moderate — open source, but no third-party auditor |
| Network security | Basic — unencrypted HTTP on private WiFi |
