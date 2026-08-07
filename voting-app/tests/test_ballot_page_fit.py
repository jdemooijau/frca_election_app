"""Regression tests for the 6-ballots-per-A4 page-fit contract.

The paper ballot layout promises the printer a sheet count of
ceil(ballots / 6). That promise is enforced by the page-fit cap in
generate_paper_ballot_pdf (pdf_generators.py). It has regressed before:
short candidate names leave the text-fit cap loose, so the page-fit cap is
the only thing holding the tile height down, and round 2 adds an extra
warning slot on top of that.

These tests pin the demo-maximum shape (Elder 10 candidates / select 5,
Deacon 8 candidates / select 4) for both name lengths and both rounds.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

from pdf_generators import generate_paper_ballot_pdf


# Realistic long Dutch/Australian names, the worst case for the text-fit cap.
LONG_ELDER_NAMES = [
    "Bastiaan van der Heijden",
    "Cornelis van Nieuwenhuizen",
    "Hendrik-Jan Oosterhuis",
    "Willem de Kempenaar",
    "Gerrit van Dijkstra",
    "Pieter van Rijksen",
    "Sebastiaan Vermeulen",
    "Alexander Boonstra",
    "Frederik van Loonen",
    "Nathanael Schuurmans",
]
LONG_DEACON_NAMES = [
    "Christiaan Brouwerhof",
    "Arend Visserman",
    "Matthias van Doorne",
    "Reinier Hoogendijk",
    "Barend van Steensel",
    "Joachim Veldkamper",
    "Leendert Molenaarse",
    "Abraham van Wijngaard",
]

# Short names. This is the case that regressed: the text-fit cap stays loose,
# so only the page-fit cap keeps the tile at 6 per A4.
SHORT_ELDER_NAMES = ["Candidate " + chr(ord("A") + i) for i in range(10)]
SHORT_DEACON_NAMES = ["Candidate " + chr(ord("K") + i) for i in range(8)]


def _office_data(elder_names, deacon_names):
    return [
        {
            "office": {"name": "Elder", "max_selections": 5, "vacancies": 5},
            "candidates": [{"name": n} for n in elder_names],
        },
        {
            "office": {"name": "Deacon", "max_selections": 4, "vacancies": 4},
            "candidates": [{"name": n} for n in deacon_names],
        },
    ]


LONG_NAMES = _office_data(LONG_ELDER_NAMES, LONG_DEACON_NAMES)
SHORT_NAMES = _office_data(SHORT_ELDER_NAMES, SHORT_DEACON_NAMES)


@pytest.mark.parametrize("name_style,office_data", [
    ("long", LONG_NAMES),
    ("short", SHORT_NAMES),
])
@pytest.mark.parametrize("round_number", [1, 2])
def test_six_ballots_per_a4_at_demo_maximum(name_style, office_data,
                                            round_number):
    """30 ballots at the demo maximum must fit on 5 A4 sheets."""
    buf = generate_paper_ballot_pdf(
        election_name="Office Bearer Election 2026",
        round_number=round_number,
        office_data=office_data,
        member_count=20,  # -> max(20 + 10, 30) = 30 ballots
    )

    doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
    try:
        page_count = doc.page_count
    finally:
        doc.close()

    assert page_count == 5, (
        "expected 5 pages (30 ballots at 6 per A4) for "
        + name_style + " names, round " + str(round_number)
        + ", got " + str(page_count)
    )
