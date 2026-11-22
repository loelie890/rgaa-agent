# Démonstration en 3 minutes

Le chemin le plus court vers un résultat vérifiable.

## 1. Lancer (20 s)

```bash
python -m rgaa serve --open
# ou
docker run --rm -p 8080:8080 -v rgaa-data:/var/lib/rgaa ghcr.io/loelie890/rgaa-agent:latest
```

Ouvrir <http://127.0.0.1:8080>.

## 1 bis. Le mode démo, deux cadres (20 s)

```bash
python -m rgaa demo --open
```

Ouvrir <http://127.0.0.1:8090>. À gauche le site tel quel, à droite le même site après corrections, avec 70,8 % et 100 % affichés en haut. Le site de droite est le résultat réel des corrections du mode CI, pas une capture. `/api/score` et `/rapport.html` donnent les chiffres et le détail.

## 2. Le campagne qui prouve le travail (40 s)

Cliquer **Lancer (replay)** sur « Mise en conformité du site ».

Attendu : statut `done`, **24 étapes, 0 erreur**, une barre de conformité **70.8 % → 100 %**, et sept artefacts :

- `deliverables/rapport-rgaa.html` : le rapport autonome, résumé chiffré, tableau des 12 critères, diff coloré avant/après de chaque correction ;
- `deliverables/audit-rgaa.md` : le même contenu en markdown ;
- `index.html`, `produits.html`, `tarifs.html`, `contact.html` : les pages réellement réécrites ;
- `rgaa-patches.json` : le journal des 15 patchs.

Cliquer sur `rapport-rgaa.html` : le diff montre la ligne `<html>` qui gagne `lang="fr"`, le `<label for="email">` inséré, les `<td>` devenus `<th>`, et la couleur `#a3aab3` remplacée par `#72777d`.

Le même résultat en terminal :

```bash
python -m rgaa run conformite
```

## 3. Le campagne d'apprentissage (40 s)

**Lancer** « Apprentissage d'une procédure ».

Attendu :

```
Apprentissage : passe 1 — sans procédure → 7 étapes · 1 erreur(s)
                passe 2 — avec la procédure apprise → 5 étapes · 0 erreur(s)
```

L'étape 4 de la passe 1 est un patch `alt=""` **refusé** (« aucun changement appliqué »). L'étape 6 écrit la procédure, que la passe 2 relit en première étape :

```bash
ls data/skills/apprentissage/
```

## 4. Vision et garde-fous (30 s)

**Lancer** « Description d'image » : l'agent appelle `inspect_image` sur `hero.png`. Sans modèle vision configuré, l'outil répond `available: false` avec la raison, et l'agent décrit l'image depuis le contexte HTML en le signalant. Pour brancher un vrai VLM :

```bash
ollama pull qwen2.5vl:3b
RGAA_VISION_URL=http://127.0.0.1:11434 RGAA_VISION_MODEL=qwen2.5vl:3b python -m rgaa run vision
```

**Lancer** « Demande hors périmètre » : refus argumenté, aucune modification, aucun artefact.

## 5. Mode CI (30 s)

```bash
cp -r fixtures/site /tmp/site-ci
python -m rgaa ci /tmp/site-ci --min-score 100 --diff /tmp/rgaa.patch.diff --report /tmp/rapport.html
echo $?          # 0 : seuil atteint, diff applicable avec git apply
python -m rgaa ci /tmp/site-ci --min-score 101
echo $?          # 1 : seuil inatteignable
```

Le diff ne touche que les pages réellement modifiées. Les corrections non devinables (description d'image, intitulé de bouton) sont marquées `review` et listées dans le rapport.

## 6. Tests (20 s)

```bash
python -m unittest discover -s tests -v
python -m rgaa validate
python -m rgaa rules
```

41 tests, environ 6 s. La CI exécute la même chose sur trois versions de Python, les deux directions du mode CI, puis démarre le conteneur et lance `conformite` par l'API.

## 7. Optionnel, un modèle de décision en live (5 min)

1. Démarrer Ollama, LM Studio ou vLLM.
2. Renseigner l'URL (`http://127.0.0.1:11434`) et le modèle (`qwen2.5:3b`).
3. **Sonder le backend**, puis **Lancer (live)** sur `audit` (plus court et plus sûr avec un petit modèle).

En live, le modèle choisit les sélecteurs et les valeurs ; les patchs s'appliquent réellement et le score est recalculé. Une erreur d'argument devient une observation journalisée, le run continue.
