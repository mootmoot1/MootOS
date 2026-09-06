"""GP-A7 -- Baseline Evidence Capture.

Reconstructs truthful, locally-derivable evidence about prior Continuous
Builder work from this repository's own git history -- read-only,
offline, no network, nothing invented.

This intentionally does NOT reuse :mod:`gpa_evidence_record`'s identity
fields (``eval_case_id`` / ``eval_case_sha256`` / ``architecture_baseline_
sha256``): those name a case from the GP-A5 corpus and a GP-A1 manifest,
neither of which existed when this history was made, and retroactively
inventing a corpus/baseline binding for a merge from months ago would be
exactly the kind of fabrication this phase forbids. Instead,
:class:`HistoricalPRObservation` is a smaller, honestly-scoped sibling
record for one already-merged pull request, built entirely from ``git``
plumbing commands (``log``, ``show``, ``diff --numstat``, ``rev-list``)
against the trusted local repository.

What this can and cannot tell us:

- Files changed / additions / deletions across a merge -- MEASURED
  DIRECTLY from ``git diff --numstat`` between the merge's two parents.
- Commit count on the merged branch -- measured directly from
  ``git rev-list --count``.
- ``provider_label`` -- RECONSTRUCTED via a heuristic: MootOS branch
  names in this repository are conventionally prefixed with the tool
  that authored them (``codex/``, ``chatgpt/``, ``claude/``, ``grok/``).
  This is a naming convention, not a verified identity claim -- a branch
  can be renamed or pushed by anyone. It is recorded with provenance
  ``"reconstructed"``, never ``"measured_directly"``.
- Token counts, dollar cost, wall-clock/model time, first-pass-vs-repair
  outcome -- git records none of this. These stay ``UNKNOWN``. This
  module makes no network call to any provider to try to fill them in.

History availability -- a *shallow* checkout (e.g. CI's ``fetch-depth:
1``) has no merge graph to inspect at all. That is a fundamentally
different state from "history was inspected and no merges were found in
range", and this module never conflates the two: both
:func:`discover_merge_commit_shas` and :func:`reconstruct_pr_observation`
raise :class:`HistoryUnavailableError` (rather than silently returning
an empty result) when the local checkout is shallow, and
:class:`BaselineEvidenceSnapshot` carries an explicit
``history_available`` flag rather than ever letting "unavailable" show
up indistinguishably as "zero historical merges".

Zero authority. A historical observation is evidence, not a judgment --
it grants no capability and does not feed any current decision.
"""

import re
import subprocess
from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    PROVENANCE_CODES,
    UNKNOWN,
    GPAEvalSchemaError,
    canonical_json,
    is_unknown,
    require_base_sha,
    require_no_authority,
    require_numeric_or_unknown,
    require_sha256,
    require_text,
    sha256_hex,
)

HISTORICAL_OBSERVATION_VERSION = "gpa-historical-pr-observation-v1"
SNAPSHOT_VERSION = "gpa-baseline-evidence-snapshot-v1"

MAX_BRANCH_NAME_BYTES = 256
MAX_PROVENANCE_ENTRIES = 16
MAX_OBSERVATIONS = 256
GIT_TIMEOUT_SECONDS = 30

# MootOS branch-naming convention observed in this repository's own git
# history: <tool-prefix>/<description>. Recording only these four known
# prefixes as a provider guess; any other prefix (or none) stays UNKNOWN
# rather than guessing further.
KNOWN_PROVIDER_PREFIXES = frozenset({"codex", "chatgpt", "claude", "grok"})

_OPTIONAL_FIELD_NAMES = (
    "additions",
    "commits_on_branch",
    "deletions",
    "files_changed",
    "provider_label",
    "pr_number",
)

_MERGE_SUBJECT = re.compile(
    r"^Merge pull request #(\d+) from [^/]+/(.+)$"
)
_TOKEN = object()
_SNAPSHOT_TOKEN = object()


class BaselineEvidenceError(GPAEvalSchemaError):
    """Raised when baseline evidence cannot be reconstructed safely."""


class HistoryUnavailableError(BaselineEvidenceError):
    """Raised when the local checkout has no usable merge history.

    Distinct from a plain :class:`BaselineEvidenceError` on purpose: a
    caller catching this specific error knows the reason nothing was
    found is "this checkout is shallow", never "the repository was fully
    inspected and genuinely has zero matching merges".
    """


