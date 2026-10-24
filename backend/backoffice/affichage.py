"""Mise en forme commune à tous les écrans du back-office : montants lisibles
et statuts en couleur, déclarés une seule fois pour que les listes, les fiches
et les rapports parlent la même langue visuelle.

Réservé à l'écran : les exports CSV gardent des valeurs brutes, exploitables
dans un tableur.
"""
from django.utils.html import format_html

from beneficiaires.models import Agent, AyantDroit, StatutVerification
from facturation.models import Facture, StatutFacture
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, StatutPrestataire

# Ton de chaque statut : vert = acquis, orange = à surveiller ou à traiter,
# rouge = refusé ou bloquant, bleu = en attente d'une décision, gris = neutre.
TONS = {
    Prescription: {
        StatutPrescription.SOUMISE: "info",
        StatutPrescription.EN_CONTROLE: "warn",
        StatutPrescription.VALIDEE: "ok",
        StatutPrescription.REJETEE: "danger",
    },
    Facture: {
        StatutFacture.RECUE: "info",
        StatutFacture.RAPPROCHEE: "warn",
        StatutFacture.VALIDEE: "ok",
        StatutFacture.CONTESTEE: "danger",
    },
    AyantDroit: {
        StatutVerification.EN_ATTENTE: "info",
        StatutVerification.VALIDE: "ok",
        StatutVerification.REJETE: "danger",
    },
    Prestataire: {
        StatutPrestataire.ACTIF: "ok",
        StatutPrestataire.SUSPENDU: "danger",
    },
}


def milliers(nombre):
    """« 1234567 » → « 1 234 567 » (espace fine insécable). Laisse tel quel
    ce qui n'est pas un entier (texte, pourcentage décimal, vide)."""
    if isinstance(nombre, bool) or not isinstance(nombre, int):
        return nombre
    return f"{nombre:,}".replace(",", " ")


def kmf(montant):
    """Montant lisible et insécable : « 120 000 KMF »."""
    if montant is None or montant == "":
        return "—"
    return f"{milliers(montant)} KMF"


def badge(libelle, ton):
    return format_html('<span class="badge badge-{}">{}</span>', ton, libelle)


def badge_statut(objet):
    """Statut de l'objet en pastille colorée, quel que soit son type."""
    if isinstance(objet, Agent):
        ton = "danger" if objet.est_sorti else "warn" if objet.est_suspendu else "ok"
        return badge(objet.libelle_statut, ton)
    if isinstance(objet, AyantDroit):
        return badge(objet.get_statut_verification_display(), TONS[AyantDroit][objet.statut_verification])
    for modele in (Prescription, Facture, Prestataire):
        if isinstance(objet, modele):
            return badge(objet.get_statut_display(), TONS[modele].get(objet.statut, "muted"))
    raise TypeError(f"Pas de statut affichable pour {type(objet).__name__}")
