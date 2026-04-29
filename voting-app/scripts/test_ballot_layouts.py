"""
Generate paper-ballot PDFs in the realistic range of office/candidate
combinations, so the dynamic scaling in generate_paper_ballot_pdf can be
inspected visually.

Default behaviour with no arguments:
  - writes one PDF per scenario into ./ballot_test_output/
  - 30 ballots per PDF (so the per-page tile size is obvious)

Optional flags:
  --out DIR         output directory (default: ./ballot_test_output)
  --member-count N  number of ballots per PDF (default: 20)
  --round N         voting round number (default: 1)
"""

import argparse
import os
import sys

# Make the sibling pdf_generators module importable when run from anywhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from pdf_generators import generate_paper_ballot_pdf  # noqa: E402


def _office(name, max_selections, candidate_names):
    return {
        "office": {"name": name, "max_selections": max_selections},
        "candidates": [{"name": n} for n in candidate_names],
    }


# Realistic range: 1-2 offices, max 8 candidates per office.
# Each tuple: (filename_tag, human_label, office_data)
SCENARIOS = [
    # Each scenario includes the long worst-case name "Pieter van der Berg"
    # to test the text-width cap.
    (
        "01_1office_2cands",
        "1 office, 2 candidates (round 2 with 1 open seat)",
        [_office("Elder", 1, ["Pieter van der Berg", "Henk Jansen"])],
    ),
    (
        "02_1office_4cands",
        "1 office, 4 candidates (2 vacancies)",
        [_office("Elder", 2, ["Pieter van der Berg",
                              "Smith", "Jones", "Brown"])],
    ),
    (
        "03_1office_6cands",
        "1 office, 6 candidates (3 vacancies)",
        [_office("Elder", 3, ["Pieter van der Berg",
                              "Bakker", "Evers", "Steenstra",
                              "Plantinga", "Postma"])],
    ),
    (
        "04_1office_8cands",
        "1 office, 8 candidates (max single office)",
        [_office("Elder", 4, ["Pieter van der Berg"]
                             + [f"Candidate {n}" for n in "ABCDEFG"])],
    ),
    (
        "05_2offices_4plus4",
        "2 offices, 4 + 4 (small slate)",
        [
            _office("Elder", 2, ["Pieter van der Berg",
                                 "Smith", "Jones", "Brown"]),
            _office("Deacon", 2, ["Pieter van der Berg",
                                  "Wilson", "Taylor", "Anderson"]),
        ],
    ),
    (
        "06_2offices_6plus4",
        "2 offices, 6 + 4 (typical)",
        [
            _office("Elder", 3, ["Pieter van der Berg",
                                 "Bakker", "Evers", "Steenstra",
                                 "Plantinga", "Postma"]),
            _office("Deacon", 2, ["Pieter van der Berg",
                                  "Wieringa", "Hofman", "Bouwman"]),
        ],
    ),
    (
        "07_2offices_8plus8",
        "2 offices, 8 + 8 (max)",
        [
            _office("Elder", 4, ["Pieter van der Berg"]
                                + [f"Elder {n}" for n in "ABCDEFG"]),
            _office("Deacon", 4, ["Pieter van der Berg"]
                                 + [f"Deacon {n}" for n in "ABCDEFG"]),
        ],
    ),
]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="ballot_test_output",
                   help="Output directory (default: ./ballot_test_output)")
    p.add_argument("--member-count", type=int, default=20,
                   help="Ballots per PDF (default: 20)")
    p.add_argument("--round", type=int, default=1,
                   help="Round number (default: 1)")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    election_name = "Office Bearer Election (Layout Test)"
    print(f"  Output dir : {args.out}")
    print(f"  Round      : {args.round}")
    print(f"  Ballots/PDF: {args.member_count}")
    print()

    for tag, label, office_data in SCENARIOS:
        path = os.path.join(args.out, f"{tag}.pdf")
        buf = generate_paper_ballot_pdf(
            election_name=election_name,
            round_number=args.round,
            office_data=office_data,
            member_count=args.member_count,
        )
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        print(f"  {tag:30}  {len(buf.getvalue()):>7} bytes  -  {label}")

    print()
    print(f"  Done. Open the PDFs in {args.out} to compare layouts.")


if __name__ == "__main__":
    main()
