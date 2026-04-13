# devflow-ai — CLAUDE.md

## Ce qu'est devflow-ai

CLI Python qui installe et orchestre un environnement de développement IA
pour Claude Code. Il ne réinvente pas Claude Code — il fournit ce que Claude
Code ne peut pas faire nativement : persistance d'état, state machine,
tracking projet, quality gate automatisée, PR automatique, reprise après
échec, affichage live du coût et de l'usage.

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

- `state.json` — persistance entre sessions, crash-safe (tmp + rename)
- State machine — transitions validées, recoverable depuis FAILED
- Quality gate — lint, tests, détection secrets (pas juste comportemental)
- Multi-features parallèles dans le même state
- `runner.py` — bridge vers `claude -p` avec prompt structuré et live progress
- `git.py` — branch, atomic commits, PR via `gh`
- `detect.py` — détection stack pour sélectionner l'agent spécialisé
- `devflow install` — sync assets vers ~/.claude/

## Flow de build (plan-first)

1. `devflow build "..."` crée une feature + branche git
2. Phase planning → affiche le plan dans un panel Rich
3. L'utilisateur valide (`y`) ou donne du feedback (`n` puis `--resume`)
4. Phases suivantes exécutent silencieusement, output live (tools + tokens)
5. Auto-commit après implementing/fixing
6. Gate locale (ruff/pytest/secrets)
7. PR créée automatiquement via `gh` avec plan en description

## Commandes

    devflow doctor                   → diagnostic de l'installation
    devflow install / update         → sync agents + skills
    devflow init                     → détection stack + bootstrap projet
    devflow build "..."              → build plan-first
    devflow build "feedback" --resume feat-001  → reprendre avec feedback
    devflow retry feat-001           → relancer la dernière phase failed
    devflow fix "..."                → workflow quick (implement + gate)
    devflow check                    → quality gate locale
    devflow status [--json] [feat-001]  → état courant
    devflow log [feat-001]           → historique avec durées

## Structure des fichiers

    devflow-ai/
    ├── src/devflow/
    │   ├── cli.py        — commandes Typer, zéro logique métier
    │   ├── models.py     — Pydantic : Feature, WorkflowState, Phase...
    │   ├── workflow.py   — chargement YAML + validation transitions
    │   ├── build.py      — orchestration plan-first + confirmation loop
    │   ├── runner.py     — bridge claude -p + build_prompt + skills inject
    │   ├── stream.py     — parser stream-json pour le live progress
    │   ├── git.py        — branch, commit, PR via gh
    │   ├── track.py      — lecture/écriture .devflow/state.json
    │   ├── gate.py       — quality gate (ruff, pytest, secrets)
    │   ├── install.py    — sync assets vers ~/.claude/
    │   ├── detect.py     — détection stack du projet
    │   ├── doctor.py     — checks de santé (python, claude, gh, agents)
    │   └── display.py    — composants Rich (panels, tables, logs)
    ├── assets/
    │   ├── agents/       — 9 agents (.md)
    │   └── skills/       — 8 skills (.md)
    ├── workflows/        — 4 YAML (quick / light / standard / full)
    ├── tests/            — ~170 tests pytest
    └── pyproject.toml

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
Dépendances CLI externes : `claude` (Claude Code), `gh` (GitHub CLI), `uv`.

## Principes de code

- Type hints partout, docstring sur les fonctions publiques
- Code en anglais, communication en français
- Un fichier = une responsabilité
- Tests écrits en même temps que le code
- Jamais de logique métier dans cli.py
- Conventional Commits pour les PR (feat: / fix:)
- Squash-merge sur main
