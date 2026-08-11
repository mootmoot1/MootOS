"""Risk-metadata gate (V0.3D).

V0.3A already makes it a documentation expectation that production
`ToolDefinition`s declare risk explicitly (`docs/TOOL_SYSTEM.md` Sec3).
This gate makes the safety-critical portion of that expectation
mechanical: risk classification must be a required field with no default,
and every currently registered tool must declare one of the three defined
risk levels. It does not enforce the rest of V0.3A's descriptive metadata
(side_effects, limitations, ...) -- those affect description, never
authorization (`backend/tool_types.py`'s own docstring), so weakening them
is not a safety-authorization concern this gate needs to block.

Two independent checks, because either one changing is a way risk could
silently weaken:

1. **Static**: `ToolDefinition.risk` (`backend/tool_types.py`) has no
   default value in its dataclass field. If a future change added
   ``risk: str = RISK_READ_ONLY``, every tool that forgot to pass ``risk``
   explicitly would silently become the most permissive classification
   instead of failing to construct. This is checked via `ast`, against the
   *current* (head) source -- not a diff -- because the property that
   matters is "is this true right now", not "did it change".
2. **Live**: every tool in the actual default registry
   (`backend.tool_registry.build_default_registry`) declares a `risk` in
   `backend.tool_types.VALID_RISK_LEVELS`. This is already guaranteed by
   `ToolDefinition.__post_init__`, which raises on construction otherwise
   -- so this check can never observe a violation today. It exists as a
   regression proof: if `__post_init__`'s validation were ever removed or
   weakened, this is the check that would catch a tool silently
   registering with an invalid or missing risk value.

Deliberately does not alter authorization: nothing here changes what a
tool is allowed to do. It only verifies the *metadata that enforcement
elsewhere reads* is present and cannot silently default weaker.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


TOOL_TYPES_PATH = "backend/tool_types.py"
TOOL_DEFINITION_CLASS = "ToolDefinition"
RISK_FIELD = "risk"


@dataclass(frozen=True)
class RiskMetadataResult:
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        if self.passed:
            return "risk-metadata gate: PASS"
        lines = [f"risk-metadata gate: FAIL ({len(self.violations)} violation(s))"]
        for violation in self.violations:
            lines.append(f"  VIOLATION: {violation}")
        return "\n".join(lines)


def check_risk_field_has_no_default(source: str) -> Optional[str]:
    """Return a violation message if `ToolDefinition.risk` has a default
    value, or if the field/class cannot be found at all (fails closed --
    an unrecognizable shape is treated as unverifiable, not safe). Returns
    ``None`` when the field is present and correctly has no default.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return f"{TOOL_TYPES_PATH} could not be parsed: {error}"

    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == TOOL_DEFINITION_CLASS):
            continue
        # Dataclass fields are AnnAssign nodes in the class body:
        # `risk: str` (no default) vs `risk: str = SOMETHING` (default).
        for statement in node.body:
            if not (isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)):
                continue
            if statement.target.id != RISK_FIELD:
                continue
            if statement.value is not None:
                return (
                    f"{TOOL_DEFINITION_CLASS}.{RISK_FIELD} has a default value -- risk "
                    "classification must remain a required field with no default, or a "
                    "tool could silently register with the most permissive risk level"
                )
            return None
        return f"{TOOL_DEFINITION_CLASS} has no '{RISK_FIELD}' field -- cannot verify risk is required"
    return f"could not find class '{TOOL_DEFINITION_CLASS}' in {TOOL_TYPES_PATH}"


def check_live_registry_risk_values() -> list[str]:
    """Every tool in the real default registry declares a valid risk.

    Imported lazily inside the function (not at module load) so this
    module stays importable, and testable in isolation, even in a context
    where the backend package is not on the path.
    """
    from backend.tool_registry import build_default_registry
    from backend.tool_types import VALID_RISK_LEVELS

    violations = []
    for definition in build_default_registry().list_definitions():
        if definition.risk not in VALID_RISK_LEVELS:
            violations.append(
                f"registered tool '{definition.name}' declares risk={definition.risk!r}, "
                f"which is not one of {sorted(VALID_RISK_LEVELS)}"
            )
    return violations


def evaluate(repository_root: Optional[Path] = None) -> RiskMetadataResult:
    # Deliberately defaults to the current working directory, not a path
    # derived from `__file__`. When CI runs this gate's logic from a
    # trusted extraction of the base ref (see .github/workflows/
    # python-package.yml "Self-protection"), `__file__` points into that
    # extraction, which contains only scripts/gates/ -- not backend/. The
    # working directory is always the real repository checkout.
    root = repository_root or Path.cwd()
    source = (root / TOOL_TYPES_PATH).read_text(encoding="utf-8")

    violations: list[str] = []
    static_violation = check_risk_field_has_no_default(source)
    if static_violation:
        violations.append(static_violation)
    violations.extend(check_live_registry_risk_values())

    return RiskMetadataResult(violations=tuple(violations))


def main(argv: list[str]) -> int:
    result = evaluate()
    print(result.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
