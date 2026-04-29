# Sprint DX v2 — Robustesse + Rendu terminal utile

## Contexte

devflow-ai v0.2.0 fonctionne mais le terminal output ne donne pas envie
de s'en servir. Session du 2026-04-29 : une tentative de refonte UI a été
revertée — trop de changements d'un coup, pas assez réfléchi sur ce qui
compte vraiment. Ce prompt cadre la reprise.

Inspiration : Archon (https://archon.diy, https://github.com/coleam00/Archon)
fait bien le streaming live des actions agent. On ne copie pas leur archi
(DAG/YAML), on s'inspire uniquement du feedback temps réel.

## Problèmes concrets

1. `devflow doctor` crash — "No backend registered" (pas de `_ensure_backend()`)
2. La commande `fix` est deprecated mais toujours visible dans `--help`
3. Le spinner pendant les builds montre UNE ligne sans timer — quand l'agent
   pense 5 min on ne sait pas si c'est bloqué
4. Les bilans de phase sont génériques — pas de données propres à chaque type
5. `devflow status` est une Rich Table à 7 colonnes illisible sur un terminal normal
6. `devflow metrics` est un data dump, pas de l'info actionnable
7. Les couleurs sont hardcodées ("cyan", "dim") au lieu d'utiliser le theme Nord
8. Les builds triviaux (`devflow do "add a comment"`) prennent 5-10 min —
   probablement un prompt trop lourd pour le workflow quick

## Tâches par ordre

### 1. Fix `devflow doctor`

`cli.py:855` doctor_cmd → `run_doctor()` → `get_backend()` crash.
Fix : appeler `_ensure_backend()` dans doctor_cmd avant run_doctor(),
avec try/except RuntimeError pour afficher un check "backend: ✗ not configured"
au lieu de crasher.

Fichiers : `src/devflow/cli.py`, `src/devflow/setup/doctor.py`

### 2. Supprimer `fix` et `retry` (deprecated)

- `cli.py:771-794` : supprimer le command handler `fix`
- `cli.py:797+` : supprimer `retry_cmd` (deprecated+hidden)
- Supprimer `start_fix` dans `orchestration/lifecycle.py` si plus référencé
- Nettoyer les tests qui référencent ces commandes
- Vérifier avec grep qu'aucun code n'appelle ces fonctions

### 3. Diagnostic lenteur builds

Investiguer pourquoi un `devflow do "add a comment"` prend 5-10 min :

- Lire `orchestration/runner.py` : `build_system_prompt()` + `build_user_prompt()`
- Lire les fichiers .md chargés : `assets/agents/`, `assets/skills/`,
  `~/.claude/agents/`, `~/.claude/skills/`
- Calculer la taille totale du prompt pour un quick workflow
- Vérifier que le complexity scorer choisit bien "quick"
- Si le prompt est trop lourd : réduire le system prompt pour quick
  (moins de skills, instructions plus courtes)

### 4. Theme Nord cohérent

`src/devflow/ui/theme.py` (85 lignes, non tracké) définit des tokens.
Les renderers utilisent encore des styles hardcodés.

Migrer TOUS les renderers pour utiliser les tokens :
- `rendering.py` : remplacer "cyan", "dim", "green bold", "yellow" etc.
- `display.py` : idem
- `gate_panel.py` : idem
- `spinner.py` : idem

Ajouter `theme.py` au git tracking.

### 5. Spinner avec timer

Le PhaseSpinner actuel (`spinner.py`, 84 lignes) = une ligne sans timer.

Nouveau comportement :
```
⠹ 1:23  implementing · Read  ui/theme.py
```

- Spinner animé (Rich Spinner "dots", 8fps) — ça c'est déjà le cas
- Timer monotonic qui monte en temps réel — À AJOUTER
- Phase name + dernière action agent
- Quand pas de tool event : `⠹ 1:23  implementing · thinking…`
- PAS d'historique empilé, juste la ligne courante qui se met à jour
- Utiliser les tokens du theme

### 6. Bilans de phase enrichis

Après chaque phase, afficher des données propres au type de phase :

- **planning** : nombre de steps dans le plan, fichiers ciblés
  (parser le plan output pour extraire ces infos)
- **implementing** : fichiers changés, +insertions/-deletions, commits
  (déjà dispo dans PhaseResult — les afficher systématiquement)
- **reviewing** : verdict, blocking issues count
  (parser le review output)
- **gate** : checks inline directement sous le bilan
  ```
  ✓ gate  6s · 3/3 passed
    ✓ ruff  ✓ pytest  ✓ secrets
  ```
  PAS dans un Panel séparé — des lignes simples
- **fixing** : gate retry count, fichiers re-touchés

Les données existent dans PhaseMetrics, PhaseResult, GateReport.
Le gate_panel.py actuel (93 lignes) utilise un Rich Panel → le remplacer
par des lignes inline.

### 7. `devflow status` utile

Remplacer la Rich Table 7 colonnes par une ligne par feature :
```
  feat-add-retry-0429     done   standard  1m29s  $0.28  2h ago
  feat-fix-structlog-0428 done   quick       42s  $0.71  yesterday

  3 features · 2 done · 1 failed · total $1.58
```

Garder le mode détail (`devflow status <id>`) pour les phases.
Garder le `--json` mode tel quel.

### 8. `devflow metrics` actionnable

Remplacer le Panel actuel par des insights :
```
  7 builds · $4.20 · 85% gate first-try · median 2m12s to PR

  most expensive   feat-add-tests-0422     $2.90 (69%)
  slowest          feat-add-verbose-0428   9m49s

  by phase    implementing 52%  reviewing 28%  planning 15%  gate 5%
  by model    sonnet $3.80  opus $0.40
  cache       94% avg
```

## Contraintes

- Tests écrits en même temps que le code
- mypy strict, ruff clean, `make check` vert
- Pas de Rich Panel/Table pour les rendus inline — du Text + couleurs du theme
- Garder Rich Table uniquement si vraiment tabulaire (status detail)
- Pas de features en plus — améliorer l'existant
- Tester manuellement avec `devflow do` et `devflow status` avant de valider
- Ne JAMAIS commit sans demander explicitement
- Code en anglais, communication en français

## Fichiers clés

```
src/devflow/cli.py                    — commands + wiring callbacks (893 lignes)
src/devflow/ui/spinner.py             — PhaseSpinner (84 lignes)
src/devflow/ui/rendering.py           — phase headers/success/commits/summary (555 lignes)
src/devflow/ui/display.py             — status/metrics/log (650 lignes)
src/devflow/ui/gate_panel.py          — gate report rendering (93 lignes)
src/devflow/ui/theme.py               — Nord tokens (85 lignes, NON TRACKÉ)
src/devflow/setup/doctor.py           — doctor checks (342 lignes)
src/devflow/orchestration/runner.py   — prompt building + phase execution
src/devflow/orchestration/events.py   — BuildCallbacks, PhaseToolListenerFactory
src/devflow/core/metrics.py           — PhaseMetrics, BuildTotals, PhaseResult
src/devflow/core/formatting.py        — format_cost, format_duration, tool_icon
tests/unit/ui/                        — tests UI (spinner, rendering, display, gate)
tests/unit/test_cli.py                — tests CLI
```
