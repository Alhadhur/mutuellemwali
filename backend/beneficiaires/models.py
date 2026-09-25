from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone

from parametrage.models import Parametrage, TrancheQuota


class LienParente(models.TextChoices):
    CONJOINT = "CONJOINT", "Conjoint(e)"
    ENFANT = "ENFANT", "Enfant"
    AUTRE = "AUTRE", "Autre"


class TypeJustificatif(models.TextChoices):
    ACTE_MARIAGE = "ACTE_MARIAGE", "Acte de mariage"
    ACTE_NAISSANCE = "ACTE_NAISSANCE", "Acte de naissance"
    CERTIFICAT_SCOLARITE = "CERTIFICAT_SCOLARITE", "Certificat de scolarité"
    AUTRE = "AUTRE", "Autre justificatif"


class StatutVerification(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    VALIDE = "VALIDE", "Validé"
    REJETE = "REJETE", "Rejeté"


class Agent(models.Model):
    """Fiche agent (bénéficiaire principal).

    L'agent porte l'enveloppe de remboursement de toute la famille : ses
    propres soins et ceux de ses ayants droit puisent dans le même quota.
    """

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent"
    )
    site = models.CharField(max_length=100)
    date_naissance = models.DateField()
    date_embauche = models.DateField()
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Agent"
        verbose_name_plural = "Agents"
        ordering = ["utilisateur__matricule"]

    def __str__(self):
        return f"{self.utilisateur.matricule} — {self.utilisateur.get_full_name()}"

    @property
    def matricule(self):
        return self.utilisateur.matricule

    @property
    def ayants_droit_couverts(self):
        """Seuls les ayants droit vérifiés et encore couverts entrent dans le
        calcul : un dossier rejeté ou un enfant au-delà de l'âge limite ne
        donne droit à rien et ne se facture pas."""
        return [
            ayant_droit
            for ayant_droit in self.ayants_droit.all()
            if ayant_droit.statut_verification == StatutVerification.VALIDE
            and not ayant_droit.limite_age_depassee
        ]

    @property
    def nombre_conjoints(self):
        return sum(1 for a in self.ayants_droit_couverts if a.lien_parente == LienParente.CONJOINT)

    @property
    def nombre_enfants(self):
        return sum(1 for a in self.ayants_droit_couverts if a.lien_parente == LienParente.ENFANT)

    @property
    def quota_mensuel(self):
        """Montant mensuel issu du barème, selon la composition familiale. Le
        quota par défaut du paramétrage sert de repli si aucune tranche ne
        couvre le cas, pour ne jamais renvoyer un montant indéfini."""
        montant = TrancheQuota.montant_pour(
            avec_conjoint=self.nombre_conjoints > 0, nombre_enfants=self.nombre_enfants
        )
        if montant is None:
            return Parametrage.charger().quota_mensuel_defaut
        return montant

    @property
    def quota_effectif(self):
        """Enveloppe de la famille pour tout le cycle : le montant mensuel
        multiplié par la durée de couverture."""
        return self.quota_mensuel * max(1, Parametrage.charger().duree_cycle_mois)

    @property
    def cotisation_mensuelle(self):
        """Cotisation de base, majorée de chaque ayant droit au-delà de ceux
        que la base inclut."""
        parametres = Parametrage.charger()
        conjoints_en_trop = max(0, self.nombre_conjoints - parametres.conjoints_inclus)
        enfants_en_trop = max(0, self.nombre_enfants - parametres.enfants_inclus)
        return (
            parametres.cotisation_base
            + conjoints_en_trop * parametres.cout_conjoint_supplementaire
            + enfants_en_trop * parametres.cout_enfant_supplementaire
        )

    @property
    def detail_cotisation(self):
        """Décomposition affichée au service mutuelle, pour justifier le
        montant auprès de l'agent."""
        parametres = Parametrage.charger()
        conjoints_en_trop = max(0, self.nombre_conjoints - parametres.conjoints_inclus)
        enfants_en_trop = max(0, self.nombre_enfants - parametres.enfants_inclus)
        lignes = [("Cotisation de base", parametres.cotisation_base)]
        if conjoints_en_trop:
            lignes.append(
                (
                    f"{conjoints_en_trop} conjoint(s) au-delà de {parametres.conjoints_inclus} inclus",
                    conjoints_en_trop * parametres.cout_conjoint_supplementaire,
                )
            )
        if enfants_en_trop:
            lignes.append(
                (
                    f"{enfants_en_trop} enfant(s) au-delà de {parametres.enfants_inclus} inclus",
                    enfants_en_trop * parametres.cout_enfant_supplementaire,
                )
            )
        return lignes

    def periode_courante(self, reference=None):
        return Parametrage.charger().periode(reference)

    def consommation_periode(self, reference=None):
        """Consommation de toute la famille sur le cycle en cours :
        prescriptions validées de l'agent lui-même **et** de ses ayants droit,
        qui puisent dans la même enveloppe."""
        from prescriptions.models import Prescription, StatutPrescription

        debut, fin = self.periode_courante(reference)
        total = Prescription.objects.filter(
            agent=self,
            statut=StatutPrescription.VALIDEE,
            date_emission__gte=debut,
            date_emission__lte=fin,
        ).aggregate(models.Sum("montant_rembourse"))["montant_rembourse__sum"]
        return total or 0

    def solde_quota(self, reference=None):
        return self.quota_effectif - self.consommation_periode(reference)


