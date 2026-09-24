from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


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
