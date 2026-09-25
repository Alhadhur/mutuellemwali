"""Import CSV déclenché depuis le back-office.

Même logique que les commandes `manage.py importer_*` (tout ou rien, rapport
ligne par ligne), mais en deux temps pour un usage au clavier/souris plutôt
qu'en terminal :

1. upload → analyse dans une transaction annulée (aperçu, erreurs) ;
2. confirmation → même analyse, transaction conservée cette fois.

Le contenu du fichier est gardé en session entre les deux étapes : un champ
`<input type=file>` ne peut pas être pré-rempli par le navigateur pour des
raisons de sécurité, il faut donc conserver le fichier côté serveur plutôt
que le faire revoyager par le client.
"""
import csv
import io
from datetime import datetime

from django.db import transaction

FORMATS_DATE = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


class LigneInvalide(Exception):
    pass


def date_ou_erreur(brut, champ="date"):
    if not brut:
        return None
    for format_date in FORMATS_DATE:
        try:
            return datetime.strptime(brut, format_date).date()
        except ValueError:
            continue
    raise LigneInvalide(f"{champ} « {brut} » illisible (formats acceptés : {', '.join(FORMATS_DATE)})")


def lire_csv(contenu):
    try:
        delimiteur = csv.Sniffer().sniff(contenu[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        delimiteur = ","
    lecteur = csv.DictReader(io.StringIO(contenu), delimiter=delimiteur)
    return [
        {(cle or "").strip().lower(): (valeur or "").strip() for cle, valeur in ligne.items()}
        for ligne in lecteur
    ]


def executer(contenu, colonnes_attendues, importer_ligne, ecrire):
    """Analyse un CSV et, si `ecrire`, applique le résultat.

    `importer_ligne(ligne)` retourne `(objet, cree)` ou lève `LigneInvalide`.
    Tout ou rien à l'écriture : la moindre ligne en erreur annule tout, pour
    ne jamais laisser la base à moitié importée.
    """
    lignes = lire_csv(contenu)
    if not lignes:
        return {"crees": 0, "maj": 0, "erreurs": [(0, "le fichier ne contient aucune ligne de données")], "apercu": []}

    manquantes = colonnes_attendues - set(lignes[0])
    if manquantes:
        message = (
            f"colonnes obligatoires absentes : {', '.join(sorted(manquantes))} "
            f"(colonnes lues : {', '.join(lignes[0])})"
        )
        return {"crees": 0, "maj": 0, "erreurs": [(0, message)], "apercu": []}

    crees, majs, erreurs = [], [], []
    with transaction.atomic():
        for numero, ligne in enumerate(lignes, start=2):
            try:
                objet, cree = importer_ligne(ligne)
            except LigneInvalide as erreur:
                erreurs.append((numero, str(erreur)))
                continue
            (crees if cree else majs).append(objet)

        if not ecrire or erreurs:
            transaction.set_rollback(True)

    return {
        "crees": len(crees),
        "maj": len(majs),
        "erreurs": erreurs,
        "apercu": [str(objet) for objet in (crees + majs)[:10]],
    }