def _run_git(repo_root, args):
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as error:
        raise BaselineEvidenceError(f"git command failed: {args}") from error
    return proc.stdout


def repository_history_is_shallow(repo_root):
    """True iff the local checkout is a shallow clone (e.g. CI's
    ``fetch-depth: 1``). Read-only (``git rev-parse``); no network.
    """
    output = _run_git(
        repo_root, ["rev-parse", "--is-shallow-repository"],
    ).strip()
    return output == "true"


def discover_merge_commit_shas(repo_root, *, limit=30):
    """Return the ``limit`` most recent merge commit SHAs on the current
    branch, newest first. Read-only (``git log``); no checkout, no
    network.

    Raises :class:`HistoryUnavailableError` -- rather than returning an
    empty tuple -- when the checkout is shallow: an empty tuple must only
    ever mean "the full history was inspected and no merges matched",
    never "there was no history to inspect".
    """
    if type(limit) is not int or limit <= 0 or limit > MAX_OBSERVATIONS:
        raise BaselineEvidenceError("limit is malformed")
    if repository_history_is_shallow(repo_root):
        raise HistoryUnavailableError(
            "repository is a shallow clone; merge history is unavailable"
        )
    output = _run_git(
        repo_root,
        ["log", "--merges", f"-n{limit}", "--pretty=format:%H"],
    )
    return tuple(line for line in output.splitlines() if line)


def _parse_provider_label(branch_path):
    if "/" not in branch_path:
        return UNKNOWN
    prefix = branch_path.split("/", 1)[0]
    if prefix in KNOWN_PROVIDER_PREFIXES:
        return prefix
    return UNKNOWN


def _numstat_totals(repo_root, before_sha, after_sha):
    output = _run_git(
        repo_root, ["diff", "--numstat", before_sha, after_sha],
    )
    files = 0
    additions = 0
    deletions = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        added, removed = parts[0], parts[1]
        if added.isdigit():
            additions += int(added)
        if removed.isdigit():
            deletions += int(removed)
    return files, additions, deletions


@dataclass(frozen=True)
class HistoricalPRObservation:
    """One reconstructed, evidence-only observation of an already-merged
    Continuous Builder pull request. Zero authority.
    """

    schema_version: str
    merge_commit_sha: str
    parent_before_sha: str
    parent_branch_sha: str
    pr_number: object
    branch_name: str
    provider_label: object
    files_changed: object
    additions: object
    deletions: object
    commits_on_branch: object
    outcome_state: str
    field_provenance: tuple
    observation_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise BaselineEvidenceError(
                "historical observation requires trusted construction"
            )
        if self.schema_version != HISTORICAL_OBSERVATION_VERSION:
            raise BaselineEvidenceError("schema_version is unsupported")
        for value, label in (
            (self.merge_commit_sha, "merge_commit_sha"),
            (self.parent_before_sha, "parent_before_sha"),
            (self.parent_branch_sha, "parent_branch_sha"),
        ):
            require_base_sha(value, label)
        require_text(self.branch_name, "branch_name", MAX_BRANCH_NAME_BYTES)
        require_numeric_or_unknown(
            self.pr_number, "pr_number", minimum=1, maximum=10**7,
            integer=True,
        )
        if self.provider_label != UNKNOWN and (
            self.provider_label not in KNOWN_PROVIDER_PREFIXES
        ):
            raise BaselineEvidenceError("provider_label is unsupported")
        for name in ("files_changed", "additions", "deletions", "commits_on_branch"):
            require_numeric_or_unknown(
                getattr(self, name), name, minimum=0, maximum=10**9,
                integer=True,
            )
        if self.outcome_state != "completed":
            raise BaselineEvidenceError(
                "a merged PR's outcome_state can only be 'completed'"
            )
        _validate_provenance(self)
        require_no_authority(self)
        require_sha256(self.observation_sha256, "observation_sha256")
        if self.observation_sha256 != sha256_hex(canonical_json(self._body())):
            raise BaselineEvidenceError("observation_sha256 mismatch")

    def _body(self):
        body = {
            "branch_name": self.branch_name,
            "field_provenance": [list(item) for item in self.field_provenance],
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "merge_commit_sha": self.merge_commit_sha,
            "outcome_state": self.outcome_state,
            "parent_before_sha": self.parent_before_sha,
            "parent_branch_sha": self.parent_branch_sha,
            "pr_number": self.pr_number,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "worker_output_trusted": False,
        }
        for name in _OPTIONAL_FIELD_NAMES:
            body[name] = getattr(self, name)
        return body

    def to_dict(self):
        body = self._body()
        body["observation_sha256"] = self.observation_sha256
        return body


