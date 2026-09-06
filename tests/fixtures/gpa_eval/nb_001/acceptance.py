"""Evaluator-only acceptance check for GP-A eval case nb_001.

Not part of the worker-visible context for nb_001 (see
``gpa_eval_corpus.create_gpa_eval_corpus_v1``'s ``context_inputs`` /
``allowed_scope`` for that case -- this file is deliberately absent from
both). Present on disk only because the fixture must be a real,
git-tracked, replayable file; a worker-facing adapter is responsible for
never surfacing evaluator-only paths in what it shows a worker.

Deliberately named ``acceptance.py`` rather than ``test_*.py`` so the
repository's own ``pytest`` run does not auto-collect it (it is meant to
fail against the frozen "before" fixture state). The GP-A6 harness
invokes it explicitly with a ``python_files`` override.
"""

from widget_counter import WidgetCounter


def test_add_clamps_to_capacity():
    counter = WidgetCounter(capacity=3)
    assert counter.add(2) == 2
    assert counter.add(5) == 3
    assert counter.count == 3


def test_add_below_capacity_is_unaffected():
    counter = WidgetCounter(capacity=10)
    assert counter.add(4) == 4
    assert counter.add(1) == 5
