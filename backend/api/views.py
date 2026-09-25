from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from beneficiaires.models import Agent
from parametrage.models import NatureSoin
from prescriptions.models import Prescription
from prestataires.models import Prestataire, StatutPrestataire

from .permissions import EstAgent
from .serializers import (
    AgentProfilSerializer,
    MonCompteSerializer,
    MonMotDePasseSerializer,
    NatureSoinSerializer,
    PrescriptionSerializer,
    PrestataireSerializer,
    UtilisateurSerializer,
)


class MoiView(APIView):
    """Identité du compte connecté (utile pour router l'UI mobile par rôle)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UtilisateurSerializer(request.user).data)


class MonCompteView(generics.RetrieveUpdateAPIView):
    """Coordonnées du compte connecté, en libre-service : accessible à tout
    utilisateur authentifié, quel que soit son rôle (agent, RH, direction…),
    contrairement aux écrans d'administration réservés au RH."""

    serializer_class = MonCompteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class MonMotDePasseView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = MonMotDePasseSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["mot_de_passe"])
        request.user.save()
        return Response({"detail": "Mot de passe mis à jour."})


class AgentProfilView(generics.RetrieveAPIView):
    """Profil complet de l'agent connecté : fiche + ayants droit + plafonds."""

    serializer_class = AgentProfilSerializer
    permission_classes = [EstAgent]

    def get_object(self):
        return Agent.objects.select_related("utilisateur").prefetch_related("ayants_droit").get(
            utilisateur=self.request.user
        )


class PrestataireListView(generics.ListAPIView):
    """Liste des prestataires actifs, pour le formulaire de soumission mobile."""

    serializer_class = PrestataireSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Prestataire.objects.filter(statut=StatutPrestataire.ACTIF).order_by("nom")
    filterset_fields = ["type_prestataire"]

    def get_queryset(self):
        qs = super().get_queryset()
        type_prestataire = self.request.query_params.get("type")
        if type_prestataire:
            qs = qs.filter(type_prestataire=type_prestataire)
        return qs


class NatureSoinListView(generics.ListAPIView):
    """Natures de soin proposées à la saisie mobile.

    Avec `?prestataire=<id>`, restreint la liste à ce que cet établissement
    propose réellement (et renvoie le taux applicable à chacune) — sauf si
    aucun tarif n'y a encore été détaillé, auquel cas la liste complète reste
    proposée, comme avant l'ajout des tarifs par nature de soin.
    """

    serializer_class = NatureSoinSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _prestataire_demande(self):
        prestataire_id = self.request.query_params.get("prestataire")
        if not prestataire_id:
            return None
        return Prestataire.objects.filter(pk=prestataire_id).first()

    def get_queryset(self):
        prestataire = self._prestataire_demande()
        if prestataire is not None:
            restreintes = prestataire.natures_proposees()
            if restreintes.exists():
                return restreintes
        return NatureSoin.proposables()

    def get_serializer_context(self):
        contexte = super().get_serializer_context()
        contexte["prestataire"] = self._prestataire_demande()
        return contexte


class PrescriptionListCreateView(generics.ListCreateAPIView):
    """Prescriptions de l'agent connecté : historique + soumission mobile
    (photo de l'ordonnance/facture)."""

    serializer_class = PrescriptionSerializer
    permission_classes = [EstAgent]

    def get_queryset(self):
        return (
            Prescription.objects.filter(agent=self.request.user.agent)
            .select_related("prestataire", "ayant_droit", "nature")
            .prefetch_related("historique")
            .order_by("-date_creation")
        )


class PrescriptionDetailView(generics.RetrieveAPIView):
    serializer_class = PrescriptionSerializer
    permission_classes = [EstAgent]

    def get_queryset(self):
        return Prescription.objects.filter(agent=self.request.user.agent)
