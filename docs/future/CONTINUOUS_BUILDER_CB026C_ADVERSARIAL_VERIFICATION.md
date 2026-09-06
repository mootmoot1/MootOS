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

**READY FOR REVIEW** (do not merge automatically). Authority flags remain false;
`human_review_required` remains true. Passing proofs are evidence, not authority.

### Delayed-create cleanup fix (CB-026B `check_runtime`)

Confirmed: when `docker create` timed out without a verified container id,
`_cleanup_container` could treat a single empty name listing as
`cleanup_confirmed=True` while the daemon later finished create (observed
orphan `a9e82eef…`). Fix: `_cleanup_container(..., create_verified=…)`; without
a verified create id, best-effort rm + bounded grace re-poll still runs, but
`cleanup_confirmed` stays false (fail closed). Regression tests cover empty-ps
after unverified create and timed-out create paths.

### Focused tests (this completion)

- Adversarial verifier + check_runner (excluding opt-in real Docker): 117 passed
- verifier_core + worker_artifact + trust_chain_proof + supervisor: 94 passed
- Cleanup regressions (`cleanup_unverified` / `cleanup_verified` /
  `timed_out_create`): 3 passed
- Opt-in real adversarial (`-k real_adversarial`): **3 passed**
- Blocking flake8 (`F,E9`) on touched Python: clean

### Real contained adversarial proofs

Image digest `a6f5e9858a815c7db9cefb9d647f919faafe63639321e658d680b48fb3d0d775`,
config `4adf2d1d6e5959603d214b4c841382668ceebbbc47438b3a2d03b32c54957b72`.
Docker Desktop 4.47.0 / Engine 28.4.0. No images built/pulled. After proofs,
`docker ps -a --filter name=cb026b` empty; CHECK_ROOT empty per case.
Upstream worker admission in these three cases is **simulated**; transport is
the real offline Docker check path. No separate host-proof harness script was
present in the worktree to re-run; earlier doc recorded one historical offline
worker admission that then failed closed on Docker control uncertainty.

**A. Positive** (`value.txt = b"2\n"`, sha256
`53c234e5e8472b6ac51c1ae1cab3fe06fad053beb8ebfd8977b010655bfdd3c3`)

- candidate_tree `1671980e21142e16a86779adca33468fcc2d7d6af9c4af76ed93ed052be1a311`
- structural `ae4062cae4e3e49c29cf8be29c068dc66ff19b2531f94a4969fa21c964e92c21`
- public: checks_passed, receipt
  `528f607a8b526425922c4008edf7c71a0dd01fe4e2b722c003927484856abb95`,
  termination+cleanup confirmed
- held-out runs: both checks_passed; containers
  `73f1893d…d2be9132`, `9383b389…e7a58328`; termination+cleanup confirmed
- classification: `adversarial_verification_passed`
- adversarial receipt
  `b6a431763140fbd49dfa95d1919e2a65f02c47fe05093442c8d464a73ef7a06f`
- all authority flags false; human_review_required true

**B. Gamed public** (`value.txt = b"3\n"`, sha256
`1121cfccd5913f0a63fec40a6ffd44ea64f9dc135c66634ba001d10bcf4302a2`)

- candidate_tree `ca3ed4a0bb08e98373e9def4b291973b7179264c6228b3d1b2a819b3a994cfae`
- public: checks_passed (weak public digit check), receipt
  `d88d9f01b3f8be552eb8f6609438131c3514a7b6b6bbbd44ccd781bc32eeacb3`
- held-out: both checks_failed (exit 1); containers
  `d09ad7c8…777174bf`, `7a0df969…3671a84`; termination+cleanup confirmed
- classification: `adversarial_verification_failed`
  (`held_out_check_failed`, `public_private_outcome_diverged`,
  `repeat_verification_failed`)
- adversarial receipt
  `6a3ddf44bdb44c47f4a3d834c4a612d917f18c678cab81e0c92ab95f6cb62f3e`

**C. Repeat / nondeterministic** (same correct value as positive; second
held-out collection deadline tightened to inject real timeout)

- public: checks_passed, receipt
  `bee0684d8b60760ad40c2b2735bf1700aa428ae0f8b8f1a6d8795db9e61b0002`
- held-out outcomes: `checks_passed` then `checks_uncertain` (timeout);
  containers `bed91ab1…8c4dcf`, `b602fa40…cdcd53b35`; cleanup confirmed
- classification: `adversarial_verification_uncertain` with
  `nondeterministic_outcome` (also `adversarial_evidence_uncertain`,
  `held_out_check_failed`, `public_private_outcome_diverged`,
  `repeat_verification_failed`)
- adversarial receipt
  `1902d6d062cd10fad5d35e77710051c550766c8fe7222d20fe3bc69952ad0575`

Do not merge automatically. CI status is recorded on the PR after push.

```bash
CB026B_TEST_IMAGE_DIGEST=a6f5e9858a815c7db9cefb9d647f919faafe63639321e658d680b48fb3d0d775 \
CB026B_TEST_CONFIG_DIGEST=4adf2d1d6e5959603d214b4c841382668ceebbbc47438b3a2d03b32c54957b72 \
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_continuous_builder_adversarial_verifier.py -k real_adversarial
```

These tests simulate upstream worker admission and use the actual production
Docker check transport. They must not be described as a real worker launch.
