"""Surname shortening utilities for ballot rendering.

Names in this congregation often have Dutch tussenvoegsels ("van der",
"ten", "de") and occasionally a long surname ("Katzenellenbogen") that
will not fit on a paper ballot at the chosen font size. This module
provides progressive shortening so the original name is preserved when
it fits, and only shrinks as needed.

Levels (mildest to most aggressive):
    0  original                          "Gary van der Katzenellenbogen"
    1  contract tussenvoegsel            "Gary vd Katzenellenbogen"
    2  + given names to initials         "G. vd Katzenellenbogen"
    3  + mild surname compression        "G. vd Katznllnbgn"
    4  + aggressive surname compression  "G. vd Ktznllnbgn"
    5  + hard truncate with ellipsis     "G. vd Ktznllnb..."

Use shorten_to_fit() to pick the mildest level that fits a width.
"""

from reportlab.pdfbase.pdfmetrics import stringWidth


# Lowercase Dutch tussenvoegsels recognised in name splitting.
TUSSENVOEGSEL_WORDS = {
    "van", "de", "der", "den", "het", "'t",
    "te", "ten", "ter",
    "in", "op", "aan", "uit", "voor", "bij",
    "onder", "over", "toe",
}

# Canonical contractions for the multi-word forms common in Dutch usage.
# Singletons fall through to a generic first-letter rule.
TUSSENVOEGSEL_CONTRACTIONS = {
    "van der": "vd",
    "van den": "vd",
    "van de": "vd",
    "van het": "vh",
    "in der": "id",
    "in den": "id",
    "in de": "id",
    "in het": "ih",
    "op der": "od",
    "op den": "od",
    "op de": "od",
    "op het": "oh",
    "aan der": "ad",
    "aan den": "ad",
    "aan de": "ad",
    "uit den": "ud",
    "uit de": "ud",
    "uit het": "uh",
    "voor de": "vd",
    "voor den": "vd",
    "voor het": "vh",
    "onder de": "od",
    "over de": "od",
    "bij de": "bd",
    "bij den": "bd",
    "bij het": "bh",
    # Singletons.
    "van": "v",
    "de": "d",
    "den": "d",
    "der": "d",
    "het": "h",
    "te": "t",
    "ten": "t",
    "ter": "t",
}

# 't is a recognised tussenvoegsel but is intentionally never shortened
# — it is short already, recognisable, and contracting it loses the
# apostrophe that signals the elision.

VOWELS = set("aeiouyAEIOUY")


def split_name(full_name):
    """Split a full name into (given, tussenvoegsel, surname).

    The tussenvoegsel is the run of one or more lowercase Dutch
    particles that separates the given names from the surname proper.
    Detection is case-insensitive so 'Van Der Berg' splits the same
    as 'van der Berg'.

    Examples:
        'Gary van der Katzenellenbogen' -> ('Gary', 'van der', 'Katzenellenbogen')
        'Henry Brouwerhof'              -> ('Henry', '', 'Brouwerhof')
        'Madonna'                       -> ('', '', 'Madonna')
        'Pieter Jan de Wit'             -> ('Pieter Jan', 'de', 'Wit')
    """
    if not full_name:
        return ("", "", "")
    parts = full_name.split()
    if not parts:
        return ("", "", "")
    if len(parts) == 1:
        return ("", "", parts[0])

    # A tussenvoegsel is never the first or last token: it must sit
    # between given names and a surname proper.
    tussen_start = None
    for i in range(1, len(parts) - 1):
        if parts[i].lower() in TUSSENVOEGSEL_WORDS:
            tussen_start = i
            break

    if tussen_start is None:
        return (" ".join(parts[:-1]), "", parts[-1])

    tussen_end = tussen_start
    # Greedy run, but always leave at least one token for the surname.
    while tussen_end + 1 < len(parts) - 1:
        if parts[tussen_end + 1].lower() in TUSSENVOEGSEL_WORDS:
            tussen_end += 1
        else:
            break

    given = " ".join(parts[:tussen_start])
    tussen = " ".join(parts[tussen_start:tussen_end + 1])
    surname = " ".join(parts[tussen_end + 1:])
    return (given, tussen, surname)


