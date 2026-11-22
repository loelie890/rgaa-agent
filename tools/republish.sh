#!/bin/sh
# Republication sous un autre compte, sans laisser de trace de l'historique.
#
# Utilisation :
#   ./tools/republish.sh "<Nom Prénom>" "<adresse@exemple.fr>" <dossier-de-sortie>
#
# Le script copie l'arbre de travail (sans .git, sans runs, sans data), recrée un
# dépôt neuf avec un commit unique signé par l'identité fournie, puis vérifie
# qu'aucune identité précédente et aucune fuite ne subsiste.
set -eu

AUTHOR_NAME="${1:-}"
AUTHOR_EMAIL="${2:-}"
TARGET="${3:-}"

if [ -z "$AUTHOR_NAME" ] || [ -z "$AUTHOR_EMAIL" ] || [ -z "$TARGET" ]; then
    echo "usage: $0 \"Nom Prénom\" \"adresse@exemple.fr\" dossier-de-sortie" >&2
    exit 2
fi

SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$TARGET"
mkdir -p "$TARGET"

tar -C "$SOURCE" \
    --exclude=.git \
    --exclude=runs \
    --exclude=data \
    --exclude=__pycache__ \
    --exclude='*.pyc' \
    -cf - . | tar -C "$TARGET" -xf -

cd "$TARGET"
git init -q -b main
git add -A
git -c user.name="$AUTHOR_NAME" -c user.email="$AUTHOR_EMAIL" commit -q -m "RGAA Agent : audit d'accessibilité qui corrige, mesure et prouve"

echo "== identités présentes dans l'historique"
git log --format='%an <%ae>' | sort -u

echo "== fuites à corriger avant publication"
if [ -n "${REPUBLISH_FORBIDDEN:-}" ] && grep -rIn -E "$REPUBLISH_FORBIDDEN" --exclude-dir=.git . ; then
    echo "^^ à traiter avant de pousser" >&2
else
    echo "aucune fuite détectée"
fi

echo "== vérifications rapides"
python3 -m unittest discover -s tests 2>&1 | tail -3
python3 -m rgaa validate 2>&1 | tail -1

echo
echo "Dépôt prêt dans $TARGET"
echo "Il reste à créer le dépôt distant et à pousser :"
echo "  git remote add origin <url-du-depot>"
echo "  git push -u origin main"
