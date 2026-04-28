# ADR-0001: Epic decomposition

## Status

Accepted (design only — implementation deferred, see Phase E of
`docs/refactor-2026-Q2.md`)

## Context

devflow-ai orchestre des builds plan-first feature par feature. En
pratique, certaines features sont trop larges pour un seul cycle
planning → implementing → gate : elles touchent plusieurs modules,
nécessitent des sous-étapes ordonnées, et font exploser le contexte
de l'agent.

Le besoin immédiat ("lancer 2 features en parallèle") est couvert
par les **worktrees per feature** (Phase B). Le système d'epic — qui
décompose automatiquement une feature en sous-features, les exécute
en parallèle dans des worktrees isolés, puis les merge avec un gate
global — n'a pas encore de use case réel validé.

Ce document capture le design cible pour qu'il soit implémentable
sans ambiguïté le jour où un trigger est réuni (cf. §Triggers).

### Infra existante

Le code supporte déjà la notion d'epic comme conteneur :

- `core/epics.py` : `create_epic()`, `add_sub_feature()`,
  `check_epic_completion()`, `epic_progress()` — crée un graphe
  parent/enfant dans state.json
- `core/models.py` : `Feature.parent_id`, `WorkflowState.children_of()`,
  `WorkflowState.epics()`, `WorkflowState.is_epic()`
- `core/workflow.py` : `mutate_feature()` avec file lock (`fcntl`) —
  empêche les writes concurrents sur state.json
- `integrations/git/repo.py` : `create_worktree()`, `remove_worktree()`,
  `list_worktrees()` — crée des worktrees dans `.devflow/.worktrees/`

Ce design construit **sur** cette base, pas la réécrit.

## Decision

### 1. DAG de décomposition

La décomposition produit un **arbre avec dépendances optionnelles**
(DAG) — pas un arbre strict, pas un graphe libre.

```
epic-refactor-auth-0501
├── sub-extract-session-store       (deps: [])
├── sub-add-jwt-validation          (deps: [extract-session-store])
├── sub-update-middleware            (deps: [add-jwt-validation])
└── sub-migrate-tests               (deps: [])
```

Chaque sous-feature est un `Feature` normal avec `parent_id` pointant
vers l'epic. Les dépendances sont stockées dans
`Feature.metadata.epic_deps: list[str]` (IDs de sous-features dont
la complétion est requise avant démarrage).

**Règles du DAG** :
- Un noeud sans dépendances est immédiatement exécutable.
- Les cycles sont interdits — validés à la création (DFS topologique).
- La profondeur max est 1 (pas de sous-sous-features). Si une
  sous-feature est trop grosse, l'utilisateur la re-décompose
  manuellement en un nouvel epic.

**Persistance** : le DAG vit entièrement dans state.json via les
champs existants (`parent_id`) + le nouveau champ metadata
(`epic_deps`). Pas de fichier séparé.

### 2. Stratégie de prompt pour le planner-agent

La décomposition est un appel one-shot au planner-agent avec un
prompt structuré :

```
Tu es un architecte logiciel. Décompose cette feature en sous-features
indépendantes et parallélisables.

## Feature
{epic.description}

## Codebase context
{tree_summary}       — output de `find src/ -name '*.py' | head -60`
{relevant_files}     — fichiers mentionnés dans la description

## Contraintes
- Chaque sous-feature doit être implémentable en un seul cycle
  devflow (planning → implementing → gate)
- Minimise les dépendances entre sous-features
- 2-7 sous-features (si >7, regroupe)

## Format de sortie (JSON strict)
{
  "sub_features": [
    {
      "id_suffix": "extract-session-store",
      "description": "Extract session storage into dedicated module",
      "deps": [],
      "estimated_complexity": "light"
    }
  ]
}
```

**Validation utilisateur** : après la décomposition, devflow affiche
le DAG dans un panel Rich (arbre + dépendances + complexité estimée)
et demande confirmation (`y/n/edit`). `edit` ouvre `$EDITOR` sur le
JSON pour permettre l'ajout/suppression/réordonnancement de
sous-features.

**Modèle** : le planner-agent utilise le tier configuré pour la phase
`planning` (par défaut Sonnet). Pas d'escalade automatique — la
décomposition est un one-shot validé par l'humain.

### 3. Architecture worktree manager

Chaque sous-feature s'exécute dans son propre worktree, via l'infra
existante de `git/repo.py`.

**Cycle de vie** :

