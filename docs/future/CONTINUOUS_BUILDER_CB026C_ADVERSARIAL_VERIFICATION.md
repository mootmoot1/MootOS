# CB-026C — adversarial held-out verification

Trusted base: `ae46b4a227f57ebe7f7107d3985917c469b9b0d7`.

## Scope and architecture

`adversarial_verifier.py` composes unchanged CB-026A structural admission and
CB-026B contained pytest execution. Its initial immutable registry contains one
scenario, `exact-value-repeat-v1`, for the existing increment-value fixture.
The only admitted replacement is `value.txt`. General executable candidates
are unsupported. Candidate bytes are read as data, never imported or evaluated.
This restriction prevents candidate code from manipulating pytest's interpreter
or terminating it with a forged successful exit.

Trusted system code creates the public contract and public plan. The fixed public
test accepts numeric data; the held-out check demands the exact correct bytes.
Neither factory accepts worker-selected tests, argv, configuration, environment,
scenario IDs, acceptance predicates, or repeat counts. The initial weak public
check is intentional: it makes public-pass/private-fail an observable control.

After a structural receipt and public execution receipt exist, registry selection
binds those exact identities, base, request, candidate, scenario content digest,
check-definition digest and policy. Every scenario requires two fresh executions.
This is repeat verification, not a repair/retry mechanism. A failed repeat cannot
be replaced with a later success. Uncertainty stops further execution.

## Two explicit tree identities

Held-out tests are absent from the original public candidate contract. Trusted
supervisor code adds the immutable registry test to a derived base snapshot and
re-runs CB-026A against the same execution receipt and admitted artifact payloads.
CB-026B then reconstructs the derived candidate independently for every run.

The adversarial receipt records both the original candidate/structural identity
and the augmented candidate/structural identity. These digests differ by design.
It also binds the original public receipt, held-out plan, ordered run receipts,
outcomes, cleanup and zero-authority flags. Receipt validation checks that the
augmentation is exactly the registry file, uses the same admission and toolchain,
and preserves the restricted paths. Reusing a run's workspace identity is rejected.

## Separation boundary

The public contract contains the visible test and value data. The worker request
and worker materialization must be assembled by trusted dispatch code without
the supervisor registry. The real-proof harness checks that the complete held-out
content is absent from the frozen request and captured worker stdout; the worker
receives only the value fixture snapshot. Registry selection occurs after admission.

This API does not redact arbitrary prompts or attest all historical worker context.
The registry resides in supervisor code and is readable by a developer with repo
access. It is information separation, not cryptographic secrecy. The task itself
states the desired value; hiding the concrete test does not hide that requirement.
Held-out tests are readable inside the verifier container, but no candidate Python
executes there in this profile. Admitted value bytes cannot modify tests or code.

## Containment and result authority

CB-026B's existing fixed pytest argv executes with `shell=False`, isolated Python,
disabled plugin autoload/conftest/config discovery, explicit environment and no
network. Each check has a ten-second deadline and 16 KiB bounds on each stream.
One public check plus two sequential held-out checks has at most thirty seconds
of check budgets, plus existing bounded Docker control/termination/cleanup grace.
Each container retains the existing read-only candidate mount/root filesystem,
nonroot identity, dropped capabilities, no-new-privileges, CPU/memory/PID/tmpfs
bounds and no host credentials, home, socket, package installation or network.

Only trusted observed exit/timeout/cleanup facts decide outcomes. Output text is
never consulted. Exact output hashes remain in CB-026B receipts; normalized
outcome digests identify materially different exit/failure outcomes across runs.
Output-only variation is not classified as behavioral nondeterminism.

Classifications are `adversarial_verification_passed`,
`adversarial_verification_failed`, and `adversarial_verification_uncertain`.
Codes include `held_out_check_failed`, `public_check_failed`,
`public_private_outcome_diverged`, `nondeterministic_outcome`,
`repeat_verification_failed`, `held_out_binding_mismatch`,
`adversarial_evidence_uncertain`, and `unauthorized_change_detected`.
Structural failures retain CB-026A's original canonical failure codes.

All eight flags remain false: `result_trusted`, `worker_output_trusted`,
`externally_verified`, `publication_authorized`, `queue_transition_authorized`,
`github_authorized`, `merge_authorized`, `main_advancement_authorized`.
`human_review_required` remains true. There is no queue, publication or GitHub
integration. Python construction tokens/content digests are in-process integrity
controls, not signatures against compromised trusted host code.

