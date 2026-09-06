"""Evaluator-only acceptance check for GP-A eval case refactor_001.

Not part of refactor_001's worker-visible context. Named ``acceptance.py``
(not ``test_*.py``) so the repository's own ``pytest`` run does not
auto-collect it; the GP-A6 harness invokes it explicitly with a
``python_files`` override.

This check is behavior-equivalence only: it asserts ``quote_standard``
and ``quote_bulk`` still return the same values as the frozen "before"
state across a fixed input table. It does NOT check that the duplication
was actually removed -- that a refactor genuinely happened is left to
human/verifier review, exactly as ``behavior_preserving_refactor`` cases
are documented (verification_difficulty="medium") to require judgement
beyond a single automated check.
"""

from pricing import quote_bulk, quote_standard

CASES = (
    (10.0, 3, 0.0, 0.0),
    (19.99, 7, 0.1, 0.08),
    (100.0, 1, 0.5, 0.2),
    (0.0, 5, 0.1, 0.1),
    (250.5, 12, 0.15, 0.0),
)

EXPECTED_STANDARD = (30.0, 136.01, 60.0, 0.0, 2555.1)
EXPECTED_BULK = (30.0, 136.01, 60.0, 0.0, 2555.1)


def test_quote_standard_matches_frozen_expected_values():
    for args, expected in zip(CASES, EXPECTED_STANDARD):
        assert quote_standard(*args) == expected


def test_quote_bulk_matches_frozen_expected_values():
    for args, expected in zip(CASES, EXPECTED_BULK):
        assert quote_bulk(*args) == expected


def test_quote_standard_and_quote_bulk_still_agree():
    for args in CASES:
        assert quote_standard(*args) == quote_bulk(*args)
