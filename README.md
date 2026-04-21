# devflow-ai

> State machine, quality gate, and cost tracking for Claude Code.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## The problem

Claude Code is stateless. Every session starts from scratch — no memory of what phase you're in, no automated checks, no cost visibility. You manage the process instead of reviewing the output.

## What devflow does

- **Persistent state machine** — features track their phase (planning, implementing, reviewing, gate). Crash mid-build? Resume where you left off.
- **Plan-first flow** — review and approve the plan before any code is written. Reject with feedback to steer without losing context.
- **Automatic quality gate** — ruff, pytest, secrets scan run in parallel. Failures trigger a targeted fix attempt with structured error context before surfacing to you.
- **Cost and token tracking** — every phase logs model, tokens, cache hits, and cost. You see what you're spending.
- **Auto PR** — branch, atomic commits, and PR via `gh`, with the plan as description.

---

## Demo

```
$ devflow build "Add caching layer"

────────────────────────────────────────────────────────────────────
Add caching layer
feat-add-caching-layer-0414  ·  python  ·  standard  ·  4 phases
────────────────────────────────────────────────────────────────────

▶ phase 1/4 · planning    opus
  ✓ planning   55s   2 tools   $0.25

╭─── Plan ─────────────────────────────────────────────────────────╮
│ 1. Create src/cache.py with Cache class                          │
│ 2. Add TTL-based expiry                                          │
│ 3. Wire into request handler                                     │
│ ...                                                              │
╰──────────────────────────────────────────────────────────────────╯
Lancer l'implémentation ? [Y/n] y

▶ phase 2/4 · implementing    sonnet
  ✓ implementing   2m34s   8 tools   $0.18

▶ phase 3/4 · reviewing    sonnet
  ✓ reviewing   48s   1 tool   $0.21

▶ phase 4/4 · gate
╭──────────────────  Gate — PASSED  ───────────────────────────────╮
│   ✓  ruff      No issues                                         │
│   ✓  pytest    174 passed                                        │
│   ✓  secrets   clean                                             │
╰��─────────────────────────────────────────────────────────────────╯

╭──────────────────  Build complete  ──────────────────────────────╮
│  Duration  4m18s                                                 │
│      Cost  $0.64                                                 │
│  🔗 https://github.com/you/repo/pull/42                          │
╰──────────────────────────────────────────────────────────────────╯
```

Resume with feedback if the plan needs work:

```bash
devflow build "use Redis instead of in-memory" --resume feat-add-caching-layer-0414
```

---

## Install

Requires Python 3.11+, [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` CLI), and [GitHub CLI](https://cli.github.com/) (`gh`).

```bash
uv tool install devflow-ai
devflow install   # sync agents & skills to ~/.claude/
devflow doctor    # verify setup
```

---

## Commands

```
devflow build "description"                  Build a feature (plan → implement → review → gate → PR)
devflow build "feedback" --resume feat-001   Resume with feedback on the plan
devflow fix "description"                    Quick fix (implement → gate, no planning)
devflow retry feat-001                       Retry from the last failed phase
devflow check                                Run quality gate locally
devflow status [feat-001]                    Show tracked features
devflow status --metrics                     Show build cost/token history
devflow log [feat-001]                       Phase history with timings
devflow sync                                 Post-merge cleanup (switch main, prune branches)
devflow install                              Install/update agents & skills
devflow doctor                               Check installation health
devflow init                                 Detect stack, initialize .devflow/
```

---

## License

MIT — see [LICENSE](LICENSE).
