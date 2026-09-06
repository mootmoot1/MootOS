"""GP-A1 -- Architecture Baseline Manifest.

A deterministic, sealed description of the exact MootOS architecture that
GP-A evaluation results are measured against. It answers, for any future
benchmark run: "what exact MootOS architecture produced this result?"

The manifest derives every fact from existing trusted, static repository
data -- it does not maintain a competing inventory of its own:

- System Model (CB-028, ``system_model.py``) supplies the repository
  inventory digest, Continuous Builder component inventory, and the TCB
  registry digest it independently binds.
- Trusted Policy (CB-027A, ``trusted_policy.py``) supplies the canonical
  TCB registry digest and protected-path/component counts directly.
- Context Engine (CB-029, ``context_engine.py``) identity is its declared
  ``ENGINE_VERSION`` plus a source-content digest of the module file itself
  (Context Engine has no self-sealed "snapshot" object of its own, so this
  manifest hashes the trusted module source as the best available identity
  evidence -- this is a content digest, not a claim the module vouches for
  its own identity).

Read-only. No network. No model call. No authority: every claim here is
observational evidence, never a capability grant.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .gpa_eval_schema import (
    GPA_SCHEMA_SUITE_VERSION,
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_base_sha,
    require_no_authority,
    require_sha256,
    sha256_hex,
)
from .context_engine import ENGINE_VERSION
from .system_model import (
    MODEL_VERSION,
    build_system_model,
    create_system_model_snapshot,
)
from .trusted_policy import POLICY_VERSION, create_trusted_policy_snapshot

BASELINE_VERSION = "gpa-architecture-baseline-v1"
GENERATOR_VERSION = "gpa-architecture-baseline-generator-v1"
REPOSITORY_IDENTITY = "mootos"
CONTEXT_ENGINE_MODULE_PATH = "backend/continuous_builder/context_engine.py"
MAX_MANIFEST_BYTES = 32 * 1024
MAX_COMPONENT_IDS = 512

_TOKEN = object()


class ArchitectureBaselineError(GPAEvalSchemaError):
    """Raised when an architecture baseline manifest is invalid."""


@dataclass(frozen=True)
class ArchitectureBaselineManifest:
    """Sealed, reproducible description of one evaluated MootOS state.

    Zero authority: every publication/queue/GitHub/merge/main/trust flag is
    structurally false. Binding a benchmark result to a manifest digest
    grants that result no capability whatsoever.
    """

    schema_version: str
    repository_identity: str
    base_sha: str
    system_model_version: str
    system_model_sha256: str
    system_model_root_fingerprint: str
    tcb_policy_version: str
    tcb_registry_sha256: str
    tcb_protected_path_count: int
    tcb_component_count: int
    context_engine_version: str
    context_engine_source_sha256: str
    cb_component_count: int
    cb_file_count: int
    cb_component_ids: tuple
    eval_schema_suite_version: str
    generator_version: str
    reproduction_inputs: tuple
    manifest_sha256: str
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
            raise ArchitectureBaselineError(
                "architecture baseline manifest requires trusted construction"
            )
        if self.schema_version != BASELINE_VERSION:
            raise ArchitectureBaselineError("schema_version is unsupported")
        if self.eval_schema_suite_version != GPA_SCHEMA_SUITE_VERSION:
            raise ArchitectureBaselineError(
                "eval_schema_suite_version is unsupported"
            )
        if self.repository_identity != REPOSITORY_IDENTITY:
            raise ArchitectureBaselineError("repository_identity is unsupported")
        if self.system_model_version != MODEL_VERSION:
            raise ArchitectureBaselineError("system_model_version is unsupported")
        if self.tcb_policy_version != POLICY_VERSION:
            raise ArchitectureBaselineError("tcb_policy_version is unsupported")
        if self.context_engine_version != ENGINE_VERSION:
            raise ArchitectureBaselineError("context_engine_version is unsupported")
        require_base_sha(self.base_sha, "base_sha")
        for value, label in (
            (self.system_model_sha256, "system_model_sha256"),
            (self.system_model_root_fingerprint, "system_model_root_fingerprint"),
            (self.tcb_registry_sha256, "tcb_registry_sha256"),
            (self.context_engine_source_sha256, "context_engine_source_sha256"),
            (self.manifest_sha256, "manifest_sha256"),
        ):
            require_sha256(value, label)
        for name in (
            "tcb_protected_path_count",
            "tcb_component_count",
            "cb_component_count",
            "cb_file_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ArchitectureBaselineError(f"{name} is malformed")
        if type(self.cb_component_ids) is not tuple or (
            len(self.cb_component_ids) > MAX_COMPONENT_IDS
        ):
            raise ArchitectureBaselineError("cb_component_ids is malformed")
        if self.cb_component_ids != tuple(sorted(self.cb_component_ids)):
            raise ArchitectureBaselineError("cb_component_ids is not canonical")
        if len(self.cb_component_ids) != self.cb_component_count:
            raise ArchitectureBaselineError(
                "cb_component_ids does not match cb_component_count"
            )
        if type(self.reproduction_inputs) is not tuple:
            raise ArchitectureBaselineError("reproduction_inputs is malformed")
        keys = tuple(item[0] for item in self.reproduction_inputs)
        if keys != tuple(sorted(keys)):
            raise ArchitectureBaselineError(
                "reproduction_inputs is not canonically ordered"
            )
        require_no_authority(self)
        if self.manifest_sha256 != sha256_hex(canonical_json(self._body())):
            raise ArchitectureBaselineError("manifest_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_MANIFEST_BYTES:
            raise ArchitectureBaselineError("manifest exceeds byte bound")

    def _body(self):
        return {
            "base_sha": self.base_sha,
            "cb_component_count": self.cb_component_count,
            "cb_component_ids": list(self.cb_component_ids),
            "cb_file_count": self.cb_file_count,
            "context_engine_source_sha256": self.context_engine_source_sha256,
            "context_engine_version": self.context_engine_version,
            "eval_schema_suite_version": self.eval_schema_suite_version,
            "generator_version": self.generator_version,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "repository_identity": self.repository_identity,
            "reproduction_inputs": [list(item) for item in self.reproduction_inputs],
            "result_trusted": False,
            "schema_version": self.schema_version,
            "system_model_root_fingerprint": self.system_model_root_fingerprint,
            "system_model_sha256": self.system_model_sha256,
            "system_model_version": self.system_model_version,
            "tcb_component_count": self.tcb_component_count,
            "tcb_policy_version": self.tcb_policy_version,
            "tcb_protected_path_count": self.tcb_protected_path_count,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["manifest_sha256"] = self.manifest_sha256
        return body


def create_architecture_baseline_manifest(repo_root, *, base_sha):
    """Seal an architecture baseline manifest for one trusted repo state.

    ``base_sha`` must be the exact trusted Main commit the caller is
    binding evaluation results against -- it is never inferred from the
    working tree. ``repo_root`` is read-only: this function scans the tree
    to build a System Model and hashes the Context Engine module source; it
    never writes, executes, or reaches the network.
    """
    require_base_sha(base_sha, "base_sha")
    root = Path(repo_root)
    model = build_system_model(root, base_sha=base_sha)
    model_snapshot = create_system_model_snapshot(model)
    tcb_snapshot = create_trusted_policy_snapshot()

    context_engine_path = root / CONTEXT_ENGINE_MODULE_PATH
    try:
        context_engine_source = context_engine_path.read_bytes()
    except OSError as error:
        raise ArchitectureBaselineError(
            "context_engine module source is unreadable"
        ) from error
    context_engine_source_sha256 = sha256_hex(context_engine_source)

    cb_components = tuple(
        sorted(
            (c for c in model.components if c.kind == "continuous_builder_module"),
            key=lambda item: item.component_id,
        )
    )
    cb_component_ids = tuple(item.component_id for item in cb_components)
    cb_file_count = sum(len(item.file_paths) for item in cb_components)

    reproduction_inputs = tuple(
        sorted(
            (
                ("base_sha", base_sha),
                ("context_engine_module_path", CONTEXT_ENGINE_MODULE_PATH),
                ("context_engine_version", ENGINE_VERSION),
                ("generator_version", GENERATOR_VERSION),
                ("system_model_version", MODEL_VERSION),
                ("tcb_policy_version", POLICY_VERSION),
            )
        )
    )

    values = {
        "schema_version": BASELINE_VERSION,
        "repository_identity": REPOSITORY_IDENTITY,
        "base_sha": base_sha,
        "system_model_version": model_snapshot.model_version,
        "system_model_sha256": model_snapshot.model_sha256,
        "system_model_root_fingerprint": model_snapshot.root_fingerprint,
        "tcb_policy_version": tcb_snapshot.policy_version,
        "tcb_registry_sha256": tcb_snapshot.registry_sha256,
        "tcb_protected_path_count": tcb_snapshot.protected_path_count,
        "tcb_component_count": tcb_snapshot.component_count,
        "context_engine_version": ENGINE_VERSION,
        "context_engine_source_sha256": context_engine_source_sha256,
        "cb_component_count": len(cb_components),
        "cb_file_count": cb_file_count,
        "cb_component_ids": cb_component_ids,
        "eval_schema_suite_version": GPA_SCHEMA_SUITE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "reproduction_inputs": reproduction_inputs,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ArchitectureBaselineManifest)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    manifest_sha256 = sha256_hex(canonical_json(provisional._body()))
    return ArchitectureBaselineManifest(
        **values, manifest_sha256=manifest_sha256, _token=_TOKEN,
    )


def architecture_baseline_is_descriptive_only():
    """TRUST REVIEW helper: True -- the manifest has no enforcement authority."""
    return True
