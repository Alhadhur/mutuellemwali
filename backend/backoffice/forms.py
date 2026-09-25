import json

from django import forms

from accounts.models import Utilisateur
from beneficiaires.models import Agent, AyantDroit
from facturation.models import MOIS, Facture
from parametrage.models import NatureSoin, Parametrage, TrancheQuota
from prescriptions.models import Prescription
from prestataires.models import Prestataire, TarifPrestataire


class DateInput(forms.DateInput):
    input_type = "date"


class UtilisateurForm(forms.ModelForm):
    class Meta:
        model = Utilisateur
        fields = [
            "matricule",
            "nom",
            "prenom",
            "email",
            "telephone",
            "role",
            "region",
            "photo",
            "is_active",
        ]


class UtilisateurCreationForm(UtilisateurForm):
    """Création d'un compte : le mot de passe initial est saisi ici, puis
    stocké haché par `set_password`."""

    mot_de_passe = forms.CharField(widget=forms.PasswordInput, label="Mot de passe")
    confirmation = forms.CharField(widget=forms.PasswordInput, label="Confirmer le mot de passe")

    def clean(self):
        donnees = super().clean()
        if donnees.get("mot_de_passe") != donnees.get("confirmation"):
            raise forms.ValidationError("Les deux mots de passe ne correspondent pas.")
        return donnees

    def save(self, commit=True):
        utilisateur = super().save(commit=False)
        utilisateur.set_password(self.cleaned_data["mot_de_passe"])
        if commit:
            utilisateur.save()
        return utilisateur


class MotDePasseForm(forms.Form):
    mot_de_passe = forms.CharField(widget=forms.PasswordInput, label="Nouveau mot de passe")
    confirmation = forms.CharField(widget=forms.PasswordInput, label="Confirmer le mot de passe")

    def clean(self):
        donnees = super().clean()
        if donnees.get("mot_de_passe") != donnees.get("confirmation"):
            raise forms.ValidationError("Les deux mots de passe ne correspondent pas.")
        return donnees


class ImportCSVForm(forms.Form):
    fichier = forms.FileField(label="Fichier CSV")


class MonProfilForm(forms.ModelForm):
    """Édition en libre-service : contrairement à UtilisateurForm, ni le
    matricule, ni le rôle, ni l'activation ne sont modifiables ici — ce n'est
    pas un écran d'administration."""

    class Meta:
        model = Utilisateur
        fields = ["nom", "prenom", "email", "telephone", "region"]


class MonMotDePasseForm(forms.Form):
    mot_de_passe_actuel = forms.CharField(widget=forms.PasswordInput, label="Mot de passe actuel")
    mot_de_passe = forms.CharField(widget=forms.PasswordInput, label="Nouveau mot de passe")
    confirmation = forms.CharField(widget=forms.PasswordInput, label="Confirmer le nouveau mot de passe")

    def __init__(self, utilisateur, *args, **kwargs):
        self.utilisateur = utilisateur
        super().__init__(*args, **kwargs)

    def clean_mot_de_passe_actuel(self):
        valeur = self.cleaned_data["mot_de_passe_actuel"]
        if not self.utilisateur.check_password(valeur):
            raise forms.ValidationError("Mot de passe actuel incorrect.")
        return valeur

    def clean(self):
        donnees = super().clean()
        if donnees.get("mot_de_passe") != donnees.get("confirmation"):
            raise forms.ValidationError("Les deux mots de passe ne correspondent pas.")
        return donnees


class AgentForm(forms.ModelForm):
    """Le quota n'est pas saisi : il découle du barème appliqué à la
    composition familiale."""

    class Meta:
        model = Agent
        fields = ["utilisateur", "site", "date_naissance", "date_embauche", "actif"]
        widgets = {"date_naissance": DateInput, "date_embauche": DateInput}


class AyantDroitForm(forms.ModelForm):
    """Le statut de vérification n'est pas modifiable ici : il passe par les
    actions Valider / Rejeter, qui tracent l'auteur et la date."""

    class Meta:
        model = AyantDroit
        fields = [
            "agent",
            "nom",
            "prenom",
            "date_naissance",
            "photo",
            "lien_parente",
            "type_justificatif",
            "justificatif",
            "date_validite",
        ]
        widgets = {"date_naissance": DateInput, "date_validite": DateInput}


