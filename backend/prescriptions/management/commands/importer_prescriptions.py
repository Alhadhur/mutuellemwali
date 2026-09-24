"""Reprise d'un historique de prescriptions depuis un fichier CSV.

    # 1. Confronter les règles actuelles à l'historique, sans rien écrire
    ./venv/bin/python manage.py importer_prescriptions historique.csv --mode rejouer

    # 2. Charger l'historique tel qu'il a été arbitré
    ./venv/bin/python manage.py importer_prescriptions historique.csv --dry-run
    ./venv/bin/python manage.py importer_prescriptions historique.csv

Deux modes, pour deux besoins distincts :

* `conserver` (défaut) écrit les lignes avec le statut et le montant remboursé
  du fichier. C'est l'historique qui fait foi : les règles d'aujourd'hui ne
  doivent pas réécrire des décisions déjà prises.
* `rejouer` n'écrit rien. Il applique les règles actuelles à chaque ligne et
  compare le verdict obtenu au statut réel, ce qui mesure les faux positifs
  et — surtout — les fraudes que les règles auraient laissé passer.
"""
import csv
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from beneficiaires.models import Agent, AyantDroit
from prescriptions.models import FENETRE_DOUBLON_JOURS, Prescription, StatutPrescription
from prestataires.models import Prestataire

COLONNES_ATTENDUES = {"agent", "prestataire", "numero_ordonnance", "montant_total", "date_emission"}

FORMATS_DATE = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")

STATUTS = {libelle.lower(): valeur for valeur, libelle in StatutPrescription.choices}
STATUTS.update({valeur.lower(): valeur for valeur in StatutPrescription.values})
STATUTS.update({"valide": StatutPrescription.VALIDEE, "rejete": StatutPrescription.REJETEE})


class LigneInvalide(Exception):
    pass


