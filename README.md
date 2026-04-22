# devflow-ai

> State machine, quality gate, and cost tracking for Claude Code.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml/badge.svg)](https://github.com/justineraze/devflow-ai/actions/workflows/lint-test.yml)

---

## The problem

Claude Code is powerful but stateless. You re-explain context every session, manually run quality checks, and have no idea what anything costs. If the agent crashes mid-feature, you start over.

## What devflow does

- **Persistent state machine** — features track their phase (planning, implementing, reviewing, gate). Crash mid-build? `--resume` picks up where you left off.
- **Plan-first flow** — review the plan before any code is written. Reject with feedback to steer without losing context.
- **Automatic quality gate** — ruff, pytest, secrets scan run in parallel. Failures auto-retry with structured error context.
- **Cost tracking** — every phase logs model, cost, and cache hit rate.
- **Auto PR** — branch, atomic commits, and PR via `gh`.

---

## Demo

Real output from devflow building its own metrics feature:

```
$ devflow build "Add metrics display to status --metrics"

────────────────────────────────────────────────────────────────
Add metrics display to status --metrics
feat-add-devflow-metrics-0421  ·  python  ·  light  ·  3 phases
────────────────────────────────────────────────────────────────

▶ phase 1/3 · planning    opus
  ✓ planning   1m38s   23 tools   $0.35   cache 99%

╭─── Plan ─────────────────────────────────────────────────────╮
│ Scope: extension · low complexity · 4 steps                   │
│                                                               │
│ 1. Split render_metrics_table into 3 helpers:                 │
│    _render_last_build, _render_phase_averages,                │
│    _render_build_history                                      │
│ 2. Add tests (empty, single build, multiple builds)           │
│ 3. Formatting: color-code phases, sort by cost                │
│ 4. Run quality gate                                           │
╰───────────────────────────────────────────────────────────────╯
Lancer l'implémentation ? [Y/n] y

▶ phase 2/3 · implementing    sonnet
  ✓ implementing   2m49s   21 tools   $0.61   cache 99%

▶ phase 3/3 · gate
╭──────────────────  Gate — PASSED  ───────────────────────────╮
│   ✓  ruff      No issues                                     │
│   ✓  pytest    498 passed                                    │
│   ✓  secrets   clean                                         │
╰──────────────────────────────────────────────────────────────╯

╭──────────────────  Build complete  ──────────────────────────╮
│  Duration  4m33s                                             │
│      Cost  $0.96                                             │
│     Tools  44                                                │
│     Cache  99%                                               │
│                                                              │
│  ● planning  ● implementing  ● gate                          │
│  1m38s       2m49s           5s                              │
│                                                              │
│  🔗 https://github.com/justineraze/devflow-ai/pull/40        │
╰──────────────────────────────────────────────────────────────╯
```

Plan not right? Reject and resume with feedback:

```bash
devflow build "use a Rich panel instead of a table" --resume feat-add-devflow-metrics-0421
```

---

## Install

Requires Python 3.11+, [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`), and [GitHub CLI](https://cli.github.com/) (`gh`).

```bash
uv tool install devflow-ai
devflow install   # sync agents & skills to ~/.claude/
devflow doctor    # verify setup
```

---

## Commands

```
devflow build "description"                  Plan, implement, review, gate, PR
devflow build "feedback" --resume feat-001   Resume with feedback on the plan
devflow build "description" --base develop   Target a specific base branch
devflow fix "description"                    Quick fix (no planning phase)
devflow retry feat-001                       Retry from the last failed phase
devflow check                                Run quality gate locally
devflow status [feat-001]                    Show tracked features
devflow status --metrics                     Build cost and cache history
devflow log [feat-001]                       Phase history with timings
devflow sync                                 Post-merge cleanup
devflow install                              Install/update agents & skills
devflow init                                 Detect stack, initialize project
devflow doctor                               Check installation health
```

---

## License

MIT — see [LICENSE](LICENSE).
