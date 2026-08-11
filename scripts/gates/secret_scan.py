"""Secret/credential/database-artifact scan (V0.3D).

A practical, repo-local, dependency-free gate over the set of paths a diff
adds or modifies. It catches obvious cases by filename and by a small set
of well-known secret-token shapes. It cannot, and does not claim to, prove
the absence of a secret -- see "Limitations" below and in
`docs/GATES_AND_RELEASE_SAFETY.md`.

Two independent checks:

1. **Filename check.** A denylist of filename patterns that should never
   be a tracked file at all: ``.env`` (exact name only -- ``.env.example``
   and ``.env.sample`` are explicitly template files and must stay
   trackable), private-key extensions/names, and database files. This
   mirrors and mechanically re-enforces `.gitignore`'s existing intent --
   `.gitignore` only stops *new* commits by a well-behaved local git
   client; this catches a force-add (`git add -f`) or a client that
   ignores it.
2. **Content pattern check.** A short list of recognizable secret-token
   *shapes* (AWS-style access keys, an OpenAI-style ``sk-...`` key, a PEM
   private-key header, a long high-entropy value assigned to an
   obviously-named variable like ``API_KEY =``). Applied only to text
   files under a size cap, to keep the scan fast and avoid binary noise.

## Limitations (read before trusting this gate)

- **This is pattern matching, not secret detection.** A real secret that
  doesn't match one of the listed shapes (a bespoke internal token, a
  password with no recognizable prefix, a secret embedded in an unusual
  format) will not be caught. This gate raises the floor; it does not
  prove a ceiling.
- **It only sees the paths it's given** (normally: a diff's changed
  files). A secret already committed in history before this gate existed
  is not retroactively found.
- **False positives are expected and acceptable.** A test fixture
  containing a string that happens to look like a key, or documentation
  demonstrating a redacted example, can trip this. When that happens, the
  fix is to make the example clearly non-matching (e.g.
  ``sk-EXAMPLE-NOT-REAL``), not to weaken the pattern.
- **No paid or third-party scanning service is used**, per V0.3D's
  constraints. A dedicated secret-scanning product (e.g. GitHub's own
  Advanced Security secret scanning, if enabled on the repository) is a
  stronger complement to this, not a replacement for it.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


MAX_SCANNED_FILE_BYTES = 200_000

# Filenames that must never be a tracked file, matched against the final
# path segment (or, for extensions, the suffix). Order-independent.
DENIED_FILENAMES = frozenset({".env"})
DENIED_FILENAME_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3")
DENIED_FILENAME_PREFIXES = ("id_rsa", "id_ecdsa", "id_ed25519")

# Explicitly allowed even though they might otherwise look denylist-ish.
ALLOWED_FILENAMES = frozenset({".env.example", ".env.sample", ".env.template"})

CONTENT_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS-style access key ID"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "OpenAI-style secret key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "PEM private key header"),
    (
        re.compile(
            r"\b(?:API_KEY|SECRET_KEY|ACCESS_TOKEN|PASSWORD|SESSION_SECRET)\s*[:=]\s*"
            r"['\"][A-Za-z0-9_\-/+]{16,}['\"]",
            re.IGNORECASE,
        ),
        "obviously-named secret variable assigned a long literal value",
    ),
)


@dataclass(frozen=True)
class SecretScanResult:
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        if self.passed:
            return "secret-scan gate: PASS (heuristic only -- see docs/GATES_AND_RELEASE_SAFETY.md)"
        lines = [f"secret-scan gate: FAIL ({len(self.violations)} finding(s))"]
        for violation in self.violations:
            lines.append(f"  FINDING: {violation}")
        return "\n".join(lines)


def _filename_violation(path: str) -> Optional[str]:
    name = path.rsplit("/", 1)[-1]
    if name in ALLOWED_FILENAMES:
        return None
    if name in DENIED_FILENAMES:
        return f"{path}: filename '{name}' must never be a tracked file"
    for suffix in DENIED_FILENAME_SUFFIXES:
        if name.endswith(suffix):
            return f"{path}: filename matches a denied suffix ({suffix})"
    for prefix in DENIED_FILENAME_PREFIXES:
        if name.startswith(prefix):
            return f"{path}: filename matches a denied private-key prefix ({prefix})"
    return None


def _content_violations(path: str, content: bytes) -> list[str]:
    if len(content) > MAX_SCANNED_FILE_BYTES:
        return []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return []  # binary file: filename check already covers the risky extensions
    violations = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern, reason in CONTENT_PATTERNS:
            if pattern.search(line):
                violations.append(f"{path}:{line_number}: possible {reason}")
    return violations


def evaluate_files(files: Sequence[tuple[str, bytes]]) -> SecretScanResult:
    """``files`` is a sequence of (relative_path, content_bytes) pairs.
    Pure evaluation, unit-testable without touching a real filesystem."""
    violations: list[str] = []
    for path, content in files:
        filename_violation = _filename_violation(path)
        if filename_violation:
            violations.append(filename_violation)
            continue  # a denied filename is already fatal; skip content scan
        violations.extend(_content_violations(path, content))
    return SecretScanResult(violations=tuple(violations))


def evaluate_paths(paths: Sequence[str], repository_root: Path) -> SecretScanResult:
    """Read each of ``paths`` (relative to ``repository_root``) from the
    working tree, skipping any that no longer exist (a deleted file has
    nothing to scan)."""
    files = []
    for relative_path in paths:
        full_path = repository_root / relative_path
        if full_path.is_file():
            files.append((relative_path, full_path.read_bytes()))
    return evaluate_files(files)


def main(argv: list[str]) -> int:
    import argparse

    from scripts.gates.protected_paths import git_changed_paths

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    repository_root = Path.cwd()  # see risk_metadata.evaluate()'s comment
    changed = git_changed_paths(args.base, args.head)
    result = evaluate_paths(changed, repository_root)
    print(result.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
