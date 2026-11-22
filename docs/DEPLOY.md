# Déployer l'image, et savoir ce qu'elle contient

L'image légère fait 43 Mo et sait tout faire sauf deux choses : ouvrir une page
dans un navigateur, et faire tourner un modèle. Ces deux-là sont des **arguments
de construction**, pas des variables d'environnement.

C'est la confusion la plus fréquente : une variable d'environnement ne reconstruit
rien, elle ne fait que passer une valeur au conteneur déjà construit. Mettre
`INSTALL_BROWSER=1` dans un fichier d'environnement n'installe pas Chromium.

## Construire les trois variantes

```bash
# légère, 43 Mo, audit statique, CI, MCP
docker build -t rgaa-agent:slim .

# avec Chromium et Xvfb, pour le passage rendu (headless et headful)
docker build --build-arg INSTALL_BROWSER=1 -t rgaa-agent:browser .

# avec Ollama embarqué, à démarrer ou non au lancement
docker build --build-arg INSTALL_OLLAMA=1 -t rgaa-agent:full .

# les deux
docker build --build-arg INSTALL_BROWSER=1 --build-arg INSTALL_OLLAMA=1 -t rgaa-agent:complet .
```

Rien à pousser : les images sont déjà publiées à chaque commit.

| Image | Contenu | Taille | Usage |
| --- | --- | --- | --- |
| `ghcr.io/loelie890/rgaa-agent:latest` | Chromium, Xvfb | environ 330 Mo | audit complet, rendu réel |
| `ghcr.io/loelie890/rgaa-agent:ollama` | Chromium, Xvfb, Ollama | environ 2,2 Go | démo hors ligne avec modèle |

Si vous construisez la vôtre, taguez avec votre compte :

```bash
docker build --build-arg INSTALL_BROWSER=1 -t ghcr.io/loelie890/rgaa-agent:1.0.0 .
docker push ghcr.io/loelie890/rgaa-agent:1.0.0
```

## Variable d'environnement : seulement pour allumer

Une fois le binaire présent dans l'image, deux variables décident du démarrage :

| Variable | Effet | Valeur par défaut |
| --- | --- | --- |
| `RGAA_EMBEDDED_OLLAMA` | démarre `ollama serve` au lancement du conteneur | `0` |
| `RGAA_CHROME` | chemin du binaire Chromium, si l'image ne le place pas au même endroit | `/usr/bin/chromium` |

`RGAA_OLLAMA_URL` sert au client, pas au serveur : `http://127.0.0.1:11434` pour
l'Ollama embarqué, `http://host.docker.internal:11434` pour celui de l'hôte.

## La démo est sur le même port

`python -m rgaa demo` ouvre un second serveur sur 8090, ce qui demande un port de
plus à publier. Sur un poste ou dans un orchestrateur, ce second port est rarement
exposé, et la démo paraît alors cassée. La même démo est donc servie par l'application
elle-même, sans port supplémentaire :

| Adresse | Contenu |
| --- | --- |
| `/demo` | le site avant et après côte à côte, avec les deux scores |
| `/demo/api/score` | les mêmes chiffres, en JSON |
| `/demo/site/avant/…` et `/demo/site/apres/…` | les pages réelles, dans les deux états |
| `/demo/rapport.html` | le rapport HTML autonome |

Un seul port à publier, `8080`, et un bouton « Voir la démo » dans l'en-tête de
l'interface. La commande `demo --open` reste utile en local, sur 8090.

La page de démonstration a deux étages, pour un examinateur pressé comme pour un
curieux : les chiffres déjà calculés en haut, sans aucune attente, puis un bloc
« Relancer l'audit, ici et maintenant » avec trois moteurs au choix, sans modèle
(0,4 s), Ollama local du conteneur, ou Ollama distant dont on saisit l'URL. Le
résultat s'affiche avec la durée mesurée et le nombre d'alternatives écrites.

## Vérifier après déploiement

```bash
curl -s http://<hôte>:<port>/healthz
curl -s http://<hôte>:<port>/api/capabilities | python3 -m json.tool
```

La réponse dit exactement ce que l'image sait faire :

```json
{
  "chrome": {"available": true, "binary": "/usr/bin/chromium", "xvfb": true, "mode": "headless"},
  "ollama": {"installed": true, "running": false, "embedded": true},
  "campagnes": 5,
  "rules": 12,
  "hints": {"note": "les arguments de build ne sont pas des variables d'environnement"}
}
```

Si `chrome.available` est faux alors que `INSTALL_BROWSER=1` a été posé dans le
panneau de l'application, c'est que l'image n'a pas été reconstruite : c'est le
seul cas où il faut relancer un build.

## Test rapide du passage rendu, depuis le conteneur

```bash
# la page de l'application elle-même, vue par son propre navigateur
curl -s -X POST http://<hôte>:<port>/api/scan \
  -d '{"url":"http://127.0.0.1:8080/","allow_private":true,"browser":true}'
```

La réponse contient `browser.available`, le mode utilisé, la durée, et la liste
des constats mesurés sur le DOM rendu. En headful, la même requête avec
`"browser_mode":"headful"` passe par Xvfb, puisque le conteneur n'a pas d'écran.

## Sans navigateur dans l'image

Deux passages restent disponibles et suffisent à un audit sérieux : le statique
(douze règles, corrections écrites) et la vision, si un modèle répond. L'agent
le dit au lieu de faire semblant : `browser.available: false` avec la raison.
