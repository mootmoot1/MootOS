"""Evaluator-only acceptance check for GP-A eval case bf_001.

Not part of bf_001's worker-visible context. Named ``acceptance.py`` (not
``test_*.py``) so the repository's own ``pytest`` run does not
auto-collect it; the GP-A6 harness invokes it explicitly with a
``python_files`` override.
"""

from inventory_counter import InventoryCounter


def test_remaining_reflects_capacity_minus_count():
    counter = InventoryCounter(capacity=5)
    assert counter.remaining() == 5
    counter.add(2)
    assert counter.remaining() == 3


def test_remaining_reaches_zero_at_capacity():
    counter = InventoryCounter(capacity=2)
    counter.add(2)
    assert counter.remaining() == 0


def test_existing_add_behavior_is_unchanged():
    counter = InventoryCounter(capacity=2)
    counter.add(2)
    try:
        counter.add(1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when exceeding capacity")