def contract_tussenvoegsel(tussen):
    """'van der' -> 'vd'. Falls back to the first letter of each word.

    A tussenvoegsel containing 't is returned verbatim: 't is short,
    recognisable, and the apostrophe that signals the elision should
    not be lost.
    """
    if not tussen:
        return ""
    words = tussen.split()
    if any(w == "'t" for w in words):
        return tussen
    key = tussen.lower()
    if key in TUSSENVOEGSEL_CONTRACTIONS:
        return TUSSENVOEGSEL_CONTRACTIONS[key]
    return "".join(w[0] for w in words if w).lower()


def initialize_given(given):
    """'Gary' -> 'G.'   'Pieter Jan' -> 'P.J.'"""
    if not given:
        return ""
    return "".join(g[0].upper() + "." for g in given.split() if g)


def _compress_word(word, head_keep, tail_keep=1):
    """Strip vowels from word[head_keep:-tail_keep], preserving case.

    The first head_keep characters and the last tail_keep characters are
    kept verbatim. Internal vowels (a/e/i/o/u/y, either case) are removed.
    Words shorter than head_keep + tail_keep + 1 are returned unchanged.
    """
    if len(word) <= head_keep + tail_keep:
        return word
    head = word[:head_keep]
    tail = word[-tail_keep:] if tail_keep > 0 else ""
    middle = word[head_keep:len(word) - tail_keep]
    stripped = "".join(ch for ch in middle if ch not in VOWELS)
    return head + stripped + tail


def compress_surname(surname, aggressive=False):
    """Compress one surname (may be hyphenated) by removing internal vowels.

    Mild      keeps the first 4 chars and the last char of each segment.
    Aggressive keeps the first 2 chars and the last char.

    Hyphenated surnames compress each segment independently. Any embedded
    lowercase tussenvoegsel within a hyphenated chunk is left alone (so
    'Smit-de Vries' compresses to 'Smit-de Vries' since neither chunk is
    long enough to compress with mild settings).
    """
    if not surname:
        return ""
    head_keep = 2 if aggressive else 4
    out_parts = []
    for chunk in surname.split("-"):
        # A hyphenated chunk may itself contain an embedded tussenvoegsel
        # ("de Vries" inside "Smit-de Vries"). Compress only the
        # capitalised tokens in such a chunk.
        tokens = chunk.split()
        new_tokens = []
        for tok in tokens:
            if tok.lower() in TUSSENVOEGSEL_WORDS:
                new_tokens.append(tok)
            else:
                new_tokens.append(_compress_word(tok, head_keep))
        out_parts.append(" ".join(new_tokens))
    return "-".join(out_parts)


def render_at_level(full_name, level):
    """Apply shortening transformations cumulatively up to `level`.

    See module docstring for the level meanings.
    """
    if not full_name or level <= 0:
        return full_name

    given, tussen, surname = split_name(full_name)
    out_tussen = contract_tussenvoegsel(tussen) if (tussen and level >= 1) else tussen
    out_given = initialize_given(given) if (given and level >= 2) else given
    out_surname = surname
    if level >= 4:
        out_surname = compress_surname(surname, aggressive=True)
    elif level >= 3:
        out_surname = compress_surname(surname, aggressive=False)

    parts = [p for p in (out_given, out_tussen, out_surname) if p]
    return " ".join(parts)


def _truncate_to_width(text, max_width_pt, font_name, font_size, ellipsis="…"):
    """Hard-truncate text with an ellipsis until it fits."""
    if stringWidth(text, font_name, font_size) <= max_width_pt:
        return text
    ell_w = stringWidth(ellipsis, font_name, font_size)
    if ell_w >= max_width_pt:
        return ellipsis
    # Binary search for the longest prefix whose width plus the ellipsis fits.
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip()
        if stringWidth(candidate + ellipsis, font_name, font_size) <= max_width_pt:
            best = candidate + ellipsis
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ellipsis


def shorten_to_fit(full_name, max_width_pt, font_name="Helvetica", font_size=10):
    """Return the mildest shortening of `full_name` that fits max_width_pt.

    If even the most aggressive level overflows, fall back to a hard
    truncation with an ellipsis.
    """
    if not full_name:
        return full_name
    for level in range(0, 5):
        candidate = render_at_level(full_name, level)
        if stringWidth(candidate, font_name, font_size) <= max_width_pt:
            return candidate
    final = render_at_level(full_name, 4)
    return _truncate_to_width(final, max_width_pt, font_name, font_size)
