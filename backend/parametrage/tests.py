from datetime import date

from django.test import TestCase

from accounts.models import Utilisateur
from beneficiaires.models import Agent
from prescriptions.models import Prescription
from prestataires.models import Prestataire, TypePrestataire

from .models import NatureSoin


class NatureSoinTest(TestCase):
    def test_le_bareme_de_natures_est_livre_pret_a_l_emploi(self):
        """La migration seme une liste de départ : le service mutuelle n'a pas
        à la saisir avant de pouvoir enregistrer une prescription."""
        self.assertGreaterEqual(NatureSoin.objects.count(), 10)
        self.assertTrue(NatureSoin.objects.filter(libelle="Consultation").exists())

    def test_une_nature_desactivee_n_est_plus_proposee(self):
        nature = NatureSoin.objects.get(libelle="Optique")
        nature.active = False
        nature.save()

        self.assertNotIn(nature, NatureSoin.proposables())
        self.assertIn(nature, NatureSoin.objects.all())

    def test_une_nature_portee_par_une_prescription_ne_peut_etre_supprimee(self):
        """PROTECT : l'historique ne doit pas perdre le type de soin."""
        from django.db.models import ProtectedError

        agent = Agent.objects.create(
            utilisateur=Utilisateur.objects.create_user("N0001", "x", nom="N", prenom="T"),
            site="Moroni",
            date_naissance=date(1990, 1, 1),
            date_embauche=date(2018, 1, 1),
        )
        prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="P", taux_prise_en_charge=80
        )
        nature = NatureSoin.objects.get(libelle="Consultation")
        Prescription.objects.create(
            agent=agent,
            prestataire=prestataire,
            nature=nature,
            numero_ordonnance="ORD-N",
            montant_total=1000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        with self.assertRaises(ProtectedError):
            nature.delete()
