"""Tests for surname shortening logic used on ballots."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.pdfbase.pdfmetrics import stringWidth

from name_formatting import (
    split_name,
    contract_tussenvoegsel,
    initialize_given,
    compress_surname,
    render_at_level,
    shorten_to_fit,
)


# ---------------------------------------------------------------------------
# split_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("full,expected", [
    ("Gary van der Katzenellenbogen", ("Gary", "van der", "Katzenellenbogen")),
    ("Henry Brouwerhof",              ("Henry", "", "Brouwerhof")),
    ("Madonna",                       ("", "", "Madonna")),
    ("Jan de Wit",                    ("Jan", "de", "Wit")),
    ("Pieter Jan de Wit",             ("Pieter Jan", "de", "Wit")),
    ("Neil ten Heuvel",               ("Neil", "ten", "Heuvel")),
    ("Gary van Dijkstra",             ("Gary", "van", "Dijkstra")),
    ("",                              ("", "", "")),
    ("  ",                            ("", "", "")),
])
def test_split_name_basic(full, expected):
    assert split_name(full) == expected


def test_split_name_case_insensitive_tussenvoegsel():
    # Capitalised tussenvoegsel still detected.
    assert split_name("Gary Van Der Berg") == ("Gary", "Van Der", "Berg")


def test_split_name_first_token_is_never_tussenvoegsel():
    # 'Van' as a given/surname start (no preceding token) should not be
    # treated as a particle.
    assert split_name("Van Halen") == ("Van", "", "Halen")


def test_split_name_keeps_at_least_one_surname_token():
    # 'Pieter de' would otherwise consume 'de' as both tussenvoegsel
    # and surname; the surname must keep at least one token.
    assert split_name("Pieter de") == ("Pieter", "", "de")


# ---------------------------------------------------------------------------
# contract_tussenvoegsel
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tussen,expected", [
    ("van der", "vd"),
    ("van den", "vd"),
    ("van de",  "vd"),
    ("Van Der", "vd"),
    ("van",     "v"),
    ("de",      "d"),
    ("ten",     "t"),
    ("ter",     "t"),
    ("in 't",   "in 't"),   # 't is preserved verbatim
    ("van 't",  "van 't"),  # 't is preserved verbatim
    ("'t",      "'t"),       # 't is preserved verbatim
    ("",        ""),
])
def test_contract_tussenvoegsel(tussen, expected):
    assert contract_tussenvoegsel(tussen) == expected


def test_contract_tussenvoegsel_unknown_falls_back_to_initials():
    # 'op het' is in the table; pick a contrived combo that isn't.
    assert contract_tussenvoegsel("zonder de") == "zd"


def test_contract_preserves_apostrophe_t_in_long_run():
    # If a multi-word tussenvoegsel contains 't, the whole thing stays.
    assert contract_tussenvoegsel("in 't") == "in 't"


# ---------------------------------------------------------------------------
# initialize_given
# ---------------------------------------------------------------------------

def test_initialize_given_single():
    assert initialize_given("Gary") == "G."


def test_initialize_given_multiple():
    assert initialize_given("Pieter Jan") == "P.J."


def test_initialize_given_empty():
    assert initialize_given("") == ""


# ---------------------------------------------------------------------------
# compress_surname
# ---------------------------------------------------------------------------

def test_compress_surname_short_name_unchanged():
    assert compress_surname("As") == "As"
    assert compress_surname("Wit") == "Wit"


def test_compress_surname_mild_keeps_first_four_and_last():
    # 'Brouwerhof' (10): keep 'Brou' + strip vowels of 'werho' + 'f'
    # 'werho' -> 'wrh' -> 'Brouwrhf'
    assert compress_surname("Brouwerhof") == "Brouwrhf"


def test_compress_surname_mild_long():
    # 'Katzenellenbogen' (16): keep 'Katz' + strip 'enellenboge' + 'n'
    # 'enellenboge' -> 'nllnbg' -> 'Katznllnbgn'
    assert compress_surname("Katzenellenbogen") == "Katznllnbgn"


def test_compress_surname_aggressive():
    # Keep first 2 + strip + last 1.
    # 'Brouwerhof' -> 'Br' + 'wrh' (from 'ouwerho') + 'f' = 'Brwrhf'
    assert compress_surname("Brouwerhof", aggressive=True) == "Brwrhf"


def test_compress_surname_hyphenated():
    # 'Smit-de Vries' -> 'Smit' (5 chars, but mild keeps 4+last so 'Smit' stays)
    # ' de Vries' -> 'de' particle preserved, 'Vries' (5 chars: 'Vrie'+'s'='Vries')
    assert compress_surname("Smit-de Vries") == "Smit-de Vries"
    # Long compound:
    out = compress_surname("Katzenellenbogen-Brouwerhof")
    assert out == "Katznllnbgn-Brouwrhf"


# ---------------------------------------------------------------------------
# render_at_level
# ---------------------------------------------------------------------------

NAME = "Gary van der Katzenellenbogen"

def test_render_level_0_is_original():
    assert render_at_level(NAME, 0) == NAME


def test_render_level_1_contracts_tussenvoegsel():
    assert render_at_level(NAME, 1) == "Gary vd Katzenellenbogen"


def test_render_level_2_initials_plus_tussenvoegsel():
    assert render_at_level(NAME, 2) == "G. vd Katzenellenbogen"


def test_render_level_3_mild_compression():
    assert render_at_level(NAME, 3) == "G. vd Katznllnbgn"


def test_render_level_4_aggressive_compression():
    # For 'Katzenellenbogen' the only vowel in the first 4 chars is at
    # position 1 ('a'), so mild and aggressive happen to coincide. Use
    # a different name to actually exercise the difference.
    assert render_at_level("Henry Brouwerhof", 3) == "H. Brouwrhf"
    assert render_at_level("Henry Brouwerhof", 4) == "H. Brwrhf"
    # Sanity: level 4 also runs through tussenvoegsel + initials.
    assert render_at_level(NAME, 4) == "G. vd Katznllnbgn"


def test_render_at_level_no_tussenvoegsel():
    assert render_at_level("Henry Brouwerhof", 1) == "Henry Brouwerhof"
    assert render_at_level("Henry Brouwerhof", 2) == "H. Brouwerhof"
    assert render_at_level("Henry Brouwerhof", 3) == "H. Brouwrhf"


def test_render_at_level_single_word():
    # Mild keeps 'Mado' (first 4) intact, has nothing to strip from middle 'nn'.
    assert render_at_level("Madonna", 3) == "Madonna"
    # Aggressive keeps 'Ma' + strips vowels from 'donn' + 'a' = 'Madnna'.
    assert render_at_level("Madonna", 4) == "Madnna"


def test_apostrophe_t_preserved_through_levels():
    # 'Pieter van 't Hoeven' should never lose the 't.
    name = "Pieter van 't Hoeven"
    for lvl in (1, 2, 3, 4):
        out = render_at_level(name, lvl)
        assert "'t" in out, f"level {lvl} dropped 't: {out!r}"


# ---------------------------------------------------------------------------
# shorten_to_fit
# ---------------------------------------------------------------------------

def _w(text, size=10):
    return stringWidth(text, "Helvetica", size)


def test_short_name_returned_unchanged_when_fits():
    name = "Jan de Wit"
    assert shorten_to_fit(name, 200, "Helvetica", 10) == name


def test_long_name_progressively_shortens():
    name = "Gary van der Katzenellenbogen"
    full_w = _w(name)
    # Pick a width too small for original but big enough for level-1.
    target = _w("Gary vd Katzenellenbogen") + 1
    out = shorten_to_fit(name, target, "Helvetica", 10)
    assert out == "Gary vd Katzenellenbogen"


def test_extremely_narrow_falls_through_to_truncation():
    name = "Gary van der Katzenellenbogen"
    out = shorten_to_fit(name, 30, "Helvetica", 10)
    # Whatever it returns, it MUST fit.
    assert _w(out) <= 30


def test_independent_per_name():
    # Two names share a ballot; only the long one is touched.
    short = "Jan Smit"
    long_name = "Gary van der Katzenellenbogen"
    width = _w("Gary vd Katzenellenbogen") + 2
    assert shorten_to_fit(short, width, "Helvetica", 10) == short
    assert shorten_to_fit(long_name, width, "Helvetica", 10) == "Gary vd Katzenellenbogen"


def test_empty_name_passthrough():
    assert shorten_to_fit("", 100, "Helvetica", 10) == ""
