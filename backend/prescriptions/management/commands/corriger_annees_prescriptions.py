"""Corrige les prescriptions dont l'année de la date d'émission a été saisie
sur 2 chiffres au lieu de 4 (ex. « 26 » au lieu de « 2026 »).

Origine du problème : le champ date d'émission est un <input type="date">
du navigateur ; si l'année n'est pas complétée sur 4 chiffres avant l'envoi
du formulaire, rien côté serveur ne bloque une date aussi improbable. La
prescription reste normalement visible dans la liste, mais une année aussi
ancienne la fait disparaître de tous les rapports et tableaux de bord, qui
filtrent par période.

Usage :
    ./venv/bin/python manage.py corriger_annees_prescriptions            (aperçu, n'écrit rien)
    ./venv/bin/python manage.py corriger_annees_prescriptions --appliquer (corrige réellement)

La correction ajoute 2000 à l'année (26 → 2026) : une mise à jour directe du
seul champ date_emission, sans repasser par Prescription.save() — le montant
remboursé, le statut et l'historique ne doivent pas bouger, seule la date
était fausse.
"""
from django.core.management.base import BaseCommand

from prescriptions.models import Prescription


class Command(BaseCommand):
    help = "Corrige les prescriptions dont l'année de date d'émission est sur 2 chiffres (ex. 26 → 2026)."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--appliquer",
            action="store_true",
            help="Écrit réellement la correction. Sans cette option : aperçu seul, rien n'est modifié.",
        )

    def handle(self, *args, **options):
        suspectes = list(Prescription.objects.filter(date_emission__year__lt=100).order_by("date_emission"))

        if not suspectes:
            self.stdout.write(self.style.SUCCESS("Aucune date suspecte (année < 100) : rien à corriger."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{len(suspectes)} prescription(s) avec une année suspecte :"))
        for prescription in suspectes:
            nouvelle_date = prescription.date_emission.replace(year=prescription.date_emission.year + 2000)
            self.stdout.write(
                f"  {prescription.numero_ordonnance:<20} "
                f"{prescription.date_emission:%d/%m/%Y} → {nouvelle_date:%d/%m/%Y}"
            )

        if not options["appliquer"]:
            self.stdout.write(self.style.WARNING("\nAperçu seul : relancez avec --appliquer pour corriger."))
            return

        corrigees = 0
        for prescription in suspectes:
            nouvelle_date = prescription.date_emission.replace(year=prescription.date_emission.year + 2000)
            Prescription.objects.filter(pk=prescription.pk).update(date_emission=nouvelle_date)
            corrigees += 1

        self.stdout.write(self.style.SUCCESS(f"\n{corrigees} prescription(s) corrigée(s)."))
