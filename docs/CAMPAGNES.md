# Écrire un campagne

Un campagne = un objectif + un jeu de pages + une ou plusieurs cassettes.
Le format est vérifié mécaniquement : `python -m rgaa validate`.

## Arborescence

```
campagnes/<slug>/
  campagne.json     objectif, budget, date de référence, passes
  cassette.json     étapes enregistrées (une passe)
  cassette-1.json   passe 1 (si apprentissage)
  cassette-2.json   passe 2
```

Les pages viennent de `fixtures/<nom>/`. Le champ `fixtures` du campagne pointe
vers ce nom ; à défaut, le nom du campagne est utilisé.

## campagne.json

```json
{
  "slug": "conformite",
  "title": "Mise en conformité du site",
  "objective": "Corrige le site jusqu'à ce que les 12 règles passent...",
  "as_of": "2026-11-20",
  "budget": 24,
  "fixtures": "site",
  "passes": [{ "label": "passe unique", "cassette": "cassette.json" }]
}
```

- `budget` : nombre maximum d'appels d'outils. Au-delà, `status: budget` — jamais
  de boucle infinie, jamais de timeout.
- `passes` : une entrée = une passe. Deux entrées = campagne d'apprentissage,
  exécuté séquentiellement, avec comparaison des étapes et des erreurs.
- `as_of` : date de référence affichée dans les rapports (reproductibilité).

## Cassette

```json
{ "thought": "raisonnement court", "tool": "patch_html", "args": { "page": "index.html", "selector": "html", "op": "set_attr", "name": "lang", "value": "fr" } }
{ "thought": "conclusion", "final": "réponse pour l'utilisateur" }
```

Règles vérifiées par `validate` : cassette non vide, dernière étape = `final`,
outil connu, arguments **exactement** conformes à la signature (ni manquant, ni
inventé).

## Créer un campagne

```bash
python -m rgaa new mon-site
# 1. déposer les pages dans fixtures/mon-site/
# 2. décrire l'objectif dans campagnes/mon-site/campagne.json
# 3. écrire la cassette
python -m rgaa validate
python -m rgaa run mon-site
```

## Mode live

Le planificateur interroge un backend OpenAI-compatible avec la table des outils
dans le prompt système et le contrat JSON rappelé à chaque étape.

```bash
python -m rgaa run conformite --live --base-url http://127.0.0.1:11434 --model qwen2.5:3b
```

Une sortie non structurée ou un argument invalide devient une observation : le run
continue, la leçon peut être capitalisée par `skill_write`.