1. **Création** : quand une sous-feature passe à `IMPLEMENTING`,
   `create_worktree(sub_feature_id)` crée
   `.devflow/.worktrees/<sub-id>/` avec une branche
   `feat/<sub-slug>` depuis la base branch.

2. **Exécution** : le build loop standard s'exécute dans le worktree
   (planning → implementing → gate). Le `cwd` du backend est le
   worktree path. state.json est partagé (main repo) et protégé par
   `_state_lock`.

3. **Cleanup** : après merge dans l'integration branch (ou après
   abort), `remove_worktree(sub_feature_id)` supprime le worktree.
   Les branches locales sont supprimées si le merge a réussi.

**Concurrence** : les sous-features sans dépendances mutuelles
s'exécutent en parallèle (via `asyncio.gather` ou `ProcessPoolExecutor`
selon le backend). Le nombre de workers parallèles est configurable :
`epic.max_parallel_workers` dans config.yaml (défaut : 3).

**State.json** : les writes concurrents sont sérialisés par
`_state_lock` (file lock POSIX). Chaque worker fait
`mutate_feature()` pour update sa sous-feature — le lock garantit
l'atomicité.

### 4. Integration branch + gate global

Le merge des sous-features suit une stratégie séquentielle avec
gate global :

1. **Integration branch** : à la création de l'epic, une branche
   `epic/<slug>` est créée depuis la base branch. C'est la cible
   de merge de toutes les sous-features.

2. **Merge séquentiel** : chaque sous-feature terminée (gate vert)
   est mergée dans `epic/<slug>` par ordre topologique (dépendances
   d'abord). Le merge est un `git merge --no-ff` pour conserver
   l'historique. En cas de conflit, la sous-feature est marquée
   `BLOCKED` et l'utilisateur est notifié.

3. **Gate global** : après le merge de la dernière sous-feature,
   un gate complet s'exécute sur `epic/<slug>` (même gate que pour
   une feature normale : lint + tests + secrets + complexité). Ce
   gate vérifie que l'ensemble intégré est cohérent, pas seulement
   chaque partie isolée.

4. **PR finale** : si le gate global passe, une PR est créée de
   `epic/<slug>` vers la base branch. Le body de la PR liste les
   sous-features avec leur statut.

**Pourquoi merge séquentiel plutôt que parallèle** : les sous-features
peuvent toucher des fichiers adjacents. Le merge séquentiel en ordre
topologique détecte les conflits tôt et les résout un par un. Le coût
est négligeable (un merge git prend < 1s).

### 5. Politique resume / abort

**Resume après crash (kill -9)** :

L'état de chaque sous-feature est persisté dans state.json après
chaque transition de phase. Au redémarrage :

1. `load_state()` reconstruit l'état complet du DAG.
2. Les sous-features `IN_PROGRESS` au moment du crash sont marquées
   `FAILED` (leur dernière phase `IN_PROGRESS` est aussi failée).
3. `devflow build --resume <epic-id>` relance l'epic :
   - Les sous-features `DONE` sont ignorées.
   - Les sous-features `FAILED` sont retried (depuis la phase failée).
   - Les sous-features `PENDING` dont les deps sont satisfaites sont
     lancées.

**Resume avec feedback** : `devflow build "feedback" --resume <epic-id>`
permet de donner du feedback sur l'epic entière. Le feedback est
propagé à toutes les sous-features non-terminées via
`metadata.feedback`.

**Abort** :

`Ctrl-C` ou `devflow abort <epic-id>` :

1. Signale l'arrêt aux workers parallèles (cooperative cancellation
   via `asyncio.Event` ou threading `Event`).
2. Attend la fin des phases en cours (pas de kill brutal — le backend
   peut avoir des writes en cours).
3. Marque les sous-features non-terminées comme `BLOCKED`
   (reason: "epic aborted").
4. Nettoie tous les worktrees (`remove_worktree` pour chaque
   sous-feature).
5. L'epic elle-même passe en `FAILED`.
6. L'integration branch est conservée (pas de suppression automatique
   — l'utilisateur peut vouloir inspecter l'état partiel).

**Audit** : chaque transition est loguée via structlog avec le
contexte `epic_id` + `sub_feature_id` pour traçabilité.

### 6. Politique cost cap

Un budget par epic est configurable :

```yaml
# config.yaml
epic:
  max_parallel_workers: 3
  budget:
    per_epic_usd: 5.0
    on_cap_reached: confirm  # confirm | abort | warn
```

**Comportement selon `on_cap_reached`** :

