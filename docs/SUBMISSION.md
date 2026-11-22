# Publication sous un autre compte

Le dépôt ne contient aucune donnée personnelle et aucune identité d'auteur dans
son contenu. Ce document liste les rares endroits qui désignent une plateforme
ou un compte, à adapter avant de republier le projet.

## 1. Recréer l'historique proprement

L'historique Git conserve l'auteur des commits. Pour repartir d'un historique
neutre, sans réécrire le contenu :

```bash
cd rgaa-agent
rm -rf .git
git init -b main
git add -A
git -c user.name="<nom affiché>" -c user.email="<email du compte>" commit -m "RGAA Agent, agent local de mise en conformité RGAA 4.1"
git remote add origin <url du nouveau dépôt>
git push -u origin main
```

Vérifier ensuite que `git log --format='%an <%ae>'` ne montre que l'identité
choisie.

## 2. Badges et liens

`README.md` et `README.en.md` utilisent un badge CI **relatif**
(`../../actions/workflows/ci.yml/badge.svg`) : il fonctionne sur n'importe quel
dépôt, sans modification. Aucun lien absolu vers un compte n'est présent.

## 3. Image Docker

Trois endroits nomment le registre :

| Fichier | À adapter |
| --- | --- |
| `.github/workflows/docker-build.yml` | `DOCKERHUB_IMAGE` et `GHCR_IMAGE` |
| `README.md`, `README.en.md`, `docs/DEMO.md` | commande `docker run` |

Les secrets du dépôt doivent exister sous les noms `DOCKERHUB_USERNAME` et
`DOCKERHUB_TOKEN`. Le nom d'image doit être en minuscules et appartenir au compte
Docker Hub utilisé ; un premier `docker push` crée le dépôt automatiquement.

## 4. Licence et auteur

`LICENSE` porte « Copyright (c) 2026 RGAA Agent contributors ». Remplacer par
l'identité du titulaire si nécessaire.

## 5. Vérifications avant envoi

```bash
grep -rIn -E "(<compte d'origine>|<autre projet>|/data/|192\.168\.)" --exclude-dir=.git .
python -m unittest discover -s tests
python -m rgaa run conformite
```

Les fixtures sont synthétiques (`example.invalid`, plaque d'exemple `AB-123-CD`,
sociétés fictives). Aucun site client, aucune image réelle : les quatre PNG sont
générés par `tools/make_fixtures.py`.

## 6. Points à annoncer honnêtement dans le formulaire

- 12 règles RGAA sur 106 critères, choisies parce qu'elles se vérifient mécaniquement.
- La pertinence d'un texte alternatif reste un jugement humain.
- Le contraste est calculé depuis les styles analysés, sans rendu navigateur.
- Le mode vision est optionnel et testé contre un endpoint simulé en CI ; il
  n'embarque aucun modèle.

## Ce qui ne doit pas apparaître dans le dépôt publié

Un dépôt de concours se lit aussi par ce qu'il ne dit pas. Avant de pousser
depuis le compte qui publie, ces vérifications sont à passer, et leur sortie à
garder :

```bash
grep -rIn -E "(<compte d'origine>|<autre projet>|<autre projet>|/data/|192\.168\.|<nom-du-concours>)" --exclude-dir=.git .
git log --format='%an <%ae>' | sort -u
grep -c '^# ' README.md
```

- Aucun lien croisé vers un autre projet du même concours, même dans une phrase de contexte.
- Aucun nom de compte personnel dans un badge, une image, un fichier compose ou un workflow : les noms d'images passent par `vars` ou par une valeur neutre.
- Aucun chemin de machine (`/data`, `/opt`, un dossier personnel) : les chemins du conteneur sont neutres, `/var/lib/rgaa`.
- Aucune adresse privée, aucun nom d'hôte de labo, aucune capture montrant un tableau de bord interne.
- Aucun titre de niveau 2 identique au README de l'autre projet, et aucun chiffre recopié d'un document de travail.
- Un seul auteur dans l'historique, celui du compte qui publie.

`tools/republish.sh` fait la copie propre, recrée l'historique et imprime ces contrôles.
