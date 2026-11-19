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
from django.utils import timezone

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
    if isinstance(valeur_brute, float):
        # Virgule décimale : avec un point, Excel en français lit « 33.3 »
        # comme du texte, voire comme une date.
        return str(valeur_brute).replace(".", ",")
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
        morceaux.append(f"{timezone.localdate():%Y%m%d}")
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


def reponse_xlsx(nom_fichier, tableau, lignes, debut, fin, edite_par, avertissement="", synthese=(), annexes=(),
                 libelle_periode="Période"):
    """Classeur Excel d'un tableau, prêt à analyser.

    Onglet 1 : le tableau seul sous un titre court — en-tête figé, filtre
    automatique, milliers, pourcentages et dates formatés, totaux à part
    (après une ligne vide, pour ne pas être triés avec les données).
    Onglet 2 : la synthèse de la période et les `annexes` (autres petits
    tableaux). Onglet 3 : le sens de chaque colonne.

    `synthese` : suite de (libellé, valeur) ; `annexes` : suite de
    (titre, colonnes, lignes) au même format que les tableaux.
    """
    from . import xlsx

    classeur = xlsx.Classeur()
    feuille = classeur.feuille(tableau.titre)
    feuille.ajouter([tableau.titre], xlsx.TITRE)
    feuille.ajouter(
        [f"{libelle_periode} du {debut:%d/%m/%Y} au {fin:%d/%m/%Y} — édité le {timezone.localdate():%d/%m/%Y} par {edite_par}"],
        xlsx.DISCRET,
    )
    if avertissement:
        feuille.ajouter([avertissement], xlsx.AVERTISSEMENT)
    feuille.ajouter()

    libelles = [libelle for libelle, _ in tableau.colonnes]
    styles = [xlsx.POURCENT if libelle.endswith("(%)") else None for libelle in libelles]
    ligne_entete = feuille.ajouter(libelles, xlsx.ENTETE)
    lignes = list(lignes)
    for objet in lignes:
        feuille.ajouter([valeur(objet, extracteur) for _, extracteur in tableau.colonnes], styles)
    derniere = ligne_entete + len(lignes)
    feuille.ligne_figee = ligne_entete
    feuille.filtre = f"A{ligne_entete}:{xlsx.lettre_colonne(len(libelles) - 1)}{derniere}"

    # Largeurs calculées avant la ligne de totaux, plus longue que les données.
    feuille.ajuster_largeurs(a_partir_de=ligne_entete, maximum=30)
    feuille.paysage = True

    if tableau.colonnes_totalisees and lignes:
        feuille.ajouter()
        totaux = ["Total"] + [None] * (len(libelles) - 1)
        styles_totaux = [xlsx.GRAS] + [xlsx.ENTIER_GRAS] * (len(libelles) - 1)
        for indice, (_, extracteur) in enumerate(tableau.colonnes):
            if extracteur in tableau.colonnes_totalisees:
                totaux[indice] = sum(valeur(objet, extracteur) or 0 for objet in lignes)
        feuille.ajouter(totaux, styles_totaux)

    annexe = classeur.feuille("Synthèse")
    annexe.ajouter([f"Synthèse — {tableau.titre}"], xlsx.TITRE)
    annexe.ajouter([f"{libelle_periode} du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"], xlsx.DISCRET)
    if avertissement:
        annexe.ajouter([avertissement], xlsx.AVERTISSEMENT)
    annexe.ajouter()
    for libelle, montant in synthese:
        annexe.ajouter([libelle, montant], [xlsx.NORMAL, xlsx.POURCENT if libelle.endswith("(%)") else None])
    for titre, colonnes, lignes_annexe in annexes:
        annexe.ajouter()
        annexe.ajouter([titre], xlsx.GRAS)
        annexe.ajouter([libelle for libelle, _ in colonnes], xlsx.ENTETE)
        styles_annexe = [xlsx.POURCENT if libelle.endswith("(%)") else None for libelle, _ in colonnes]
        for objet in lignes_annexe:
            annexe.ajouter([valeur(objet, extracteur) for _, extracteur in colonnes], styles_annexe)
    annexe.ajuster_largeurs(a_partir_de=4, maximum=45)
    annexe.paysage = True
    if tableau.definitions:
        lexique = classeur.feuille("Sens des colonnes")
        lexique.ajouter(["Sens des colonnes"], xlsx.TITRE)
        lexique.ajouter()
        lexique.ajouter(["Colonne", "Ce qu'elle mesure"], xlsx.ENTETE)
        for libelle, sens in tableau.definitions:
            lexique.ajouter([libelle, sens], [xlsx.GRAS, xlsx.NOTE])
        lexique.largeurs = {0: 34, 1: 95}
        lexique.paysage = True
    return classeur.reponse(nom_fichier)
