# CLAUDE.md

Project rules for Claude Code. Follow these on every task. If a rule conflicts with a direct instruction from me in chat, ask before deviating.

## 1. Git: Commit Messages

Use Conventional Commits: `type(scope): short description`

Allowed types:

- `feat` - new feature
- `fix` - bug fix
- `docs` - documentation only
- `style` - formatting, whitespace, no logic change
- `refactor` - code change that neither fixes a bug nor adds a feature
- `perf` - performance improvement
- `test` - adding or updating tests
- `build` - build system or dependency changes
- `ci` - CI/CD configuration
- `chore` - maintenance tasks, tooling, configs
- `revert` - reverting a previous commit

Subject line rules:

- Format: `feat(auth): add login endpoint`
- Scope is required and lowercase (module, feature or folder name)
- Imperative mood ("add", not "added" or "adds")
- Max 72 characters, no trailing period

Body rules (only when the change needs explanation):

- Leave one blank line after the subject
- Write the body as bullet points, one change per bullet
- Explain what and why, not how

Example:

```
feat(auth): add JWT login endpoint

- add POST /auth/login with email and password validation
- issue access token with 15 minute expiry
- add unit tests for invalid credentials
```

Breaking changes: add `!` after the scope (`feat(api)!: ...`) and a `BREAKING CHANGE:` bullet in the body.

## 2. Git: Authorship (IMPORTANT)

- NEVER add Claude or Anthropic as a contributor or author.
- NEVER add `Co-Authored-By: Claude ...` or any co-author trailer for Claude/Anthropic.
- NEVER add lines like "Generated with Claude Code" to commit messages, PR titles, PR descriptions, code comments or files.
- Commits must appear only under my git identity. Do not change `git config user.name` or `user.email`.

## 3. Git: Branching

- NEVER commit directly to `main` / `master` / `develop`.
- Create a new branch for every feature, fix or task before writing code.
- Branch naming: `type/short-kebab-description`
  - `feat/user-authentication`
  - `fix/cart-total-rounding`
  - `refactor/payment-service`
  - `docs/update-readme`
  - `chore/upgrade-dependencies`
- Branch off the latest updated base branch (pull first).
- One branch = one purpose. Do not mix unrelated changes.
- Merge via pull request. Do not merge or push to the base branch yourself unless I say so.

### 3.1 Git: Commits Workflow

- Make small, atomic commits. Each commit does one logical thing and leaves the project in a working state.
- Commit early and often; do not batch a whole feature into one commit.
- Separate concerns into separate commits (for example: refactor, then feature, then tests, then docs).
- Before every commit:
  - Run `git status` and `git diff` to review exactly what is being committed
  - Stage files explicitly by name; avoid `git add .` / `git add -A`
  - Run the linter and relevant tests (see Project Commands)
- NEVER use `--no-verify` to skip hooks.
- NEVER force push (`--force`), rewrite shared history, or run `git reset --hard` / `git clean -fd` without asking me first.
- Do not push to remote unless I ask.

## 4. Safety: Never Commit

- Secrets of any kind: `.env` files, API keys, tokens, passwords, private keys, credentials
- Build output and dependencies: `node_modules/`, `dist/`, `build/`, `__pycache__/`, `.venv/`
- OS and editor junk: `.DS_Store`, `.idea/`, `.vscode/` (unless already tracked)
- Large binaries or generated files that are not meant to be tracked (this repo ignores `*.sqlite`, `*.sqlite3`, `*.db`; do not force-add run databases)
- If you spot a secret already in the code, stop and tell me instead of committing.

## 5. Code Quality

- Read the existing code first; follow the existing style, naming and structure.
- Keep changes minimal and focused on the task. No drive-by refactors or unrelated edits.
- Write clear, self-explanatory code; add comments only for the why, not the what.
- No dead code, commented-out code, debug prints or leftover TODOs in commits.
- Handle errors explicitly; never swallow exceptions silently.
- Validate input at boundaries; never trust user input.
- Do not add a new dependency without asking me; prefer what the project already uses.
- Prefer small functions with a single responsibility.

## 6. Testing

- Add or update tests for every new feature and bug fix.
- For a bug fix, write a failing test that reproduces it first, then fix it.
- All tests and the linter must pass before a commit.
- Never delete or weaken a test just to make it pass; tell me why it fails instead.

## 7. Working Style

- For anything non-trivial, briefly state your plan before making changes.
- Ask me when requirements are unclear instead of guessing.
- Do not delete files, drop databases or run destructive commands without explicit approval.
- Do not modify unrelated files, lock files or config files unless the task requires it.
- After finishing, summarize what changed and what I should check, in short bullet points.
- If something is out of scope but worth fixing, mention it instead of doing it.

## 8. Documentation

