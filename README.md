# devflow-ai

> Autonomous build engine for AI coding agents — state machine, quality gate, cost tracking.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml/badge.svg)](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml)
[![Tests](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/justineraze/10e0ec33f99478dc423de8dda3517994/raw/devflow-ai-tests.json)](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml)

---

AI coding agents are powerful but stateless. You re-explain context every session, manually run quality checks, and have no idea what anything costs. If the agent crashes mid-feature, you start over.

**devflow** wraps your AI agent with a persistent state machine, plan-first flow, automatic quality gate, cost tracking, and auto PR creation. You review the output — not manage the process.

Ships with a Claude Code backend. The backend is a Protocol — bring your own (Gemini, OpenAI, Aider, etc.).

---

## Build

One command: plan, implement, gate, PR.

![devflow build](docs/demo-build.png)

Plan not right? Reject and resume with feedback:

```bash
devflow build "use a Rich panel instead of a table" --resume feat-001
```

---

## Track

Every build logs cost, model, cache rate, and phase timings.

![devflow status](docs/demo-status.png)

---

## How it works

### Three tiers

| Command | Branch | PR | Use case |
|---|---|---|---|
| `devflow do "..."` | Current branch | No | Quick task, refactor, commit on current branch. Reverts on failure. |
| `devflow build "..."` | New `feat/` or `fix/` branch | Yes | Feature or bugfix with planning, review, gate, and auto PR. |
| `devflow epic "..."` | *(coming soon)* | — | Decompose large features into coordinated sub-features. |

The workflow (quick / light / standard / full) is auto-selected from task complexity. Override with `--workflow`.

### Autonomous feedback loops

devflow doesn't just run phases sequentially — it self-corrects:

- **Gate retry** — if the quality gate fails, devflow retries up to 3 times with model escalation (Haiku → Sonnet → Opus). Each retry receives the previous attempt's diff and errors.
- **Review cycle** — after fixing, the reviewer re-checks that its issues are resolved (max 2 cycles). If the reviewer says `REQUEST_CHANGES`, the fixer gets another pass.
- **Smart commit messages** — commit messages, PR titles, and PR descriptions are generated from the actual diff via a fast one-shot call — not truncated prompt text.

### Quality gate

Runs lint, tests, and secrets detection in parallel. Configure custom commands in `.devflow/config.yaml`:

```yaml
gate:
  lint: make check
  test: make test
```

Without custom commands, devflow auto-detects the stack (Python → ruff/pytest, TypeScript → biome/vitest, PHP → pint/pest).

Additional structural checks report warnings for cyclomatic complexity and module size.

### Architecture-aware agents

- **Architect** — verifies layering, coupling, and single responsibility before planning.
- **Planner** — audits existing code quality (duplication, file size, missing tests) before writing the plan.
- **Reviewer** — 6-pass review: architecture compliance, patch detection, plan compliance, correctness, security, conventions.

### Metrics & cost tracking

Every build logs cost, tokens, cache hit rate, and duration per phase. View with:

```bash
devflow status --metrics
```

Warns when cache hit rate drops below 40% (sign of prompt drift).

### Configuration

All project settings live in `.devflow/config.yaml`:

```yaml
stack: python               # auto-detected, overridable
base_branch: main           # base branch for PRs
backend: claude             # claude (default) — extensible via Backend Protocol

gate:
  lint: make check           # custom lint command (optional)
  test: make test            # custom test command (optional)

linear:
  team: ABC                  # Linear team key (optional)
```

Without this file, everything works with auto-detected defaults. State (features, phases) is kept separately in `.devflow/state.json`.

### Linear integration (optional)

Issues are auto-created in Linear when a build starts and auto-synced on completion. Configure in `.devflow/config.yaml` or via:

```bash
devflow install --linear-team ABC
export LINEAR_API_KEY=lin_api_...
```

---

## Install

Requires Python 3.11+, an AI coding agent CLI, and [GitHub CLI](https://cli.github.com/) (`gh`).

Default backend is [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`). Other backends can be added by implementing the `Backend` Protocol.

```bash
uv tool install devflow-ai
devflow install   # sync assets, detect stack, run diagnostic
```

---

## Commands

```
devflow do "description"                     Task on current branch (no PR, reverts on failure)
devflow build "description"                  Plan, implement, review, gate, PR
devflow build "feedback" --resume feat-001   Resume with feedback on the plan
devflow build --retry feat-001               Retry from the last failed phase
devflow check                                Run quality gate locally
devflow status [feat-001]                    Show tracked features
devflow status --log [feat-001]              Phase history with timings
devflow status --metrics                     Build cost and cache history
devflow sync                                 Post-merge cleanup (+ --linear for Linear sync)
devflow install                              Install assets + init + diagnostic
devflow install --check                      Diagnostic only
devflow --version                            Show version
```

---

## License

MIT — see [LICENSE](LICENSE).
