"""Import du réseau conventionné depuis un fichier CSV.

    ./venv/bin/python manage.py importer_prestataires reseau.csv --dry-run
    ./venv/bin/python manage.py importer_prestataires reseau.csv

L'import est idempotent : une ligne portant un `code` existant met à jour la
fiche, sinon le rapprochement se fait sur (nom, ville) pour éviter de créer un
doublon quand le même fichier est rejoué.
"""
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from prestataires.models import Prestataire, StatutPrestataire, TypePrestataire

COLONNES_ATTENDUES = {"type", "nom"}

# Le fichier fourni par la mutuelle peut employer les libellés français.
TYPES = {
    "pharmacie": TypePrestataire.PHARMACIE,
    "pharmacies": TypePrestataire.PHARMACIE,
    "etablissement": TypePrestataire.ETABLISSEMENT,
    "établissement": TypePrestataire.ETABLISSEMENT,
    "clinique": TypePrestataire.ETABLISSEMENT,
    "hopital": TypePrestataire.ETABLISSEMENT,
    "hôpital": TypePrestataire.ETABLISSEMENT,
    "centre medical": TypePrestataire.ETABLISSEMENT,
    "centre médical": TypePrestataire.ETABLISSEMENT,
    "praticien": TypePrestataire.PRATICIEN,
    "medecin": TypePrestataire.PRATICIEN,
    "médecin": TypePrestataire.PRATICIEN,
}
TYPES.update({valeur.lower(): valeur for valeur in TypePrestataire.values})

STATUTS = {
    "actif": StatutPrestataire.ACTIF,
    "active": StatutPrestataire.ACTIF,
    "suspendu": StatutPrestataire.SUSPENDU,
    "suspendue": StatutPrestataire.SUSPENDU,
}


class LigneInvalide(Exception):
    pass


def _taux(brut):
    if not brut:
        return Decimal("80")
    try:
        taux = Decimal(brut.replace(",", ".").replace("%", "").strip())
    except InvalidOperation:
        raise LigneInvalide(f"taux « {brut} » illisible")
    if not 0 <= taux <= 100:
        raise LigneInvalide(f"taux « {brut} » hors de l'intervalle 0–100")
    return taux


def importer_ligne(ligne):
    """Analyse une ligne et applique la création/mise à jour du prestataire.

    Fonction de module (pas une méthode de Command) pour être réutilisable
    telle quelle par l'import web équivalent (backoffice.views.PrestataireImport).
    """
    nom = ligne.get("nom", "")
    if not nom:
        raise LigneInvalide("nom vide")

    brut_type = ligne.get("type", "").lower()
    type_prestataire = TYPES.get(brut_type)
    if not type_prestataire:
        raise LigneInvalide(
            f"type « {ligne.get('type', '')} » inconnu (attendu : pharmacie, établissement ou praticien)"
        )

    champs = {
        "type_prestataire": type_prestataire,
        "nom": nom,
        "ville": ligne.get("ville", ""),
        "adresse": ligne.get("adresse", ""),
        "telephone": ligne.get("telephone", "") or ligne.get("téléphone", ""),
        "statut": STATUTS.get(ligne.get("statut", "").lower(), StatutPrestataire.ACTIF),
        "taux_prise_en_charge": _taux(ligne.get("taux", "") or ligne.get("taux_prise_en_charge", "")),
    }

    code = ligne.get("code", "")
    if code:
        existant = Prestataire.objects.filter(code=code).first()
        if not existant:
            raise LigneInvalide(f"code « {code} » introuvable en base")
    else:
        existant = Prestataire.objects.filter(nom__iexact=nom, ville__iexact=champs["ville"]).first()

    if existant:
        for attribut, valeur in champs.items():
            setattr(existant, attribut, valeur)
        existant.save()
        return existant, False

    return Prestataire.objects.create(**champs), True


class Command(BaseCommand):
    help = "Importe ou met à jour le réseau de prestataires conventionnés depuis un CSV."

    def add_arguments(self, parseur):
        parseur.add_argument("fichier", type=str, help="Chemin du fichier CSV à importer.")
        parseur.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyse le fichier et affiche le résultat sans rien écrire en base.",
        )
        parseur.add_argument(
            "--delimiteur",
            type=str,
            default="",
            help="Séparateur de colonnes ; détecté automatiquement par défaut.",
        )

    def handle(self, *args, **options):
        chemin = Path(options["fichier"])
        if not chemin.exists():
            raise CommandError(f"Fichier introuvable : {chemin}")

        lignes = self._lire(chemin, options["delimiteur"])
        if not lignes:
            raise CommandError("Le fichier ne contient aucune ligne de données.")

        manquantes = COLONNES_ATTENDUES - set(lignes[0])
        if manquantes:
            raise CommandError(
                f"Colonnes obligatoires absentes : {', '.join(sorted(manquantes))}. "
                f"Colonnes lues : {', '.join(lignes[0])}."
            )

        crees, majs, erreurs = [], [], []
        with transaction.atomic():
            for numero, ligne in enumerate(lignes, start=2):
                try:
                    prestataire, cree = importer_ligne(ligne)
                except LigneInvalide as erreur:
                    erreurs.append((numero, str(erreur)))
                    continue
                (crees if cree else majs).append(prestataire)

            # Tout ou rien : un fichier partiellement importé laisserait un
            # réseau incohérent, impossible à rejouer sans doublons.
            if options["dry_run"] or erreurs:
                transaction.set_rollback(True)

        self._rapport(crees, majs, erreurs, options["dry_run"])
        if erreurs and not options["dry_run"]:
            raise CommandError(
                f"{len(erreurs)} ligne(s) en erreur : rien n'a été importé, corrigez le fichier."
            )

    def _lire(self, chemin, delimiteur):
        # utf-8-sig retire le BOM que place Excel en tête de fichier.
        with chemin.open(encoding="utf-8-sig", newline="") as fichier:
            echantillon = fichier.read(4096)
            fichier.seek(0)
            if not delimiteur:
                try:
                    delimiteur = csv.Sniffer().sniff(echantillon, delimiters=",;\t").delimiter
                except csv.Error:
                    delimiteur = ","
            lecteur = csv.DictReader(fichier, delimiter=delimiteur)
            return [
                {(cle or "").strip().lower(): (valeur or "").strip() for cle, valeur in ligne.items()}
                for ligne in lecteur
            ]

    def _rapport(self, crees, majs, erreurs, simulation):
        titre = "SIMULATION (aucune écriture)" if simulation else "IMPORT EFFECTUÉ"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{titre}"))
        self.stdout.write(f"  Créations      : {len(crees)}")
        self.stdout.write(f"  Mises à jour   : {len(majs)}")
        self.stdout.write(f"  Lignes en erreur : {len(erreurs)}")

        for prestataire in crees[:10]:
            self.stdout.write(self.style.SUCCESS(f"    + {prestataire.nom} ({prestataire.ville})"))
        if len(crees) > 10:
            self.stdout.write(f"    … et {len(crees) - 10} autre(s)")

        for numero, message in erreurs:
            self.stdout.write(self.style.ERROR(f"    ligne {numero} : {message}"))

        if simulation and not erreurs:
            self.stdout.write("\n  Relancez sans --dry-run pour appliquer.")
