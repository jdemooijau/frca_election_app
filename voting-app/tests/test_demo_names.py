"""Tests for demo candidate name generation (10 elder + 8 deacon capacity)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demo_names import (
    DUTCH_SURNAMES,
    FALLBACK_DEACON_CANDIDATES,
    FALLBACK_ELDER_CANDIDATES,
    FIRST_NAMES,
    generate_demo_names,
)


class TestFallbackLists:
    def test_fallback_supports_ten_elders_and_eight_deacons(self):
        assert len(FALLBACK_ELDER_CANDIDATES) == 10
        assert len(FALLBACK_DEACON_CANDIDATES) == 8

    def test_fallback_names_are_unique(self):
        combined = FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES
        assert len(set(combined)) == 18

    def test_fallback_surnames_are_invented_not_pool(self):
        # Fallback surnames must be mashups, never real pool surnames,
        # so demo candidates cannot collide with real families.
        pool = {s.lower() for s in DUTCH_SURNAMES}
        for full in FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES:
            surname = full.split(" ", 1)[1].lower()
            assert surname not in pool, f"{full} uses a real pool surname"

    def test_fallback_first_names_come_from_first_names_list(self):
        allowed = set(FIRST_NAMES) | {"Henry", "James", "William", "Neil",
                                      "Gary", "Peter", "Fred", "Ryan",
                                      "Derek", "Andrew"}
        for full in FALLBACK_ELDER_CANDIDATES + FALLBACK_DEACON_CANDIDATES:
            first = full.split(" ", 1)[0]
            assert first in allowed, f"{full} first name not Australian style"


class TestGenerateDemoNames:
    def test_fallback_mode_returns_all_18(self):
        names = generate_demo_names(count=18, member_names=None)
        assert len(names) == 18

    def test_pool_mode_yields_18_unique_names(self):
        members = ["John Smith", "Adam Brown", "Carl Jones", "Dan White"]
        names = generate_demo_names(count=18, member_names=members)
        assert len(names) == 18
        assert len(set(names)) == 18
