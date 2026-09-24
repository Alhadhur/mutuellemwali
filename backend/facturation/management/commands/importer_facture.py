"""Import d'une facture mensuelle de prestataire depuis un fichier CSV.

    ./venv/bin/python manage.py importer_facture facture.csv \\
        --prestataire PHA-0001 --numero F-2026-03 --mois 3 --annee 2026 \\
        --total 450000 --dry-run

Colonnes attendues : `date`, `matricule`, `beneficiaire`, `nature`, `montant`.

Le soin coûte 100 %, dont l'agent règle sa part au guichet et la mutuelle le
reste. La colonne `montant` peut donc porter l'un ou l'autre : `--montant`
indique lequel (`total` ou `reclame`, ce dernier par défaut, puisque le
prestataire facture à la mutuelle ce qu'elle lui doit). Le montant manquant est
déduit du taux de la convention. Un fichier qui fournit explicitement les deux
colonnes (`montant_soin` et `montant_reclame`) prime sur cette déduction, et
permet de contrôler que le taux a bien été appliqué.

L'import se contente de charger les lignes puis de lancer le rapprochement : il
ne valide rien. La décision reste au service mutuelle, au vu des écarts.
"""
import csv
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from facturation.models import Facture, LigneFacture
from prestataires.models import Prestataire

COLONNES_ATTENDUES = {"date", "matricule", "beneficiaire", "nature"}
FORMATS_DATE = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


class LigneInvalide(Exception):
    pass