class Command(BaseCommand):
    help = "Importe un historique de prescriptions, ou confronte les règles de détection à cet historique."

    def add_arguments(self, parseur):
        parseur.add_argument("fichier", type=str)
        parseur.add_argument(
            "--mode",
            choices=("conserver", "rejouer"),
            default="conserver",
            help="conserver : charge l'historique tel quel. rejouer : compare les règles à l'historique, sans écrire.",
        )
        parseur.add_argument("--dry-run", action="store_true", help="Analyse sans écrire.")
        parseur.add_argument("--delimiteur", type=str, default="")

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

        if options["mode"] == "rejouer":
            self._rejouer(lignes)
        else:
            self._conserver(lignes, options["dry_run"])

    # --- lecture ----------------------------------------------------------

    def _lire(self, chemin, delimiteur):
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

    def _analyser(self, ligne):
        """Traduit une ligne du fichier en objets métier, sans rien écrire."""
        matricule = ligne["agent"]
        agent = Agent.objects.filter(utilisateur__matricule__iexact=matricule).first()
        if not agent:
            raise LigneInvalide(f"agent « {matricule} » introuvable")

        reference = ligne["prestataire"]
        prestataire = (
            Prestataire.objects.filter(code__iexact=reference).first()
            or Prestataire.objects.filter(nom__iexact=reference).first()
        )
        if not prestataire:
            raise LigneInvalide(f"prestataire « {reference} » introuvable (ni code, ni nom)")

        ayant_droit = None
        nom_ayant_droit = ligne.get("ayant_droit", "")
        if nom_ayant_droit:
            ayant_droit = self._trouver_ayant_droit(agent, nom_ayant_droit)

        return {
            "agent": agent,
            "prestataire": prestataire,
            "ayant_droit": ayant_droit,
            "numero_ordonnance": ligne["numero_ordonnance"] or "",
            "montant_total": self._entier(ligne["montant_total"], "montant_total"),
            "date_emission": self._date(ligne["date_emission"]),
            "statut": self._statut(ligne.get("statut", "")),
            "montant_rembourse": (
                self._entier(ligne["montant_rembourse"], "montant_rembourse")
                if ligne.get("montant_rembourse")
                else None
            ),
        }

    def _trouver_ayant_droit(self, agent, libelle):
        for candidat in agent.ayants_droit.all():
            noms = {f"{candidat.prenom} {candidat.nom}".lower(), f"{candidat.nom} {candidat.prenom}".lower()}
            if libelle.lower() in noms:
                return candidat
        raise LigneInvalide(f"ayant droit « {libelle} » non rattaché à l'agent {agent.matricule}")

    def _entier(self, brut, champ):
        nettoye = brut.replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            valeur = float(nettoye)
        except ValueError:
            raise LigneInvalide(f"{champ} « {brut } » illisible")
        if valeur < 0:
            raise LigneInvalide(f"{champ} négatif")
        # Le KMF n'a pas de sous-unité : on arrondit au franc le plus proche.
        return int(round(valeur))

    def _date(self, brut):
        for format_date in FORMATS_DATE:
            try:
                return datetime.strptime(brut, format_date).date()
            except ValueError:
                continue
        raise LigneInvalide(f"date « {brut} » illisible (formats acceptés : {', '.join(FORMATS_DATE)})")

    def _statut(self, brut):
        if not brut:
            return StatutPrescription.SOUMISE
        statut = STATUTS.get(brut.lower())
        if not statut:
            raise LigneInvalide(f"statut « {brut} » inconnu")
        return statut

    # --- mode conserver ---------------------------------------------------

    def _conserver(self, lignes, simulation):
        importees, erreurs = 0, []
        with transaction.atomic():
            for numero, ligne in enumerate(lignes, start=2):
                try:
                    donnees = self._analyser(ligne)
                except LigneInvalide as erreur:
                    erreurs.append((numero, str(erreur)))
                    continue

                prescription = Prescription(
                    agent=donnees["agent"],
                    ayant_droit=donnees["ayant_droit"],
                    prestataire=donnees["prestataire"],
                    numero_ordonnance=donnees["numero_ordonnance"],
                    montant_total=donnees["montant_total"],
                    date_emission=donnees["date_emission"],
                    statut=donnees["statut"],
                    justificatif=ligne.get("justificatif", ""),
                )
                prescription.montant_rembourse = (
                    donnees["montant_rembourse"]
                    if donnees["montant_rembourse"] is not None
                    else prescription.calculer_montant_rembourse()
                )
                prescription.save(detecter=False)
                importees += 1

            # Tout ou rien : un historique à moitié chargé fausserait toutes
            # les analyses ultérieures.
            if simulation or erreurs:
                transaction.set_rollback(True)

        titre = "SIMULATION (aucune écriture)" if simulation else "IMPORT EFFECTUÉ"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{titre}"))
        self.stdout.write(f"  Prescriptions reprises : {importees}")
        self.stdout.write(f"  Lignes en erreur       : {len(erreurs)}")
        for numero, message in erreurs[:20]:
            self.stdout.write(self.style.ERROR(f"    ligne {numero} : {message}"))
        if len(erreurs) > 20:
            self.stdout.write(f"    … et {len(erreurs) - 20} autre(s)")

        if erreurs and not simulation:
            raise CommandError(f"{len(erreurs)} ligne(s) en erreur : rien n'a été importé.")
        if simulation and not erreurs:
            self.stdout.write("\n  Relancez sans --dry-run pour appliquer.")

    # --- mode rejouer -----------------------------------------------------

    def _rejouer(self, lignes):
        """Confronte le verdict des règles au statut réellement retenu."""
        vrais_positifs = faux_positifs = manques = concordances = 0
        erreurs, exemples_manques, exemples_faux_positifs = [], [], []

        # Les lignes se comparent entre elles : on les analyse toutes d'abord.
        analysees = []
        for numero, ligne in enumerate(lignes, start=2):
            try:
                analysees.append((numero, self._analyser(ligne)))
            except LigneInvalide as erreur:
                erreurs.append((numero, str(erreur)))

        for numero, donnees in analysees:
            signalee = self._regle_se_declenche(donnees, analysees)
            suspecte = donnees["statut"] in (StatutPrescription.EN_CONTROLE, StatutPrescription.REJETEE)

            if signalee and suspecte:
                vrais_positifs += 1
            elif signalee and not suspecte:
                faux_positifs += 1
                if len(exemples_faux_positifs) < 5:
                    exemples_faux_positifs.append((numero, donnees))
            elif not signalee and suspecte:
                manques += 1
                if len(exemples_manques) < 5:
                    exemples_manques.append((numero, donnees))
            else:
                concordances += 1

        total = len(analysees)
        self.stdout.write(self.style.MIGRATE_HEADING("\nCONFRONTATION DES RÈGLES À L'HISTORIQUE"))
        self.stdout.write(f"  Lignes exploitables : {total}   (fenêtre ±{FENETRE_DOUBLON_JOURS} jours)")
        if erreurs:
            self.stdout.write(self.style.WARNING(f"  Lignes ignorées     : {len(erreurs)}"))
            for numero, message in erreurs[:10]:
                self.stdout.write(self.style.ERROR(f"    ligne {numero} : {message}"))

        if not total:
            return

        self.stdout.write("")
        self.stdout.write(f"  Détectées et effectivement suspectes : {vrais_positifs:>5}")
        self.stdout.write(f"  Non détectées et non suspectes       : {concordances:>5}")
        self.stdout.write(self.style.WARNING(f"  Fausses alertes                      : {faux_positifs:>5}"))
        self.stdout.write(self.style.ERROR(f"  Fraudes NON détectées                : {manques:>5}"))

        detectables = vrais_positifs + manques
        if detectables:
            rappel = vrais_positifs / detectables * 100
            self.stdout.write(f"\n  Taux de détection des cas suspects : {rappel:.1f} %")
        signalees = vrais_positifs + faux_positifs
        if signalees:
            precision = vrais_positifs / signalees * 100
            self.stdout.write(f"  Part d'alertes justifiées          : {precision:.1f} %")

        if exemples_manques:
            self.stdout.write(self.style.MIGRATE_HEADING("\nCAS SUSPECTS QUE LES RÈGLES LAISSENT PASSER"))
            for numero, donnees in exemples_manques:
                self.stdout.write(
                    f"  ligne {numero} : {donnees['numero_ordonnance']} — {donnees['montant_total']} KMF — "
                    f"{donnees['agent'].matricule} chez {donnees['prestataire'].nom} — statut réel {donnees['statut']}"
                )
            self.stdout.write("  → Ces cas justifient d'ajouter un critère de détection.")

        if exemples_faux_positifs:
            self.stdout.write(self.style.MIGRATE_HEADING("\nALERTES QUI SERAIENT INJUSTIFIÉES"))
            for numero, donnees in exemples_faux_positifs:
                self.stdout.write(
                    f"  ligne {numero} : {donnees['numero_ordonnance']} — {donnees['montant_total']} KMF — "
                    f"{donnees['agent'].matricule} chez {donnees['prestataire'].nom} — statut réel {donnees['statut']}"
                )
            self.stdout.write("  → Charge de travail inutile pour le service mutuelle.")

        self.stdout.write("\n  Aucune écriture effectuée.")

    def _regle_se_declenche(self, donnees, analysees):
        """Réplique la règle de `Prescription.detecter_doublons`, mais sur les
        lignes du fichier : l'historique n'est pas encore en base."""
        for _, autre in analysees:
            if autre is donnees:
                continue
            if autre["agent"].pk != donnees["agent"].pk:
                continue
            if autre["prestataire"].pk != donnees["prestataire"].pk:
                continue
            if autre["numero_ordonnance"] == donnees["numero_ordonnance"]:
                return True
            ecart = abs((autre["date_emission"] - donnees["date_emission"]).days)
            if autre["montant_total"] == donnees["montant_total"] and ecart <= FENETRE_DOUBLON_JOURS:
                return True
        return False
