# Architecture

## Overview

devflow-ai is a Python CLI that orchestrates AI coding agents through a
disciplined, plan-first workflow. It provides what agents don't have
natively: persistent state, quality gates, cost tracking, and feedback
loops.

```
┌──────────────────────────────────────────────────────┐
│  CLI (cli.py)                                        │
│  Commands, flags, DI boot — zero business logic      │
├──────────────────────────────────────────────────────┤
│  Orchestration                                       │
│  Build loop, retry, review cycle, phase dispatch     │
├──────────────────────────────────────────────────────┤
│  Integrations                                        │
│  Backends (Claude, Pi), gate, git, Linear            │
├──────────────────────────────────────────────────────┤
│  Core                                                │
│  State machine, models, config, metrics, protocols   │
└──────────────────────────────────────────────────────┘

  UI (rendering, display, spinner) ──→ Core only
  Setup (install, doctor, init) ──→ Core only
```

Imports are strictly top-down. Enforced by `import-linter` — a violation
fails `make check`.

---

## Layers

### Core (`src/devflow/core/`)

Domain logic with zero external I/O. Everything here is testable
without mocks.

| Module | Responsibility |
|---|---|
| `models.py` | Feature, FeatureStatus, PhaseName, WorkflowState |
| `state_machine.py` | Valid transitions, FAILED recovery |
| `config.py` | DevflowConfig (YAML-backed), PiConfig, BudgetConfig, GateConfig |
| `workflow.py` | state.json persistence, atomic write, file lock |
| `backend.py` | Backend Protocol + ModelTier (FAST/STANDARD/THINKING) |
| `tracker.py` | IssueTracker Protocol |
| `stack.py` | StackPlugin Protocol |
| `registry.py` | Backend + tracker registry, entry_points discovery |
| `phases.py` | PhaseSpec registry (name, model, skills, context deps) |
| `phase_outputs.py` | ReviewOutput parser (structured verdict + issues) |
| `artifacts.py` | Phase artifact I/O (.devflow/\<feat-id\>/) |
| `history.py` | MetricsRecord v2 (per-phase JSONL), reader/writer |
| `kpis.py` | MetricsDashboard (cost, gate rate, time-to-PR, cache, budget) |
| `migrations.py` | Schema versioning for state.json, config.yaml, metrics.jsonl |
| `logging.py` | structlog setup (dev console / CI JSON) |
| `errors.py` | Typed error hierarchy (DevflowError subclasses) |
| `epics.py` | Epic parent/child hierarchy, progress aggregation |
| `complexity.py` | ComplexityScore model (4 dimensions → workflow selection) |
| `metrics.py` | PhaseMetrics, ToolUse, BuildTotals dataclasses |

### Orchestration (`src/devflow/orchestration/`)

The engine. Coordinates phases, retries, reviews, and finalization.

| Module | Responsibility |
|---|---|
| `build.py` | Entry points: `execute_build_loop()` (145 LOC orchestrator) |
| `planning.py` | Planning loop + plan metadata extraction |
| `execution.py` | Execution loop (implement → review → gate → fix) |
| `phase_handlers.py` | Post-phase dispatch (commit, gate panel, retry, double-review) |
| `finalize.py` | PR creation, metrics summary, cache warning |
| `retry.py` | Diff similarity check, anti-loop abort |
| `lifecycle.py` | Feature creation, resume, retry |
| `phase_exec.py` | Phase state transitions, tracker sync |
| `runner.py` | Backend bridge, prompt building, skill injection |
| `model_routing.py` | Model selection (config > complexity > default) |
| `review.py` | Review cycle (re-review after fixing) |
| `sync.py` | Post-merge cleanup (branches, worktrees, Linear) |
| `events.py` | BuildEventListener, BuildPrompter callbacks |

### Integrations (`src/devflow/integrations/`)

Bridges to external systems. Each integration can import `core/` only.

| Module | Responsibility |
|---|---|
| `claude/backend.py` | ClaudeCodeBackend — subprocess `claude -p`, stream-json parsing |
| `pi/backend.py` | PiBackend — subprocess `pi -p --mode json`, JSONL parsing |
| `complexity.py` | LLM scorer (Haiku one-shot) + fallback heuristic |
| `detect.py` | StackPlugin implementations (Python, TS, PHP, Frontend) |
| `gate/` | Quality gate: parallel checks, secrets scan, complexity, module size |
| `git/` | Repo ops, smart commit messages, PR body generation |
| `linear/` | GraphQL client + IssueTracker adapter + bidirectional sync |

### UI (`src/devflow/ui/`)

Rich rendering. Imports `core/` only.

| Module | Responsibility |
|---|---|
| `rendering.py` | Banners, phase chips, summary panels, plan confirmation |
| `display.py` | Status tables, feature detail, metrics dashboard |
| `gate_panel.py` | Gate check result rendering |
| `spinner.py` | Live spinner during phase execution |

### Setup (`src/devflow/setup/`)

Installation and diagnostics. Imports `core/` only.

| Module | Responsibility |
|---|---|
| `init.py` | Interactive project wizard (`devflow init`) |
| `install.py` | Asset sync to `~/.claude/` |
| `doctor.py` | Health checks + `--fix` auto-repair |

---

## Protocols (extension points)

