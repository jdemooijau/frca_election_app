"""
Election Rules — implementation of one congregation's interpretation of the
Rules for the Election of Office Bearers (FRCA).

This module is the single home for election arithmetic and rule decisions.
Other code (Flask handlers, templates, scripts) imports from here. Keep this
module pure: no DB access, no Flask, no I/O — just functions that take
numbers/dicts in and return numbers/dicts out.

If your congregation's interpretation differs from what is encoded here,
this is the file to fork and edit. See docs/ELECTION_RULES.md for the
verbatim rule text alongside this app's interpretation, and decision
provenance for non-obvious calls.

Rule citations refer to the Rules for the Election of Office Bearers
(distinct from the Church Order itself; Article 1 of these rules cites
Article 3 of the Church Order). Articles 1-13 below are Election Rules
articles.
"""

import math


# ---------------------------------------------------------------------------
# Threshold calculations (Article 6)
# ---------------------------------------------------------------------------

def calculate_thresholds(vacancies, valid_votes_cast, participants):
    """
    Article 6 threshold calculations.

    6a: candidate must receive STRICTLY MORE THAN
        (valid_votes_cast / vacancies / 2)
    6b: candidate must receive AT LEAST
        ceil(participants * 2 / 5)  (fractions rounded up per Article 7)

    See docs/ELECTION_RULES.md "Article 6" section for the verbatim rule text
    and the interpretation this app implements (including the meaning of
    "valid votes cast").
    """
    if vacancies <= 0:
        return 0, 0
    threshold_6a = valid_votes_cast / (2 * vacancies)
    threshold_6b = math.ceil(participants * 2 / 5)
    return threshold_6a, threshold_6b


def check_candidate_elected(votes, threshold_6a, threshold_6b):
    """
    Check if a candidate meets BOTH Article 6 thresholds.
    Returns (meets_thresholds, passes_6a, passes_6b).

    NOTE: meets_thresholds alone is NOT sufficient to declare a candidate elected.
    Per Article 6 ("candidates who receive the MOST votes... provided that ..."),
    only the top-N candidates by vote count (N = vacancies) among those who pass
    both thresholds are elected. Use resolve_elected_status() to apply that rule.
    """
    passes_6a = votes > threshold_6a   # strict greater than
    passes_6b = votes >= threshold_6b  # greater than or equal
    return (passes_6a and passes_6b), passes_6a, passes_6b


def resolve_elected_status(candidates, vacancies):
    """
    Apply Article 6 + 7 to decide which candidates are elected this round.

    Preconditions: each candidate dict has "total", "passes_6a", "passes_6b".
    Sets "elected" to True only for the top `vacancies` threshold-passers by
    vote count. Candidates tied on votes at the cutoff are NOT elected (they
    must face a runoff per Article 7).
    """
    for c in candidates:
        c["elected"] = False

    if vacancies <= 0:
        return

    passing = [c for c in candidates if c.get("passes_6a") and c.get("passes_6b")]
    if not passing:
        return

    passing.sort(key=lambda c: c["total"], reverse=True)

    if len(passing) <= vacancies:
        for c in passing:
            c["elected"] = True
        return

    cutoff_votes = passing[vacancies - 1]["total"]
    next_votes = passing[vacancies]["total"]

    if cutoff_votes == next_votes:
        # Tie at the boundary - only elect candidates strictly above the tie
        for c in passing:
            if c["total"] > cutoff_votes:
                c["elected"] = True
    else:
        for c in passing[:vacancies]:
            c["elected"] = True
