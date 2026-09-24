"""Tests des rapports d'activité.

Chaque rapport est vérifié sur un jeu de données dont on connaît le résultat
attendu à la main : c'est la seule façon de repérer une agrégation qui compte
deux fois, ou qui oublie une catégorie.
"""
import csv
import io
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, StatutVerification, TypeJustificatif
from parametrage.models import NatureSoin
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, TypePrestataire

from . import services


class BaseRapports(TestCase):
    def setUp(self):
        self.rh = Utilisateur.objects.create_user(
            "RH1", "x", nom="Rh", prenom="Service", role=Role.RH, region="Ngazidja"
        )
        self.agent = self.creer_agent("A0001", "Zahra", "Fatima", site="Moroni", region="Ngazidja")
        self.autre_agent = self.creer_agent("A0002", "Said", "Ali", site="Mutsamudu", region="Ndzuwani")

        self.pharmacie = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Pharmacie Centrale",
            ville="Moroni", taux_prise_en_charge=80,
        )
        self.clinique = Prestataire.objects.create(
            type_prestataire=TypePrestataire.ETABLISSEMENT, nom="Clinique El Maarouf",
            ville="Moroni", taux_prise_en_charge=80,
        )
        self.consultation = NatureSoin.objects.get(libelle="Consultation")
        self.pharmacie_nature = NatureSoin.objects.get(libelle="Pharmacie / médicaments")

    def creer_agent(self, matricule, nom, prenom, site, region):
        compte = Utilisateur.objects.create_user(
            matricule, "x", nom=nom, prenom=prenom, role=Role.AGENT, region=region
        )
        return Agent.objects.create(
            utilisateur=compte, site=site,
            date_naissance=date(1990, 1, 1), date_embauche=date(2018, 1, 1),
        )

    def prescription(self, agent, montant, nature=None, prestataire=None, jours=0,
                     numero=None, statut=None, ayant_droit=None):
        prescription = Prescription.objects.create(
            agent=agent,
            ayant_droit=ayant_droit,
            prestataire=prestataire or self.pharmacie,
            nature=nature or self.consultation,
            numero_ordonnance=numero or f"ORD-{Prescription.objects.count() + 1}",
            montant_total=montant,
            date_emission=date.today() - timedelta(days=jours),
            justificatif="x.jpg",
        )
        if statut:
            prescription.statut = statut
            prescription.save()
        return prescription

    def periode(self):
        return date.today() - timedelta(days=60), date.today()


class ActiviteGlobaleTest(BaseRapports):
    def test_les_totaux_recoupent_les_prescriptions(self):
        self.prescription(self.agent, 10000, statut=StatutPrescription.VALIDEE)
        self.prescription(self.agent, 5000, numero="ORD-B")
        self.prescription(self.autre_agent, 3000, numero="ORD-C")

        synthese = services.activite_globale(*self.periode())

        self.assertEqual(synthese["nombre_actes"], 3)
        self.assertEqual(synthese["cout_total_soins"], 18000)
        self.assertEqual(synthese["nombre_agents_consommateurs"], 2)
        self.assertEqual(synthese["panier_moyen"], 6000)

    def test_seuls_les_dossiers_valides_alimentent_la_part_mutuelle(self):
        """Une prescription soumise n'engage pas encore l'argent de la mutuelle."""
        self.prescription(self.agent, 10000, statut=StatutPrescription.VALIDEE)
        self.prescription(self.agent, 50000, numero="ORD-B")

        synthese = services.activite_globale(*self.periode())

        self.assertEqual(synthese["part_mutuelle"], 8000)
        self.assertEqual(synthese["part_agents"], 2000)

    def test_les_deux_parts_reconstituent_le_cout_des_dossiers_valides(self):
        self.prescription(self.agent, 9999, statut=StatutPrescription.VALIDEE)

        synthese = services.activite_globale(*self.periode())

        self.assertEqual(synthese["part_mutuelle"] + synthese["part_agents"], 9999)


class FrequenceTest(BaseRapports):
    def test_le_classement_place_le_plus_consommateur_en_tete(self):
        for i in range(3):
            self.prescription(self.agent, 1000, numero=f"A-{i}")
        self.prescription(self.autre_agent, 1000, numero="B-0")

        classement = services.frequence_par_agent(*self.periode())

        self.assertEqual(classement[0]["matricule"], "A0001")
        self.assertEqual(classement[0]["nombre"], 3)
        self.assertEqual(classement[1]["nombre"], 1)

    def test_les_agents_sans_aucun_acte_apparaissent_dans_la_distribution(self):
        """Sinon la tranche « aucun acte » serait toujours vide, et la lecture
        de l'assiduité complètement faussée."""
        self.prescription(self.agent, 1000)

        distribution = {ligne["tranche"]: ligne["agents"] for ligne in services.distribution_frequence(*self.periode())}

        self.assertEqual(distribution["Aucun acte"], 1)
        self.assertEqual(distribution["1 à 2 actes"], 1)

    def test_les_tranches_totalisent_l_effectif(self):
        self.prescription(self.agent, 1000)

        distribution = services.distribution_frequence(*self.periode())

        self.assertEqual(sum(ligne["agents"] for ligne in distribution), 2)


