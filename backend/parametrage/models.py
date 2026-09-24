from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db import models


class Parametrage(models.Model):
    """Paramètres de la mutuelle, modifiables par le service RH / la direction
    depuis le back-office, sans intervention technique.

    Table volontairement limitée à une seule ligne (pk=1) : `save()` force la
    clé primaire et l'admin interdit l'ajout/suppression.
    """

    quota_mensuel_defaut = models.PositiveIntegerField(
        default=0,
        verbose_name="Quota mensuel par défaut (KMF)",
        help_text=(
            "Enveloppe mensuelle partagée entre un agent et ses ayants droit, "
            "appliquée aux agents sans quota personnalisé. En KMF, sans décimale."
        ),
    )
    age_limite_enfant = models.PositiveSmallIntegerField(
        default=18,
        verbose_name="Âge limite de couverture d'un enfant",
        help_text="Un enfant n'est plus couvert à partir de cet âge révolu.",
    )

    duree_cycle_mois = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Durée du cycle de quota (mois)",
        help_text=(
            "Nombre de mois pendant lesquels le quota du barème doit être consommé. "
            "À l'échéance, le quota est remis au montant plein : le reliquat non "
            "consommé est perdu, il ne se reporte pas."
        ),
    )

    cotisation_base = models.PositiveIntegerField(
        default=0,
        verbose_name="Cotisation mensuelle de base (KMF)",
        help_text="Montant dû par tout agent, couvrant les ayants droit inclus ci-dessous.",
    )
    conjoints_inclus = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Conjoints inclus dans la base",
        help_text="Au-delà, chaque conjoint est facturé en supplément.",
    )
    enfants_inclus = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Enfants inclus dans la base",
        help_text="Au-delà, chaque enfant est facturé en supplément.",
    )
    cout_conjoint_supplementaire = models.PositiveIntegerField(
        default=2000,
        verbose_name="Coût d'un conjoint supplémentaire (KMF)",
    )
    cout_enfant_supplementaire = models.PositiveIntegerField(
        default=2000,
        verbose_name="Coût d'un enfant supplémentaire (KMF)",
    )

    # --- Seuils de détection des anomalies ---------------------------------
    # Jusqu'ici figés dans le code : les remonter ici permet au service
    # mutuelle de régler la sensibilité sans intervention technique.
    fenetre_analyse_jours = models.PositiveSmallIntegerField(
        default=30,
        verbose_name="Fenêtre d'analyse des anomalies (jours)",
        help_text="Période observée par défaut sur l'écran des anomalies.",
    )
    seuil_volume_ecart_type = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.50"),
        verbose_name="Sensibilité du volume anormal (écarts-types)",
        help_text=(
            "Un prestataire est signalé quand son volume dépasse la moyenne du "
            "réseau de ce nombre d'écarts-types. Plus la valeur est basse, plus "
            "la détection est sensible (et bavarde)."
        ),
    )
    seuil_alerte_quota = models.PositiveSmallIntegerField(
        default=10,
        verbose_name="Seuil d'alerte sur le quota restant (%)",
        help_text="Un agent est signalé quand il lui reste moins que ce pourcentage de son enveloppe.",
    )

    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Paramètres de la mutuelle"
        verbose_name_plural = "Paramètres de la mutuelle"

    def __str__(self):
        return "Paramètres de la mutuelle"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def charger(cls):
        parametres, _ = cls.objects.get_or_create(pk=1)
        return parametres

    def periode(self, reference=None):
        """Bornes du cycle de quota contenant la date de référence.

        Les cycles sont calés sur l'année civile : le renouvellement tombe
        toujours au 1er janvier, quelle que soit la durée choisie. Une durée
        qui ne divise pas 12 laisse donc un dernier cycle plus court en fin
        d'année, plutôt qu'un décalage qui dériverait d'année en année.
        """
        reference = reference or date.today()
        duree = max(1, self.duree_cycle_mois)

        mois_debut = ((reference.month - 1) // duree) * duree + 1
        mois_fin = min(mois_debut + duree - 1, 12)

        debut = date(reference.year, mois_debut, 1)
        fin = date(reference.year, mois_fin, monthrange(reference.year, mois_fin)[1])
        return debut, fin


class ConditionPartenaire(models.TextChoices):
    INDIFFERENT = "INDIFFERENT", "Peu importe"
    AVEC = "AVEC", "Avec conjoint"
    SANS = "SANS", "Sans conjoint"


class TrancheQuota(models.Model):
    """Barème du quota **mensuel** selon la composition familiale.

    L'enveloppe réellement ouverte vaut ce montant multiplié par la durée du
    cycle de couverture.

    Les tranches sont évaluées dans l'ordre et **la première qui correspond
    l'emporte** : c'est ce qui permet de traiter un cas particulier en le
    plaçant avant une règle plus générale, sans toucher au code.
    """

    ordre = models.PositiveSmallIntegerField(
        default=10,
        help_text="Les tranches sont examinées du plus petit au plus grand ; la première qui correspond s'applique.",
    )
    libelle = models.CharField(max_length=120)
    partenaire = models.CharField(
        max_length=12,
        choices=ConditionPartenaire.choices,
        default=ConditionPartenaire.INDIFFERENT,
        verbose_name="Condition sur le conjoint",
    )
    enfants_min = models.PositiveSmallIntegerField(default=0, verbose_name="Nombre d'enfants minimum")
    enfants_max = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Nombre d'enfants maximum",
        help_text="Laisser vide pour « et plus ».",
    )
    montant = models.PositiveIntegerField(verbose_name="Quota mensuel (KMF)")

    class Meta:
        verbose_name = "Tranche de quota"
        verbose_name_plural = "Barème des quotas"
        ordering = ["ordre", "enfants_min"]

    def __str__(self):
        return f"{self.libelle} → {self.montant} KMF"

    def correspond(self, avec_conjoint: bool, nombre_enfants: int) -> bool:
        if self.partenaire == ConditionPartenaire.AVEC and not avec_conjoint:
            return False
        if self.partenaire == ConditionPartenaire.SANS and avec_conjoint:
            return False
        if nombre_enfants < self.enfants_min:
            return False
        return self.enfants_max is None or nombre_enfants <= self.enfants_max

    @classmethod
    def montant_pour(cls, avec_conjoint: bool, nombre_enfants: int):
        """Retourne le montant de la première tranche correspondante, ou None
        si aucune ne couvre ce cas — l'appelant décide alors du repli."""
        for tranche in cls.objects.all():
            if tranche.correspond(avec_conjoint, nombre_enfants):
                return tranche.montant
        return None


class NatureSoin(models.Model):
    """Nature du soin porté par une prescription : consultation, pharmacie,
    hospitalisation…

    La liste est en base et non dans le code : le service mutuelle l'adapte
    sans intervention technique, comme le barème. Une nature retirée est
    désactivée plutôt que supprimée, pour ne pas amputer l'historique des
    prescriptions déjà saisies.
    """

    ordre = models.PositiveSmallIntegerField(
        default=10,
        help_text="Ordre d'affichage dans les listes de saisie.",
    )
    libelle = models.CharField(max_length=100, unique=True, verbose_name="Nature du soin")
    active = models.BooleanField(
        default=True,
        verbose_name="Proposée à la saisie",
        help_text=(
            "Décocher retire la nature des nouveaux formulaires sans toucher "
            "aux prescriptions qui la portent déjà."
        ),
    )

    class Meta:
        verbose_name = "Nature de soin"
        verbose_name_plural = "Natures de soin"
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle

    @classmethod
    def proposables(cls):
        return cls.objects.filter(active=True)
