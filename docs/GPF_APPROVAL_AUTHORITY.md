# GP-F4 trusted receipt signature verification

This slice authenticates an exact receipt only. It does not satisfy a live gate,
launch a worker, call a provider, or grant any capability. Ordinary receipts and
launch preparation retain their false authority flags. GP-D is execution truth.

## Dependency review and layout

The existing CI installs requirements-dev.txt, which includes requirements.txt;
application installation uses the shared requirements.txt. A dedicated included
manifest would not isolate the interpreter/package set: the parent installation
input could still replace dependencies. Protecting only that included file
would therefore give a misleading boundary. A separate interpreter/build path
would add unnecessary deployment complexity for this slice.

We intentionally protect requirements.txt as a temporary broad boundary:
**changing ANY dependency in that file becomes human-reviewed**, because the
verifier depends on the installed package set. Consider finer dependency
isolation in a later architecture-economy pass. This is a CB TCB classification,
not a modification to the separate ADR-031 path policy. Requirements-dev.txt and
CI do not configure a production authority; test interpreters must never serve
as production approval authorities. Production import paths, installed packages,
and interpreter are human-controlled, outside worker write access.

Concrete reviewed pins (no extras):

- cryptography==46.0.7
- cffi==2.0.0 (direct on CPython >=3.9)
- pycparser==2.23 (cffi transitive dependency)
- typing-extensions==4.15.0 (cryptography direct on Python <3.11; pinned on all
  versions because the application also uses it)

Metadata supports CI Python 3.9 (except 3.9.0/3.9.1), 3.10, and 3.11. The 46.0.7
maintenance release retains universal2 Intel macOS wheels for this host; newer
50.x releases omit Intel macOS wheels. No source build/toolchain is introduced.
The reviewed release includes the buffer handling security fix and wheels with
OpenSSL 3.5.6. This is a targeted API/metadata/changelog review, not an independent
cryptographic audit or a claim that the entire package is vulnerability-free.
Only raw Ed25519 public-key verification is used, never PEM, X.509 or PKCS7.

Sources reviewed:
- https://pypi.org/pypi/cryptography/46.0.7/json
- https://cryptography.io/en/46.0.7/changelog/
- https://pypi.org/project/cffi/2.0.0/
- https://pypi.org/project/pycparser/2.23/

Native trust closure includes cryptography's compiled Rust/Python bindings,
OpenSSL, cffi/_cffi_backend and the platform runtime. Version pins do not attest
installed bytes or prevent import-path substitution. Production must install
reviewed distributions into a worker-inaccessible environment. Source-built or
substituted native backends need separate review; they are not validated here.

## Signed format and API

verify_human_approval accepts only receipt_bytes: bytes, detached_signature:
bytes, signer_key_id: str. Sign exactly:

    b"MootOS/GPF/HumanApprovalReceipt/v1\x00" + receipt_bytes

Receipt bytes are the complete existing HumanApprovalReceipt.to_dict() encoding:
UTF-8 json.dumps with ensure_ascii=False, sort_keys=True, separators=(",", ":"),
allow_nan=False. No trailing newline. Receipt limit: 8192 bytes. Signature:
64 raw Ed25519 bytes. Duplicate, unknown/missing fields, noncanonical encodings,
invalid shapes/digests and any promoted false authority flag fail closed.

The verifier recomputes both subject and receipt SHA-256. It authenticates
subject strings without interpreting them as scope/capability grants. Receipt
semantics, current candidate, expiration at consumption, admission, gate binding,
and every F1-F4 blocker remain obligations of a future trusted consumer.

Authorized public keys live only in the module's immutable production map,
currently empty. IDs are "sha256:" + SHA256(raw 32-byte public key). Enrollment
and rotation require human-only changes; no public-key loader or caller trust
root is accepted. The caller-asserted approver name is not authenticated identity.
Human-held private keys never enter MootOS. Tests generate ephemeral keys in
memory and never serialize their private material.

TrustedHumanApprovalEvidence contains schema_version, receipt_sha256,
approval_id, job_id, attempt_id, request_id, gate, signer_key_id,
signature_algorithm, authenticated and evidence_sha256. No full receipt copy.
Its canonical digest excludes evidence_sha256. No public constructor/reseal path.
Python privacy/frozen records are not a security boundary: consumers must call
validate_trusted_human_approval_evidence with the original receipt/signature.
That helper repeats cryptographic verification against current pins and compares
all fields, including exact types. A stolen/recomputed digest grants nothing.

## TCB delta and next stop

cb_launch_approval_authority / approval_authority / human_only /
cb_launch_receipt_signature_verification protects:
- backend/continuous_builder/gpf_approval_authority.py
- requirements.txt

13 -> 15 paths; 10 -> 11 components. Registry digest:
56e38846274900aaab74c396afd65635187c369d5b1928764adb5aadde857dec

Registry metadata hashes do not cover module/library content. No other runtime
module enters the repository import closure. The ordinary receipt remains outside
TCB. The production allowlist is empty: no real approval authenticates yet.

Next stop: human public-key enrollment and separately reviewed trusted launch
consumption/decision boundary. Preparation is deliberately not wired to this
verifier and cannot set launch_authorized=True. Its existing “authority absent”
helper describes that unwired preparation path. Any new launch-authority TCB
surface requires a separate proposal before editing. Main merge is human-only.

## Slice validation

- Focused signature-authority suite: 68 passed on Python 3.9.6.
- GP-B/C/D/E/F, trusted policy, TCB, system model, Context Engine adversarial,
  CB027 and mechanical-gate unit regressions: 858 passed.
- Context Engine integration: 16 passed (requires its existing generated
  performance-artifact write permission; artifact excluded from this slice).
- New module/tests: full flake8 clean. Repository CI blocking flake8: 0 errors.
- pip check: no broken requirements. Exact closure resolves binary Linux wheels
  for Python 3.10 and 3.11; local Python 3.9.6 uses a universal2 wheel and reports
  OpenSSL 3.5.6. Remote CI is the execution check for 3.10/3.11.
- An unchanged GP-A history assertion expects CB029 among the latest five merge
  commits and fails against this existing full-history checkout. No GP-A behavior
  or history test was changed to hide that failure.
