"""Export CSV des tableaux du back-office.

Un seul moteur pour tous les exports : une table s'exporte en déclarant ses
colonnes de la même façon que les listes à l'écran — un libellé et un moyen
d'extraire la valeur. L'écran et le fichier lisent ainsi la même définition,
ce qui évite qu'ils finissent par raconter deux choses différentes.

Format retenu : point-virgule et UTF-8 **avec BOM**. C'est ce qu'attend Excel
en configuration française ; sans le BOM, les accents arrivent illisibles, et
avec une virgule les montants se répartissent sur plusieurs colonnes.
"""
import csv
from datetime import date

from django.http import HttpResponse

SEPARATEUR = ";"
BOM = "﻿"


def valeur(objet, extracteur):
    """Une colonne s'exprime soit par un nom d'attribut, soit par une fonction.

    Les objets exportés sont tantôt des modèles, tantôt des dictionnaires
    d'agrégation : les deux formes sont acceptées.
    """
    if callable(extracteur):
        return extracteur(objet)
    if isinstance(objet, dict):
        return objet.get(extracteur, "")
    attribut = getattr(objet, extracteur, "")
    return attribut() if callable(attribut) else attribut


def _formater(valeur_brute):
    if valeur_brute is None:
        return ""
    if isinstance(valeur_brute, bool):
        return "oui" if valeur_brute else "non"
    if isinstance(valeur_brute, date):
        return valeur_brute.strftime("%d/%m/%Y")
    return str(valeur_brute)


def reponse_csv(nom_fichier, colonnes, lignes, entete=()):
    """Construit la réponse HTTP d'un export.

    `colonnes` : suite de (libellé, extracteur), comme les listes à l'écran.
    `entete`   : lignes libres placées avant le tableau (période, filtres…),
                 pour que le fichier reste interprétable une fois détaché de
                 l'écran qui l'a produit.
    """
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    reponse.write(BOM)

    redacteur = csv.writer(reponse, delimiter=SEPARATEUR, lineterminator="\r\n")
    for ligne_entete in entete:
        redacteur.writerow(ligne_entete)
    if entete:
        redacteur.writerow([])

    redacteur.writerow([libelle for libelle, _ in colonnes])
    for objet in lignes:
        redacteur.writerow([_formater(valeur(objet, extracteur)) for _, extracteur in colonnes])

    return reponse


def nom_de_fichier(prefixe, debut=None, fin=None):
    """Nom horodaté : les exports successifs ne s'écrasent pas dans le dossier
    de téléchargement."""
    morceaux = [prefixe]
    if debut and fin:
        morceaux.append(f"{debut:%Y%m%d}-{fin:%Y%m%d}")
    else:
        morceaux.append(f"{date.today():%Y%m%d}")
    return "-".join(morceaux) + ".csv"


def reponse_csv_sections(nom_fichier, sections, entete=()):
    """Export d'un seul fichier regroupant plusieurs tableaux.

    Chaque tableau est précédé de son titre et suivi d'une ligne vide. Excel
    ouvre le tout dans une feuille unique : moins pratique qu'un classeur à
    onglets, mais lisible sans dépendance supplémentaire, et le destinataire
    reçoit un seul fichier plutôt que six.
    """
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    reponse.write(BOM)

    redacteur = csv.writer(reponse, delimiter=SEPARATEUR, lineterminator="\r\n")
    for ligne_entete in entete:
        redacteur.writerow(ligne_entete)
    if entete:
        redacteur.writerow([])

    for titre, colonnes, lignes in sections:
        lignes = list(lignes)
        redacteur.writerow([titre.upper(), f"{len(lignes)} ligne(s)"])
        redacteur.writerow([libelle for libelle, _ in colonnes])
        for objet in lignes:
            redacteur.writerow([_formater(valeur(objet, extracteur)) for _, extracteur in colonnes])
        redacteur.writerow([])

    return reponse
