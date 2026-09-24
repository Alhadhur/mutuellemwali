"""Tests des agrégations d'anomalies et de leur export.

Le point sensible : l'écran et le fichier CSV doivent lire la **même** source.
Un test s'en assure explicitement, parce qu'une divergence silencieuse entre
les deux ruinerait la confiance dans l'outil.
"""
import csv
import io
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent
from facturation.models import Facture, LigneFacture, StatutLigne
from parametrage.models import NatureSoin, Parametrage
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, TypePrestataire

from . import services


class BaseAnomalies(TestCase):
    def setUp(self):
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.compte_agent = Utilisateur.objects.create_user(
            "A0001", "x", nom="Zahra", prenom="Fatima", role=Role.AGENT
        )
        self.agent = Agent.objects.create(
            utilisateur=self.compte_agent,
            site="Moroni",
            date_naissance=date(1990, 1, 1),
            date_embauche=date(2018, 6, 1),
        )
        self.prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Pharmacie Centrale", taux_prise_en_charge=80
        )
        self.nature = NatureSoin.objects.get(libelle="Consultation")

    def prescription(self, montant=10000, jours=0, numero="ORD-1", statut=None):
        prescription = Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            nature=self.nature,
            numero_ordonnance=numero,
            montant_total=montant,
            date_emission=date.today() - timedelta(days=jours),
            justificatif="x.jpg",
        )
        if statut:
            prescription.statut = statut
            prescription.save()
        return prescription

    def ligne_facture(self, montant_soin=10000, montant_reclame=8000, statut=StatutLigne.ECART_TAUX):
        """Les lignes s'ajoutent à une même facture : le couple
        (prestataire, numéro) est unique."""
        facture, _ = Facture.objects.get_or_create(
            prestataire=self.prestataire,
            numero="F-001",
            defaults={
                "mois": date.today().month,
                "annee": date.today().year,
                "montant_total_declare": 0,
            },
        )
        return LigneFacture.objects.create(
            facture=facture,
            date_soin=date.today(),
            matricule=self.agent.matricule,
            nom_beneficiaire="Fatima Zahra",
            nature="Consultation",
            montant_soin=montant_soin,
            montant_reclame=montant_reclame,
            statut=statut,
        )


class SeuilsParametrablesTest(BaseAnomalies):
    def test_le_seuil_d_alerte_quota_vient_des_parametres(self):
        parametres = Parametrage.charger()
        parametres.seuil_alerte_quota = 90
        parametres.save()
        # Seules les prescriptions validées entament l'enveloppe.
        self.prescription(montant=5000, statut=StatutPrescription.VALIDEE)

        signales = [r["agent"].pk for r in services.agents_proche_quota()]
        self.assertIn(self.agent.pk, signales)

        parametres.seuil_alerte_quota = 1
        parametres.save()
        self.assertEqual(services.agents_proche_quota(), [])

    def test_la_fenetre_d_analyse_vient_des_parametres(self):
        parametres = Parametrage.charger()
        parametres.fenetre_analyse_jours = 7
        parametres.save()

        debut, fin = services.periode_par_defaut()
        self.assertEqual((fin - debut).days, 7)


class EcartsDeFacturationTest(BaseAnomalies):
    def test_seules_les_lignes_en_anomalie_sont_remontees(self):
        anormale = self.ligne_facture(statut=StatutLigne.ECART_TAUX)
        self.ligne_facture(statut=StatutLigne.CONCORDANTE)

        ecarts = services.ecarts_de_facturation()

        self.assertEqual([l.pk for l in ecarts], [anormale.pk])

    def test_la_synthese_calcule_le_taux_d_anomalie_et_la_surfacturation(self):
        # Attendu au taux de 80 % sur 10 000 = 8 000 ; le prestataire réclame 9 500.
        self.ligne_facture(montant_soin=10000, montant_reclame=9500, statut=StatutLigne.ECART_TAUX)
        self.ligne_facture(statut=StatutLigne.CONCORDANTE)

        synthese = services.synthese_ecarts_par_prestataire()

        self.assertEqual(len(synthese), 1)
        self.assertEqual(synthese[0]["lignes_total"], 2)
        self.assertEqual(synthese[0]["lignes_anormales"], 1)
        self.assertEqual(synthese[0]["taux_anomalie"], 50.0)
        self.assertEqual(synthese[0]["surfacturation"], 1500)

    def test_un_prestataire_qui_reclame_moins_que_son_du_n_est_pas_compte_en_surfacturation(self):
        """Réclamer trop peu n'est pas de la fraude : ça ne doit pas gonfler
        le montant présenté comme surfacturé."""
        self.ligne_facture(montant_soin=10000, montant_reclame=5000, statut=StatutLigne.ECART_TAUX)

        self.assertEqual(services.synthese_ecarts_par_prestataire()[0]["surfacturation"], 0)


