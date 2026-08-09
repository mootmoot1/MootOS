# Repository Guidelines

## Project Structure & Module Organization

MootOS is one FastAPI service backed by SQLite. Python code lives in `backend/`; keep routes, persistence, model routing, and tool controls separated. The vanilla HTML/CSS/JavaScript UI is in `frontend/`. Tests in `tests/` generally mirror backend features. Architecture decisions and operations guidance live in `docs/`. Review `ARCHITECTURE.md`, `DECISIONS.md`, and relevant ADRs before changing system boundaries.

## Build, Test, and Development Commands

Use Python 3.9–3.11 in an isolated environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Run locally with `python -m uvicorn backend.application:app --reload`. Run `pytest` for all tests or `pytest tests/test_tasks.py -q` for a focused file. Lint with `flake8 backend tests`.

## Coding Style & Naming Conventions

Follow PEP 8, four-space Python indentation, and flake8 defaults. Use `snake_case` for modules/functions, `PascalCase` for classes/exceptions, and `UPPER_SNAKE_CASE` for constants. Keep functions focused and errors explicit. Frontend files use two spaces and page-oriented names such as `memory.js`.

## Testing Guidelines

Name pytest files `test_<feature>.py` and cases `test_<behavior>`. Cover each behavior change, especially authentication, migrations, atomicity, tool approval, and sanitized failures. Use temporary databases through fixtures such as `tmp_path`; never use `data/mootos.db`. No numeric coverage threshold is enforced.

## Codex Worker Boundaries

Codex operates only as an isolated worker. Treat `main` as read-only. Before editing, run `git branch --show-current`; if it returns `main`, stop before any edit and ask for a dedicated branch or worktree. Work only on a dedicated non-main branch, stay within the assigned scope, and preserve unrelated changes.

Unless the user explicitly instructs otherwise, Codex must not:

- commit, push, merge, or open a pull request;
- modify secrets, credentials, `.env` files, or permissions;
- read, print, copy, or expose secrets or credentials, including `.env`, API keys, tokens, or deployment credentials;
- change production/deployment configuration, including `railway.toml`; or
- add, edit, delete, stage, or otherwise touch anything under `data/`.

Never run destructive Git operations such as `git reset --hard`, `git clean`, force-push, or commands that discard or revert existing user changes unless explicitly authorized.

After changes, run relevant tests; use the full suite when scope or risk warrants it. Report exactly what changed, every test/check and result, and any risks or unresolved issues. Never claim unrun verification.

## Commit & Pull Request Conventions

When explicitly authorized, keep commits small and use `type: short description`, such as `fix: reject expired approvals`. PRs should explain what and why, affected systems, tests, limitations, security/privacy impact, and related ADRs. Include screenshots for UI changes.

## Security & Documentation

Never commit secrets, private profile data, databases, or backups. Preserve fail-closed authentication, storage, and tool boundaries. Update documentation with behavior; supersede decisions through a new ADR rather than rewriting history.
