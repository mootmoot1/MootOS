"""Protected-path diff gate (V0.3D, ADR-031).

Deterministic: given a set of changed paths, decides pass/fail purely by
membership against `policy.DENIED_PATHS`/`policy.ALLOWED_EXCEPTIONS`. No
model judgment is involved anywhere in this file.
"""

import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence

from scripts.gates import policy


@dataclass(frozen=True)
class ProtectedPathResult:
    """The outcome of evaluating one set of changed paths against policy."""

    changed_paths: tuple[str, ...]
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        if self.passed:
            return f"protected-path gate: PASS ({len(self.changed_paths)} changed path(s), none protected)"
        lines = [f"protected-path gate: FAIL ({len(self.violations)} protected path(s) touched)"]
        for path in self.violations:
            lines.append(f"  - {path}")
        lines.append(
            "This diff touches a protected-core path (ADR-031). Automated merge is "
            "blocked; this requires explicit human review and an intentional "
            "override, not a policy-file change in the same diff (see "
            "docs/GATES_AND_RELEASE_SAFETY.md)."
        )
        return "\n".join(lines)


def is_denied(path: str) -> bool:
    """Whether one repository-relative path is a protected path.

    A path matches a `DENIED_PATHS` entry either exactly, or -- for an
    entry ending in ``/`` -- by living under that directory. An entry in
    `ALLOWED_EXCEPTIONS` always overrides a match, even under a denied
    directory.
    """
    if path in policy.ALLOWED_EXCEPTIONS:
        return False
    for denied in policy.DENIED_PATHS:
        if denied.endswith("/"):
            if path == denied.rstrip("/") or path.startswith(denied):
                return True
        elif path == denied:
            return True
    return False


def evaluate_changed_paths(paths: Sequence[str]) -> ProtectedPathResult:
    """Pure evaluation over an already-computed list of changed paths.

    Kept separate from git invocation so this is trivially unit-testable
    without a real repository/diff.
    """
    normalized = tuple(path.strip() for path in paths if path.strip())
    violations = tuple(path for path in normalized if is_denied(path))
    return ProtectedPathResult(changed_paths=normalized, violations=violations)


def git_changed_paths(base: str, head: str = "HEAD") -> list[str]:
    """The paths changed between ``base`` and ``head``, using the same
    three-dot (merge-base) semantics GitHub uses for a PR's "Files
    changed" tab -- i.e. only what this branch actually introduces, not
    unrelated commits that landed on ``base`` after the branch point.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def evaluate(base: str, head: str = "HEAD") -> ProtectedPathResult:
    """Compute the real diff between ``base`` and ``head`` and evaluate it."""
    return evaluate_changed_paths(git_changed_paths(base, head))


def main(argv: Sequence[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base ref/commit to diff against")
    parser.add_argument("--head", default="HEAD", help="Head ref/commit (default: HEAD)")
    args = parser.parse_args(argv)

    result = evaluate(args.base, args.head)
    print(result.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