def _validate_provenance(obj):
    if type(obj.field_provenance) is not tuple:
        raise BaselineEvidenceError("field_provenance is malformed")
    if len(obj.field_provenance) > MAX_PROVENANCE_ENTRIES:
        raise BaselineEvidenceError("field_provenance exceeds bound")
    seen = set()
    for entry in obj.field_provenance:
        if type(entry) is not tuple or len(entry) != 2:
            raise BaselineEvidenceError("field_provenance entry is malformed")
        name, code = entry
        if name not in _OPTIONAL_FIELD_NAMES:
            raise BaselineEvidenceError(f"unknown field in provenance: {name}")
        if name in seen:
            raise BaselineEvidenceError(f"duplicate provenance entry: {name}")
        seen.add(name)
        if code not in PROVENANCE_CODES:
            raise BaselineEvidenceError(f"unsupported provenance code: {code}")
    named = frozenset(entry[0] for entry in obj.field_provenance)
    for name in _OPTIONAL_FIELD_NAMES:
        known = not is_unknown(getattr(obj, name))
        if known and name not in named:
            raise BaselineEvidenceError(f"{name} is known but unattributed")
        if not known and name in named:
            raise BaselineEvidenceError(f"{name} is UNKNOWN but attributed")
    if obj.field_provenance != tuple(sorted(obj.field_provenance)):
        raise BaselineEvidenceError("field_provenance is not canonically ordered")


