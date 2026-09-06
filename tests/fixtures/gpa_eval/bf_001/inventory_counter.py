"""Synthetic GP-A eval fixture (case bf_001). NOT production code.

Disposable, deterministic fixture: frozen "before" state of eval case
bf_001 (bounded_feature_addition). The class intentionally lacks a
``remaining()`` method -- adding it is the task.
"""


class InventoryCounter:
    """Tracks how many units of a fixed-capacity item are in stock."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.count = 0

    def add(self, amount=1):
        if self.count + amount > self.capacity:
            raise ValueError("exceeds capacity")
        self.count += amount
        return self.count
