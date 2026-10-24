#!/usr/bin/env bash
# Sauvegarde complète de la base de production, sur ce poste.
#
# Complète la récupération à un instant donné de Render (quelques jours de
# rétention seulement) par une copie conservée hors de Render, aussi longtemps
# qu'on le souhaite.
#
# Utilisation :
#   1. Sur render.com : base « mutuelle-sante-db » → Connect → copier
#      l'« External Database URL ».
#   2. Lancer, depuis la racine du dépôt :
#        ./scripts/sauvegarder_production.sh
#      et coller l'URL quand elle est demandée (saisie masquée).
#
# L'URL contient le mot de passe de la base : elle n'est jamais affichée,
# ni écrite dans un fichier, l'historique du terminal ou le dépôt.
#
# Le fichier produit contient TOUTES les données nominatives et de santé, ainsi
# que les empreintes de mots de passe : il reste dans `sauvegardes/` (exclu du
# dépôt par .gitignore), lisible par votre seul compte. Ne pas l'envoyer par
# e-mail ni le déposer sur un partage non chiffré.
set -o errexit -o nounset -o pipefail

# Sans variable fournie, le script la demande, en saisie masquée : rien ne
# s'affiche à l'écran ni ne reste dans l'historique du terminal.
if [[ -z "${PROD_DATABASE_URL:-}" && -t 0 ]]; then
  read -rsp "Collez l'External Database URL de Render, puis Entrée : " PROD_DATABASE_URL
  echo
fi
if [[ -z "${PROD_DATABASE_URL:-}" ]]; then
  echo "Adresse de la base absente : voir l'en-tête de ce script." >&2
  exit 1
fi
if [[ "$PROD_DATABASE_URL" != postgres* ]]; then
  echo "Adresse inattendue : elle doit commencer par postgresql:// (External Database URL de Render)." >&2
  exit 1
fi

racine="$(cd "$(dirname "$0")/.." && pwd)"
dossier="$racine/sauvegardes"
mkdir -p "$dossier"
chmod 700 "$dossier"

horodatage="$(date +%Y%m%d_%H%M%S)"
fichier="$dossier/production_${horodatage}.dump"

# Les fichiers créés ne sont lisibles que par le compte courant.
umask 077

echo "Sauvegarde en cours vers $fichier…"
# Format « custom » : compressé, et restaurable table par table si besoin.
# --no-owner / --no-privileges : restaurable dans une autre base que celle
# de Render (poste local, nouvelle base de secours).
pg_dump --format=custom --no-owner --no-privileges --file="$fichier" "$PROD_DATABASE_URL"

# Une sauvegarde illisible ne vaut rien : on vérifie tout de suite que
# l'archive s'ouvre et contient bien les tables métier.
sommaire="$(pg_restore --list "$fichier")"
tables=$(grep -c " TABLE DATA " <<<"$sommaire" || true)
if [[ "$tables" -eq 0 ]]; then
  echo "ÉCHEC : l'archive ne contient aucune donnée de table." >&2
  exit 1
fi
for table in prescriptions_prescription beneficiaires_agent beneficiaires_ayantdroit; do
  if ! grep -q " TABLE DATA public $table " <<<"$sommaire"; then
    echo "ÉCHEC : la table $table est absente de l'archive." >&2
    exit 1
  fi
done

echo "Sauvegarde terminée : $fichier ($(du -h "$fichier" | cut -f1), $tables tables)."
echo "Pour vérifier qu'elle se restaure réellement : ./scripts/tester_restauration.sh \"$fichier\""
