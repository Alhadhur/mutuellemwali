"""Mesure le comportement des règles de détection de doublons sur les données
réellement présentes en base.

    ./venv/bin/python manage.py analyser_detection
    ./venv/bin/python manage.py analyser_detection --fenetres 1,3,5,7,10

Les deux critères actuels n'ont pas la même force : un même numéro d'ordonnance
est un signal quasi certain, alors qu'un même montant chez le même prestataire
peut simplement traduire un traitement chronique renouvelé. La commande sépare
donc les deux, pour décider en connaissance de cause du réglage de la fenêtre.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count

from prescriptions.models import FENETRE_DOUBLON_JOURS, Prescription, StatutPrescription


class Command(BaseCommand):
    help = "Analyse les règles de détection de doublons sur les données réelles."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--fenetres",
            type=str,
            default="",
            help="Fenêtres en jours à comparer, séparées par des virgules (ex. 1,3,5,7).",
        )

    def handle(self, *args, **options):
        total = Prescription.objects.count()
        if not total:
            self.stdout.write(self.style.WARNING("Aucune prescription en base : rien à analyser."))
            return

        self._volumetrie(total)
        self._par_critere()

        fenetres = self._fenetres(options["fenetres"])
        if fenetres:
            self._comparer_fenetres(fenetres)

        self._suspects_montant_repete()

    def _volumetrie(self, total):
        self.stdout.write(self.style.MIGRATE_HEADING("\nVOLUMÉTRIE"))
        self.stdout.write(f"  Prescriptions en base : {total}")
        for statut, libelle in StatutPrescription.choices:
            nombre = Prescription.objects.filter(statut=statut).count()
            part = nombre / total * 100
            self.stdout.write(f"    {libelle:<14} {nombre:>5}  ({part:.1f} %)")

    def _par_critere(self):
        """Rejoue les deux critères séparément pour connaître la part de
        signalements imputable à chacun."""
        self.stdout.write(self.style.MIGRATE_HEADING("\nPOIDS DE CHAQUE CRITÈRE"))

        par_numero = par_montant = par_les_deux = 0
        for prescription in Prescription.objects.select_related("prestataire"):
            autres = Prescription.objects.filter(
                agent_id=prescription.agent_id, prestataire_id=prescription.prestataire_id
            ).exclude(pk=prescription.pk)

            meme_numero = autres.filter(numero_ordonnance=prescription.numero_ordonnance).exists()
            borne = timedelta(days=FENETRE_DOUBLON_JOURS)
            meme_montant = autres.filter(
                montant_total=prescription.montant_total,
                date_emission__gte=prescription.date_emission - borne,
                date_emission__lte=prescription.date_emission + borne,
            ).exists()

            if meme_numero and meme_montant:
                par_les_deux += 1
            elif meme_numero:
                par_numero += 1
            elif meme_montant:
                par_montant += 1

        self.stdout.write(f"  Fenêtre appliquée : ±{FENETRE_DOUBLON_JOURS} jours")
        self.stdout.write(f"    Numéro d'ordonnance identique seul : {par_numero:>4}   (signal fort)")
        self.stdout.write(f"    Montant identique seul             : {par_montant:>4}   (signal faible, à surveiller)")
        self.stdout.write(f"    Les deux critères                  : {par_les_deux:>4}")
        if par_montant:
            self.stdout.write(
                self.style.WARNING(
                    "    → Ces signalements reposent sur le seul montant : vérifiez qu'il ne\n"
                    "      s'agit pas de traitements chroniques renouvelés au même prix."
                )
            )

    def _fenetres(self, brut):
        if not brut:
            return []
        return sorted({int(valeur) for valeur in brut.split(",") if valeur.strip().isdigit()})

    def _comparer_fenetres(self, fenetres):
        """Le seul paramètre réglable de la règle « même montant » est la
        largeur de la fenêtre : on montre son effet sur le volume d'alertes."""
        self.stdout.write(self.style.MIGRATE_HEADING("\nEFFET DE LA FENÊTRE SUR LE CRITÈRE « MÊME MONTANT »"))
        self.stdout.write("  Fenêtre   Prescriptions signalées")

        prescriptions = list(Prescription.objects.all())
        for jours in fenetres:
            borne = timedelta(days=jours)
            signalees = 0
            for prescription in prescriptions:
                if Prescription.objects.filter(
                    agent_id=prescription.agent_id,
                    prestataire_id=prescription.prestataire_id,
                    montant_total=prescription.montant_total,
                    date_emission__gte=prescription.date_emission - borne,
                    date_emission__lte=prescription.date_emission + borne,
                ).exclude(pk=prescription.pk).exists():
                    signalees += 1
            marque = "  ← réglage actuel" if jours == FENETRE_DOUBLON_JOURS else ""
            self.stdout.write(f"  ±{jours:<3} j    {signalees:>5}{marque}")

    def _suspects_montant_repete(self):
        """Un même couple (agent, prestataire, montant) qui revient souvent est
        le motif typique d'un faux positif : on le remonte pour arbitrage."""
        repetitions = (
            Prescription.objects.values("agent__utilisateur__matricule", "prestataire__nom", "montant_total")
            .annotate(nombre=Count("id"))
            .filter(nombre__gt=1)
            .order_by("-nombre")[:10]
        )
        if not repetitions:
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\nMONTANTS RÉPÉTÉS (faux positifs probables)"))
        for ligne in repetitions:
            self.stdout.write(
                f"  {ligne['nombre']}× {ligne['montant_total']} KMF — "
                f"agent {ligne['agent__utilisateur__matricule']} chez {ligne['prestataire__nom']}"
            )
