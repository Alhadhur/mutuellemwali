"""Factures mensuelles des prestataires conventionnés.

L'intérêt de ces factures n'est pas comptable mais de contrôle : confrontée aux
prescriptions déclarées, une facture fait ressortir trois anomalies que rien
d'autre ne révèle —

* une ligne facturée **sans prescription** : le prestataire facture un soin que
  personne n'a déclaré ;
* une prescription **non facturée** : l'agent a déclaré un soin que le
  prestataire ne réclame pas, cas typique de la fausse ordonnance ;
* un **écart de montant** entre ce qui est déclaré et ce qui est facturé.
"""
from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone

from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire

MOIS = [
    (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
    (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
    (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
]


class StatutFacture(models.TextChoices):
    RECUE = "RECUE", "Reçue"
    RAPPROCHEE = "RAPPROCHEE", "Rapprochée"
    VALIDEE = "VALIDEE", "Validée"
    CONTESTEE = "CONTESTEE", "Contestée"


class StatutLigne(models.TextChoices):
    A_RAPPROCHER = "A_RAPPROCHER", "À rapprocher"
    CONCORDANTE = "CONCORDANTE", "Concordante"
    ECART_MONTANT = "ECART_MONTANT", "Écart de montant"
    ECART_TAUX = "ECART_TAUX", "Taux mal appliqué"
    SANS_PRESCRIPTION = "SANS_PRESCRIPTION", "Aucune prescription déclarée"
    AGENT_INCONNU = "AGENT_INCONNU", "Matricule inconnu"


class Facture(models.Model):
    prestataire = models.ForeignKey(Prestataire, on_delete=models.PROTECT, related_name="factures")
    numero = models.CharField(max_length=60, verbose_name="N° de facture")
    mois = models.PositiveSmallIntegerField(choices=MOIS, verbose_name="Mois facturé")
    annee = models.PositiveSmallIntegerField(verbose_name="Année")

    date_reception = models.DateField(default=timezone.localdate)
    montant_total_declare = models.PositiveIntegerField(
        verbose_name="Total réclamé à la mutuelle (KMF)",
        help_text="Total figurant sur la facture ; comparé à la somme réclamée sur les lignes.",
    )
    fichier = models.FileField(upload_to="factures/", blank=True)

    statut = models.CharField(max_length=20, choices=StatutFacture.choices, default=StatutFacture.RECUE)
    commentaire = models.TextField(blank=True)

    saisie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures_saisies"
    )
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures_validees"
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Facture prestataire"
        verbose_name_plural = "Factures prestataires"
        ordering = ["-annee", "-mois", "prestataire"]
        constraints = [
            models.UniqueConstraint(
                fields=["prestataire", "numero"], name="numero_facture_unique_par_prestataire"
            )
        ]

    def __str__(self):
        return f"{self.numero} — {self.prestataire.nom} ({self.get_mois_display()} {self.annee})"

    @property
    def montant_total_lignes(self):
        return self.lignes.aggregate(models.Sum("montant_reclame"))["montant_reclame__sum"] or 0

    @property
    def ecart_total(self):
        """Différence entre le total annoncé et la somme réelle des lignes."""
        return self.montant_total_declare - self.montant_total_lignes

    @property
    def periode(self):
        from calendar import monthrange

        return date(self.annee, self.mois, 1), date(self.annee, self.mois, monthrange(self.annee, self.mois)[1])

    def prescriptions_de_la_periode(self):
        debut, fin = self.periode
        return Prescription.objects.filter(
            prestataire=self.prestataire, date_emission__gte=debut, date_emission__lte=fin
        ).select_related("agent__utilisateur", "ayant_droit")

    def prescriptions_non_facturees(self):
        """Soins déclarés par les agents que le prestataire ne facture pas.

        C'est l'anomalie la plus grave : elle peut révéler une ordonnance
        fabriquée de toutes pièces."""
        rapprochees = self.lignes.exclude(prescription__isnull=True).values_list("prescription_id", flat=True)
        return self.prescriptions_de_la_periode().exclude(pk__in=rapprochees)

    def rapprocher(self):
        """Confronte chaque ligne aux prescriptions de la période.

        N'écrit aucun statut de prescription : le rapprochement éclaire la
        décision, il ne la prend pas."""
        from beneficiaires.models import Agent

        deja_prises = set()
        for ligne in self.lignes.all():
            agent = Agent.objects.filter(utilisateur__matricule__iexact=ligne.matricule).first()
            if not agent:
                ligne.prescription = None
                ligne.statut = StatutLigne.AGENT_INCONNU
                ligne.save()
                continue

            candidates = self.prescriptions_de_la_periode().filter(
                agent=agent, date_emission=ligne.date_soin
            ).exclude(pk__in=deja_prises)

            exacte = candidates.filter(montant_total=ligne.montant_soin).first()
            if exacte:
                ligne.prescription = exacte
                deja_prises.add(exacte.pk)
                # Le coût du soin concorde : reste à vérifier que le
                # prestataire ne réclame pas plus que son taux ne l'autorise.
                ligne.statut = (
                    StatutLigne.CONCORDANTE if ligne.ecart_taux == 0 else StatutLigne.ECART_TAUX
                )
            else:
                approchante = candidates.first()
                if approchante:
                    ligne.prescription = approchante
                    ligne.statut = StatutLigne.ECART_MONTANT
                    deja_prises.add(approchante.pk)
                else:
                    ligne.prescription = None
                    ligne.statut = StatutLigne.SANS_PRESCRIPTION
            ligne.save()

        self.statut = StatutFacture.RAPPROCHEE
        self.save()

    def synthese(self):
        lignes = self.lignes.all()
        return {
            "nombre_lignes": lignes.count(),
            "concordantes": lignes.filter(statut=StatutLigne.CONCORDANTE).count(),
            "ecarts_montant": lignes.filter(statut=StatutLigne.ECART_MONTANT).count(),
            "ecarts_taux": lignes.filter(statut=StatutLigne.ECART_TAUX).count(),
            "sans_prescription": lignes.filter(statut=StatutLigne.SANS_PRESCRIPTION).count(),
            "agents_inconnus": lignes.filter(statut=StatutLigne.AGENT_INCONNU).count(),
            "non_facturees": self.prescriptions_non_facturees().count(),
            "ecart_total": self.ecart_total,
        }

    def valider(self, utilisateur):
        """Le service mutuelle valide la facture ; les prescriptions dont la
        ligne concorde exactement passent alors en « Validée », avec la
        référence de la facture dans leur historique.

        Les lignes en écart ne valident rien : elles restent à arbitrer une
        par une.
        """
        validees = 0
        for ligne in self.lignes.filter(statut=StatutLigne.CONCORDANTE).select_related("prescription"):
            prescription = ligne.prescription
            if prescription and prescription.statut != StatutPrescription.VALIDEE:
                prescription.changer_statut(
                    StatutPrescription.VALIDEE,
                    utilisateur=utilisateur,
                    commentaire=f"Confirmée par la facture {self.numero} du prestataire.",
                )
                validees += 1

        self.statut = StatutFacture.VALIDEE
        self.validee_par = utilisateur
        self.date_validation = timezone.now()
        self.save()
        return validees


class LigneFacture(models.Model):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name="lignes")

    date_soin = models.DateField()
    matricule = models.CharField(max_length=20, help_text="Matricule de l'agent, tel qu'indiqué sur la facture.")
    nom_beneficiaire = models.CharField(max_length=150)
    nature = models.CharField(max_length=255, verbose_name="Nature du soin")

    montant_soin = models.PositiveIntegerField(
        verbose_name="Coût total du soin (KMF)",
        help_text="Les 100 % : part agent comprise.",
    )
    montant_reclame = models.PositiveIntegerField(
        verbose_name="Montant réclamé à la mutuelle (KMF)",
        help_text="La part prise en charge, soit le coût total × taux du prestataire.",
    )

    prescription = models.ForeignKey(
        Prescription, on_delete=models.SET_NULL, null=True, blank=True, related_name="lignes_facture"
    )
    statut = models.CharField(max_length=20, choices=StatutLigne.choices, default=StatutLigne.A_RAPPROCHER)
    commentaire = models.TextField(blank=True)

    class Meta:
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"
        ordering = ["date_soin", "matricule"]

    def __str__(self):
        return f"{self.date_soin} — {self.matricule} — {self.montant_soin} KMF"

    @property
    def ecart_montant(self):
        if not self.prescription:
            return None
        return self.montant_soin - self.prescription.montant_total

    @property
    def montant_reclame_attendu(self):
        """Ce que le prestataire devrait réclamer, au taux de sa convention."""
        from decimal import ROUND_HALF_UP, Decimal

        taux = self.facture.prestataire.taux_prise_en_charge
        montant = Decimal(self.montant_soin) * taux / Decimal("100")
        return int(montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def ecart_taux(self):
        return self.montant_reclame - self.montant_reclame_attendu
