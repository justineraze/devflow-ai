# devflow-ai — CLAUDE.md

## Ce qu'est devflow-ai

CLI Python qui orchestre des agents IA (Claude Code, Pi) pour des builds
plan-first avec quality gate, cost tracking et PR automatique. Deux backends
built-in, extensible via Backend Protocol. 1049 tests, mypy strict, layering enforced.

## Architecture

    cli.py              → commandes Typer, zéro logique métier
    orchestration/      → build loop, retry, review cycle, phase dispatch
    integrations/       → backends (Claude, Pi), gate, git, Linear
    core/               → state machine, models, config, metrics, protocols
    ui/                 → Rich rendering, dashboard, spinners
    setup/              → install, doctor, init wizard

Imports strictement top-down. Enforced par `import-linter` (3 contrats).
Détail complet : `docs/architecture.md`.

## Trois tiers d'exécution

    devflow do "..."                     → branche courante, pas de PR, revert si fail
    devflow build "..."                  → nouvelle branche + PR, workflow auto-détecté
    devflow build "..." --worktree       → feature isolée dans un git worktree

`do` et `build` utilisent le même moteur (mêmes phases, même gate, mêmes agents).
Le workflow (quick/light/standard/full) est auto-sélectionné par le complexity scorer.

## Flow de build

1. Création feature + branche git
2. Complexity scoring → workflow selection
3. Phase planning → plan affiché, user valide (`y`) ou feedback (`--resume`)
4. Implementing → auto-commit par step
5. Reviewing → output structuré parsé (Verdict + Blocking issues)
6. Fixing si REQUEST_CHANGES (max 2 cycles review→fix)
7. Gate parallèle (lint/tests/secrets + checks structurels)
8. Gate retry si fail (3× avec escalade modèle + diff-min anti-boucle)
9. PR créée via `gh` (titre + body générés par le backend)

## Backends

- **Claude Code** (défaut) : `claude -p` subprocess, stream-json parsing
- **Pi** : `pi -p --mode json` subprocess, JSONL parsing, 18+ providers

Config dans `.devflow/config.yaml` :

```yaml
backend: pi                         # claude | pi
pi:
  models:
    fast: ollama/llama3.1:8b
    standard: anthropic/sonnet
    thinking: anthropic/opus
```

## Quality gate

Gate parallèle : lint, tests, secrets, complexité, module size.
Auto-détection par stack ou custom dans config :

```yaml
gate:
  lint: make lint
  test: make test
  diff_min_threshold: 0.95          # abort retry si < 5% change
```

Double-review configurable sur paths critiques :

```yaml
double_review_on:
  - "src/auth/**"
```

## Tests + lint

    make check       # = make test + make lint + make typecheck + lint-imports
    make test        # pytest (unit + e2e, smoke deselected) avec --cov-fail-under=80
    make lint        # ruff check src/ tests/
    make typecheck   # mypy src/
    make fix         # ruff --fix
    make smoke       # smoke tests (vrai agent, coûte des tokens)

## Commandes

    devflow init                                 → wizard setup projet
    devflow build "description"                  → plan-first build avec PR
    devflow build "feedback" --resume feat-001   → reprendre avec feedback
    devflow build --retry feat-001               → relancer la dernière phase failed
    devflow build "task" --worktree              → build dans un worktree isolé
    devflow build "task" --backend pi            → utiliser Pi
    devflow do "description"                     → tâche sur la branche courante
    devflow check [--json]                       → quality gate locale
    devflow status [feat-001] [--json]           → état des features
    devflow metrics [--since 7d] [--export json] → dashboard coût/perf
    devflow sync [--dry-run]                     → post-merge cleanup
    devflow install                              → install assets
    devflow doctor [--fix]                       → diagnostic + auto-fix
    devflow --version                            → version

## Configuration (.devflow/)

    config.yaml   — configuration projet (versionné, stable)
    state.json    — état runtime des features (crash-safe, file lock)
    <feat-id>/    — artefacts par feature (planning.md, review.json, gate.json, files.json)
    metrics.jsonl — historique per-phase (coût, tokens, cache, durée, backend)
    hooks/        — scripts utilisateur (pre-build.sh, post-gate.sh, on-failure.sh)

## State machine

    pending → planning → plan_review → implementing → reviewing
           → fixing → gate → done
           → blocked (depuis n'importe quel état non-terminal)
           → failed  (récupérable via resume / retry)

## Protocols (extension points)

- **Backend** : 5 méthodes (name, model_name, execute, one_shot, check_available)
- **IssueTracker** : 5 méthodes (name, check_available, create_issue, update_status, link_pr)
- **StackPlugin** : 4 méthodes (name, detect, agent_name, gate_commands)

Tous `@runtime_checkable`. Contract tests dans `tests/contract/`.

## Stack technique

Python 3.11+, Typer, Rich, Pydantic v2, PyYAML, structlog, pytest, ruff, mypy.
Dépendances CLI externes : `gh` (GitHub CLI), `uv`.

## Principes de code

- Type hints partout, docstring une ligne max
- Code en anglais, communication en français
- Un fichier = une responsabilité
- Tests écrits en même temps que le code
- Jamais de logique métier dans cli.py
- Conventional Commits (feat: / fix: / refactor:)
- Pydantic pour les modèles sérialisés, dataclass pour les DTO internes
- Config (config.yaml) ≠ State (state.json) — jamais mélanger
