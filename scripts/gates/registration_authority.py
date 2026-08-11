"""Registration/execution authority gate (V0.3D).

Narrow, evidence-based pattern scan over `backend/*.py` — not a
static-analysis compiler, and not a proof that no bypass exists anywhere.
It checks for the *concrete* bypass shapes ADR-031 names: plugin
auto-discovery, dynamic import scanning, an alternate execution registry,
or a tool's executor being invoked from somewhere other than the one
approved central path. Each pattern below exists because it is a real,
checkable way one of those could be introduced; this is deliberately not
extended to "anything that looks vaguely suspicious".

Two independent checks:

1. **Dangerous-construct scan.** A small, fixed list of dynamic-code/
   plugin-discovery constructs (`importlib.import_module`, `__import__`,
   `pkgutil.iter_modules`, `pkg_resources`, `entry_points(`, bare `eval(`/
   `exec(`) must not appear anywhere in `backend/*.py`. None of MootOS's
   current, explicit registration design needs any of them
   (`docs/TOOL_SYSTEM.md` Sec4: "no plugin discovery, no import-by-name").
   A hit here does not prove malice -- it proves the code no longer matches
   that documented invariant, which is exactly what should stop and get a
   human's attention.

2. **Single-executor-caller check.** `ToolDefinition.executor` is a plain
   callable (`backend/tool_types.py`); the *only* place MootOS is meant to
   invoke it is `backend/tool_executor.py`'s `execute_tool`
   (`docs/TOOL_SYSTEM.md` Sec7: "the single centralized executor... the
   only function allowed to invoke a tool's executor callable"). This
   check greps for the literal text `.executor(` — a call-shaped use of an
   attribute named exactly `executor` — anywhere under `backend/` outside
   `tool_executor.py` and `tool_types.py` itself (which defines the field
   but never calls it) or a re-raise of the same violation from a test
   double. A real hit means some other code is calling a tool's executor
   directly, bypassing risk/approval enforcement entirely.

Limitations, stated plainly: this is a textual/regex scan, not semantic
analysis. It cannot detect an indirect bypass built from generic
primitives it does not know to look for (e.g. `getattr(obj, "exec" +
"utor")(...)`), and the executor-caller check can false-positive on an
unrelated attribute that happens to be named `executor`. Both are accepted
trade-offs for a check that must stay simple and reliable rather than
complete -- see ADR-031's Tradeoffs and `docs/GATES_AND_RELEASE_SAFETY.md`.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


BACKEND_GLOB = "backend/**/*.py"

# (pattern, human-readable reason). Matched as a plain substring/regex
# against file text, one line at a time, so violations can report a line
# number.
DANGEROUS_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bimportlib\.import_module\b"), "dynamic import (importlib.import_module)"),
    (re.compile(r"(?<!_)\b__import__\s*\("), "dynamic import (__import__)"),
    (re.compile(r"\bpkgutil\.iter_modules\b"), "plugin auto-discovery (pkgutil.iter_modules)"),
    (re.compile(r"\bpkg_resources\b"), "plugin auto-discovery (pkg_resources)"),
    (re.compile(r"\bentry_points\s*\("), "plugin auto-discovery (entry_points)"),
    (re.compile(r"(?<!\.)\beval\s*\("), "dynamic code execution (eval)"),
    (re.compile(r"(?<!\.)\bexec\s*\("), "dynamic code execution (exec)"),
)

# Files allowed to reference `.executor(` because they either define the
# field (never call it) or are the one approved caller.
EXECUTOR_CALL_ALLOWED_FILES = frozenset({"backend/tool_executor.py", "backend/tool_types.py"})
EXECUTOR_CALL_PATTERN = re.compile(r"\.executor\s*\(")


@dataclass(frozen=True)
class RegistrationAuthorityResult:
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        if self.passed:
            return "registration-authority gate: PASS"
        lines = [f"registration-authority gate: FAIL ({len(self.violations)} violation(s))"]
        for violation in self.violations:
            lines.append(f"  VIOLATION: {violation}")
        return "\n".join(lines)


def scan_dangerous_constructs(files: Sequence[tuple[str, str]]) -> list[str]:
    """``files`` is a sequence of (relative_path, source_text) pairs."""
    violations = []
    for relative_path, source in files:
        for line_number, line in enumerate(source.splitlines(), start=1):
            for pattern, reason in DANGEROUS_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{relative_path}:{line_number}: {reason}: {line.strip()}")
    return violations


def scan_executor_call_sites(files: Sequence[tuple[str, str]]) -> list[str]:
    violations = []
    for relative_path, source in files:
        if relative_path in EXECUTOR_CALL_ALLOWED_FILES:
            continue
        for line_number, line in enumerate(source.splitlines(), start=1):
            if EXECUTOR_CALL_PATTERN.search(line):
                violations.append(
                    f"{relative_path}:{line_number}: calls '.executor(' outside the central "
                    f"executor ({sorted(EXECUTOR_CALL_ALLOWED_FILES)}): {line.strip()}"
                )
    return violations


def evaluate_files(files: Sequence[tuple[str, str]]) -> RegistrationAuthorityResult:
    """Pure evaluation over (relative_path, source_text) pairs. Unit-testable
    without a real filesystem."""
    violations = scan_dangerous_constructs(files) + scan_executor_call_sites(files)
    return RegistrationAuthorityResult(violations=tuple(violations))


def _read_backend_files(repository_root: Path) -> list[tuple[str, str]]:
    files = []
    for path in sorted((repository_root / "backend").glob("**/*.py")):
        relative = path.relative_to(repository_root).as_posix()
        files.append((relative, path.read_text(encoding="utf-8")))
    return files


def evaluate(repository_root: Optional[Path] = None) -> RegistrationAuthorityResult:
    # See risk_metadata.evaluate()'s comment: defaults to the current
    # working directory, not `__file__`, so this remains correct when run
    # from a trusted extraction that contains only scripts/gates/.
    root = repository_root or Path.cwd()
    return evaluate_files(_read_backend_files(root))


def main(argv: list[str]) -> int:
    result = evaluate()
    print(result.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
