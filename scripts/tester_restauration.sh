#!/usr/bin/env bash
# Restaure une sauvegarde dans une base PostgreSQL jetable (Docker), pour
# prouver qu'elle est exploitable — une sauvegarde jamais restaurée n'est
# qu'une supposition.
#
# Utilisation, depuis la racine du dépôt :
#   ./scripts/tester_restauration.sh sauvegardes/production_AAAAMMJJ_HHMMSS.dump
#
# Ne touche ni à la production ni à la base de développement : le conteneur
# est créé pour l'occasion puis supprimé, avec les données restaurées.
set -o errexit -o nounset -o pipefail

fichier="${1:-}"
if [[ -z "$fichier" || ! -f "$fichier" ]]; then
  echo "Indiquez le fichier de sauvegarde à tester." >&2
  exit 1
fi

conteneur="mutuelle_test_restauration_$$"
trap 'docker rm -f "$conteneur" >/dev/null 2>&1 || true' EXIT

echo "Démarrage d'une base PostgreSQL jetable…"
# Serveur de même version majeure que les outils du poste : pg_restore émet
# des réglages propres à sa version, qu'un serveur plus ancien refuse.
version="$(pg_restore --version | grep -oE '[0-9]+' | head -1)"
# Port choisi par Docker : pas de conflit avec une base déjà présente.
docker run -d --rm --name "$conteneur" -e POSTGRES_PASSWORD=restauration -e POSTGRES_DB=restauration \
  -p 127.0.0.1::5432 "postgres:$version" >/dev/null
port="$(docker port "$conteneur" 5432/tcp | head -1 | cut -d: -f2)"
url="postgresql://postgres:restauration@127.0.0.1:$port/restauration"
# Le serveur redémarre une fois à l'initialisation : on attend qu'une vraie
# requête passe, pas seulement que le port réponde.
for _ in $(seq 1 60); do
  psql "$url" -c "select 1" >/dev/null 2>&1 && break
  sleep 1
done

# pg_restore du poste (et non celui du conteneur) : c'est le même outil que
# celui qui a produit l'archive, un pg_restore plus ancien refuserait de la lire.
echo "Restauration de $fichier…"
pg_restore --no-owner --no-privileges --exit-on-error -d "$url" "$fichier"

echo
echo "Contenu restauré :"
psql "$url" -c "
  select 'Agents' as donnees, count(*) as nombre from beneficiaires_agent
  union all select 'Ayants droit', count(*) from beneficiaires_ayantdroit
  union all select 'Prescriptions', count(*) from prescriptions_prescription
  union all select 'Prestataires', count(*) from prestataires_prestataire;"
psql "$url" -At -c "select 'Dernière prescription saisie le ' || coalesce(to_char(max(date_creation) at time zone 'Indian/Comoro', 'DD/MM/YYYY HH24:MI'), '—') from prescriptions_prescription;"

echo
echo "Restauration réussie. Comparez ces chiffres à ceux du back-office."
