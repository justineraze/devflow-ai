# devflow-ai

> CLI that installs and orchestrates an AI development environment for Claude Code.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org)

devflow-ai doesn't reinvent Claude Code — it provides what Claude Code can't do natively: **persistent state**, **state machine**, **project tracking**, **automated quality gates**, **artifact-aware context sharing**, and **cost-aware model routing**.

---

## Prerequisites

- [Python 3.11+](https://www.python.org)
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — `claude` CLI
- [GitHub CLI](https://cli.github.com/) — `gh` (for PR creation)

```bash
devflow doctor                  # check your setup
```

## Quickstart

```bash
uv tool install devflow-ai      # install globally

devflow install                 # sync agents & skills to ~/.claude/
devflow init                    # detect stack + initialize project
devflow build "Add user auth"   # plan → review → implement → PR
devflow fix "Fix login bug"     # quick fix (no planning phase)
devflow check                   # run quality gate
devflow status                  # see what's in progress
```

---

## How a build looks

```
$ devflow build "Add caching layer"

devflow build — Add caching layer
feat-add-caching-layer-0413 | workflow: standard | 4 phases
branch: feat/feat-add-caching-layer-0413

Phase 1/4: planning... ✓ (1m12s)

╭─── Plan proposé ─────────────────────────────────────────╮
│ Plan: feat-add-caching-layer-0413                        │
│ Scope: new-feature, medium complexity                    │
│ Affected files: 3                                        │
│ Steps: 6                                                 │
│ ...                                                      │
╰──────────────────────────────────────────────────────────╯

Lancer l'implémentation ? [Y/n] y

Phase 2/4: implementing...
  📖 Read: models.py
  ✏️ Edit: cache.py
  ⚡ Bash: pytest tests/test_cache.py
  ⚡ Bash: git commit -m "feat: add Cache class"
  → 8 tools | 5.2k in / 1.8k out | 18¢
 ✓ (2m34s)

Phase 3/4: reviewing... ✓ (48s)
Phase 4/4: gate... ✓ (1s)
  ✓ ruff: No lint issues  ✓ pytest: 174 passed  ✓ secrets: clean

✓ Feature complete [4/4]
PR: https://github.com/you/repo/pull/42
```

The plan-first flow lets you review and approve before code is touched.
If the plan needs tweaks, refuse with `n` and resume with feedback:

```bash
devflow build "use Redis instead of in-memory" --resume feat-add-caching-layer-0413
```

Each phase shows live tool usage and token cost. Auto-commit after each
implementation slice. PR created automatically with the plan as description.

---

## Architecture

```mermaid
flowchart TB
    YOU([You])

    subgraph CORE[core/ — state & domain]
        MODELS[models.py]
        WORKFLOW[workflow.py]
        ARTIFACTS[artifacts.py]
        TRACK[track.py]
    end

    subgraph ORCH[orchestration/ — the engine]
        BUILD[build.py]
        RUNNER[runner.py]
        ROUTING[model_routing.py]
        STREAM[stream.py]
    end

    subgraph INTEG[integrations/ — external]
        GATE[gate.py]
        GIT[git.py]
        DETECT[detect.py]
    end

    subgraph STATE_DIR[".devflow/"]
        STATE[(state.json)]
        FEATART[(feat-id/<br>planning.md<br>gate.json<br>files.json)]
    end

    subgraph ASSETS[~/.claude/]
        AGENTS[agents/<br>9 roles]
        SKILLS[skills/<br>8 disciplines]
    end

    subgraph TOOLS[External]
        CLAUDE([claude -p])
        GH([gh pr create])
    end

    YOU --> BUILD
    BUILD --> RUNNER
    BUILD --> GIT
    BUILD --> GATE
    BUILD --> STATE
    BUILD --> FEATART
    RUNNER --> ROUTING
    RUNNER --> ARTIFACTS
    RUNNER --> CLAUDE
    RUNNER --> AGENTS
    RUNNER --> SKILLS
    ROUTING --> FEATART
    GIT --> GH

    classDef user fill:#f9c,stroke:#333,stroke-width:2px
    classDef data fill:#ffe082,stroke:#333
    classDef md fill:#b3e5fc,stroke:#333
    classDef ext fill:#c8e6c9,stroke:#333
    class YOU user
    class STATE,FEATART data
    class AGENTS,SKILLS md
    class CLAUDE,GH ext
```

**The split:** Python handles what must be programmatic (state, validation, automation). Markdown handles what must be flexible (agent behavior, instructions, prompts).

**Per-feature artifacts.** Every phase output lives on disk under `.devflow/<feat-id>/` — `planning.md`, `reviewing.md`, `gate.json`, `files.json`. Downstream phases load only the artifacts they depend on (selective injection), keeping the user prompt compact and stable enough for prompt caching. No more concatenating every previous phase's output.

---

## Workflows

Four built-in workflows, from fast to thorough:

| Workflow | Phases | Use case |
|----------|--------|----------|
| `quick` | implement → gate | Bug fixes, small changes |
| `light` | plan → implement → gate | Known scope, low risk |
| `standard` | plan → implement → review → gate | Default for features |
| `full` | architect → plan → plan review → implement → review → fix → gate | Complex features |

```bash
devflow build "Add caching layer" --workflow full
devflow fix "Fix timezone bug"    # uses quick automatically
```

### Cost-aware model routing

Each phase picks the cheapest Claude tier that fits the task. Resolution
order, first hit wins:

1. **YAML override** — set `model: opus` on any phase in a workflow `.yaml`.
2. **Artifact-aware selector** — inspects `gate.json` or `files.json` and
   downgrades when the work is trivial.
3. **Per-phase default** — sensible Opus/Sonnet baseline.

| Phase | Default | Downgrade rule |
|-------|---------|----------------|
| `architecture`, `planning` | Opus | — |
| `reviewing` | Opus | → **Sonnet** if diff < 50 lines and no critical path touched |
| `fixing` | Sonnet | → **Haiku** if `gate.json` only fails on ruff/biome/pint/secrets |
| `plan_review`, `implementing` | Sonnet | — |
| `gate` | (local) | No Claude involved — ruff/pytest/secrets in parallel |

Critical paths (`auth`, `secret`, `token`, `crypto`, `payment`, `billing`, `password`) never trigger a reviewing downgrade. Combined with prompt caching and selective context injection, typical savings are **40-55% per feature** versus running everything on Opus.

### Automatic gate recovery

When the quality gate fails, devflow doesn't kill the build. It reroutes once through a focused fixing phase that receives the **structured** `gate.json` (ruff rule codes, pytest tracebacks, secret matches) instead of free-form text — so the fix is targeted, not guessed. After fixing, gate runs again; if it still fails, the feature moves to `FAILED` and you resume manually.

---

## State machine

Every feature follows a lifecycle with validated transitions:

```mermaid
stateDiagram-v2
    direction LR
    [*] --> pending
    pending --> planning : build
    pending --> implementing : fix

    planning --> plan_review
    plan_review --> implementing
    implementing --> reviewing
    reviewing --> fixing : issues
    reviewing --> gate : clean
    fixing --> gate
    gate --> done : pass
    gate --> fixing : fail
    done --> [*]

    note left of pending
      failed → retry from last phase
      blocked → waiting on user
    end note
```

Invalid transitions raise `InvalidTransition`. State persists to `.devflow/state.json` before every phase change (crash-safe via tmp + rename).

---

## Agents

9 specialized agents installed to `~/.claude/agents/`:

| | Agent | Role |
|-|-------|------|
| **Planning** | `architect` | System design, module boundaries, dependency graphs |
| | `planner` | Step-by-step plans with risk assessment |
| **Implementation** | `developer` | Base rules: git workflow, architecture, error handling |
| | `developer-python` | Pydantic v2, typing, pytest, crash-safe I/O |
| | `developer-typescript` | Strict types, Zod, ESM, discriminated unions |
| | `developer-php` | PHP 8.2+, Laravel patterns, Pest, PHPStan |
| | `developer-frontend` | React/Next.js, CSS modules, a11y, performance |
| **Quality** | `reviewer` | 5-pass review: plan, correctness, security, quality, tests |
| | `tester` | Quality gate, coverage analysis, edge case audit |

Each agent has deep behavioral instructions with code examples, anti-patterns, output formats, and constraints. Not generic prompts — real engineering standards.

---

## Skills

8 skills injected into prompts based on the phase. Skills encode discipline
(how the agent should behave) separately from role (agent .md files).

| Skill | Injected on | Purpose |
|-------|-------------|---------|
| **context-discipline** | every phase | Strict rules to prevent over-exploration and token waste |
| **planning-rigor** | planning, architecture | Rigorous plans with named files, tests, quality audit |
| **refactor-first** | reviewing | Refactor dirty code instead of shipping patches — scoped here where "patch or refactor?" is actually decided |
| **incremental-build** | implementing, fixing | Thin vertical slices, commit per step, verify-then-next |
| **tdd-discipline** | implementing, fixing | Tests alongside code, not after |
| **code-review** | reviewing, plan_review | 5-pass review catching patches and quality issues |
| **build** | devflow-specific | How the build loop orchestrates phases |
| **check** | devflow-specific | Quality gate checklist |

Skills per phase are kept narrow on purpose — each skill adds ~100 lines to the system prompt and fragments the prompt cache.

---

## Commands

| Command | Description |
|---------|-------------|
| `devflow doctor` | Check installation health (Python, Claude, gh, agents) |
| `devflow version` | Show devflow version |
| `devflow install` / `devflow update` | Sync agents and skills to `~/.claude/` |
| `devflow init` | Detect stack + initialize `.devflow/` |
| `devflow build "..."` | Build a feature (default: standard workflow) |
| `devflow build "feedback" --resume feat-001` | Resume with feedback on the plan |
| `devflow retry feat-001` | Retry the last failed phase without feedback |
| `devflow fix "..."` | Fix a bug (quick workflow) |
| `devflow check` | Run quality gate (ruff + pytest + secrets) |
| `devflow status` | Show all tracked features |
| `devflow status feat-001` | Show details for one feature |
| `devflow log` | Show feature history (status, duration, date) |
| `devflow log feat-001` | Detailed log for one feature with phase timings |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
