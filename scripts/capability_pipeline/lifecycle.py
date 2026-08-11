"""The manual capability-build lifecycle (V0.3E).

A small, explicit state model -- **not** the larger proposed -> ... ->
installed -> deprecated -> rolled-back machine ADR-034 defers to V0.4A
(automated builder). This is the minimum needed to prove the *manual*
pipeline once by hand:

    proposed -> specified -> implemented -> tested -> reviewed
             -> ready_for_pr -> merged

Every transition is a deliberate, human-invoked function call with a
required ``actor`` and ``note`` -- there is no code path anywhere in this
module (or reachable from it) that advances a record's state on its own,
in response to a review being attached, a test passing, or any other
event. See ``docs/CAPABILITY_BUILD_PIPELINE.md`` Sec4.

**Persistence is a plain JSON file, not a database.** A ``CapabilityRecord``
is small, append-only history plus a spec; ``capability_specs/*.json`` in
this repository is the only "storage" this phase introduces, and it is
ordinary version-controlled text -- reviewed the same way any other
source file is, with no separate access path or query surface.

**This module has no dependency on, and no awareness of,
``backend/tool_registry.py``.** That is deliberate: nothing here can
register a tool, and nothing in the registry consults these files. A
``CapabilityRecord`` reaching ``merged`` records that a human performed
the real merge elsewhere (a Git action, external to this module) -- it
does not, and structurally cannot, cause one.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from scripts.capability_pipeline.review import AdvisoryReview
from scripts.capability_pipeline.spec import CapabilitySpec, CapabilitySpecError, spec_from_dict


class LifecycleError(ValueError):
    """Raised on an invalid or malformed lifecycle transition/record."""


STATE_PROPOSED = "proposed"
STATE_SPECIFIED = "specified"
STATE_IMPLEMENTED = "implemented"
STATE_TESTED = "tested"
STATE_REVIEWED = "reviewed"
STATE_READY_FOR_PR = "ready_for_pr"
STATE_MERGED = "merged"

# Order matters: this tuple IS the allowed transition graph. A transition
# is valid only from a state to the very next state in this sequence --
# no skipping ahead, no moving backward, no jumping straight to "merged".
LIFECYCLE_STATES = (
    STATE_PROPOSED,
    STATE_SPECIFIED,
    STATE_IMPLEMENTED,
    STATE_TESTED,
    STATE_REVIEWED,
    STATE_READY_FOR_PR,
    STATE_MERGED,
)
_STATE_INDEX = {state: index for index, state in enumerate(LIFECYCLE_STATES)}


@dataclass(frozen=True)
class LifecycleEvent:
    """One recorded, human-attributed state transition."""

    state: str
    actor: str
    note: str
    at: str

    def to_dict(self) -> dict:
        return {"state": self.state, "actor": self.actor, "note": self.note, "at": self.at}


@dataclass(frozen=True)
class CapabilityRecord:
    """A capability spec plus its lifecycle history and attached advisory
    reviews. Immutable -- every "mutating" operation in this module
    returns a *new* record rather than modifying one in place, so an old
    reference can never be surprised by a later transition happening
    somewhere else.
    """

    spec: CapabilitySpec
    state: str
    history: tuple = ()
    reviews: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict(),
            "state": self.state,
            "history": [event.to_dict() for event in self.history],
            "reviews": [review.to_dict() for review in self.reviews],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"


def new_record(spec: CapabilitySpec, *, actor: str, note: str) -> CapabilityRecord:
    """Create a brand-new record in the initial ``proposed`` state. This
    is the only way to create a record -- there is no constructor path
    that starts anywhere other than ``proposed``."""
    if not actor or not actor.strip():
        raise LifecycleError("actor is required and cannot be empty")
    if not note or not note.strip():
        raise LifecycleError("note is required and cannot be empty")
    event = LifecycleEvent(state=STATE_PROPOSED, actor=actor, note=note, at=_now())
    return CapabilityRecord(spec=spec, state=STATE_PROPOSED, history=(event,), reviews=())


def transition(record: CapabilityRecord, new_state: str, *, actor: str, note: str) -> CapabilityRecord:
    """Advance ``record`` to ``new_state``, explicitly and only one step
    at a time. Raises ``LifecycleError`` (not a silent no-op) for:

    - any state not the immediate successor of the current one (no
      skipping, no jumping straight to ``merged``, no going backward);
    - a missing/blank ``actor`` or ``note``.

    There is no keyword or code path that bypasses this check -- this is
    the *only* function in this module that changes ``state``.
    """
    if new_state not in _STATE_INDEX:
        raise LifecycleError(f"Unknown lifecycle state: {new_state!r}")
    if not actor or not actor.strip():
        raise LifecycleError("actor is required and cannot be empty")
    if not note or not note.strip():
        raise LifecycleError("note is required and cannot be empty")

    current_index = _STATE_INDEX[record.state]
    target_index = _STATE_INDEX[new_state]
    if target_index != current_index + 1:
        raise LifecycleError(
            f"Cannot transition from {record.state!r} to {new_state!r}: "
            f"only the immediate next state "
            f"({LIFECYCLE_STATES[current_index + 1]!r}, if any) is allowed. "
            "No automatic or skipped transitions exist in this pipeline."
        )

    event = LifecycleEvent(state=new_state, actor=actor, note=note, at=_now())
    return CapabilityRecord(
        spec=record.spec,
        state=new_state,
        history=record.history + (event,),
        reviews=record.reviews,
    )


def attach_review(record: CapabilityRecord, review: AdvisoryReview) -> CapabilityRecord:
    """Attach one advisory review to ``record``. **Never changes
    ``state``** -- a review, regardless of its verdict, is data appended
    for a human to read, exactly like every other AI review in this
    architecture (ADR-032). To move the record forward after reading the
    reviews, a human still calls ``transition`` explicitly.
    """
    return CapabilityRecord(
        spec=record.spec,
        state=record.state,
        history=record.history,
        reviews=record.reviews + (review,),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_record(record: CapabilityRecord, path) -> None:
    Path(path).write_text(record.to_json(), encoding="utf-8")


def load_record(path) -> CapabilityRecord:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise LifecycleError(f"{path}: not valid JSON: {error}") from error
    return record_from_dict(data)


def record_from_dict(data: Mapping[str, Any]) -> CapabilityRecord:
    if not isinstance(data, Mapping):
        raise LifecycleError("A capability record must be a JSON/YAML object")

    unknown = set(data.keys()) - {"spec", "state", "history", "reviews"}
    if unknown:
        raise LifecycleError(f"Unknown capability-record field(s): {', '.join(sorted(unknown))}")

    if "spec" not in data or "state" not in data:
        raise LifecycleError("A capability record requires 'spec' and 'state'")

    try:
        spec = spec_from_dict(data["spec"])
    except CapabilitySpecError as error:
        raise LifecycleError(f"Invalid embedded spec: {error}") from error

    state = data["state"]
    if state not in _STATE_INDEX:
        raise LifecycleError(f"Unknown lifecycle state in record: {state!r}")

    history = tuple(
        LifecycleEvent(state=item["state"], actor=item["actor"], note=item["note"], at=item["at"])
        for item in data.get("history", [])
    )
    reviews = tuple(AdvisoryReview.from_dict(item) for item in data.get("reviews", []))

    return CapabilityRecord(spec=spec, state=state, history=history, reviews=reviews)


def main(argv: Optional[list] = None) -> int:
    """CLI: report a capability record's current state and history --
    read-only, never mutates the file."""
    import argparse

    parser = argparse.ArgumentParser(description="Inspect a V0.3E capability record JSON file.")
    parser.add_argument("path", help="Path to a capability record JSON file")
    args = parser.parse_args(argv)

    try:
        record = load_record(args.path)
    except LifecycleError as error:
        print(f"INVALID: {error}")
        return 1

    print(f"{record.spec.capability_id}: state={record.state}")
    for event in record.history:
        print(f"  {event.at}  {event.state:14s} actor={event.actor!r}  {event.note}")
    for review in record.reviews:
        print(f"  [review:{review.role}] {review.verdict} -- {review.reviewer}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
