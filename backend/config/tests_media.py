"""Tests du service protégé des fichiers déposés.

Ces fichiers sont des ordonnances et des actes de naissance : le contrôle
d'accès est la partie du code où une erreur coûte le plus cher. Chaque cas
d'accès légitime et chaque cas de refus est donc couvert explicitement.
"""
import tempfile
from datetime import date
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, TypeJustificatif
from prescriptions.models import Prescription
from prestataires.models import Prestataire, TypePrestataire

DOSSIER_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA)
class FichierProtegeTest(TestCase):
    def setUp(self):
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.direction = Utilisateur.objects.create_user("DIR1", "x", nom="D", prenom="C", role=Role.DIRECTION)

        self.agent = self.creer_agent("A0001", "Zahra")
        self.autre_agent = self.creer_agent("A0002", "Said")

        prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Pharmacie", taux_prise_en_charge=80
        )
        self.chemin = "justificatifs_prescriptions/ordonnance_1.jpg"
        self.ecrire(self.chemin)
        Prescription.objects.create(
            agent=self.agent, prestataire=prestataire, numero_ordonnance="ORD-1",
            montant_total=10000, date_emission=date.today(), justificatif=self.chemin,
        )

    def creer_agent(self, matricule, nom):
        compte = Utilisateur.objects.create_user(matricule, "x", nom=nom, prenom="T", role=Role.AGENT)
        return Agent.objects.create(
            utilisateur=compte, site="Moroni",
            date_naissance=date(1990, 1, 1), date_embauche=date(2018, 1, 1),
        )

    def ecrire(self, chemin, contenu=b"image"):
        cible = Path(DOSSIER_MEDIA) / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(contenu)
        return cible

    def url(self, chemin=None):
        return reverse("fichier_protege", args=[chemin or self.chemin])

    # --- Accès refusés -----------------------------------------------------

    def test_un_visiteur_non_connecte_est_redirige(self):
        """Sans cette vue, l'URL suffirait à lire une ordonnance."""
        reponse = self.client.get(self.url())

        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/login/", reponse.url)

    def test_un_agent_ne_voit_pas_le_justificatif_d_un_autre(self):
        self.client.force_login(self.autre_agent.utilisateur)

        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_un_fichier_inexistant_repond_comme_un_fichier_interdit(self):
        """Même réponse dans les deux cas : un 403 confirmerait à qui essaie
        des URL au hasard que le fichier existe."""
        self.client.force_login(self.autre_agent.utilisateur)
        interdit = self.client.get(self.url())

        self.client.force_login(self.rh)
        inexistant = self.client.get(self.url("justificatifs_prescriptions/inconnu.jpg"))

        self.assertEqual(interdit.status_code, 404)
        self.assertEqual(inexistant.status_code, 404)

    def test_un_chemin_remontant_l_arborescence_est_rejete(self):
        """Sans ce contrôle, n'importe quel fichier du serveur serait lisible."""
        self.client.force_login(self.rh)

        reponse = self.client.get("/media/../../etc/passwd")

        self.assertIn(reponse.status_code, (301, 404))

    # --- Accès autorisés ---------------------------------------------------

    def test_l_agent_concerne_accede_a_son_justificatif(self):
        self.client.force_login(self.agent.utilisateur)

        reponse = self.client.get(self.url())

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(b"".join(reponse.streaming_content), b"image")

    def test_le_service_mutuelle_accede_a_tout(self):
        self.client.force_login(self.rh)

        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_la_direction_accede_a_tout(self):
        self.client.force_login(self.direction)

        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_l_agent_accede_au_justificatif_de_son_ayant_droit(self):
        chemin = "justificatifs_ayants_droit/acte_naissance.pdf"
        self.ecrire(chemin, b"acte")
        AyantDroit.objects.create(
            agent=self.agent, nom="Zahra", prenom="Ali",
            date_naissance=date(2015, 1, 1), lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE, justificatif=chemin,
        )
        self.client.force_login(self.agent.utilisateur)

        self.assertEqual(self.client.get(self.url(chemin)).status_code, 200)

    def test_un_agent_ne_voit_pas_l_ayant_droit_d_un_autre(self):
        chemin = "justificatifs_ayants_droit/acte_prive.pdf"
        self.ecrire(chemin, b"acte")
        AyantDroit.objects.create(
            agent=self.autre_agent, nom="Said", prenom="Amina",
            date_naissance=date(2016, 1, 1), lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE, justificatif=chemin,
        )
        self.client.force_login(self.agent.utilisateur)

        self.assertEqual(self.client.get(self.url(chemin)).status_code, 404)


class SondeDeSanteTest(TestCase):
    def test_la_sonde_repond_sans_authentification(self):
        """L'hébergeur interroge cette adresse sans session : si elle exigeait
        une connexion, le service serait déclaré indisponible."""
        reponse = self.client.get(reverse("sante"))

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.content, b"ok")