class Command(BaseCommand):
    help = "Importe une facture prestataire (entête + lignes) et lance le rapprochement."

    def add_arguments(self, parseur):
        parseur.add_argument("fichier", type=str)
        parseur.add_argument("--prestataire", required=True, help="Code ou nom du prestataire.")
        parseur.add_argument("--numero", required=True, help="Numéro de la facture.")
        parseur.add_argument("--mois", type=int, required=True)
        parseur.add_argument("--annee", type=int, required=True)
        parseur.add_argument("--total", type=int, required=True, help="Montant total annoncé sur la facture (KMF).")
        parseur.add_argument(
            "--montant",
            choices=("reclame", "total"),
            default="reclame",
            help="Ce que porte la colonne « montant » : la part réclamée à la mutuelle (défaut) ou le coût total du soin.",
        )
        parseur.add_argument("--dry-run", action="store_true")
        parseur.add_argument("--delimiteur", type=str, default="")

    def handle(self, *args, **options):
        chemin = Path(options["fichier"])
        if not chemin.exists():
            raise CommandError(f"Fichier introuvable : {chemin}")

        reference = options["prestataire"]
        prestataire = (
            Prestataire.objects.filter(code__iexact=reference).first()
            or Prestataire.objects.filter(nom__iexact=reference).first()
        )
        if not prestataire:
            raise CommandError(f"Prestataire « {reference} » introuvable (ni code, ni nom).")

        if not 1 <= options["mois"] <= 12:
            raise CommandError("Le mois doit être compris entre 1 et 12.")

        lignes = self._lire(chemin, options["delimiteur"])
        if not lignes:
            raise CommandError("Le fichier ne contient aucune ligne de données.")

        manquantes = COLONNES_ATTENDUES - set(lignes[0])
        if manquantes:
            raise CommandError(
                f"Colonnes obligatoires absentes : {', '.join(sorted(manquantes))}. "
                f"Colonnes lues : {', '.join(lignes[0])}."
            )

        if Facture.objects.filter(prestataire=prestataire, numero=options["numero"]).exists():
            raise CommandError(
                f"La facture « {options['numero'] } » de {prestataire.nom} est déjà enregistrée."
            )

        erreurs, importees = [], 0
        with transaction.atomic():
            facture = Facture.objects.create(
                prestataire=prestataire,
                numero=options["numero"],
                mois=options["mois"],
                annee=options["annee"],
                montant_total_declare=options["total"],
            )
            for numero, ligne in enumerate(lignes, start=2):
                try:
                    LigneFacture.objects.create(
                        facture=facture,
                        **self._analyser(ligne, prestataire.taux_prise_en_charge, options["montant"]),
                    )
                    importees += 1
                except LigneInvalide as erreur:
                    erreurs.append((numero, str(erreur)))

            if not erreurs:
                facture.rapprocher()

            # Le rapport interroge la base : il doit être produit avant
            # l'annulation, sinon une simulation n'afficherait que des zéros.
            self._rapport(facture, importees, erreurs, options["dry_run"])

            # Tout ou rien : une facture partiellement chargée fausserait le
            # rapprochement et laisserait croire à des soins non facturés.
            if options["dry_run"] or erreurs:
                transaction.set_rollback(True)

        if erreurs and not options["dry_run"]:
            raise CommandError(f"{len(erreurs)} ligne(s) en erreur : la facture n'a pas été enregistrée.")

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

    def _analyser(self, ligne, taux, colonne_montant):
        if not ligne["matricule"]:
            raise LigneInvalide("matricule vide")
        if not ligne["beneficiaire"]:
            raise LigneInvalide("bénéficiaire vide")

        soin, reclame = self._montants(ligne, taux, colonne_montant)
        return {
            "date_soin": self._date(ligne["date"]),
            "matricule": ligne["matricule"].upper(),
            "nom_beneficiaire": ligne["beneficiaire"],
            "nature": ligne["nature"],
            "montant_soin": soin,
            "montant_reclame": reclame,
        }

    def _montants(self, ligne, taux, colonne_montant):
        """Le fichier peut porter le coût total, la part réclamée, ou les deux.
        Le montant absent se déduit du taux de la convention."""
        soin = ligne.get("montant_soin", "")
        reclame = ligne.get("montant_reclame", "")

        if soin and reclame:
            return self._montant(soin), self._montant(reclame)
        if soin:
            return self._montant(soin), self._part_mutuelle(self._montant(soin), taux)
        if reclame:
            return self._cout_total(self._montant(reclame), taux), self._montant(reclame)

        brut = ligne.get("montant", "")
        if not brut:
            raise LigneInvalide("aucun montant (colonne « montant », « montant_soin » ou « montant_reclame »)")
        valeur = self._montant(brut)
        if colonne_montant == "total":
            return valeur, self._part_mutuelle(valeur, taux)
        return self._cout_total(valeur, taux), valeur

    def _part_mutuelle(self, cout_total, taux):
        montant = Decimal(cout_total) * taux / Decimal("100")
        return int(montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def _cout_total(self, part_mutuelle, taux):
        if taux <= 0:
            raise LigneInvalide("taux de prise en charge nul : coût total indéductible")
        montant = Decimal(part_mutuelle) * Decimal("100") / taux
        return int(montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def _date(self, brut):
        for format_date in FORMATS_DATE:
            try:
                return datetime.strptime(brut, format_date).date()
            except ValueError:
                continue
        raise LigneInvalide(f"date « {brut} » illisible (formats acceptés : {', '.join(FORMATS_DATE)})")

    def _montant(self, brut):
        nettoye = brut.replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            valeur = float(nettoye)
        except ValueError:
            raise LigneInvalide(f"montant « {brut} » illisible")
        if valeur <= 0:
            raise LigneInvalide("montant nul ou négatif")
        return int(round(valeur))

    def _rapport(self, facture, importees, erreurs, simulation):
        titre = "SIMULATION (aucune écriture)" if simulation else "FACTURE ENREGISTRÉE"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{titre}"))
        self.stdout.write(f"  Lignes lues      : {importees}")
        self.stdout.write(f"  Lignes en erreur : {len(erreurs)}")
        for numero, message in erreurs[:20]:
            self.stdout.write(self.style.ERROR(f"    ligne {numero} : {message}"))

        if erreurs:
            return

        synthese = facture.synthese()
        self.stdout.write(self.style.MIGRATE_HEADING("\nRAPPROCHEMENT"))
        self.stdout.write(f"  Concordantes                  : {synthese['concordantes']:>4}")
        self.stdout.write(self.style.WARNING(f"  Écarts de montant             : {synthese['ecarts_montant']:>4}"))
        self.stdout.write(self.style.WARNING(f"  Taux mal appliqué             : {synthese['ecarts_taux']:>4}"))
        self.stdout.write(self.style.ERROR(f"  Facturées sans prescription   : {synthese['sans_prescription']:>4}"))
        self.stdout.write(self.style.ERROR(f"  Déclarées mais non facturées  : {synthese['non_facturees']:>4}"))
        if synthese["agents_inconnus"]:
            self.stdout.write(self.style.WARNING(f"  Matricules inconnus           : {synthese['agents_inconnus']:>4}"))
        if synthese["ecart_total"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\n  Total annoncé {facture.montant_total_declare} KMF, somme des lignes "
                    f"{facture.montant_total_lignes} KMF — écart de {synthese['ecart_total']} KMF."
                )
            )

        if simulation:
            self.stdout.write("\n  Relancez sans --dry-run pour enregistrer.")
        else:
            self.stdout.write("\n  Facture à arbitrer dans le back-office : aucune prescription n'a été validée.")
