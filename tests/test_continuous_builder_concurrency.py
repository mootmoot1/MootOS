"""Real-thread concurrency tests: concurrent queue CAS, concurrent lease
acquisition, migration concurrency, and an actual transaction rollback
under conflict -- not mocked, real ``sqlite3`` connections racing against
each other through ``BEGIN IMMEDIATE``.
"""

import threading

from backend.continuous_builder.leases import LeaseError, acquire_lease, create_attempt
from backend.continuous_builder.queue_store import QueueStoreError, append_event
from backend.migrations import run_migrations
from test_continuous_builder_queue_store import prepared

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:01:00+00:00"


def _run_concurrently(functions):
    results = [None] * len(functions)
    errors = [None] * len(functions)

    def runner(index, function):
        try:
            results[index] = function()
        except Exception as error:  # noqa: BLE001 - capturing for assertion
            errors[index] = error

    threads = [
        threading.Thread(target=runner, args=(index, function))
        for index, function in enumerate(functions)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


def test_concurrent_append_event_cas_serializes_to_exactly_one_winner(tmp_path):
    path, event = prepared(tmp_path)

    def attempt():
        return append_event(path, event, 0, None)

    results, errors = _run_concurrently([attempt for _ in range(6)])
    successes = [result for result in results if result is not None]
    failures = [
        error for error in errors
        if isinstance(error, QueueStoreError)
    ]
    assert len(successes) == 1
    assert len(failures) == 5
    for failure in failures:
        assert "compare-and-swap" in str(failure) or "duplicate" in str(failure)


def test_concurrent_lease_acquisition_serializes_to_exactly_one_winner(tmp_path):
    path, _ = prepared(tmp_path)
    for index in range(6):
        create_attempt(
            path, f"attempt-{index}", "continuous-builder", "phase-1",
            "CB-001", "1", f"owner-{index}", T0,
        )

    def attempt(index):
        return lambda: acquire_lease(
            path, f"lease-{index}", f"attempt-{index}", "CB-001",
            f"owner-{index}", T0, T1,
        )

    _, errors = _run_concurrently([attempt(index) for index in range(6)])
    lease_errors = [error for error in errors if isinstance(error, LeaseError)]
    successes = [error for error in errors if error is None]
    assert len(successes) == 1
    assert len(lease_errors) == 5


def test_migration_run_concurrently_reaches_one_consistent_final_version(tmp_path):
    path = tmp_path / "mootos.db"

    def apply():
        return run_migrations(path)

    results, errors = _run_concurrently([apply for _ in range(4)])
    real_errors = [error for error in errors if error is not None]
    assert not real_errors
    assert all(result == results[0] for result in results)
    assert results[0] > 0


def test_conflicting_writers_actually_roll_back_not_partially_commit(tmp_path):
    path, event = prepared(tmp_path)

    def first():
        return append_event(path, event, 0, None)

    def second():
        return append_event(path, event, 0, None)

    results, errors = _run_concurrently([first, second])
    successes = [result for result in results if result is not None]
    assert len(successes) == 1

    import sqlite3
    connection = sqlite3.connect(path)
    count = connection.execute(
        "SELECT count(*) FROM builder_events"
    ).fetchone()[0]
    connection.close()
    assert count == 1
