# devflow-ai

> Spec-driven build orchestrator for AI coding agents — plan-first workflow, quality gate, multi-provider, cost tracking.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml/badge.svg)](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml)
[![Tests: 1049](https://img.shields.io/badge/tests-1049-brightgreen)](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml)

---

AI coding agents are powerful but undisciplined. They skip plans, ignore tests, burn tokens on retry loops that go nowhere, and give you no visibility on cost or quality.

**devflow** is the orchestration layer that agents don't have: a persistent state machine, plan-first approval flow, automatic quality gate with model escalation, structured code review, cost tracking, and auto PR creation. You validate the plan — devflow handles the rest.

Two built-in backends: **Claude Code** (default) and **Pi** (18+ LLM providers including Ollama local). The backend is a Protocol — add your own in one file.

---

## What it does

```
devflow build "add user authentication"
```

1. Creates a feature branch
2. **Plans** — agent produces a step-by-step plan, you review it
3. **Implements** — agent follows the plan, commits after each step
4. **Reviews** — structured reviewer with blocking/non-blocking issues
5. **Gate** — lint + tests + secrets scan in parallel, auto-retry on failure
6. **PR** — title and body generated from the actual diff

If the gate fails, devflow retries with model escalation (Haiku → Sonnet → Opus). If the reviewer finds issues, the fixer gets a targeted pass. If a retry produces no meaningful diff, it aborts instead of burning tokens.

---

## Three tiers

| Command | Branch | PR | Use case |
|---|---|---|---|
| `devflow do "..."` | Current | No | Quick task, revert on failure |
| `devflow build "..."` | New branch | Yes | Feature with plan, review, gate, PR |
| `devflow build "..." --worktree` | Isolated worktree | Yes | Parallel features on separate scopes |

The workflow (quick / light / standard / full) is auto-selected from task complexity.

---

## Key features

### Plan-first with human approval

The agent plans before coding. You review, approve, or reject with feedback. No implementation starts without your sign-off.

```bash
devflow build "feedback about the plan" --resume feat-001
```

### Multi-provider via Pi

Switch between 18+ LLM providers without changing your workflow:

```yaml
# .devflow/config.yaml
backend: pi
pi:
  models:
    fast: ollama/llama3.1:8b       # local, free, for one-shots
    standard: anthropic/sonnet     # most phases
    thinking: anthropic/opus       # planning, review
```

```bash
devflow build "fix typo" --backend pi
```

### Quality gate with escalation

Runs lint, tests, and secrets detection in parallel. On failure:
- **3 retries** with model escalation (Haiku → Sonnet → Opus)
- **Diff-min anti-loop** — aborts if retry produces < 5% change
- Each retry receives the previous attempt's errors

Custom gate commands per project:

```yaml
gate:
  lint: make lint
  test: make test
```

Without config, devflow auto-detects the stack (Python → ruff/pytest, TypeScript → biome/vitest, PHP → pint/pest).

### Structured code review

The reviewer produces machine-parseable output:

```
Verdict: REQUEST_CHANGES

Blocking issues:
- src/auth.py:42 — security — SQL injection in user lookup query
- src/auth.py:78 — correctness — missing null check on token expiry

Non-blocking notes:
- Consider extracting the token validation into a helper
```

If the output doesn't match the format, devflow re-prompts automatically. No more vague "looks good" reviews.

**Double-review** on critical paths — configure sensitive files that require two independent reviewers:

```yaml
double_review_on:
  - "src/auth/**"
  - "src/payment/**"
```

### Metrics dashboard

```bash
devflow metrics                  # ASCII dashboard
devflow metrics --since 7d       # last 7 days
devflow metrics --export json    # JSON for scripting
```

Tracks per-phase: cost, tokens, cache hit rate, duration, model, backend. Budget alerts when a feature exceeds the configured threshold.

### Parallel features

Run multiple features simultaneously in isolated git worktrees:

```bash
devflow build "add auth" --worktree &
devflow build "fix payments" --worktree &
```

Each feature gets its own worktree. State is protected by file locks — no corruption.

### User hooks

```
.devflow/hooks/pre-build.sh      # exit non-0 = skip build
.devflow/hooks/post-gate.sh      # receives "passed" or "failed"
.devflow/hooks/on-failure.sh     # receives phase name + error
```

### Scripting & CI

```bash
devflow status --json | jq '.features[] | select(.status == "implementing")'
devflow check --json
devflow --quiet build "fix typo"   # no banners, no spinners
```

---

## Install

Requires Python 3.11+, [GitHub CLI](https://cli.github.com/) (`gh`), and an AI backend.

```bash
uv tool install devflow-ai
devflow init                # interactive setup wizard
devflow install             # sync agent assets
devflow doctor              # check everything works
devflow doctor --fix        # auto-fix common issues
```

Default backend: [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Alternative: [Pi](https://github.com/badlogic/pi-mono) (18+ providers).

---

## Commands

```
devflow init                                 Interactive project setup
devflow build "description"                  Plan → implement → review → gate → PR
devflow build "feedback" --resume feat-001   Resume with feedback
devflow build --retry feat-001               Retry last failed phase
devflow build "task" --worktree              Run in isolated worktree
devflow build "task" --backend pi            Use Pi backend
devflow do "description"                     Quick task on current branch
devflow check                                Run quality gate locally
devflow status [feat-001]                    Show tracked features
devflow metrics                              Cost & performance dashboard
devflow sync                                 Post-merge cleanup
devflow install                              Install agent assets
devflow doctor [--fix]                       Health check & auto-fix
```

---

## Configuration

```yaml
# .devflow/config.yaml
stack: python                    # auto-detected
base_branch: main                # PR target
backend: claude                  # claude | pi

pi:
  models:
    fast: ollama/llama3.1:8b
    standard: anthropic/sonnet
    thinking: anthropic/opus

gate:
  lint: make lint
  test: make test
  diff_min_threshold: 0.95       # abort retry if < 5% change

double_review_on:                # paths requiring 2 reviewers
  - "src/auth/**"

budget:
  per_feature_usd: 0.50          # soft warning threshold

tracker:
  name: linear
  linear:
    team: TEAM-ID

# Tracker plugins: pip install devflow-jira (coming soon)
```

---

## Architecture

```
cli.py                  → commands (zero business logic)
orchestration/          → build loop, retry, review cycle, phase dispatch
integrations/           → backends (Claude, Pi), gate, git, Linear
core/                   → state machine, models, config, metrics, protocols
ui/                     → Rich rendering, dashboard, spinners
```

Layering enforced via `import-linter` — `core/` never imports from upper layers.

Backends and trackers implement typed Protocols. Adding a new backend is one file implementing 5 methods. Adding a tracker is one file implementing 4 methods.

**1049 tests** | **83% coverage** | **mypy strict** | **ruff** | **import-linter**

---

## License

MIT — see [LICENSE](LICENSE).
