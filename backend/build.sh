#!/usr/bin/env bash
# Script de construction exécuté par Render à chaque déploiement.
# `set -o errexit` : une erreur interrompt le déploiement au lieu de mettre en
# ligne une version à moitié installée.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Rassemble les fichiers statiques là où WhiteNoise ira les chercher.
python manage.py collectstatic --no-input

# Applique les migrations en attente. Idempotent : sans migration nouvelle,
# la commande ne fait rien.
python manage.py migrate

# Crée le compte administrateur au tout premier déploiement, s'il est demandé.
# Sans ce compte, personne ne pourrait ouvrir le back-office de la nouvelle base.
python manage.py creer_admin_initial
