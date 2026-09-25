from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from parametrage.models import NatureSoin


class TypePrestataire(models.TextChoices):
    PHARMACIE = "PHARMACIE", "Pharmacie"
    ETABLISSEMENT = "ETABLISSEMENT", "Établissement médical (clinique, hôpital)"
    PRATICIEN = "PRATICIEN", "Praticien (médecin, urgentiste)"


class StatutPrestataire(models.TextChoices):
    ACTIF = "ACTIF", "Actif"
    SUSPENDU = "SUSPENDU", "Suspendu"


PREFIXES_CODE = {
    TypePrestataire.PHARMACIE: "PHA",
    TypePrestataire.ETABLISSEMENT: "ETB",
    TypePrestataire.PRATICIEN: "PRA",
}


class Prestataire(models.Model):
    """Prestataire de santé conventionné : pharmacie, établissement médical
    ou praticien."""

    code = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    type_prestataire = models.CharField(max_length=20, choices=TypePrestataire.choices)
    nom = models.CharField(max_length=150)
    ville = models.CharField(max_length=100, blank=True)
    adresse = models.CharField(max_length=255, blank=True)
    telephone = models.CharField(max_length=30, blank=True)

    taux_prise_en_charge = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=80,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Pourcentage prix en charge par la mutuelle (ex. 80 = mutuelle rembourse 80%, agent paie 20%).",
    )
    statut = models.CharField(max_length=20, choices=StatutPrestataire.choices, default=StatutPrestataire.ACTIF)

    # Compte de connexion optionnel, pour la saisie directe par le
    # prestataire lui-même (phase ultérieure).
    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prestataire",
    )

    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Prestataire conventionné"
        verbose_name_plural = "Prestataires conventionnés"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.nom} ({self.get_statut_display()})"

    def save(self, *args, **kwargs):
        if not self.code:
            prefix = PREFIXES_CODE[self.type_prestataire]
            dernier = (
                Prestataire.objects.filter(code__startswith=f"{prefix}-")
                .order_by("-code")
                .first()
            )
            if dernier:
                dernier_num = int(dernier.code.split("-")[-1])
            else:
                dernier_num = 0
            self.code = f"{prefix}-{dernier_num + 1:04d}"
        super().save(*args, **kwargs)

    @property
    def est_actif(self):
        return self.statut == StatutPrestataire.ACTIF

    def taux_pour(self, nature_soin):
        """Taux applicable pour une nature de soin donnée : le tarif détaillé
        s'il existe, sinon le taux général du prestataire — un établissement
        qui n'a pas encore été détaillé continue de fonctionner comme avant."""
        if nature_soin is not None:
            tarif = self.tarifs.filter(nature_soin=nature_soin).first()
            if tarif is not None:
                return tarif.taux_prise_en_charge
        return self.taux_prise_en_charge

    def natures_proposees(self):
        """Natures de soin actives réellement tarifées chez ce prestataire —
        sert à restreindre la saisie mobile. Vide tant qu'aucun tarif détaillé
        n'a été configuré : l'appelant doit alors se rabattre sur la liste
        complète des natures, pour ne pas bloquer un prestataire pas encore
        détaillé."""
        return NatureSoin.objects.filter(tarifs__prestataire=self, active=True).order_by("ordre")


class TarifPrestataire(models.Model):
    """Taux de prise en charge d'une nature de soin précise chez ce
    prestataire, qui remplace pour ce couple le taux général ci-dessus.

    Un établissement (hôpital, clinique) propose plusieurs services à des
    taux différents — une consultation ne coûte pas comme une chirurgie.
    Un prestataire sans aucun tarif ici (le cas le plus courant : pharmacies,
    praticiens, ou tout établissement pas encore détaillé) reste au taux
    général : ajouter cette précision n'est pas une migration cassante.
    """

    prestataire = models.ForeignKey(Prestataire, on_delete=models.CASCADE, related_name="tarifs")
    nature_soin = models.ForeignKey(NatureSoin, on_delete=models.CASCADE, related_name="tarifs")
    taux_prise_en_charge = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Pourcentage pris en charge par la mutuelle pour cette nature de soin chez ce prestataire.",
    )

    class Meta:
        verbose_name = "Tarif par nature de soin"
        verbose_name_plural = "Tarifs par nature de soin"
        ordering = ["nature_soin__ordre"]
        constraints = [
            models.UniqueConstraint(fields=["prestataire", "nature_soin"], name="unique_tarif_prestataire_nature")
        ]

    def __str__(self):
        return f"{self.prestataire.nom} — {self.nature_soin.libelle} : {self.taux_prise_en_charge}%"
