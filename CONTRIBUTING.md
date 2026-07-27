# Contributing to MootOS

## Purpose

This document defines the development rules for MootOS.

These rules apply to:

- Moot
- Human developers
- Codex
- GitHub Copilot
- AI coding agents
- Future contributors

Anyone making changes to MootOS should follow these rules.

The goal is to keep MootOS organized, secure, understandable, and under Moot's control as it grows.

---

## 1. Follow the Architecture

All development must follow the direction established in:

- `README.md`
- `ARCHITECTURE.md`
- `ROADMAP.md`
- `V0.1_REQUIREMENTS.md`
- `DECISIONS.md`
- `CONTRIBUTING.md`

Before creating or changing a major feature, contributors should review the relevant documentation.

Code should not contradict the documented architecture without an approved architectural decision.

---

## 2. Respect Architecture Decision Records

Major technical and architectural decisions must be documented using Architecture Decision Records.

Every major decision must receive a unique identifier.

Examples:

- `ADR-001`
- `ADR-002`
- `ADR-003`

An Architecture Decision Record should explain:

- The title of the decision
- The status
- The date
- The decision
- The reason
- The consequences
- Any alternatives considered

Existing decisions should not be silently removed or rewritten.

If a previous decision needs to change:

1. Create a new ADR.
2. Reference the previous ADR.
3. Explain why the previous decision is being replaced.
4. Mark the previous decision as superseded.
5. Keep the original decision in the project history.

Architecture Decision Records are part of the permanent history of MootOS.

---

## 3. Keep Version 0.1 Focused

Version 0.1 must remain focused on its approved requirements.

The main objective is:

> Build a secure, mobile-friendly conversational AI that can maintain context, remember important information, organize memories into projects, and allow Moot to control its memory.

Do not add unrelated features to Version 0.1 unless they are required for the foundation.

Features intentionally excluded from Version 0.1 include:

- Social media automation
- Voice conversations
- Camera access
- Screen control
- Email automation
- Financial account access
- Multiple autonomous agents
- Automatic code deployment
- Advanced computer control
- Vehicle integrations
- Home automation

These features should remain on the roadmap until their proper version.

---

## 4. Work in Small Changes

Changes should be small enough to understand, test, and review.

Avoid combining many unrelated changes into one commit.

Good examples:

- Add the initial FastAPI application.
- Add the database connection.
- Add the memory model.
- Add the login page.
- Fix conversation history loading.

Bad examples:

- Build the entire backend, frontend, memory system, authentication system, and tool system in one commit.

Small changes are easier to:

- Review
- Test
- Debug
- Reverse
- Explain
- Approve

---

## 5. Use Branches for Major Work

The `main` branch should contain the most stable approved version of MootOS.

Major features and risky changes should be developed in separate branches.

Suggested branch naming:

- `feature/chat-interface`
- `feature/memory-system`
- `feature/project-system`
- `fix/login-error`
- `fix/memory-retrieval`
- `docs/update-roadmap`
- `security/api-key-storage`

A branch should focus on one main purpose.

Changes should be reviewed before being merged into `main`.

---

## 6. Human Approval is Required

Coding agents may:

- Read the repository
- Suggest changes
- Create plans
- Write code
- Create tests
- Fix bugs
- Prepare branches
- Prepare pull requests
- Explain their work

Coding agents may not silently:

- Merge major changes
- Delete important files
- Change architecture
- Remove security controls
- Publish the application
- Spend money
- Change account permissions
- Expose private information
- Commit credentials
- Deploy unreviewed code

Moot remains the final authority over important changes.

---

## 7. Explain Changes Clearly

Every important change should include a plain-language explanation.

The explanation should answer:

- What changed?
- Why was it changed?
- Which files were affected?
- How was it tested?
- Are there any risks?
- Can the change be reversed?
- Does the change affect an ADR?

Technical explanations should be understandable to Moot, even if an AI coding agent created the code.

---

## 8. Write Understandable Code

Code should be organized and readable.

Contributors should:

- Use clear names
- Keep functions focused
- Avoid unnecessary complexity
- Add comments when the reason is not obvious
- Separate unrelated responsibilities
- Remove unused code
- Follow consistent formatting
- Handle expected errors
- Avoid duplicating logic