- `confirm` (défaut) : pause l'exécution, affiche le coût courant
  et demande confirmation pour continuer. Les sous-features en cours
  finissent leur phase actuelle avant la pause.
- `abort` : arrête l'epic immédiatement (même flow que abort manuel).
- `warn` : log un warning structlog et continue.

**Tracking** : le coût est agrégé depuis `metrics.jsonl` (chaque
phase loggue déjà tokens/cost via `BuildMetrics`). L'agrégation se
fait sur les sous-features dont le `parent_id` matche l'epic.

**Vérification** : le coût est vérifié avant le lancement de chaque
nouvelle sous-feature (pas en continu pendant une phase — granularité
trop fine et overhead inutile).

### 7. Tests d'acceptance cibles

Ces scénarios devront passer quand l'implémentation sera faite :

**T1 — 3 sous-features parallèles → merge → gate vert**

Setup : epic avec 3 sous-features sans dépendances.
Action : `devflow epic "refactor auth module"`.
Attendu : les 3 sous-features s'exécutent en parallèle (worktrees
séparés), chacune passe son gate, merge séquentiel dans
`epic/<slug>`, gate global vert, PR créée.

**T2 — kill -9 mid-epic → resume → completion**

Setup : epic avec 3 sous-features, dont 1 en cours.
Action : `kill -9` pendant l'exécution, puis
`devflow build --resume <epic-id>`.
Attendu : la sous-feature interrompue reprend depuis sa dernière
phase persistée. Les sous-features déjà terminées ne sont pas
relancées. L'epic se complète normalement.

**T3 — abort clean → worktrees nettoyés, state cohérent**

Setup : epic avec 3 sous-features, dont 2 en cours.
Action : `Ctrl-C` pendant l'exécution.
Attendu : les phases en cours finissent proprement, les sous-features
non-terminées sont marquées `BLOCKED`, tous les worktrees sont
supprimés, state.json est cohérent (pas de données corrompues).

**T4 — cost cap atteint → confirm → continue ou abort**

Setup : epic avec `budget.per_epic_usd: 0.50` et 3 sous-features.
Action : la 2e sous-feature fait dépasser le cap.
Attendu (confirm) : pause, affichage du coût, prompt utilisateur.
Si `y` : reprise. Si `n` : abort propre (cf. T3).

**T5 — sous-feature avec dépendance → exécution ordonnée**

Setup : epic avec A (no deps), B (deps: [A]), C (no deps).
Action : `devflow epic "..."`.
Attendu : A et C démarrent en parallèle. B attend que A soit DONE
avant de démarrer. L'ordre de merge respecte le DAG.

## Consequences

### Positif

- Les features larges sont découpables automatiquement, réduisant
  le risque de contexte perdu par l'agent sur des tâches longues.
- L'exécution parallèle des sous-features réduit le temps total
  (wall-clock) d'un epic.
- Le gate global après merge détecte les problèmes d'intégration
  que les gates individuels ne voient pas.
- Le resume après crash rend le système robuste pour les epics
  longues (heures de build).

### Négatif

- Complexité significative : ~4 semaines d'implémentation estimées.
- Le merge séquentiel peut échouer sur des conflits non triviaux,
  nécessitant une intervention humaine.
- Le coût en tokens est multiplié par le nombre de sous-features
  (chaque sous-feature a son propre cycle planning → gate).
- La concurrence sur state.json via file lock fonctionne sur POSIX
  mais pas sur Windows (dégradation en séquentiel).

### Neutre

- Le champ `Feature.metadata.epic_deps` est un ajout backward-compatible
  (default `[]`). Les state.json existants restent valides.
- L'API `devflow epic "..."` est une nouvelle commande, pas une
  modification de `build` ou `do` — pas de régression possible sur
  les flows existants.

## Triggers de déclenchement

L'implémentation démarre quand **au moins un** de ces critères est
réuni :

1. **Douleur manuelle** : 2-3 features ont été découpées manuellement
   en sous-features et le process était pénible (branches manuelles,
   merges manuels, pas de gate global).

2. **Scale** : un projet nécessite 5+ sous-features parallèles à
   orchestrer — la coordination manuelle devient un bottleneck.

3. **ROI** : le coût annuel attendu en epics dépasse 4 semaines de
   développement one-shot — l'automatisation est rentabilisée.

Quand un trigger est réuni, rouvrir cet ADR, valider que le design
est encore pertinent par rapport à l'état du code, et démarrer
l'implémentation sur une branche dédiée avec un planning en 6
sous-PRs (cf. estimation dans `docs/refactor-2026-Q2.md` §Phase E).
