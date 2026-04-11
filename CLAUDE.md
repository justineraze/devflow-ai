# devflow-ai — CLAUDE.md

## Ce qu'est devflow-ai

CLI Python léger qui installe et orchestre un environnement de développement IA.
Il ne réinvente pas Claude Code — il fournit ce que Claude Code ne peut pas faire
nativement : persistance d'état, state machine, tracking projet, quality gate automatisée.

## Architecture — ligne de partage fondamentale

    ~/.claude/skills/   → le "comment" — comportement, workflow, règles
    ~/.claude/agents/   → les subagents spécialisés
    src/devflow/        → le "quoi"   — état, persistance, tracking, gates

### Ce qui vit dans les .md (skills + agents)

- build.md — ralph loop, orchestration des phases comme instructions comportementales
- gsd.md   — règles de contexte frais par phase
- rtk.md   — règles de compression tokens
- check.md — checklist comportementale pour les agents
- Les agents : planner, developer, reviewer, tester

### Ce qui vit dans le Python (irremplaçable)

- state.json — persistance entre sessions, crash-safe
- State machine — transitions validées entre phases
- Quality gate automatisée — lint, tests, détection secrets (pas juste comportemental)
- Tracking multi-features en parallèle
- devflow install — sync vers ~/.claude/agents/ et ~/.claude/skills/

## Commandes

    devflow install                  → sync agents + skills vers ~/.claude/
    devflow update                   → met à jour les composants
    devflow init                     → bootstrap projet local
    devflow build "..."              → lance le ralph loop via skill Claude Code
    devflow fix "..."                → corrige un bug, workflow allégé
    devflow check                    → quality gate automatisée Python
    devflow status                   → état des features en cours
    devflow build --resume feat-001  → reprend une feature en cours

## Structure des fichiers

    devflow-ai/
    ├── src/devflow/
    │   ├── cli.py        — commandes Typer, zéro logique métier
    │   ├── models.py     — Pydantic : Feature, WorkflowState, Phase...
    │   ├── workflow.py   — chargement YAML + validation transitions
    │   ├── track.py      — lecture/écriture .devflow/state.json
    │   ├── gate.py       — quality gate automatisée (lint, tests, secrets)
    │   ├── install.py    — sync assets vers ~/.claude/
    │   └── display.py    — composants Rich centralisés
    ├── assets/
    │   ├── agents/       — subagent definitions (.md)
    │   └── skills/       — skill definitions (.md)
    ├── workflows/        — YAML workflow definitions
    ├── tests/
    └── pyproject.toml

## State machine — états d'une feature

    pending → planning → plan_review → implementing → reviewing
           → fixing → gate → done
           → blocked  (depuis n'importe quel état)
           → failed   (terminal)

Toute transition illégale lève InvalidTransition.
Chaque phase persiste son état dans .devflow/state.json avant de passer à la suivante.

## Features parallèles

Plusieurs features coexistent dans state.json avec chacune son état isolé.
--resume permet de switcher entre features sans perte d'état.

## Stack

Python 3.11+, Typer, Rich, Pydantic v2, PyYAML, pytest

## Principes de code

- Type hints partout, docstring sur les fonctions publiques
- Code en anglais, communication en français
- Un fichier = une responsabilité
- Tests écrits en même temps que le code
- Jamais de logique métier dans cli.py