Code should not be made complicated simply to appear advanced.

The simplest reliable solution should usually be preferred.

---

## 9. Keep Systems Modular

Major MootOS systems should remain separated.

Examples include:

- Interface
- Conversation engine
- Memory system
- Model providers
- Tool system
- Permissions
- Projects
- Logging
- Storage
- Authentication

A change to one system should not unnecessarily require rebuilding unrelated systems.

AI providers must remain replaceable.

Tools should be added through a controlled tool interface.

Memory storage should not be tightly tied to the user interface.

---

## 10. Protect Secrets and Private Information

Never commit any of the following to GitHub:

- Passwords
- API keys
- Access tokens
- Private keys
- Authentication cookies
- Database passwords
- Personal messages
- Financial information
- Private contact information
- Sensitive memory exports

Secrets should be stored in environment variables or another approved secure storage system.

Local secret files should be excluded using `.gitignore`.

Example secret file:

`.env`

The repository may include a safe example file:

`.env.example`

The example file must contain placeholder values only.

Example:

`OPENAI_API_KEY=your_api_key_here`

Never place a real API key inside `.env.example`.

---

## 11. Protect User Data

MootOS may eventually store sensitive personal information.

Contributors must:

- Collect only necessary information
- Avoid sending private information to outside services without approval
- Clearly document cloud usage
- Validate user input
- Prevent accidental data exposure
- Protect memory records
- Avoid logging sensitive secrets
- Provide a way to delete stored information

Privacy should be considered during development, not added only after the system is finished.

---

## 12. Test Important Changes

New features and bug fixes should be tested before approval.

Tests may include:

- Automated unit tests
- Integration tests
- Manual testing
- Security checks
- Database migration tests
- Mobile browser testing

At minimum, contributors should confirm:

- The application starts
- Existing features still work
- The new feature behaves as expected
- Errors are handled safely
- No secrets were added to the repository

A feature should not be considered complete only because the code was generated successfully.

---

## 13. Do Not Hide Failures

Errors, failed tests, incomplete work, and uncertainty must be reported honestly.

Coding agents should not claim:

- A feature works without testing it
- A test passed when it was not run
- A bug is fixed without verification
- A system is secure without evidence
- A deployment succeeded without confirmation

If something is incomplete, explain what remains.

If something is uncertain, clearly state the uncertainty.

---

## 14. Maintain Documentation

Documentation should be updated when behavior changes.

Examples:

- Update `README.md` when setup instructions change.
- Update `ARCHITECTURE.md` when the system structure changes.
- Update `ROADMAP.md` when version plans change.
- Update `V0.1_REQUIREMENTS.md` when approved requirements change.
- Update `DECISIONS.md` when a major architectural decision is made.
- Update this file when contribution rules change.

Code and documentation should not describe two different systems.

---

## 15. Commit Message Guidelines

Commit messages should briefly explain what changed.

Recommended format:

`type: short description`

Examples:

- `docs: add contribution guidelines`
- `build: create initial project structure`
- `feat: add basic chat endpoint`
- `feat: add memory storage`
- `fix: correct conversation loading`
- `test: add memory service tests`
- `security: protect API key configuration`
- `refactor: separate model provider interface`

Suggested commit types:

- `docs`
- `build`
- `feat`
- `fix`
- `test`
- `security`
- `refactor`
- `chore`

Avoid unclear commit messages such as:

- `update`
- `stuff`
- `changes`
- `fixed it`
- `new code`

---

## 16. Pull Request Guidelines

A pull request should include:

- A clear title
- A summary of the change
- The reason for the change
- Files or systems affected
- Testing performed
- Known limitations
- Security or privacy impact
- Related requirement
- Related ADR, if applicable

Major pull requests should not be merged until Moot understands and approves the change.

---

## 17. Definition of Complete

A feature is complete when:

- It matches an approved requirement.
- It follows the architecture.
- It respects existing ADRs.
- The code is understandable.
- Important errors are handled.
- Relevant tests pass.
- No secrets are committed.
- Documentation is updated.
- Moot receives a clear explanation.
- Required approval is given.

Generated code alone does not mean the feature is complete.

---

## 18. Core Rule

MootOS should become more capable without becoming less understandable, less secure, or less controllable.

Every contributor should protect that principle.