class PrescriptionForm(forms.ModelForm):
    """Saisie d'une ordonnance reçue au format papier. Le statut n'est pas
    proposé : il est posé par la détection de doublons, comme pour une
    soumission mobile."""

    class Meta:
        model = Prescription
        fields = [
            "agent",
            "ayant_droit",
            "prestataire",
            "nature",
            "numero_ordonnance",
            "montant_total",
            "date_emission",
            "justificatif",
        ]
        widgets = {"date_emission": DateInput}
        labels = {"montant_total": "Coût total du soin (KMF)"}
        help_texts = {
            "ayant_droit": "Laisser vide si l'ordonnance concerne l'agent lui-même.",
            "montant_total": (
                "Les 100 % portés sur l'ordonnance, avant prise en charge — "
                "et non la part réglée au guichet. La répartition est calculée "
                "ci-dessous."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prestataire"].queryset = Prestataire.objects.filter(statut="ACTIF")
        # Une nature désactivée reste portée par l'historique mais n'est plus
        # proposée à la saisie.
        self.fields["nature"].queryset = NatureSoin.proposables()
        self.fields["nature"].empty_label = "— choisir —"
        # Le taux voyage avec l'option : la répartition s'affiche sans
        # aller-retour serveur au changement de prestataire.
        self.taux_par_prestataire = json.dumps(
            {
                str(prestataire.pk): float(prestataire.taux_prise_en_charge)
                for prestataire in self.fields["prestataire"].queryset
            }
        )


class PrestataireForm(forms.ModelForm):
    class Meta:
        model = Prestataire
        fields = [
            "type_prestataire",
            "nom",
            "ville",
            "adresse",
            "telephone",
            "taux_prise_en_charge",
            "statut",
            "utilisateur",
        ]


class TarifPrestataireForm(forms.ModelForm):
    """Renseigner une nature déjà tarifée chez ce prestataire met à jour son
    taux au lieu d'en créer un doublon (voir TarifPrestataireAjouter)."""

    nature_soin = forms.ModelChoiceField(queryset=NatureSoin.proposables(), label="Nature de soin")

    class Meta:
        model = TarifPrestataire
        fields = ["nature_soin", "taux_prise_en_charge"]


class FactureForm(forms.ModelForm):
    """Entête de facture. Les lignes arrivent par import CSV."""

    class Meta:
        model = Facture
        fields = ["prestataire", "numero", "mois", "annee", "date_reception", "montant_total_declare", "fichier"]
        widgets = {"date_reception": DateInput}


class ImportFactureForm(forms.Form):
    """Entête + lignes d'une facture en une seule fois, avec aperçu des
    erreurs avant écriture (voir backoffice.views.FactureImport)."""

    prestataire = forms.ModelChoiceField(queryset=Prestataire.objects.all(), label="Prestataire")
    numero = forms.CharField(label="N° de facture", max_length=60)
    mois = forms.ChoiceField(choices=MOIS, label="Mois facturé")
    annee = forms.IntegerField(label="Année", min_value=2000, max_value=2100)
    montant_total_declare = forms.IntegerField(label="Total réclamé à la mutuelle (KMF)", min_value=0)
    montant_colonne = forms.ChoiceField(
        label="La colonne « montant » du fichier porte",
        choices=(("reclame", "La part réclamée à la mutuelle"), ("total", "Le coût total du soin")),
        initial="reclame",
    )
    fichier_csv = forms.FileField(label="Fichier CSV des lignes")

    def clean(self):
        donnees = super().clean()
        prestataire = donnees.get("prestataire")
        numero = donnees.get("numero")
        if prestataire and numero and Facture.objects.filter(prestataire=prestataire, numero=numero).exists():
            self.add_error("numero", "Cette facture est déjà enregistrée pour ce prestataire.")
        return donnees


class ParametrageForm(forms.ModelForm):
    class Meta:
        model = Parametrage
        fields = [
            "cotisation_base",
            "conjoints_inclus",
            "enfants_inclus",
            "cout_conjoint_supplementaire",
            "cout_enfant_supplementaire",
            "age_limite_enfant",
            "duree_cycle_mois",
            "quota_mensuel_defaut",
            "fenetre_analyse_jours",
            "seuil_volume_ecart_type",
            "seuil_alerte_quota",
        ]


class TrancheQuotaForm(forms.ModelForm):
    class Meta:
        model = TrancheQuota
        fields = ["ordre", "libelle", "partenaire", "enfants_min", "enfants_max", "montant"]


class NatureSoinForm(forms.ModelForm):
    class Meta:
        model = NatureSoin
        fields = ["ordre", "libelle", "active"]


class ChangementStatutForm(forms.Form):
    """Commentaire accompagnant un changement de statut de prescription :
    il est repris dans l'historique horodaté."""

    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Motif / commentaire",
    )

    def __init__(self, *args, statuts=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["statut"] = forms.ChoiceField(choices=statuts, label="Nouveau statut")

    field_order = ["statut", "commentaire"]


class PrescriptionFiltreForm(forms.Form):
    statut = forms.ChoiceField(required=False, label="Statut")
    recherche = forms.CharField(required=False, label="Recherche")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from prescriptions.models import StatutPrescription

        self.fields["statut"].choices = [("", "Tous les statuts")] + list(StatutPrescription.choices)


class AyantDroitVerificationForm(forms.Form):
    commentaire = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Commentaire"
    )