class FileDAttenteTest(BaseAnomalies):
    def test_une_prescription_ancienne_en_controle_reste_visible(self):
        """Une file d'attente ne doit pas se vider toute seule : une
        prescription suspecte de l'an dernier reste à traiter."""
        ancienne = self.prescription(jours=400)
        ancienne.statut = StatutPrescription.EN_CONTROLE
        ancienne.save(detecter=False)

        self.assertIn(ancienne, services.prescriptions_en_controle())


class ExportTest(BaseAnomalies):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.ligne = self.ligne_facture(montant_soin=10000, montant_reclame=9500)

    def lire_csv(self, reponse):
        contenu = reponse.content.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(contenu), delimiter=";"))

    def test_l_export_d_une_famille_contient_ses_lignes(self):
        reponse = self.client.get(
            reverse("backoffice:anomalies_export_famille", args=["facturation"])
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertIn("attachment", reponse["Content-Disposition"])
        lignes = self.lire_csv(reponse)
        plat = [cellule for ligne in lignes for cellule in ligne]
        self.assertIn("Pharmacie Centrale", plat)
        self.assertIn("9500", plat)

    def test_le_fichier_s_ouvre_correctement_dans_excel(self):
        """BOM UTF-8 et point-virgule : sans eux, Excel en français affiche
        des accents cassés et tout le contenu dans une seule colonne."""
        reponse = self.client.get(reverse("backoffice:anomalies_export"))

        self.assertTrue(reponse.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b";", reponse.content)

    def test_l_export_global_regroupe_toutes_les_familles(self):
        reponse = self.client.get(reverse("backoffice:anomalies_export"))

        contenu = reponse.content.decode("utf-8-sig")
        for titre in ("ÉCARTS DE FACTURATION", "PRESCRIPTIONS EN CONTRÔLE", "JUSTIFICATIFS EXPIRÉS"):
            self.assertIn(titre, contenu)

    def test_l_export_rappelle_la_periode_et_son_auteur(self):
        """Un fichier détaché de l'écran doit rester interprétable."""
        reponse = self.client.get(reverse("backoffice:anomalies_export"), {"debut": "2026-01-01", "fin": "2026-03-31"})

        contenu = reponse.content.decode("utf-8-sig")
        self.assertIn("du 01/01/2026 au 31/03/2026", contenu)
        self.assertIn("Service Rh", contenu)

    def test_une_famille_inconnue_renvoie_404(self):
        reponse = self.client.get(reverse("backoffice:anomalies_export_famille", args=["inventée"]))

        self.assertEqual(reponse.status_code, 404)

    def test_l_ecran_et_l_export_montrent_les_memes_lignes(self):
        """Le point le plus important : une seule source pour les deux."""
        ecran = self.client.get(reverse("backoffice:anomalies"))
        tableau_ecran = next(t for t in ecran.context["tableaux"] if t["cle"] == "facturation")

        export = self.lire_csv(
            self.client.get(reverse("backoffice:anomalies_export_famille", args=["facturation"]))
        )
        lignes_export = [l for l in export if l and l[0] == "Pharmacie Centrale"]

        self.assertEqual(len(tableau_ecran["lignes"]), len(lignes_export))

    def test_un_agent_n_accede_pas_aux_anomalies(self):
        self.client.force_login(self.compte_agent)

        self.assertEqual(self.client.get(reverse("backoffice:anomalies")).status_code, 403)
        self.assertEqual(self.client.get(reverse("backoffice:anomalies_export")).status_code, 403)