All extension points are `@runtime_checkable` Protocols in `core/`.

### Backend Protocol

```python
class Backend(Protocol):
    @property
    def name(self) -> str: ...
    def model_name(self, tier: ModelTier) -> str: ...
    def execute(self, *, system_prompt, user_prompt, model, timeout, cwd, env, on_tool) -> tuple[bool, str, PhaseMetrics]: ...
    def one_shot(self, *, system, user, model, timeout) -> str | None: ...
    def check_available(self) -> tuple[bool, str]: ...
```

Built-in: `ClaudeCodeBackend`, `PiBackend`. Both are subprocess wrappers
that parse streaming output (stream-json for Claude, JSONL for Pi).

Adding a backend: implement these 5 methods in one file, register in
`cli.py`. The contract test (`tests/contract/test_backend_contract.py`)
validates structural conformity.

### IssueTracker Protocol

```python
class IssueTracker(Protocol):
    @property
    def name(self) -> str: ...
    def check_available(self) -> tuple[bool, str]: ...
    def create_issue(self, *, title, description, parent_id=None) -> str: ...
    def update_status(self, *, issue_id, status) -> None: ...
    def link_pr(self, *, issue_id, pr_url) -> None: ...
```

Built-in: `LinearTracker`. External plugins discoverable via
`entry_points(group="devflow.trackers")`.

### StackPlugin Protocol

```python
class StackPlugin(Protocol):
    @property
    def name(self) -> str: ...
    def detect(self, project_root: Path) -> bool: ...
    def agent_name(self) -> str: ...
    def gate_commands(self) -> list[tuple[str, list[str]]]: ...
```

Built-in: Python, TypeScript, PHP, Frontend.

---

## State machine

```
pending → planning → plan_review → implementing → reviewing
       → fixing → gate → done
       → blocked (from any non-terminal)
       → failed  (recoverable via resume / retry)
```

Only DONE is terminal. FAILED can return to any non-terminal state.
Transitions are validated in `core/state_machine.py`.

---

## Feedback loops

### Gate retry with model escalation

When the quality gate fails:
1. Retry with the same model (attempt 1)
2. Escalate to STANDARD tier (attempt 2)
3. Escalate to THINKING tier (attempt 3)
4. If diff similarity > 95% between attempts → abort (anti-loop)

Each retry receives the previous attempt's diff and error output.

### Review cycle

After fixing:
1. Reviewer re-checks that its issues are resolved
2. If new issues found → another fix pass (max 2 cycles)
3. Structured output parsed — no vague "looks good" passes

### Double-review on critical paths

Files matching `double_review_on` glob patterns require two independent
APPROVE verdicts. Configured per-project.

---

## Data flow

### Build

```
User prompt
  → complexity scorer → workflow selection (quick/light/standard/full)
  → planning phase (agent + skills injection)
  → user approval
  → implementing (agent, auto-commit per step)
  → reviewing (structured output, parsed)
  → fixing (if REQUEST_CHANGES)
  → gate (parallel: lint + tests + secrets + complexity + module size)
  → retry loop (if gate fails, up to 3× with escalation)
  → PR creation (title + body from diff)
  → metrics append (per-phase JSONL)
```

### Artifacts

Each phase reads only its declared dependencies (`PHASE_CONTEXT_DEPS`
in `artifacts.py`). This keeps prompts small and stable for cache
efficiency.

```
.devflow/<feat-id>/
  planning.md        ← planning output
  reviewing.md       ← review output (raw)
  review.json        ← structured review (parsed verdict + issues)
  gate.json          ← gate report (checks passed/failed)
  files.json         ← diff summary (paths, lines, critical paths)
  gate_diff_N.txt    ← diff per retry attempt (for anti-loop)
```

### Metrics

Per-phase records in `.devflow/metrics.jsonl` (v2 format):

```json
{
  "version": 2,
  "feature_id": "feat-042",
  "phase": "implementing",
  "backend": "claude",
  "cost_usd": 0.12,
  "tokens": {"in": 12000, "out": 800, "cache_read": 8000, "cache_creation": 0},
  "model": "claude-sonnet-4-6",
  "outcome": "success"
}
```

---

## Tooling

| Tool | Purpose |
|---|---|
| `make check` | pytest + ruff + mypy + import-linter (one command, exit 0 = green) |
| `make test` | pytest with 80% coverage gate |
| `make lint` | ruff check |
| `make typecheck` | mypy strict on src/ |
| `make smoke` | Real agent execution (costs tokens) |
| `import-linter` | Layering enforcement (3 contracts) |
| `structlog` | Structured logging (dev console / CI JSON) |

---

## Configuration

```yaml
# .devflow/config.yaml — project config (stable across sessions)
version: 1
stack: python
base_branch: main
backend: claude                    # claude | pi

pi:
  models:
    fast: ollama/llama3.1:8b
    standard: anthropic/sonnet
    thinking: anthropic/opus

gate:
  lint: make lint
  test: make test
  diff_min_threshold: 0.95

double_review_on:
  - "src/auth/**"

budget:
  per_feature_usd: 0.50

tracker:
  name: linear
  linear:
    team: TEAM-ID
```

State (features, phases, metadata) is kept separately in
`.devflow/state.json` — changes every phase, crash-safe via atomic
write + file lock.