class AyantDroit(models.Model):
    """Fiche ayant droit rattachée à un agent."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="ayants_droit")
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    date_naissance = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos_ayants_droit/", blank=True, null=True)
    lien_parente = models.CharField(max_length=20, choices=LienParente.choices)
    type_justificatif = models.CharField(max_length=30, choices=TypeJustificatif.choices)
    justificatif = models.FileField(upload_to="justificatifs_ayants_droit/")
    date_validite = models.DateField(
        null=True, blank=True, help_text="Laisser vide si le justificatif n'expire pas."
    )

    statut_verification = models.CharField(
        max_length=20, choices=StatutVerification.choices, default=StatutVerification.EN_ATTENTE
    )
    verifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ayants_droit_verifies",
    )
    date_verification = models.DateTimeField(null=True, blank=True)
    commentaire_verification = models.TextField(blank=True)

    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ayant droit"
        verbose_name_plural = "Ayants droit"
        ordering = ["agent", "nom", "prenom"]

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.get_lien_parente_display()}) — {self.agent}"

    @property
    def est_expire(self):
        return bool(self.date_validite) and self.date_validite < timezone.localdate()

    @property
    def age(self):
        if not self.date_naissance:
            return None
        aujourdhui = timezone.localdate()
        anniversaire_passe = (aujourdhui.month, aujourdhui.day) >= (
            self.date_naissance.month,
            self.date_naissance.day,
        )
        return aujourdhui.year - self.date_naissance.year - (not anniversaire_passe)

    @property
    def age_limite(self):
        return Parametrage.charger().age_limite_enfant

    @property
    def limite_age_depassee(self):
        """Un enfant n'est plus couvert à partir de l'âge limite paramétré."""
        if self.lien_parente != LienParente.ENFANT or self.age is None:
            return False
        return self.age >= self.age_limite

    def consommation_periode(self, reference=None):
        """Part de l'enveloppe familiale consommée par cet ayant droit sur le
        cycle. Indicatif : le solde restant se calcule sur l'agent."""
        from prescriptions.models import Prescription, StatutPrescription

        debut, fin = Parametrage.charger().periode(reference)
        total = Prescription.objects.filter(
            ayant_droit=self,
            statut=StatutPrescription.VALIDEE,
            date_emission__gte=debut,
            date_emission__lte=fin,
        ).aggregate(models.Sum("montant_rembourse"))["montant_rembourse__sum"]
        return total or 0
