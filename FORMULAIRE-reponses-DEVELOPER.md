# Formulaire, catégorie Developer

À remplir au moment de la soumission. Les champs marqués `À COMPLÉTER` ne doivent
pas être inventés : ils attendent une valeur réelle.

## Identification

| Champ | Valeur |
| --- | --- |
| Catégorie | Developer |
| Nom du projet | RGAA Agent |
| Dépôt public | `À COMPLÉTER` (URL du dépôt après republication) |
| Vidéo de démonstration | `À COMPLÉTER` (lien non répertorié) |
| Nom et prénom | `À COMPLÉTER` |
| Téléphone | `À COMPLÉTER` |
| Date de naissance | `À COMPLÉTER` |
| Adresse électronique | `À COMPLÉTER` |

## Description courte, à recopier telle quelle

Un agent local qui corrige l'accessibilité au lieu de la signaler. Il lit le HTML,
écrit la correction dans le fichier, relit le score et recommence, puis publie un
rapport avant et après. Douze règles RGAA 4.1 corrigées mécaniquement, dix-sept
détectées, et un tableau qui dit honnêtement ce qui reste à un humain. Aucune
dépendance, aucun compte, aucun réseau pour la démonstration.

## Ce que le projet démontre, en trois chiffres mesurés

- 48 contrôles sur 48 après correction, sur quatre pages, en 0,45 s sans GPU.
- 24 étapes d'agent, zéro erreur, quinze corrections réellement écrites sur disque.
- Deux passes d'apprentissage : 7 étapes et 1 erreur, puis 5 étapes et 0 erreur.

Chaque chiffre vient d'une commande exécutée sur le dépôt : `python -m rgaa run
conformite`, `python -m rgaa run apprentissage`, `python -m unittest discover -s tests`.

## Bénéfices apportés par du matériel ASUS performant

Le seul endroit où un modèle travaille vraiment est la passe vision, et elle
demande de la mémoire. Sur la carte actuelle, 4 Go, un seul modèle vision tient, le plus petit. Sur les 16 Go d'une RTX 5080, quatre tiennent, dont un 7B et un 8B : l'agent cesse de deviner les alternatives d'images et les décrit vraiment, sur un site entier et en une passe.

## Ce que le formulaire ne doit pas contenir

- Aucune mention d'un autre projet ou d'un autre palier.
- Aucun lien vers un autre dépôt que celui soumis.
- Aucun chiffre non mesuré, aucune promesse de conformité RGAA complète.