## Security review and adversarial matrix

- Public test edit, weakening or empty replacement: protected-path rejection.
- Test omitted from replacement artifacts: base test retained; no deletion opcode.
- Extra file, pytest.ini, pyproject.toml, setup.cfg, conftest.py, package initializer,
  pytest shadow module, sitecustomize or environment injection: path rejection.
- Verifier core, check runner/runtime, adversarial registry or held-out test edits:
  protected-path rejection before a check plan can execute.
- Worker success claims or Python text in value.txt: inert data, no status authority.
- Public pass/private fail: failed; public pass cannot override held-out evidence.
- Pass then fail (or fail then pass): failed, with inconsistent outcome recorded.
- Timeout, incomplete evidence, termination or cleanup uncertainty: cannot pass.
- Forged scenario/receipt, cross-candidate binding or promoted authority: rejected.

## Remaining Trusted Policy / TCB work

General code requires an independent oracle process boundary, carefully scoped
I/O, and protection against candidate code inspecting/patching its test process.
This slice intentionally does not claim that arbitrary Python imports are safe.
Future work also includes reviewed task-to-scenario policy expansion, production
context exclusion, durable authenticated evidence storage, toolchain supply-chain
policy and stronger determinism specifications. No automated registration,
scheduling, retries, worker PR authority or Main advancement is added here.

## Validation status

**HOLD: mandatory real contained adversarial proofs remain incomplete.**

- Initial focused verifier/check-runner/artifact/trust-chain/supervisor run:
  205 passed, 6 opt-in Docker cases skipped.
- Final CB-026C tests after security review: 47 passed, 3 real cases skipped.
- Broader Continuous Builder run interrupted after 464.86 seconds:
  554 passed, 2 failed, 6 skipped; not a completed/passing broader run.
  The two existing overflow tests observed `check_timeout` rather than overflow
  during host delays. Their unchanged isolated rerun passed both in 0.96 seconds.
- Full flake8 passed for both new Python files.

Real proof used the existing local CB-026B image manifest
`a6f5e9858a815c7db9cefb9d647f919faafe63639321e658d680b48fb3d0d775`,
config `4adf2d1d6e5959603d214b4c841382668ceebbbc47438b3a2d03b32c54957b72`.
No images were built/pulled or packages installed. Docker Desktop reported
4.47.0 (206054), Engine 28.4.0, API 1.51, amd64. Image inspection intermittently
returned HTTP 500; bounded daemon diagnostics also timed out.

One actual offline worker completed and its output was admitted:
execution `cb026c-worker-positive`, receipt
`af6cf94b2ef69c53bcc634fa0c2d34c86117fa0e175a134df6bf6a9feba35014`.
Worker cleanup and stdout provenance were confirmed. The following public check
failed closed during Docker control with `checks_uncertain` / `execution_uncertain`:
receipt `b427466f20494c375698ef9e0957ac2c5acd94dadb3de16aacf79af722fdab47`.
No verifier execution was confirmed in that receipt. Workspace cleanup was true;
the check, worker and artifact staging roots were subsequently observed empty.

Positive public/private success, the gamed-public real rejection, and the real
repeat control have **not** been established. The local proof harness is ready
to run them once Docker responds within existing bounds. Its repeat negative
tightens only the second collection deadline to inject a real timeout; it does
not fabricate a receipt or change the candidate/check plan. That control would
prove inconsistent execution evidence fails closed, not that a deterministic
data-only candidate became intrinsically nondeterministic. Unit tests separately
cover pass/fail and fail/pass observed repeat outcomes.

Do not merge until the mandatory real cases and normal CI are complete.

The three opt-in cases are reproducible with the existing reviewed image:

```bash
CB026B_TEST_IMAGE_DIGEST=a6f5e9858a815c7db9cefb9d647f919faafe63639321e658d680b48fb3d0d775 \
CB026B_TEST_CONFIG_DIGEST=4adf2d1d6e5959603d214b4c841382668ceebbbc47438b3a2d03b32c54957b72 \
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_continuous_builder_adversarial_verifier.py -k real_adversarial
```

These tests simulate upstream worker admission and use the actual production
Docker check transport. They must not be described as a real worker launch.
The separate host proof harness uses the actual worker runtime as described above.