def reconstruct_pr_observation(repo_root, merge_commit_sha):
    """Reconstruct one :class:`HistoricalPRObservation` from git history.

    Raises :class:`HistoryUnavailableError` if the checkout is shallow
    (an arbitrary historical commit's parent objects are typically absent
    in that case, even when the commit's own SHA happens to be known) --
    never silently treats a shallow checkout as "not a merge commit".

    Raises :class:`BaselineEvidenceError` if ``merge_commit_sha`` is not a
    two-parent merge commit -- callers building a snapshot over many
    commits are expected to skip and record such failures rather than
    treat them as a hard stop (see :func:`create_baseline_evidence_snapshot`).
    """
    require_base_sha(merge_commit_sha, "merge_commit_sha")
    if repository_history_is_shallow(repo_root):
        raise HistoryUnavailableError(
            "repository is a shallow clone; merge history is unavailable"
        )
    parents_line = _run_git(
        repo_root, ["show", "-s", "--format=%P", merge_commit_sha],
    ).strip()
    parents = parents_line.split()
    if len(parents) != 2:
        raise BaselineEvidenceError(
            f"{merge_commit_sha} is not a two-parent merge commit"
        )
    before_sha, branch_sha = parents
    subject = _run_git(
        repo_root, ["show", "-s", "--format=%s", merge_commit_sha],
    ).strip()
    match = _MERGE_SUBJECT.match(subject)
    pr_number = int(match.group(1)) if match else UNKNOWN
    branch_path = match.group(2) if match else subject
    provider_label = _parse_provider_label(branch_path) if match else UNKNOWN

    files_changed, additions, deletions = _numstat_totals(
        repo_root, before_sha, branch_sha
    )
    commit_count_output = _run_git(
        repo_root, ["rev-list", "--count", f"{before_sha}..{branch_sha}"],
    ).strip()
    commits_on_branch = (
        int(commit_count_output) if commit_count_output.isdigit() else UNKNOWN
    )

    # files_changed/additions/deletions come straight from a successful
    # `git diff --numstat` (always a real int here, never UNKNOWN, since a
    # failing git command already raised above); pr_number/provider_label/
    # commits_on_branch can each independently be UNKNOWN.
    field_provenance = [
        ("files_changed", "reconstructed"),
        ("additions", "reconstructed"),
        ("deletions", "reconstructed"),
    ]
    if not is_unknown(pr_number):
        field_provenance.append(("pr_number", "reconstructed"))
    if not is_unknown(provider_label):
        field_provenance.append(("provider_label", "reconstructed"))
    if not is_unknown(commits_on_branch):
        field_provenance.append(("commits_on_branch", "reconstructed"))
    field_provenance = tuple(sorted(field_provenance))

    values = {
        "schema_version": HISTORICAL_OBSERVATION_VERSION,
        "merge_commit_sha": merge_commit_sha,
        "parent_before_sha": before_sha,
        "parent_branch_sha": branch_sha,
        "pr_number": pr_number,
        "branch_name": branch_path[:MAX_BRANCH_NAME_BYTES] or "unknown",
        "provider_label": provider_label,
        "files_changed": files_changed,
        "additions": additions,
        "deletions": deletions,
        "commits_on_branch": commits_on_branch,
        "outcome_state": "completed",
        "field_provenance": field_provenance,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(HistoricalPRObservation)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return HistoricalPRObservation(
        **values,
        observation_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


@dataclass(frozen=True)
class BaselineEvidenceSnapshot:
    """Sealed, ordered collection of historical PR observations.

    ``history_available`` is the explicit signal distinguishing "the
    repository's merge history was inspected" from "it could not be":
    when ``False``, ``observations`` is always empty -- but an empty
    ``observations`` with ``history_available=True`` is also a valid,
    meaningful state (history was checked; there was genuinely nothing
    in range). The two must never be confused.
    """

    version: str
    observations: tuple
    history_available: bool
    snapshot_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _SNAPSHOT_TOKEN:
            raise BaselineEvidenceError(
                "snapshot requires trusted construction"
            )
        if self.version != SNAPSHOT_VERSION:
            raise BaselineEvidenceError("version is unsupported")
        if type(self.observations) is not tuple or (
            len(self.observations) > MAX_OBSERVATIONS
        ):
            raise BaselineEvidenceError("observations is malformed")
        if any(
            not isinstance(item, HistoricalPRObservation)
            for item in self.observations
        ):
            raise BaselineEvidenceError("observations contains an invalid entry")
        shas = tuple(item.merge_commit_sha for item in self.observations)
        if shas != tuple(sorted(set(shas))):
            raise BaselineEvidenceError(
                "observations are not canonically ordered/unique"
            )
        if type(self.history_available) is not bool:
            raise BaselineEvidenceError("history_available must be a bool")
        if not self.history_available and self.observations:
            raise BaselineEvidenceError(
                "observations must be empty when history_available is False"
            )
        require_no_authority(self)
        require_sha256(self.snapshot_sha256, "snapshot_sha256")
        if self.snapshot_sha256 != sha256_hex(canonical_json(self._body())):
            raise BaselineEvidenceError("snapshot_sha256 mismatch")

    def _body(self):
        return {
            "github_authorized": False,
            "history_available": self.history_available,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "observations": [item.to_dict() for item in self.observations],
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "version": self.version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["snapshot_sha256"] = self.snapshot_sha256
        return body


def create_baseline_evidence_snapshot(repo_root, *, limit=15):
    """Reconstruct a sealed snapshot over the ``limit`` most recent merges.

    Merge commits that are not a clean two-parent merge (rare, but
    possible after a rebase-and-merge or an octopus merge) are silently
    skipped rather than aborting the whole snapshot -- this function
    trades completeness for never crashing on repository history it
    cannot cleanly interpret.

    When the checkout is shallow, this does NOT raise and does NOT
    pretend zero merges exist -- it returns a snapshot with
    ``history_available=False`` and empty ``observations``, so a caller
    can tell "nothing to report" apart from "couldn't check" by reading
    ``history_available`` rather than guessing from an empty list.
    """
    try:
        shas = discover_merge_commit_shas(repo_root, limit=limit)
        history_available = True
    except HistoryUnavailableError:
        shas = ()
        history_available = False
    observations = []
    for sha in shas:
        try:
            observations.append(reconstruct_pr_observation(repo_root, sha))
        except BaselineEvidenceError:
            continue
    ordered = tuple(
        sorted(observations, key=lambda item: item.merge_commit_sha)
    )
    values = {
        "version": SNAPSHOT_VERSION,
        "observations": ordered,
        "history_available": history_available,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(BaselineEvidenceSnapshot)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return BaselineEvidenceSnapshot(
        **values,
        snapshot_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_SNAPSHOT_TOKEN,
    )


def baseline_evidence_is_observational_only():
    """TRUST REVIEW helper: True -- a historical observation grants no
    capability."""
    return True
