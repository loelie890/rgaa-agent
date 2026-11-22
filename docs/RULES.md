# Les 12 règles

Chaque règle est vérifiée mécaniquement sur l'arbre HTML. Le tableau dit aussi ce
que la règle **ne** vérifie pas : c'est la partie qui compte pour un auditeur.

| # | Règle (`id`) | Critère RGAA 4.1 | Sévérité | Vérifié mécaniquement | Non vérifié |
| --- | --- | --- | --- | --- | --- |
| 1 | Langue de la page (`lang`) | 8.3 | bloquant | présence et non-vacuité de `lang` sur `<html>` | cohérence de la langue déclarée avec le contenu |
| 2 | Titre de page (`title`) | 8.6 | bloquant | `<title>` présent et non vide | pertinence du titre |
| 3 | Alternatives des images (`img-alt`) | 1.1 | bloquant | `alt` présent ; `alt=""` accepté seulement avec `role="presentation"` ou `aria-hidden="true"` | qualité de la description, distinction information/décoration dans le contenu |
| 4 | Intitulé de lien (`link-name`) | 6.1 | majeur | texte hors `aria-hidden`, `aria-label`, `title`, ou `alt` d'une image enfant | caractère explicite de l'intitulé hors contexte |
| 5 | Intitulé de bouton (`button-name`) | 11.9 | majeur | texte accessible ou `aria-label`/`title` | pertinence de l'intitulé |
| 6 | Étiquette de champ (`label`) | 11.1 | bloquant | `<label for>` correspondant, `aria-label`, `aria-labelledby` ou `title` | visibilité et pertinence de l'étiquette |
| 7 | Hiérarchie des titres (`headings`) | 9.1 | majeur | premier titre = `h1`, pas de saut de niveau, un seul `h1` | pertinence de la structure pour le contenu |
| 8 | En-têtes de tableau (`table-header`) | 5.6 | majeur | au moins un `<th>` dans la première ligne | `scope`, `headers`, tableaux de mise en page vs données |
| 9 | Cadre avec titre (`iframe-title`) | 2.1 | majeur | `title` non vide sur `<iframe>` | pertinence du titre |
| 10 | Contraste (`contrast`) | 3.2 | majeur | ratio WCAG calculé depuis les styles en ligne **et** les blocs `<style>` (cascade simplifiée, fond hérité des ancêtres), seuil 4.5:1, 3:1 pour un grand texte | feuille de style externe, `@media`, variables CSS, dégradés, images de fond, rendu réel |
| 11 | Identifiants uniques (`duplicate-id`) | 8.2 | mineur | unicité des attributs `id` dans la page | validité complète du code (DTD, imbrication) |
| 12 | Structure de liste (`list-structure`) | 9.3 | mineur | enfants directs de `ul`/`ol` limités à `li` (ou listes imbriquées) | listes de définition, listes générées en JavaScript |

## Sévérités

- **bloquant** : l'information ou le contrôle devient inaccessible à un utilisateur de lecteur d'écran ;
- **majeur** : dégradation forte de l'usage, sans blocage total ;
- **mineur** : validité ou confort.

## Score

`conformité = (règles × pages conformes) / (règles × pages)`.

Sur la démo : 12 règles × 3 pages = 36 contrôles, 23 conformes avant correction (63.9 %), 36 après (100 %). Le score est recalculé à chaque appel d'`audit_run`/`audit_score`, depuis le HTML du bac à sable — il baisse si une correction casse autre chose, ce qui est testé.

## Étendre l'ensemble de règles

Une règle est une fonction `(Document) -> [(Node, message[, sélecteur])]` déclarée dans `rgaa/audit.py` :

```python
Rule("image-decorative", "Images décoratives marquées", "1.2", "mineur", _check_decorative)
```

Le sélecteur optionnel permet de cibler précisément l'élément fautif quand la balise seule est ambiguë (cas des listes). Ajouter une règle ne demande aucune modification du noyau : le registre d'outils et le score la prennent en compte automatiquement.
