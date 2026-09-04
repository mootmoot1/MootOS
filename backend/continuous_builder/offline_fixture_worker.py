"""Deterministic offline proof worker intended for the pinned CB-022 image."""

import json
import sys
from pathlib import Path


SOURCE_ROOT = Path("/source")
WORKSPACE_ROOT = Path("/workspace")
OUTPUT_NAME = "cb022-fixture-output.json"


def main(argv=None):
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        raise SystemExit("expected attempt_id request_digest workspace_root")
    attempt_id, request_digest, workspace_value = arguments
    if workspace_value != str(WORKSPACE_ROOT):
        raise SystemExit("workspace root is not fixed")
    workspace = WORKSPACE_ROOT
    if not SOURCE_ROOT.is_dir() or not workspace.is_dir():
        raise SystemExit("fixed source and workspace roots are required")
    result = {
        "attempt_id": attempt_id,
        "operation": "offline_fixture_write",
        "request_digest": request_digest,
        "result_verified": False,
    }
    content = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    output = workspace / OUTPUT_NAME
    output.write_bytes(content)
    sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
