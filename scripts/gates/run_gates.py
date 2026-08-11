"""Run all V0.3D mechanical release gates and report a combined result.

This is the single entry point CI invokes (see
`.github/workflows/python-package.yml`). It intentionally does NOT re-run
tests or lint -- those remain their own existing, separate CI steps
(AGENTS.md, ADR-031's "preserve the existing test/lint workflow"). This
script covers only the *new* V0.3D checks: protected-path, migration
safety, risk metadata, registration authority, and secret scan.

Every gate below is mechanical and deterministic (ADR-031/ADR-032): none
of them asks a model anything, and none of them is a source of merge
authority by itself -- a human still decides whether to merge, always. A
failing gate here means "do not auto-merge", not "this can never be
merged"; see `docs/GATES_AND_RELEASE_SAFETY.md` for how a legitimate,
human-reviewed protected-path or migration change is expected to proceed.
"""

import sys
from pathlib import Path

from scripts.gates import migration_safety, protected_paths, registration_authority, risk_metadata, secret_scan


def run(base: str, head: str = "HEAD") -> bool:
    """Run every gate, print each result, and return overall pass/fail.

    ``repository_root`` is the current working directory, not a path
    derived from ``__file__`` -- see risk_metadata.evaluate()'s comment.
    CI always invokes this from the real repository checkout even when the
    gate *code* itself was loaded from a trusted extraction elsewhere.
    """
    repository_root = Path.cwd()
    changed_paths = protected_paths.git_changed_paths(base, head)

    results = [
        protected_paths.evaluate_changed_paths(changed_paths),
        migration_safety.evaluate(base, head),
        risk_metadata.evaluate(repository_root),
        registration_authority.evaluate(repository_root),
        secret_scan.evaluate_paths(changed_paths, repository_root),
    ]

    print(f"V0.3D mechanical release gates -- base={base} head={head}")
    print(f"({len(changed_paths)} path(s) changed)")
    print("-" * 72)
    overall_passed = True
    for result in results:
        print(result.summary())
        print()
        overall_passed = overall_passed and result.passed

    print("-" * 72)
    if overall_passed:
        print("ALL GATES PASSED")
    else:
        print(
            "ONE OR MORE GATES FAILED. This is a mechanical block, not a final "
            "verdict -- see docs/GATES_AND_RELEASE_SAFETY.md for how a "
            "legitimate protected-path or migration change proceeds. AI review "
            "remains advisory only; only a human controls merge (ADR-032)."
        )
    return overall_passed


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base ref/commit to diff against")
    parser.add_argument("--head", default="HEAD", help="Head ref/commit (default: HEAD)")
    args = parser.parse_args(argv)

    return 0 if run(args.base, args.head) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