class RepartitionsTest(BaseRapports):
    def test_la_repartition_par_nature_conserve_les_prescriptions_sans_nature(self):
        """Une reprise d'historique n'a pas de nature : l'écarter fausserait
        les totaux."""
        self.prescription(self.agent, 10000, nature=self.consultation)
        sans_nature = self.prescription(self.agent, 5000, numero="ORD-B")
        Prescription.objects.filter(pk=sans_nature.pk).update(nature=None)

        lignes = services.consommation_par_nature(*self.periode())

        self.assertEqual(sum(l["montant"] for l in lignes), 15000)
        self.assertIn("Non renseignée", [l["nature"] for l in lignes])

    def test_la_part_de_chaque_prestataire_se_calcule_sur_le_total(self):
        self.prescription(self.agent, 7500, prestataire=self.pharmacie)
        self.prescription(self.agent, 2500, prestataire=self.clinique, numero="ORD-B")

        lignes = {l["prestataire"]: l["part_reseau"] for l in services.consommation_par_prestataire(*self.periode())}

        self.assertEqual(lignes["Pharmacie Centrale"], 75.0)
        self.assertEqual(lignes["Clinique El Maarouf"], 25.0)

    def test_la_consommation_se_ventile_par_region(self):
        self.prescription(self.agent, 1000)
        self.prescription(self.autre_agent, 2000, numero="ORD-B")

        lignes = {l["region"]: l["montant"] for l in services.consommation_par_region(*self.periode())}

        self.assertEqual(lignes["Ngazidja"], 1000)
        self.assertEqual(lignes["Ndzuwani"], 2000)

    def test_la_consommation_des_ayants_droit_est_distinguee(self):
        enfant = AyantDroit.objects.create(
            agent=self.agent, nom="Zahra", prenom="Ali",
            date_naissance=date(2015, 1, 1), lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE, justificatif="a.jpg",
            statut_verification=StatutVerification.VALIDE,
        )
        self.prescription(self.agent, 6000)
        self.prescription(self.agent, 4000, numero="ORD-B", ayant_droit=enfant)

        lignes = {l["beneficiaire"]: l for l in services.repartition_agent_ayants_droit(*self.periode())}

        self.assertEqual(lignes["L'agent lui-même"]["montant"], 6000)
        self.assertEqual(lignes["Ayants droit"]["montant"], 4000)
        self.assertEqual(lignes["Ayants droit"]["part"], 40.0)


class ActiviteDuServiceTest(BaseRapports):
    def test_le_delai_de_traitement_se_lit_dans_l_historique(self):
        prescription = self.prescription(self.agent, 10000)
        prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=self.rh)

        lignes = services.activite_du_service(*self.periode())

        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0]["utilisateur"], "Service Rh")
        self.assertEqual(lignes[0]["traitees"], 1)
        self.assertEqual(lignes[0]["validees"], 1)
        self.assertEqual(lignes[0]["delai_moyen_jours"], 0.0)

    def test_le_taux_de_rejet_est_calcule_par_agent_traitant(self):
        for i in range(3):
            prescription = self.prescription(self.agent, 1000, numero=f"R-{i}")
            decision = StatutPrescription.REJETEE if i == 0 else StatutPrescription.VALIDEE
            prescription.changer_statut(decision, utilisateur=self.rh)

        lignes = services.activite_du_service(*self.periode())

        self.assertEqual(lignes[0]["traitees"], 3)
        self.assertEqual(lignes[0]["taux_rejet"], 33.3)


class ExportRapportsTest(BaseRapports):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.prescription(self.agent, 12000, statut=StatutPrescription.VALIDEE)

    def test_l_export_d_un_rapport_contient_ses_lignes(self):
        reponse = self.client.get(reverse("backoffice:rapports_export_un", args=["frequence"]))

        self.assertEqual(reponse.status_code, 200)
        contenu = reponse.content.decode("utf-8-sig")
        self.assertIn("A0001", contenu)
        self.assertIn("12000", contenu)

    def test_l_export_complet_reprend_la_synthese_en_tete(self):
        """Le fichier doit se suffire à lui-même une fois transmis."""
        reponse = self.client.get(reverse("backoffice:rapports_export"))

        contenu = reponse.content.decode("utf-8-sig")
        self.assertIn("Coût total des soins (KMF);12000", contenu)
        self.assertIn("FRÉQUENCE DES CONSULTATIONS PAR AGENT", contenu)
        self.assertIn("ACTIVITÉ DU SERVICE MUTUELLE", contenu)

    def test_un_rapport_inconnu_renvoie_404(self):
        self.assertEqual(
            self.client.get(reverse("backoffice:rapports_export_un", args=["inventé"])).status_code, 404
        )

    def test_l_ecran_et_l_export_montrent_les_memes_lignes(self):
        ecran = self.client.get(reverse("backoffice:rapports"))
        tableau = next(t for t in ecran.context["tableaux"] if t["cle"] == "frequence")

        export = list(csv.reader(
            io.StringIO(self.client.get(
                reverse("backoffice:rapports_export_un", args=["frequence"])
            ).content.decode("utf-8-sig")),
            delimiter=";",
        ))
        lignes_export = [l for l in export if l and l[0] == "A0001"]

        self.assertEqual(len(tableau["lignes"]), len(lignes_export))

    def test_un_agent_n_accede_pas_aux_rapports(self):
        self.client.force_login(self.agent.utilisateur)

        self.assertEqual(self.client.get(reverse("backoffice:rapports")).status_code, 403)
        self.assertEqual(self.client.get(reverse("backoffice:rapports_export")).status_code, 403)
