"""Migration safety gate (V0.3D, ADR-031).

Implements ADR-031's nuance for `backend/migrations.py`: migration
*machinery* and *historical* migrations are always protected; a brand-new,
*additive* migration is allowed through, but flagged for the higher
review ADR-031 calls for -- never silently treated the same as an ordinary
change.

This is a function-level diff over one file's Python source, using the
standard library `ast` module -- not a general static-analysis engine.
`backend/migrations.py` is small and has one clear convention (each
migration is one `_migration_<version>_<name>` function, wired into the
`MIGRATIONS` tuple), which is exactly the "smallest reliable
implementation" ADR-031/V0.3D calls for. It does not generalize to
arbitrary Python files.

Deliberately does NOT execute the migration or inspect the database --
this is a source-diff safety check, not a schema-correctness check (that
remains the job of the existing migration tests, e.g.
`tests/test_tool_system_migration.py`).
"""

import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


MIGRATION_FUNCTION_PATTERN = re.compile(r"^_migration_(\d+)_")
MIGRATIONS_TUPLE_NAME = "MIGRATIONS"


@dataclass(frozen=True)
class MigrationSafetyResult:
    """The outcome of diffing one version of migrations.py against another."""

    violations: tuple[str, ...]
    additive_notices: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        lines = [
            "migration-safety gate: "
            + ("PASS" if self.passed else f"FAIL ({len(self.violations)} violation(s))")
        ]
        for violation in self.violations:
            lines.append(f"  VIOLATION: {violation}")
        for notice in self.additive_notices:
            lines.append(f"  NOTICE (requires human migration review, ADR-031): {notice}")
        return "\n".join(lines)


def _function_sources(source: str) -> dict[str, str]:
    """Map top-level function name -> its exact source text."""
    tree = ast.parse(source)
    functions: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                functions[node.name] = segment
    return functions


def _migrations_tuple_entries(source: str) -> Optional[list[tuple[int, str, str]]]:
    """Extract ``(version, name, function_name)`` for every entry in the
    module-level ``MIGRATIONS = (...)`` tuple. Returns ``None`` if the
    tuple cannot be found or does not match the expected
    ``Migration(<int>, <str>, <function name>)`` call shape -- callers
    must treat that as "cannot verify" rather than "safe"."""
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == MIGRATIONS_TUPLE_NAME for target in node.targets):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            return None
        entries: list[tuple[int, str, str]] = []
        for element in node.value.elts:
            if not isinstance(element, ast.Call) or len(element.args) < 3:
                return None
            version_node, name_node, function_node = element.args[0], element.args[1], element.args[2]
            if not (
                isinstance(version_node, ast.Constant)
                and isinstance(version_node.value, int)
                and isinstance(name_node, ast.Constant)
                and isinstance(name_node.value, str)
                and isinstance(function_node, ast.Name)
            ):
                return None
            entries.append((version_node.value, name_node.value, function_node.id))
        return entries
    return None


def evaluate_migration_diff(base_source: str, head_source: str) -> MigrationSafetyResult:
    """Pure evaluation over two full-file source strings. Unit-testable
    without a real repository/diff."""
    violations: list[str] = []
    additive: list[str] = []

    try:
        base_functions = _function_sources(base_source)
    except SyntaxError:
        violations.append("base version of migrations.py could not be parsed")
        base_functions = {}
    try:
        head_functions = _function_sources(head_source)
    except SyntaxError:
        violations.append("proposed version of migrations.py could not be parsed -- fails closed")
        return MigrationSafetyResult(violations=tuple(violations), additive_notices=())

    base_versions = [
        int(match.group(1))
        for name in base_functions
        if (match := MIGRATION_FUNCTION_PATTERN.match(name))
    ]
    base_max_version = max(base_versions, default=0)

    for name, head_src in head_functions.items():
        base_src = base_functions.get(name)
        match = MIGRATION_FUNCTION_PATTERN.match(name)
        version = int(match.group(1)) if match else None

        if base_src is None:
            # A brand-new function.
            if version is not None:
                if version <= base_max_version:
                    violations.append(
                        f"new function '{name}' reuses historical migration version "
                        f"{version} (highest existing version is {base_max_version})"
                    )
                else:
                    additive.append(f"new migration function '{name}' (version {version})")
            continue

        if head_src != base_src:
            if version is not None:
                violations.append(
                    f"historical migration function '{name}' (version {version}) was "
                    "modified -- migration history must not be rewritten"
                )
            else:
                violations.append(f"migration machinery function '{name}' was modified")

    for name in base_functions:
        if name not in head_functions:
            match = MIGRATION_FUNCTION_PATTERN.match(name)
            if match:
                violations.append(f"historical migration function '{name}' was removed")
            else:
                violations.append(f"migration machinery function '{name}' was removed")

    base_entries = _migrations_tuple_entries(base_source)
    head_entries = _migrations_tuple_entries(head_source)
    if base_entries is None:
        violations.append(
            f"could not verify the base '{MIGRATIONS_TUPLE_NAME}' tuple shape -- fails closed"
        )
    elif head_entries is None:
        violations.append(
            f"the proposed '{MIGRATIONS_TUPLE_NAME}' tuple no longer matches the expected "
            "Migration(version, name, function) shape -- fails closed"
        )
    else:
        head_by_version = {entry[0]: entry for entry in head_entries}
        for entry in base_entries:
            version = entry[0]
            if version > base_max_version:
                continue  # defensive; should not happen given base_max_version's derivation
            if head_by_version.get(version) != entry:
                violations.append(
                    f"'{MIGRATIONS_TUPLE_NAME}' entry for historical version {version} was "
                    "changed or removed"
                )

    return MigrationSafetyResult(violations=tuple(violations), additive_notices=tuple(additive))


def evaluate(base: str, head: str = "HEAD", path: str = "backend/migrations.py") -> MigrationSafetyResult:
    """Read ``path`` at ``base`` and ``head`` via ``git show`` and evaluate.

    If the file is unchanged between the two revisions this still runs
    (cheaply) and always passes -- there is nothing to distinguish.
    """
    base_source = _git_show(base, path)
    head_source = _git_show(head, path)
    if base_source is None or head_source is None:
        # The file not existing at one revision is not this gate's concern
        # (e.g. it is new in this repository) -- nothing to protect yet.
        return MigrationSafetyResult(violations=(), additive_notices=())
    return evaluate_migration_diff(base_source, head_source)


def _git_show(ref: str, path: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    result = evaluate(args.base, args.head)
    print(result.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
