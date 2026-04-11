# devflow-ai

> CLI that installs and orchestrates an AI development environment for Claude Code.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org)

devflow-ai doesn't reinvent Claude Code — it provides what Claude Code can't do natively: **persistent state**, **state machine**, **project tracking**, and **automated quality gates**.

## What it does

```
You describe a feature
    → devflow creates a tracked feature with a state machine
    → specialized agents (planner, developer, reviewer, tester) execute each phase
    → state persists in .devflow/state.json (crash-safe, resumable)
    → quality gate runs automatically (lint, tests, secrets scan)
    → feature marked done only when gate passes
```

## Quickstart

```bash
# Install
pip install devflow-ai  # or: uv add devflow-ai

# Set up agents and skills in ~/.claude/
devflow install

# Initialize in your project
devflow init

# Build a feature end-to-end
devflow build "Add user authentication"

# Fix a bug (lightweight workflow, no planning)
devflow fix "Login fails on empty password"

# Check quality gate manually
devflow check

# See what's in progress
devflow status
```

## Architecture

```
                    YOU
                     │
                     ▼
               ┌───────────┐
               │  devflow   │  CLI (Typer)
               │   cli.py   │  zero business logic
               └─────┬──────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ build.py │ │ track.py │ │ gate.py  │
   │orchestr. │ │  state   │ │ quality  │
   └────┬─────┘ └────┬─────┘ └──────────┘
        │             │
        ▼             ▼
   ┌──────────┐ ┌──────────────┐
   │workflow.py│ │.devflow/     │
   │YAML+state│ │ state.json   │
   └────┬─────┘ └──────────────┘
        │
        ▼
   ┌──────────┐
   │models.py │  Pydantic types
   │state     │  + state machine
   │machine   │
   └──────────┘

   ~/.claude/agents/  ← devflow install
   ~/.claude/skills/  ← syncs from assets/
```

### The fundamental split

| Lives in Python | Lives in .md files |
|---|---|
| State persistence (state.json) | Agent behavior (how to plan, code, review) |
| State machine (validated transitions) | Skills (build workflow, GSD, RTK) |
| Quality gate (lint, tests, secrets) | Checklists and conventions |
| Multi-feature tracking | Context management rules |
| `devflow install` (file sync) | — |

Python handles what **must be programmatic** (state, validation, automation).
Markdown handles what **must be flexible** (behavior, instructions, prompts).

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
devflow fix "Fix timezone bug"  # uses quick automatically
```

## Agents

9 specialized agents installed to `~/.claude/agents/`:

| Agent | Role |
|-------|------|
| **architect** | System design, module boundaries, dependency graphs |
| **planner** | Step-by-step implementation plans with risk assessment |
| **developer** | Base rules: git workflow, architecture, error handling |
| **developer-python** | Pydantic v2, typing, pytest, crash-safe I/O |
| **developer-typescript** | Strict types, Zod, ESM, discriminated unions |
| **developer-php** | PHP 8.2+, Laravel patterns, Pest, PHPStan |
| **developer-frontend** | React/Next.js, CSS modules, a11y, performance |
| **reviewer** | 5-pass code review (plan, correctness, security, quality, tests) |
| **tester** | Quality gate, coverage analysis, edge case audit |

Each agent has deep behavioral instructions: code examples, anti-patterns,
output formats, and constraints. Not generic prompts — real engineering standards.

## State machine

Every feature follows a lifecycle with validated transitions:

```
pending → planning → plan_review → implementing → reviewing
       → fixing → gate → done

Any state → blocked  (question needs answering)
Any state → failed   (terminal)
```

Invalid transitions raise `InvalidTransition`. State persists to
`.devflow/state.json` before every phase change (crash-safe via tmp + rename).

## Skills

4 skills installed to `~/.claude/skills/`:

| Skill | Purpose |
|-------|---------|
| **build** | Orchestrates the feature build loop through the state machine |
| **check** | Quality gate checklist (automated + behavioral) |
| **gsd** | Fresh context per phase, atomic commits, verify-after-change |
| **rtk** | Token compression: targeted reads, filtered output, skip known-good |

## Commands

| Command | Description |
|---------|-------------|
| `devflow install` | Sync agents and skills to `~/.claude/` |
| `devflow update` | Update agents and skills to latest |
| `devflow init` | Initialize `.devflow/` in current project |
| `devflow build "..."` | Build a feature (default: standard workflow) |
| `devflow build --resume feat-001` | Resume a feature |
| `devflow fix "..."` | Fix a bug (quick workflow) |
| `devflow check` | Run quality gate (ruff + pytest + secrets) |
| `devflow status` | Show all tracked features |
| `devflow status feat-001` | Show details for one feature |

## Project structure

```
devflow-ai/
├── src/devflow/
│   ├── cli.py        — Typer commands, zero logic
│   ├── models.py     — Pydantic types + state machine
│   ├── workflow.py   — YAML loading, state persistence
│   ├── build.py      — Build/fix orchestration
│   ├── track.py      — Feature state read/write
│   ├── gate.py       — Quality gate (ruff, pytest, secrets)
│   ├── install.py    — Sync assets to ~/.claude/
│   └── display.py    — Rich display components
├── assets/
│   ├── agents/       — 9 agent definitions (.md)
│   └── skills/       — 4 skill definitions (.md)
├── workflows/        — 4 YAML workflow definitions
├── tests/            — 71 tests
└── pyproject.toml
```

## Inspired by

- **[Everything Claude Code](https://github.com/anthropics/everything-claude-code)** — agents as .md files, skills composable, continuous learning
- **[AWF](https://github.com/awf-project/cli)** — chained phases with context injection, externalized prompts
- **GSD** — fresh context per phase, no context rot
- **RTK** — token compression for agent operations

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
