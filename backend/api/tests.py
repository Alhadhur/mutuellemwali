from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent
from parametrage.models import NatureSoin
from prescriptions.models import Prescription
from prestataires.models import Prestataire, TypePrestataire


class SoumettrePrescriptionTest(TestCase):
    """Soumission mobile d'une ordonnance (voir PrescriptionListCreateView) :
    l'agent est fixé depuis le compte connecté (PrescriptionSerializer.create),
    pas depuis les données envoyées."""

    def setUp(self):
        self.compte = Utilisateur.objects.create_user("A0001", "x", nom="Zahra", prenom="Fatima", role=Role.AGENT)
        self.agent = Agent.objects.create(utilisateur=self.compte, site="Moroni")
        self.prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Pharmacie Centrale", taux_prise_en_charge=80
        )
        self.nature = NatureSoin.objects.get(libelle="Consultation")
        self.client = APIClient()
        self.client.force_authenticate(user=self.compte)

    def _donnees(self, **extra):
        donnees = {
            "prestataire": self.prestataire.pk,
            "nature": self.nature.pk,
            "montant_total": "10000",
            "date_emission": "2026-10-05",
        }
        donnees.update(extra)
        return donnees

    def test_la_soumission_fixe_l_agent_depuis_le_compte_connecte(self):
        reponse = self.client.post("/api/prescriptions/", self._donnees(), format="multipart")

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(Prescription.objects.get().agent_id, self.agent.pk)

    def test_une_annee_sur_deux_chiffres_est_refusee(self):
        """Le mobile construit toujours une année sur 4 chiffres, mais rien
        ne garantit qu'un autre client de l'API fasse pareil : sans cette
        garde, une telle date rendrait la prescription invisible de tous les
        rapports filtrés par période, tout en ayant l'air normale dans la
        liste brute (même défaut que côté formulaire web, voir
        Prescription.clean())."""
        reponse = self.client.post(
            "/api/prescriptions/", self._donnees(date_emission="0026-10-05"), format="multipart"
        )

        self.assertEqual(reponse.status_code, 400)
        self.assertIn("date_emission", reponse.data)
        self.assertEqual(Prescription.objects.count(), 0)
