# devflow-ai — CLAUDE.md

## Ce qu'est devflow-ai

CLI Python qui orchestre un environnement de développement IA
pour agents de code (Claude Code par défaut, extensible via Backend Protocol).
Il fournit ce que les agents ne font pas nativement : persistance d'état,
state machine, quality gate automatisée, PR automatique, reprise après
échec, tracking coût et usage, boucles de rétroaction autonomes.

## Architecture — ligne de partage fondamentale

    ~/.claude/skills/   → la discipline — règles de comportement par phase
    ~/.claude/agents/   → les rôles — specialisés par techno
    src/devflow/        → le moteur    — état, orchestration, gate, PR

### Ce qui vit dans les .md (skills + agents)

**Skills de discipline (injectés dans le prompt par phase)** :
- context-discipline — règles anti sur-exploration, toujours injecté
- planning-rigor     — plans rigoureux avec audit qualité
- refactor-first     — refactor plutôt que patch
- incremental-build  — slices verticales, commit par step
- tdd-discipline     — tests pendant, pas après
- code-review        — review en 5 passes

**Skills devflow-specific** :
- build.md — décrit le flow de build devflow
- check.md — checklist du quality gate

**Agents spécialisés** :
- architect, planner, reviewer, tester (rôles)
- developer (base) + developer-python / -typescript / -php / -frontend

### Ce qui vit dans le Python (irremplaçable)

- `config.yaml` — configuration projet (stack, gate, linear, backend)
- `state.json` — état runtime des features, crash-safe (tmp + rename)
- `backend.py` — Protocol abstrait pour les agents IA (Claude, Gemini, etc.)
- State machine — transitions validées, recoverable depuis FAILED
- Quality gate — lint, tests, secrets, complexité, taille modules
- Boucles de rétroaction — gate retry (3×, escalade modèle), review cycle (2×)
- `runner.py` — bridge vers le backend avec prompt structuré et live progress
- `smart_messages.py` — commit/PR messages générés par le backend (one-shot)
- `git.py` — branch, atomic commits, PR via `gh`
- `detect.py` — détection stack pour sélectionner l'agent spécialisé

## Trois tiers d'exécution

    devflow do "..."    → branche courante, pas de PR, revert si gate fail
    devflow build "..." → nouvelle branche + PR, workflow auto-détecté
    devflow epic "..."  → (à venir) décomposition en sub-features

`do` et `build` utilisent le même moteur (mêmes phases, même gate,
mêmes agents). Seule différence : `do` reste sur la branche courante
et ne crée pas de PR. Le workflow (quick/light/standard/full) est
auto-sélectionné par le complexity scorer dans les deux cas.

## Flow de build (plan-first)

1. Création feature + branche git (`build`) ou pas (`do`)
2. Titre généré par le backend (one-shot, fast tier) si prompt long
3. Phase planning → affiche le plan dans un panel Rich
4. L'utilisateur valide (`y`) ou donne du feedback (`n` puis `--resume`)
5. Phases suivantes exécutent silencieusement, output live (tools + tokens)
6. Auto-commit après implementing/fixing (messages générés par le backend)
7. Gate locale (lint/tests/secrets + checks structurels)
8. Boucle retry si gate fail (3× avec escalade de modèle)
9. PR créée via `gh` (titre + body générés par le backend)

## Boucles de rétroaction

- **Gate → fix → gate** : 3 retries max avec escalade de modèle.
  Chaque retry reçoit le diff et les erreurs des tentatives précédentes.
- **Review → fix → re-review** : max 2 cycles. Le reviewer re-vérifie
  que ses issues sont résolues après fixing.

## Tests + lint (quality gate)

Une seule commande pour savoir si le repo est vert :

    make check       # = make test + make lint + make typecheck, exit 0 si vert
    make test        # pytest (unit + e2e, smoke deselected) avec --cov-fail-under=80
    make lint        # ruff check src/ tests/
    make typecheck   # mypy src/
    make fix         # ruff --fix
    make coverage    # rapport HTML (htmlcov/index.html)
    make smoke       # smoke tests (vrai claude -p, coûte des tokens)

Ne pas multiplier les variantes (`pytest tests/unit -v`, `pytest tests/e2e`, etc.) :
pyproject.toml configure déjà `testpaths` et `-m "not smoke"`.

**Smoke tests** : exécutent le pipeline réel avec `claude -p`. Lancer
manuellement avant chaque release ou avant un merge important :

    make smoke    # nécessite ANTHROPIC_API_KEY ou claude CLI authentifié

Coût indicatif : ~3 features × 1-5 min × ~$0.05-0.20 par run.

## Commandes

    devflow do "..."                 → tâche sur la branche courante (revert si fail)
    devflow build "..."              → build plan-first avec PR
    devflow build "feedback" --resume feat-001  → reprendre avec feedback
    devflow build --retry feat-001   → relancer la dernière phase failed
    devflow check                    → quality gate locale
    devflow status [feat-001]        → état courant (+ --log, --metrics, --archived)
    devflow sync [--dry-run]         → post-merge cleanup (+ --linear pour Linear)
    devflow install                  → install assets + init + diagnostic (+ --check, --linear-team)
    devflow --version                → version

