from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from beneficiaires.models import Agent, AyantDroit
from parametrage.models import NatureSoin
from prestataires.models import Prestataire

# Fenêtre (en jours) dans laquelle un montant identique du même agent, chez
# le même prestataire, est considéré comme un doublon potentiel.
FENETRE_DOUBLON_JOURS = 5


class StatutPrescription(models.TextChoices):
    SOUMISE = "SOUMISE", "Soumise"
    EN_CONTROLE = "EN_CONTROLE", "En contrôle"
    VALIDEE = "VALIDEE", "Validée"
    REJETEE = "REJETEE", "Rejetée"


# Statuts qui ne peuvent être atteints que par une intervention manuelle du
# service mutuelle (jamais posés automatiquement à la création).
STATUTS_MANUELS = {StatutPrescription.VALIDEE, StatutPrescription.REJETEE}


class Prescription(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="prescriptions")
    ayant_droit = models.ForeignKey(
        AyantDroit,
        on_delete=models.CASCADE,
        related_name="prescriptions",
        null=True,
        blank=True,
        help_text="Laisser vide si la prescription concerne l'agent lui-même.",
    )
    prestataire = models.ForeignKey(Prestataire, on_delete=models.PROTECT, related_name="prescriptions")

    nature = models.ForeignKey(
        NatureSoin,
        on_delete=models.PROTECT,
        related_name="prescriptions",
        null=True,
        verbose_name="Nature du soin",
        help_text="Type de prestation reçue : consultation, pharmacie, hospitalisation…",
    )

    numero_ordonnance = models.CharField(max_length=100)
    montant_total = models.PositiveIntegerField(help_text="Montant en KMF (sans décimale).")
    montant_rembourse = models.PositiveIntegerField(editable=False, default=0)
    date_emission = models.DateField()
    justificatif = models.FileField(upload_to="justificatifs_prescriptions/")

    statut = models.CharField(max_length=20, choices=StatutPrescription.choices, default=StatutPrescription.SOUMISE)
    motif_signalement = models.TextField(blank=True)

    soumis_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="prescriptions_soumises",
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Prescription"
        verbose_name_plural = "Prescriptions"
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.numero_ordonnance} — {self.agent} — {self.montant_total}"

    def beneficiaire(self):
        return self.ayant_droit if self.ayant_droit_id else self.agent

    def detecter_doublons(self):
        """Retourne le queryset des prescriptions existantes qui rendent
        cette prescription suspecte : même agent, même prestataire, et
        (même numéro d'ordonnance) OU (montant identique à quelques jours
        d'écart)."""
        qs = Prescription.objects.filter(agent=self.agent, prestataire=self.prestataire).exclude(pk=self.pk)

        meme_numero = qs.filter(numero_ordonnance=self.numero_ordonnance)

        borne_min = self.date_emission - timedelta(days=FENETRE_DOUBLON_JOURS)
        borne_max = self.date_emission + timedelta(days=FENETRE_DOUBLON_JOURS)
        meme_montant = qs.filter(
            montant_total=self.montant_total,
            date_emission__gte=borne_min,
            date_emission__lte=borne_max,
        )

        return (meme_numero | meme_montant).distinct()

    def calculer_montant_rembourse(self):
        taux = self.prestataire.taux_pour(self.nature)
        montant = Decimal(self.montant_total) * taux / Decimal("100")
        return int(montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def clean(self):
        if self.ayant_droit_id and self.ayant_droit.agent_id != self.agent_id:
            raise ValidationError("L'ayant droit sélectionné n'appartient pas à cet agent.")

    def save(self, *args, detecter=True, **kwargs):
        """`detecter=False` charge la prescription telle quelle : réservé à
        l'import d'un historique déjà arbitré, dont les statuts et montants
        font foi et ne doivent pas être réécrits par les règles actuelles.
        """
        est_nouvelle = self._state.adding
        ancien_statut = None
        if not est_nouvelle:
            ancien_statut = Prescription.objects.get(pk=self.pk).statut

        if detecter:
            self.montant_rembourse = self.calculer_montant_rembourse() if self.prestataire.est_actif else 0

        if est_nouvelle and detecter:
            doublons = self.detecter_doublons()
            if doublons.exists():
                self.statut = StatutPrescription.EN_CONTROLE
                numeros = ", ".join(sorted(set(doublons.values_list("numero_ordonnance", flat=True))))
                self.motif_signalement = (
                    "Doublon potentiel détecté avec la/les prescription(s) portant le(s) "
                    f"numéro(s) {numeros} (même agent, même prestataire, numéro ou montant "
                    f"identique à ±{FENETRE_DOUBLON_JOURS} jours)."
                )
            if not self.prestataire.est_actif:
                self.statut = StatutPrescription.EN_CONTROLE
                self.motif_signalement = (self.motif_signalement + " " if self.motif_signalement else "") + (
                    "Prestataire suspendu : non éligible au remboursement."
                )

        super().save(*args, **kwargs)

        if est_nouvelle:
            HistoriqueStatut.objects.create(
                prescription=self,
                ancien_statut="",
                nouveau_statut=self.statut,
                utilisateur=self.soumis_par,
                commentaire="Soumission initiale." if detecter else "Reprise d'historique (import).",
            )
        elif ancien_statut and ancien_statut != self.statut:
            HistoriqueStatut.objects.create(
                prescription=self,
                ancien_statut=ancien_statut,
                nouveau_statut=self.statut,
            )

    def changer_statut(self, nouveau_statut, utilisateur=None, commentaire=""):
        """Point d'entrée unique pour un changement manuel de statut (RH /
        Direction), avec traçabilité horodatée."""
        ancien_statut = self.statut
        if ancien_statut == nouveau_statut:
            return
        self.statut = nouveau_statut
        super(Prescription, self).save(update_fields=["statut", "date_maj"])
        HistoriqueStatut.objects.create(
            prescription=self,
            ancien_statut=ancien_statut,
            nouveau_statut=nouveau_statut,
            utilisateur=utilisateur,
            commentaire=commentaire,
        )


class HistoriqueStatut(models.Model):
    """Trace horodatée de chaque changement de statut d'une prescription."""

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="historique")
    ancien_statut = models.CharField(max_length=20, blank=True)
    nouveau_statut = models.CharField(max_length=20)
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    commentaire = models.TextField(blank=True)
    date_changement = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Historique de statut"
        verbose_name_plural = "Historiques de statut"
        ordering = ["date_changement"]

    def __str__(self):
        return f"{self.prescription} : {self.ancien_statut or '—'} → {self.nouveau_statut}"
