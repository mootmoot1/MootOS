# MootOS Documentation Policy

Documentation is part of the product. It is not optional cleanup after coding.

This policy applies to human contributors, ChatGPT, Codex, Copilot, Grok, other coding agents, and future developers.

## 1. Documentation goals

MootOS documentation must allow a reader to answer:

- What exists today?
- What is only planned?
- How does the current system work?
- Where is production data stored?
- How is the application deployed and recovered?
- Why was an architectural choice made?
- What changed in a pull request?
- What remains incomplete or uncertain?

The documentation should be understandable to Moot without requiring him to read Python code.

## 2. Documentation categories

### Current implementation

Describes verified code and runtime behavior.

Examples:

- `docs/CURRENT_IMPLEMENTATION.md`
- `docs/API_REFERENCE.md`
- `docs/DATA_AND_PERSISTENCE.md`

Use direct language such as:

- “MootOS stores conversations in SQLite.”
- “The current provider is OpenAI.”

Do not describe planned features as current behavior.

### Operations

Describes deployment, verification, recovery, security response, and rollback.

Examples:

- `docs/PHONE_DEPLOYMENT.md`
- `docs/OPERATIONS_RUNBOOK.md`

Operational instructions must identify destructive steps and required approvals.

### Architecture history

Explains why major decisions were made.

Examples:

- ADR files
- `DECISIONS.md`

Do not rewrite old ADRs merely because the design later changes. Add a new ADR and identify what it supersedes.

### Planning

Describes future versions and proposed capabilities.

Examples:

- `ROADMAP.md`
- `ARCHITECTURE.md`
- `V0.1_REQUIREMENTS.md`

Planned items must be clearly labeled as planned, proposed, future, or not implemented.

## 3. Required documentation updates by change type

### API behavior change

Update:

- `docs/API_REFERENCE.md`
- `docs/CURRENT_IMPLEMENTATION.md`
- Tests
- README summary when the public feature set changes

### Database or schema change

Update:

- `docs/DATA_AND_PERSISTENCE.md`
- `docs/CURRENT_IMPLEMENTATION.md`
- Migration documentation
- Backup and rollback instructions
- Relevant ADR

### Authentication or security change

Update:

- README security section
- `docs/CURRENT_IMPLEMENTATION.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/PHONE_DEPLOYMENT.md` when configuration changes
- Relevant ADR

### Deployment change

Update:

- `docs/PHONE_DEPLOYMENT.md`
- `docs/OPERATIONS_RUNBOOK.md`
- README deployment section
- `docs/CURRENT_CHECKPOINT.md`

### New feature

Update:

- README feature list
- `docs/CURRENT_IMPLEMENTATION.md`
- `ROADMAP.md` status
- `V0.1_REQUIREMENTS.md` when release criteria are affected
- Relevant API or operations documents

### New architectural direction

Update:

- Add a new ADR
- Update `ARCHITECTURE.md`
- Update `ROADMAP.md`
- Explain compatibility and migration impact

## 4. Pull request documentation checklist

Every behavior-changing pull request should answer:

- [ ] What changed?
- [ ] Why did it change?
- [ ] Which files and systems changed?
- [ ] What was tested?
- [ ] What was not tested?
- [ ] Are there security or privacy effects?
- [ ] Are there data-migration effects?
- [ ] Is rollback documented?
- [ ] Did the README need an update?
- [ ] Did current implementation documentation need an update?
- [ ] Did API documentation need an update?
- [ ] Did operations documentation need an update?
- [ ] Was a new ADR required?
- [ ] Does the checkpoint reflect the new state after merge?

A documentation-only pull request should explicitly state that runtime behavior was not changed.

## 5. Accuracy rules

Contributors must not claim:

- A feature works without code and verification
- A deployment succeeded without checking it
- Data is backed up merely because it survives redeployment
- A database migration is safe without an upgrade test
- A security control exists because it is planned
- An AI action happened when it was only suggested
- A test passed when it was not run

When uncertain, use language such as:

- “Not yet verified”
- “Planned but not implemented”
- “The code appears to…”
- “Requires production confirmation”

## 6. Current truth versus future vision

`ARCHITECTURE.md` and `ROADMAP.md` contain long-term direction.

`docs/CURRENT_IMPLEMENTATION.md` and the code describe current behavior.

Every future-facing document should link back to the current implementation so a reader does not confuse ambition with shipped capability.

## 7. Plain-language requirement

Technical detail is welcome, but important documents must also explain consequences in normal language.

Example:

Technical:

> Railway supplies `RAILWAY_VOLUME_MOUNT_PATH`, and MootOS appends `mootos.db`.

Plain language:

> The database is stored on the attached Railway volume, so normal rebuilds do not erase conversations.

Both explanations may appear together.

## 8. Secret-handling rule

Documentation may name required environment variables but must never include real values.

Never document:

- Real API keys
- Real passwords
- Session secrets
- Authentication cookies
- Private tokens
- Personal memory exports
- Sensitive production data

Use placeholders:

```text
OPENAI_API_KEY=<secret>
```

## 9. Change history

The project checkpoint should be updated after significant verified milestones.

ADRs preserve architectural history.

Pull requests preserve implementation history.

The README should remain a current entry point rather than a changelog.

## 10. Review standard

Before approving documentation, verify:

- Links point to real files
- Commands match the repository
- Environment variables match the code
- Route names match FastAPI
- Planned features are labeled
- Production claims have evidence
- Destructive actions include warnings
- The document does not expose secrets
- The wording is understandable without code knowledge

## 11. Core documentation rule

A future developer or AI agent should be able to understand MootOS from the repository itself without depending on old screenshots, copied chat messages, or one person's memory.