- Update the README and relevant docs when behavior, setup or commands change (`README.md`, `docs/spec_pxp_n.md`, `docs/metrics.md`).
- Keep `.env.example` in sync when adding new environment variables (never real values). The repo has none yet; create one if a new variable is introduced.

## 9. Project Commands

Python is managed with [uv](https://docs.astral.sh/uv/); the UI needs Node 24.

- Install: `uv sync` and `npm --prefix ui install`
- Run dev: `uv run python -m server --demo` (open http://127.0.0.1:8000), and `npm --prefix ui run dev` for hot reload (proxies to :8000, open http://localhost:5173)
- Lint: `uv run ruff check .` and `npm --prefix ui run typecheck`
- Format: `uv run ruff format .` (check only: `uv run ruff format --check .`)
- Test: `uv run pytest -q` and `npm --prefix ui test`
- Build: `npm --prefix ui run build` (the server serves `ui/dist`)

Other useful commands:

- Terminal demo with mock agents: `uv run python -m scheduler.demo`
- Archived run in the viewer: `uv run python -m server --db results/runs/j3_prelim_hot/shard-1-of-1/board.sqlite`
- Pipeline smoke test with no model: `uv run python -m bench.run configs/j3_prelim_hot.json --mock --limit 2 --out results/roadmap-smoke`
- Run or resume an experiment: `uv run python -m bench.run configs/<job>.json --shard 1/1 --parallel 8`
- Figures from a metrics CSV: `uv run python -m bench.plots results/metrics.csv --out results/figures`
- macOS: if `python -m` reports `No module named 'scheduler'` (or `bench`, `server`), run `chflags -R nohidden .venv`.

## 10. Project Overview

**Purpose:** Course project (Reasoning Agents AI) on an "Intelligible Blackboard". Several LLM agents post predictions and explanations to one shared, append-only log, tagging each reply with the PXP protocol (Baskar, Srinivasan, Bain, Coiera, arXiv:2301.01819). Agents can replay one of their own past replies differently in a sandbox ("counterfactual credit assignment"). The research question is whether this helps break deadlocks faster and more cheaply. Pilots J1-J3 recorded zero replays, so the current work follows `Intelligible_Blackboard_Roadmap.pdf`: a scheduler recovery checkpoint, two matched sandbox branches, adoption as a real reply, and a paired study of three arms (standard, forward repair, replay), plus a session explorer UI.

**Stack:**

- Python 3.11+, pydantic, FastAPI/uvicorn (REST + WebSocket), httpx, matplotlib, SQLite
- pytest and ruff (line length 100)
- UI: Vite, React 19, D3, TypeScript, vitest
- Models: OpenAI-compatible endpoint (Ollama locally or vLLM on Colab) chosen by `LLM_BACKEND`, `LLM_BASE_URL`, `LLM_MODEL`; a deterministic mock client covers tests

**Structure:**

| Path | Contents |
|---|---|
| `src/blackboard/` | `EventStore` (SQLite, append-only, `fork`, `snapshot`, `subscribe`), `BoardState` |
| `src/protocol/` | Event schema, validator, tag state machine, intelligibility classifier |
| `src/scheduler/` | `Scheduler` (priority, consensus/cap/impasse/stall stops), mock agents |
| `src/agents/` | `LLMClient`, prompts, `parse_pxp`, `PEXAgent`, scripted scenarios |
| `src/counterfactual/` | `sandbox.replay` (fork, replay, credit delta), `CounterfactualAgent` |
| `src/server/` | FastAPI app, `--demo` streamer |
| `src/bench/` | MSCoRe ingest, correctness rules, resumable runner, metrics CSV, plots |
| `ui/src/` | React/D3 viewer: graph, scrubber, state panel, counterfactual panel |
| `tests/` | pytest suite and `fixtures/pxp_sequences/` |
| `configs/` | Experiment job configs (`j2_baseline`, `j3_prelim`, `j3_prelim_hot`) |
| `docs/` | `spec_pxp_n.md` (protocol), `metrics.md` (CSV columns), `compute.md` |
| `results/` | Run outputs (J1-J3 pilots); contents are git-ignored except the README |

**Key conventions:**

- The log is append-only (SQLite triggers block update/delete). `seq` is assigned by the store, contiguous per session.
- Only `kind=message`, non-counterfactual events count toward real-message totals; rollback events are read-only records with `counterfactual=true`.
- Only `system` writes TERM, with the stop reason (`consensus`, `impasse`, `cap`) in `explanation`.
- Keep agreement, adoption and correctness as separate outcomes; keep posted (board) tokens separate from full-trial tokens.
- Scripted agents drive fixtures so recovery logic is testable without a model. The toy X/Y fixture stays out of the benchmark.
- Historical J1-J3 results are labelled "historical pilot"; they give no estimate of replay's effect.
- Pass `session_id` as a query parameter for archive reads, since real session IDs contain `/`, `|` and `#`.
