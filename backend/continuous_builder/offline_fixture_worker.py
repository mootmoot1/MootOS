"""Deterministic offline proof worker intended for the pinned CB-022 image."""

import base64
import hashlib
import json
import sys
from pathlib import Path


SOURCE_ROOT = Path("/source")
WORKSPACE_ROOT = Path("/workspace")
OUTPUT_NAME = "cb022-fixture-output.json"
PROTOCOL_VERSION = "mootos-artifact-output-v1"


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

    candidate = b"2\n"
    artifact = {
        "content_base64": base64.b64encode(candidate).decode("ascii"),
        "content_sha256": hashlib.sha256(candidate).hexdigest(),
        "path": "value.txt",
    }
    result = {
        "artifacts": [artifact],
        "attempt_id": attempt_id,
        "protocol": PROTOCOL_VERSION,
        "request_digest": request_digest,
        "result_verified": False,
    }
    content = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"

    # Workspace output remains disposable and is not used as provenance.
    # The trusted supervisor receipt captures this exact stdout transport.
    output = workspace / OUTPUT_NAME
    output.write_bytes(content)
    sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
