"""GP-A2 -- MootOS Task Taxonomy.

A deterministic, sealed taxonomy of representative coding-task classes
MootOS is likely to hand to a worker, used to classify eval corpus cases
(GP-A3/GP-A5) and to describe evaluation dimensions for benchmark results.

IMPORTANT -- this taxonomy is DESCRIPTIVE ONLY:

- ``autonomy_experiment_suitable`` and every risk/difficulty field describe
  a class of task; they do not grant, restrict, or imply any capability.
- Trusted capability policy (what a worker is actually permitted to touch,
  and under what review) is decided elsewhere, in a future phase (GP-C),
  never by this taxonomy.
- Nothing here changes TCB membership, sandbox policy, or verifier
  authority. Classifying a case as "tcb_adjacent_change" does not, by
  itself, subject any real file to TCB review -- that continues to be
  decided solely by ``trusted_policy.create_mootos_tcb_registry_v1()``.

Read-only. No network. No model call. Zero authority.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_id,
    require_no_authority,
    require_sha256,
    require_text,
    sha256_hex,
)

TAXONOMY_VERSION = "gpa-task-taxonomy-v1"
MAX_DESCRIPTION_BYTES = 512
MAX_RISK_INDICATORS = 8
MAX_CLASSES = 32

SCOPE_SIZES = frozenset({"narrow", "bounded", "multi_file", "wide"})
FILE_COUNT_HINTS = frozenset(
    {"single_file", "few_files", "several_files", "many_files"}
)
BREADTH_LEVELS = frozenset({"low", "medium", "high"})
RISK_INDICATORS = frozenset(
    {
        "none",
        "tcb_adjacent",
        "security_sensitive",
        "schema_migration",
        "dependency_boundary_change",
        "irreversible_change",
        "policy_sensitive",
        "high_context_demand",
    }
)
REVERSIBILITY_LEVELS = frozenset({"easy", "moderate", "hard"})

_TOKEN = object()
_CONTAINER_TOKEN = object()


class TaskTaxonomyError(GPAEvalSchemaError):
    """Raised when task taxonomy evidence is invalid."""


@dataclass(frozen=True)
class TaxonomyClass:
    """One descriptive coding-task class. Grants no capability."""

    class_id: str
    description: str
    expected_scope_size: str
    file_count_hint: str
    dependency_breadth: str
    context_demand: str
    verification_difficulty: str
    reversibility: str
    risk_indicators: tuple
    autonomy_experiment_suitable: bool
    class_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TaskTaxonomyError(
                "taxonomy class requires trusted construction"
            )
        require_id(self.class_id, "class_id")
        require_text(self.description, "description", MAX_DESCRIPTION_BYTES)
        if self.expected_scope_size not in SCOPE_SIZES:
            raise TaskTaxonomyError("expected_scope_size is unsupported")
        if self.file_count_hint not in FILE_COUNT_HINTS:
            raise TaskTaxonomyError("file_count_hint is unsupported")
        for name in ("dependency_breadth", "context_demand", "verification_difficulty"):
            if getattr(self, name) not in BREADTH_LEVELS:
                raise TaskTaxonomyError(f"{name} is unsupported")
        if self.reversibility not in REVERSIBILITY_LEVELS:
            raise TaskTaxonomyError("reversibility is unsupported")
        if type(self.risk_indicators) is not tuple or not self.risk_indicators:
            raise TaskTaxonomyError("risk_indicators is malformed")
        if len(self.risk_indicators) > MAX_RISK_INDICATORS:
            raise TaskTaxonomyError("risk_indicators exceeds bound")
        if self.risk_indicators != tuple(sorted(set(self.risk_indicators))):
            raise TaskTaxonomyError("risk_indicators is not canonical")
        if any(item not in RISK_INDICATORS for item in self.risk_indicators):
            raise TaskTaxonomyError("risk_indicators contains an unknown code")
        if type(self.autonomy_experiment_suitable) is not bool:
            raise TaskTaxonomyError(
                "autonomy_experiment_suitable must be a bool"
            )
        require_sha256(self.class_sha256, "class_sha256")
        if self.class_sha256 != sha256_hex(canonical_json(self._body())):
            raise TaskTaxonomyError("class_sha256 mismatch")

    def _body(self):
        return {
            "autonomy_experiment_suitable": self.autonomy_experiment_suitable,
            "class_id": self.class_id,
            "context_demand": self.context_demand,
            "dependency_breadth": self.dependency_breadth,
            "description": self.description,
            "expected_scope_size": self.expected_scope_size,
            "file_count_hint": self.file_count_hint,
            "reversibility": self.reversibility,
            "risk_indicators": list(self.risk_indicators),
            "verification_difficulty": self.verification_difficulty,
        }

    def to_dict(self):
        body = self._body()
        body["class_sha256"] = self.class_sha256
        return body


def _seal_class(**values):
    values = dict(values)
    values["risk_indicators"] = tuple(sorted(set(values["risk_indicators"])))
    provisional = object.__new__(TaxonomyClass)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TaxonomyClass(
        **values,
        class_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


@dataclass(frozen=True)
class TaskTaxonomy:
    """Sealed, ordered collection of every known taxonomy class."""

    version: str
    classes: tuple
    taxonomy_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _CONTAINER_TOKEN:
            raise TaskTaxonomyError(
                "task taxonomy requires trusted construction"
            )
        if self.version != TAXONOMY_VERSION:
            raise TaskTaxonomyError("version is unsupported")
        if type(self.classes) is not tuple or not self.classes:
            raise TaskTaxonomyError("classes is malformed")
        if len(self.classes) > MAX_CLASSES:
            raise TaskTaxonomyError("classes exceeds bound")
        if any(not isinstance(item, TaxonomyClass) for item in self.classes):
            raise TaskTaxonomyError("classes contains an invalid entry")
        ids = tuple(item.class_id for item in self.classes)
        if ids != tuple(sorted(set(ids))):
            raise TaskTaxonomyError("class IDs are not canonically ordered")
        require_no_authority(self)
        require_sha256(self.taxonomy_sha256, "taxonomy_sha256")
        if self.taxonomy_sha256 != sha256_hex(canonical_json(self._body())):
            raise TaskTaxonomyError("taxonomy_sha256 mismatch")

    def _body(self):
        return {
            "classes": [item.to_dict() for item in self.classes],
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "version": self.version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["taxonomy_sha256"] = self.taxonomy_sha256
        return body


def _class_definitions():
    """Return the 12 required class specs as plain kwargs dicts."""
    return (
        dict(
            class_id="narrow_bug_fix",
            description=(
                "A single, well-localized defect corrected in one function "
                "or one file with an existing or trivially added regression "
                "test."
            ),
            expected_scope_size="narrow",
            file_count_hint="single_file",
            dependency_breadth="low",
            context_demand="low",
            verification_difficulty="low",
            reversibility="easy",
            risk_indicators=("none",),
            autonomy_experiment_suitable=True,
        ),
        dict(
            class_id="bounded_feature_addition",
            description=(
                "A new, additive capability confined to one component with "
                "a clear acceptance test and no change to existing "
                "behavior."
            ),
            expected_scope_size="bounded",
            file_count_hint="few_files",
            dependency_breadth="low",
            context_demand="medium",
            verification_difficulty="medium",
            reversibility="easy",
            risk_indicators=("none",),
            autonomy_experiment_suitable=True,
        ),
        dict(
            class_id="test_addition",
            description=(
                "New test coverage for existing, unchanged production "
                "behavior; production code is not expected to change."
            ),
            expected_scope_size="narrow",
            file_count_hint="single_file",
            dependency_breadth="low",
            context_demand="low",
            verification_difficulty="low",
            reversibility="easy",
            risk_indicators=("none",),
            autonomy_experiment_suitable=True,
        ),
        dict(
            class_id="behavior_preserving_refactor",
            description=(
                "Structural change intended to leave externally observable "
                "behavior unchanged; correctness hinges on the invariant "
                "holding across every caller."
            ),
            expected_scope_size="bounded",
            file_count_hint="several_files",
            dependency_breadth="medium",
            context_demand="medium",
            verification_difficulty="medium",
            reversibility="moderate",
            risk_indicators=("none",),
            autonomy_experiment_suitable=True,
        ),
        dict(
            class_id="docs_spec_sync",
            description=(
                "Documentation or ADR/spec text brought back into agreement "
                "with already-shipped behavior; no production code path "
                "changes."
            ),
            expected_scope_size="narrow",
            file_count_hint="few_files",
            dependency_breadth="low",
            context_demand="low",
            verification_difficulty="low",
            reversibility="easy",
            risk_indicators=("none",),
            autonomy_experiment_suitable=True,
        ),
        dict(
            class_id="multi_file_feature",
            description=(
                "A feature that necessarily spans several components/files "
                "with real cross-file dependencies and a broader "
                "acceptance surface."
            ),
            expected_scope_size="wide",
            file_count_hint="several_files",
            dependency_breadth="high",
            context_demand="high",
            verification_difficulty="high",
            reversibility="moderate",
            risk_indicators=("none",),
            autonomy_experiment_suitable=False,
        ),
        dict(
            class_id="security_sensitive_change",
            description=(
                "Change touches an authentication, secret-handling, "
                "sandboxing, or trust-boundary code path even if outside "
                "the formal TCB registry."
            ),
            expected_scope_size="bounded",
            file_count_hint="few_files",
            dependency_breadth="medium",
            context_demand="high",
            verification_difficulty="high",
            reversibility="hard",
            risk_indicators=("security_sensitive",),
            autonomy_experiment_suitable=False,
        ),
        dict(
            class_id="tcb_adjacent_change",
            description=(
                "Change targets, or directly borders, a path enumerated by "
                "the canonical TCB registry (verifier, sandbox, approval, "
                "publication, worker authorization, trusted policy)."
            ),
            expected_scope_size="bounded",
            file_count_hint="few_files",
            dependency_breadth="medium",
            context_demand="high",
            verification_difficulty="high",
            reversibility="hard",
            risk_indicators=("tcb_adjacent", "policy_sensitive"),
            autonomy_experiment_suitable=False,
        ),
        dict(
            class_id="migration_schema_change",
            description=(
                "Change to a persisted schema, on-disk format, or "
                "migration path where a wrong step is expensive or "
                "irreversible to unwind."
            ),
            expected_scope_size="bounded",
            file_count_hint="few_files",
            dependency_breadth="medium",
            context_demand="medium",
            verification_difficulty="high",
            reversibility="hard",
            risk_indicators=("schema_migration", "irreversible_change"),
            autonomy_experiment_suitable=False,
        ),
        dict(
            class_id="dependency_api_boundary_change",
            description=(
                "Change to a public function signature, module boundary, "
                "or third-party dependency contract that other components "
                "already call."
            ),
            expected_scope_size="bounded",
            file_count_hint="several_files",
            dependency_breadth="high",
            context_demand="high",
            verification_difficulty="high",
            reversibility="moderate",
            risk_indicators=("dependency_boundary_change",),
            autonomy_experiment_suitable=False,
        ),
        dict(
            class_id="context_heavy_navigation_task",
            description=(
                "Goal is reachable only after locating and correctly "
                "relating several distant parts of the repository; success "
                "depends primarily on context assembly quality rather than "
                "code volume."
            ),
            expected_scope_size="bounded",
            file_count_hint="several_files",
            dependency_breadth="high",
            context_demand="high",
            verification_difficulty="medium",
            reversibility="moderate",
            risk_indicators=("high_context_demand",),
            autonomy_experiment_suitable=True,
        ),
        dict(
            class_id="verifier_policy_sensitive_task",
            description=(
                "Correctness of the change is judged primarily by a "
                "deterministic verifier/policy gate rather than human "
                "review; the case exists to test whether workers can "
                "satisfy a referee they cannot see or influence."
            ),
            expected_scope_size="bounded",
            file_count_hint="few_files",
            dependency_breadth="medium",
            context_demand="medium",
            verification_difficulty="high",
            reversibility="moderate",
            risk_indicators=("policy_sensitive",),
            autonomy_experiment_suitable=False,
        ),
    )


def create_gpa_task_taxonomy_v1():
    """Seal the canonical GP-A task taxonomy (12 classes)."""
    classes = tuple(
        sorted(
            (_seal_class(**spec) for spec in _class_definitions()),
            key=lambda item: item.class_id,
        )
    )
    values = {"version": TAXONOMY_VERSION, "classes": classes}
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(TaskTaxonomy)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TaskTaxonomy(
        **values,
        taxonomy_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_CONTAINER_TOKEN,
    )


def taxonomy_class_by_id(taxonomy, class_id):
    """Look up one class by ID; ``None`` if unknown."""
    if not isinstance(taxonomy, TaskTaxonomy):
        raise TaskTaxonomyError("taxonomy is invalid")
    for item in taxonomy.classes:
        if item.class_id == class_id:
            return item
    return None


def is_known_taxonomy_class_id(taxonomy, class_id):
    return taxonomy_class_by_id(taxonomy, class_id) is not None


def task_taxonomy_is_descriptive_only():
    """TRUST REVIEW helper: True -- the taxonomy grants no capability."""
    return True
