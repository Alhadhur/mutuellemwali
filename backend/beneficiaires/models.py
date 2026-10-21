from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from parametrage.models import Parametrage, TrancheQuota


class LienParente(models.TextChoices):
    CONJOINT = "CONJOINT", "Partenaire"
    ENFANT = "ENFANT", "Enfant"
    AUTRE = "AUTRE", "Autre"


class TypeJustificatif(models.TextChoices):
    ACTE_MARIAGE = "ACTE_MARIAGE", "Acte de mariage"
    ACTE_NAISSANCE = "ACTE_NAISSANCE", "Acte de naissance"
    CERTIFICAT_SCOLARITE = "CERTIFICAT_SCOLARITE", "Certificat de scolarité"
    AUTRE = "AUTRE", "Autre justificatif"


class MotifFinCouverture(models.TextChoices):
    DIVORCE = "DIVORCE", "Divorce / séparation"
    DECES = "DECES", "Décès"
    AUTRE = "AUTRE", "Autre"


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
    date_naissance = models.DateField(null=True, blank=True)
    date_embauche = models.DateField(null=True, blank=True)
    actif = models.BooleanField(
        default=True,
        verbose_name="Membre de la mutuelle",
        help_text="À décocher lorsque l'agent quitte la mutuelle, en renseignant la date de sortie.",
    )
    date_sortie = models.DateField(
        null=True,
        blank=True,
        verbose_name="Date de sortie",
        help_text="Dernier jour couvert : les soins datés après ne sont plus remboursés, pour lui comme pour ses ayants droit.",
    )
    motif_sortie = models.CharField(max_length=255, blank=True, verbose_name="Motif de sortie")

    # Suspension temporaire (fraude, sanction…) : l'agent reste membre, mais
    # ni lui ni ses ayants droit ne sont remboursés pour les soins datés dans
    # la période. Sans date de fin, la suspension court jusqu'à sa levée.
    suspendu_du = models.DateField(null=True, blank=True, verbose_name="Suspendu du")
    suspendu_jusqu_au = models.DateField(
        null=True,
        blank=True,
        verbose_name="Suspendu jusqu'au",
        help_text="Inclus. Laisser vide pour une suspension sans échéance, à lever manuellement.",
    )
    motif_suspension = models.CharField(max_length=255, blank=True, verbose_name="Motif de suspension")

    class Meta:
        verbose_name = "Agent"
        verbose_name_plural = "Agents"
        ordering = ["utilisateur__matricule"]

    def __str__(self):
        return f"{self.utilisateur.matricule} — {self.utilisateur.get_full_name()}"

    @property
    def matricule(self):
        return self.utilisateur.matricule

    def clean(self):
        erreurs = {}
        if not self.actif and not self.date_sortie:
            erreurs["date_sortie"] = "Indiquez la date de sortie de l'agent qui quitte la mutuelle."
        if self.suspendu_jusqu_au and not self.suspendu_du:
            erreurs["suspendu_du"] = "Indiquez le début de la suspension."
        if self.suspendu_du and self.suspendu_jusqu_au and self.suspendu_jusqu_au < self.suspendu_du:
            erreurs["suspendu_jusqu_au"] = "La fin de la suspension précède son début."
        if self.suspendu_du and not self.motif_suspension:
            erreurs["motif_suspension"] = "Indiquez le motif de la suspension."
        if erreurs:
            raise ValidationError(erreurs)

    def est_suspendu_le(self, jour):
        return bool(
            self.suspendu_du
            and self.suspendu_du <= jour
            and (self.suspendu_jusqu_au is None or jour <= self.suspendu_jusqu_au)
        )

    @property
    def est_suspendu(self):
        return self.est_suspendu_le(timezone.localdate())

    @property
    def est_sorti(self):
        return not self.actif or bool(self.date_sortie and self.date_sortie < timezone.localdate())

    @property
    def libelle_statut(self):
        if self.est_sorti:
            return "Sorti de la mutuelle"
        if self.est_suspendu:
            return "Suspendu"
        return "Actif"

    def message_blocage_suspension(self, jour):
        """Message opposé à toute nouvelle soumission (mobile, web, saisie
        RH) pour un soin daté dans la période de suspension — chaîne vide
        sinon. Le motif de la suspension n'y figure pas : l'agent le lit."""
        if not self.est_suspendu_le(jour):
            return ""
        fin = f"jusqu'au {self.suspendu_jusqu_au:%d/%m/%Y}" if self.suspendu_jusqu_au else "jusqu'à nouvel ordre"
        return (
            f"Dossier suspendu du {self.suspendu_du:%d/%m/%Y} {fin} : aucune prescription ne peut être "
            "soumise pour un soin de cette période, ni pour l'agent ni pour ses ayants droit. "
            "Rapprochez-vous du service mutuelle."
        )

    def motif_non_couverture(self, jour):
        """Raison pour laquelle un soin daté de `jour` n'est pas couvert du
        fait de l'agent (sortie ou suspension) — chaîne vide s'il l'est.
        S'applique aussi aux soins de ses ayants droit, rattachés à lui."""
        if (self.date_sortie and jour > self.date_sortie) or (not self.actif and not self.date_sortie):
            sortie = f" le {self.date_sortie:%d/%m/%Y}" if self.date_sortie else ""
            return f"L'agent a quitté la mutuelle{sortie} : non éligible au remboursement."
        if self.est_suspendu_le(jour):
            fin = f" au {self.suspendu_jusqu_au:%d/%m/%Y}" if self.suspendu_jusqu_au else " (sans échéance)"
            return (
                f"Agent suspendu du {self.suspendu_du:%d/%m/%Y}{fin} — {self.motif_suspension} : "
                "non éligible au remboursement, pour lui comme pour ses ayants droit."
            )
        return ""

    @property
    def ayants_droit_couverts(self):
        """Seuls les ayants droit vérifiés et encore couverts entrent dans le
        calcul : un dossier rejeté, un enfant au-delà de l'âge limite ou un
        partenaire divorcé ne donne droit à rien et ne se facture pas."""
        return [
            ayant_droit
            for ayant_droit in self.ayants_droit.all()
            if ayant_droit.statut_verification == StatutVerification.VALIDE
            and not ayant_droit.limite_age_depassee
            and not ayant_droit.couverture_terminee
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
    justificatif = models.FileField(
        upload_to="justificatifs_ayants_droit/",
        blank=True,
        help_text="Facultatif à la saisie : à joindre dès que possible pour permettre la vérification du dossier.",
    )
    date_validite = models.DateField(
        null=True, blank=True, help_text="Laisser vide si le justificatif n'expire pas."
    )

    # Fin de droits (divorce, décès…) : la fiche est conservée, avec ses
    # prescriptions passées, mais l'ayant droit ne compte plus dans le quota
    # ni la cotisation, et ses soins datés après cette date ne sont plus
    # remboursés. Supprimer la fiche effacerait aussi tout son historique.
    date_fin_couverture = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fin de couverture",
        help_text="Dernier jour couvert (ex. date du divorce). Laisser vide tant que l'ayant droit est couvert.",
    )
    motif_fin_couverture = models.CharField(
        max_length=20, choices=MotifFinCouverture.choices, blank=True, verbose_name="Motif de fin de couverture"
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

    def clean(self):
        if self.date_fin_couverture and not self.motif_fin_couverture:
            raise ValidationError({"motif_fin_couverture": "Indiquez le motif de la fin de couverture."})
        if self.motif_fin_couverture and not self.date_fin_couverture:
            raise ValidationError({"date_fin_couverture": "Indiquez la date de fin de couverture."})

    def couverture_terminee_le(self, jour):
        return bool(self.date_fin_couverture and jour > self.date_fin_couverture)

    @property
    def couverture_terminee(self):
        return self.couverture_terminee_le(timezone.localdate())

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
        """Un enfant reste couvert jusqu'au 31 décembre de l'année où il
        atteint l'âge limite (convention de la mutuelle) — pas dès son
        anniversaire. Exemple : 18 ans le 12/07/2026, couvert jusqu'au
        31/12/2026, plus couvert à partir du 01/01/2027."""
        return self.limite_age_depassee_pour(self.age_limite)

    def limite_age_depassee_pour(self, age_limite_enfant):
        """Même règle que `limite_age_depassee`, mais sans relire
        `Parametrage` à chaque appel : réservé aux parcours qui évaluent déjà
        beaucoup d'ayants droit (voir `anomalies.services`), où rappeler la
        propriété reviendrait à refaire la même requête des centaines de fois."""
        if self.lien_parente != LienParente.ENFANT or not self.date_naissance:
            return False
        annee_limite = self.date_naissance.year + age_limite_enfant
        return timezone.localdate().year > annee_limite

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
