"""Synthetic GP-A eval fixture (case nb_001). NOT production code.

Disposable, deterministic fixture used only so the GP-A6 offline
evaluation harness has something real to verify a worker's patch
against. The bug below is intentional: it is the frozen "before" state
of eval case nb_001 (narrow_bug_fix).
"""


class WidgetCounter:
    """Counts widgets without exceeding a fixed capacity."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.count = 0

    def add(self, amount=1):
        """Add ``amount`` widgets and return the new count.

        BUG: does not clamp to ``capacity`` -- ``count`` can exceed it.
        """
        self.count = self.count + amount
        return self.count
