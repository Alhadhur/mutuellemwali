from rest_framework import serializers

from beneficiaires.models import Agent, AyantDroit
from parametrage.models import NatureSoin
from prescriptions.models import HistoriqueStatut, Prescription
from prestataires.models import Prestataire


class UtilisateurSerializer(serializers.Serializer):
    matricule = serializers.CharField()
    nom = serializers.CharField()
    prenom = serializers.CharField()
    telephone = serializers.CharField()
    role = serializers.CharField()
    role_display = serializers.CharField(source="get_role_display")
    region = serializers.CharField()
    photo = serializers.ImageField()


class AyantDroitSerializer(serializers.ModelSerializer):
    est_expire = serializers.BooleanField(read_only=True)
    age = serializers.IntegerField(read_only=True)
    age_limite = serializers.IntegerField(read_only=True)
    limite_age_depassee = serializers.BooleanField(read_only=True)
    consommation_periode = serializers.SerializerMethodField()
    lien_parente_display = serializers.CharField(source="get_lien_parente_display", read_only=True)
    statut_verification_display = serializers.CharField(source="get_statut_verification_display", read_only=True)

    class Meta:
        model = AyantDroit
        fields = [
            "id",
            "nom",
            "prenom",
            "date_naissance",
            "age",
            "age_limite",
            "limite_age_depassee",
            "photo",
            "lien_parente",
            "lien_parente_display",
            "type_justificatif",
            "date_validite",
            "consommation_periode",
            "statut_verification",
            "statut_verification_display",
            "est_expire",
        ]

    def get_consommation_periode(self, obj):
        return obj.consommation_periode()


class AgentProfilSerializer(serializers.ModelSerializer):
    matricule = serializers.CharField(source="utilisateur.matricule", read_only=True)
    nom = serializers.CharField(source="utilisateur.nom", read_only=True)
    prenom = serializers.CharField(source="utilisateur.prenom", read_only=True)
    quota = serializers.IntegerField(source="quota_effectif", read_only=True)
    cotisation_mensuelle = serializers.IntegerField(read_only=True)
    nombre_conjoints = serializers.IntegerField(read_only=True)
    nombre_enfants = serializers.IntegerField(read_only=True)
    periode_debut = serializers.SerializerMethodField()
    periode_fin = serializers.SerializerMethodField()
    solde_quota = serializers.SerializerMethodField()
    consommation_periode = serializers.SerializerMethodField()
    ayants_droit = AyantDroitSerializer(many=True, read_only=True)

    class Meta:
        model = Agent
        fields = [
            "id",
            "matricule",
            "nom",
            "prenom",
            "site",
            "date_naissance",
            "date_embauche",
            "quota",
            "cotisation_mensuelle",
            "nombre_conjoints",
            "nombre_enfants",
            "periode_debut",
            "periode_fin",
            "solde_quota",
            "consommation_periode",
            "ayants_droit",
        ]

    def get_periode_debut(self, obj):
        return obj.periode_courante()[0]

    def get_periode_fin(self, obj):
        return obj.periode_courante()[1]

    def get_solde_quota(self, obj):
        return obj.solde_quota()

    def get_consommation_periode(self, obj):
        return obj.consommation_periode()


class PrestataireSerializer(serializers.ModelSerializer):
    type_prestataire_display = serializers.CharField(source="get_type_prestataire_display", read_only=True)

    class Meta:
        model = Prestataire
        fields = ["id", "code", "nom", "type_prestataire", "type_prestataire_display", "ville", "taux_prise_en_charge"]


class HistoriqueStatutSerializer(serializers.ModelSerializer):
    nouveau_statut_display = serializers.SerializerMethodField()

    class Meta:
        model = HistoriqueStatut
        fields = ["ancien_statut", "nouveau_statut", "nouveau_statut_display", "commentaire", "date_changement"]

    def get_nouveau_statut_display(self, obj):
        return dict(Prescription._meta.get_field("statut").choices).get(obj.nouveau_statut, obj.nouveau_statut)


class NatureSoinSerializer(serializers.ModelSerializer):
    class Meta:
        model = NatureSoin
        fields = ["id", "libelle"]


class PrescriptionSerializer(serializers.ModelSerializer):
    prestataire_nom = serializers.CharField(source="prestataire.nom", read_only=True)
    nature_libelle = serializers.CharField(source="nature.libelle", read_only=True, default="")
    beneficiaire_nom = serializers.SerializerMethodField()
    statut_display = serializers.CharField(source="get_statut_display", read_only=True)
    historique = HistoriqueStatutSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = [
            "id",
            "ayant_droit",
            "beneficiaire_nom",
            "prestataire",
            "prestataire_nom",
            "nature",
            "nature_libelle",
            "numero_ordonnance",
            "montant_total",
            "montant_rembourse",
            "date_emission",
            "justificatif",
            "statut",
            "statut_display",
            "motif_signalement",
            "date_creation",
            "historique",
        ]
        read_only_fields = ["montant_rembourse", "statut", "motif_signalement", "date_creation"]

    def get_beneficiaire_nom(self, obj):
        return str(obj.beneficiaire())

    def validate_ayant_droit(self, value):
        request = self.context["request"]
        agent = request.user.agent
        if value is not None and value.agent_id != agent.id:
            raise serializers.ValidationError("Cet ayant droit n'appartient pas à votre dossier.")
        return value

    def validate_prestataire(self, value):
        if not value.est_actif:
            raise serializers.ValidationError("Ce prestataire n'est plus conventionné (suspendu).")
        return value

    def validate_nature(self, value):
        """Le mobile peut avoir en cache une nature retirée depuis."""
        if value is not None and not value.active:
            raise serializers.ValidationError("Cette nature de soin n'est plus proposée.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["agent"] = request.user.agent
        validated_data["soumis_par"] = request.user
        return super().create(validated_data)