## Structure des fichiers

    devflow-ai/
    ├── src/devflow/
    │   ├── cli.py                      — commandes Typer, zéro logique métier
    │   ├── core/                       — état & domaine
    │   │   ├── config.py               — DevflowConfig (Pydantic) + load/save config.yaml
    │   │   ├── backend.py              — Backend Protocol + ModelTier + registry
    │   │   ├── models.py               — Feature, PhaseName, PhaseStatus, WorkflowState
    │   │   ├── phases.py               — registry unifié (PhaseSpec + PHASES)
    │   │   ├── metrics.py              — DTOs PhaseMetrics / ToolUse
    │   │   ├── history.py              — BuildMetrics + persistence JSONL
    │   │   ├── workflow.py             — chargement YAML + persistance state.json
    │   │   ├── track.py                — lecture/écriture state (haut niveau)
    │   │   └── artifacts.py            — I/O atomique sur .devflow/<feat-id>/
    │   ├── orchestration/              — le moteur
    │   │   ├── build.py                — build loop + do loop + boucles retry/review
    │   │   ├── lifecycle.py            — création/resume/retry features
    │   │   ├── phase_exec.py           — state machine des phases + gate retry
    │   │   ├── runner.py               — bridge backend + build_prompt
    │   │   ├── model_routing.py        — routing modèle (YAML > sélecteur > défaut)
    │   │   └── stream.py               — parser stream-json
    │   ├── integrations/               — ponts vers l'extérieur
    │   │   ├── claude/                 — ClaudeCodeBackend (implémente Backend Protocol)
    │   │   ├── gate/                   — quality gate (lint, test, secrets, complexité, taille)
    │   │   ├── git/                    — branch, commit, PR, smart_messages
    │   │   ├── linear/                 — client GraphQL + sync bidirectionnel
    │   │   └── detect.py               — détection stack
    │   ├── setup/
    │   │   ├── install.py              — sync assets vers ~/.claude/
    │   │   └── doctor.py               — checks de santé
    │   └── ui/
    │       ├── display.py              — composants Rich (status, log, metrics)
    │       ├── rendering.py            — banner, phase chip, summary
    │       └── gate_panel.py           — affichage gate results
    ├── assets/
    │   ├── agents/                     — 9 agents (.md)
    │   └── skills/                     — 9 skills (.md)
    ├── workflows/                      — 4 YAML (quick / light / standard / full)
    ├── tests/                          — mirror de src/devflow/ (~740 tests)
    └── pyproject.toml

## Configuration (.devflow/)

    config.yaml  — configuration projet (stack, base_branch, gate, linear, backend)
    state.json   — état runtime des features uniquement
    <feat-id>/   — artefacts par feature (planning.md, gate.json, etc.)
    metrics.jsonl — historique des builds (coût, tokens, cache, durée)

## Artefacts par feature (.devflow/<feat-id>/)

    planning.md      — output de la phase planning
    reviewing.md     — output de la phase reviewing
    gate.md          — texte humain du gate (snapshot dernière run)
    gate.json        — rapport structuré du gate (checks passed/failed + details)
    files.json       — diff summary (lines_added, paths, critical_paths)

Chaque phase ne lit que les artefacts qu'elle déclare en dépendance
(cf. `PHASE_CONTEXT_DEPS` dans artifacts.py). Prompts user plus petits
et stables → prompt caching efficace. Gate.json alimente le router de
modèle (Haiku pour fixes triviaux) et le prompt structuré de `fixing`.

## State machine

    pending → planning → plan_review → implementing → reviewing
           → fixing → gate → done
           → blocked (depuis n'importe quel état non-terminal)
           → failed  (récupérable via resume / retry)

Seul DONE est terminal. FAILED peut revenir vers n'importe quel état
non-terminal pour retry.

## Features parallèles

Plusieurs features coexistent dans state.json avec leur état isolé.
--resume permet de switcher entre features sans perte d'état.

## Stack

Python 3.11+, Typer, Rich, Pydantic v2, PyYAML, pytest, ruff.
Dépendances CLI externes : `gh` (GitHub CLI), `uv`.
Backend par défaut : `claude` (Claude Code). Extensible via Backend Protocol.

## Principes de code

- Type hints partout, docstring sur les fonctions publiques
- Code en anglais, communication en français
- Un fichier = une responsabilité
- Tests écrits en même temps que le code
- Jamais de logique métier dans cli.py
- Conventional Commits pour les PR (feat: / fix:)
- Squash-merge sur main

**Pydantic vs dataclass** : `BaseModel` Pydantic pour tout modèle sérialisé
(Feature, WorkflowState, DevflowConfig, PhaseSpec) — validation + round-trip JSON/YAML.
`@dataclass` pour les DTO internes jamais persistés (PhaseMetrics, ToolUse,
BuildTotals, BuildMetrics, SyncResult, CheckResult).

**Config vs State** : `config.yaml` contient la configuration projet (stack,
gate, linear, backend) — stable entre les sessions. `state.json` contient
uniquement l'état runtime des features — change à chaque phase.
