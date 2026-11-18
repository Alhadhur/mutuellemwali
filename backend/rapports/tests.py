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
            type_prestataire=TypePrestataire.CLINIQUE, nom="Clinique El Maarouf",
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
        reponse = self.client.get(reverse("backoffice:rapports_export_un", args=["frequence"]) + "?format=csv")

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
                reverse("backoffice:rapports_export_un", args=["frequence"]) + "?format=csv"
            ).content.decode("utf-8-sig")),
            delimiter=";",
        ))
        lignes_export = [l for l in export if len(l) > 1 and l[1] == "A0001"]

        self.assertEqual(len(tableau["lignes"]), len(lignes_export))

    def test_un_agent_n_accede_pas_aux_rapports(self):
        self.client.force_login(self.agent.utilisateur)

        self.assertEqual(self.client.get(reverse("backoffice:rapports")).status_code, 403)
        self.assertEqual(self.client.get(reverse("backoffice:rapports_export")).status_code, 403)


class FrequenceEcranLimiteeTest(BaseRapports):
    """Avec beaucoup d'agents consommateurs, la liste à l'écran ne doit pas
    grandir sans limite — voir Tableau.limite_ecran. L'export, lui, garde
    toujours la liste complète."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        # self.agent et self.autre_agent ont chacun déjà leur propre matricule ;
        # 23 de plus donnent 25 agents consommateurs au total, au-delà de la
        # limite de 20 fixée sur ce tableau.
        self.matricules = ["A0001", "A0002"]
        for i in range(23):
            matricule = f"A{100 + i}"
            agent = self.creer_agent(matricule, "Perf", f"Agent{i}", site="Moroni", region="Ngazidja")
            self.prescription(agent, 1000 + i)
            self.matricules.append(matricule)
        self.prescription(self.agent, 5000)
        self.prescription(self.autre_agent, 5000)

    def test_l_ecran_plafonne_la_liste_mais_garde_le_vrai_total(self):
        reponse = self.client.get(reverse("backoffice:rapports"))
        tableau = next(t for t in reponse.context["tableaux"] if t["cle"] == "frequence")

        self.assertEqual(tableau["nombre_total"], 25)
        self.assertEqual(len(tableau["lignes"]), 20)
        self.assertTrue(tableau["tronque"])
        self.assertContains(reponse, "exportez le tableau complet")

    def test_l_export_garde_les_25_agents(self):
        reponse = self.client.get(reverse("backoffice:rapports_export_un", args=["frequence"]) + "?format=csv")

        lignes = list(csv.reader(io.StringIO(reponse.content.decode("utf-8-sig")), delimiter=";"))
        matricules_exportes = {l[1] for l in lignes if len(l) > 1 and l[1] in self.matricules}
        self.assertEqual(matricules_exportes, set(self.matricules))


class MontantsDusTest(BaseRapports):
    """Part mutuelle (taux 80 %) due à chaque prestataire, validé et en
    attente séparés, rejets écartés."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.prescription(self.agent, 10000, statut=StatutPrescription.VALIDEE)  # 8 000 validés
        self.prescription(self.autre_agent, 5000)  # 4 000 en attente (soumise)
        self.prescription(self.agent, 2500, jours=10, statut=StatutPrescription.EN_CONTROLE)  # 2 000 en attente
        self.prescription(self.agent, 50000, jours=20, statut=StatutPrescription.REJETEE)  # écarté
        self.prescription(self.agent, 20000, prestataire=self.clinique, statut=StatutPrescription.VALIDEE)

    def test_valide_et_en_attente_sont_separes_et_les_rejets_ecartes(self):
        lignes = services.montants_dus_par_prestataire(*self.periode())
        pharmacie = next(ligne for ligne in lignes if ligne["prestataire"] == "Pharmacie Centrale")

        self.assertEqual(pharmacie["actes_valides"], 1)
        self.assertEqual(pharmacie["du_valide"], 8000)
        self.assertEqual(pharmacie["actes_en_attente"], 2)
        self.assertEqual(pharmacie["du_en_attente"], 6000)
        self.assertEqual(pharmacie["du_estime"], 14000)

    def test_le_tableau_est_trie_par_montant_du(self):
        lignes = services.montants_dus_par_prestataire(*self.periode())

        self.assertEqual([ligne["prestataire"] for ligne in lignes], ["Clinique El Maarouf", "Pharmacie Centrale"])

    def test_la_synthese_donne_le_total_en_attente(self):
        synthese = services.activite_globale(*self.periode())

        self.assertEqual(synthese["part_mutuelle"], 24000)
        self.assertEqual(synthese["part_mutuelle_en_attente"], 6000)

    def test_le_tableau_apparait_sur_la_page_des_rapports(self):
        reponse = self.client.get(reverse("backoffice:rapports"))

        self.assertContains(reponse, "Montants dus aux prestataires")


class PeriodesTest(TestCase):
    """Période par défaut, raccourcis et comparaison à date égale."""

    def test_la_periode_par_defaut_est_le_mois_en_cours(self):
        debut, fin = services.periode_par_defaut()

        self.assertEqual(debut, date.today().replace(day=1))
        self.assertEqual(fin, date.today())

    def test_les_raccourcis(self):
        raccourcis = {cle: (d, f) for cle, _, d, f in services.raccourcis_periode(date(2026, 11, 12))}

        self.assertEqual(raccourcis["mois"], (date(2026, 11, 1), date(2026, 11, 12)))
        self.assertEqual(raccourcis["mois_dernier"], (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(raccourcis["trimestre"], (date(2026, 10, 1), date(2026, 11, 12)))
        self.assertEqual(raccourcis["annee"], (date(2026, 1, 1), date(2026, 11, 12)))
        self.assertEqual(raccourcis["douze_mois"], (date(2025, 12, 1), date(2026, 11, 12)))

    def test_le_mois_dernier_de_janvier_est_decembre(self):
        raccourcis = {cle: (d, f) for cle, _, d, f in services.raccourcis_periode(date(2027, 1, 5))}

        self.assertEqual(raccourcis["mois_dernier"], (date(2026, 12, 1), date(2026, 12, 31)))

    def test_le_mois_en_cours_se_compare_a_date_egale(self):
        self.assertEqual(
            services.periode_de_comparaison(date(2026, 11, 1), date(2026, 11, 12)),
            (date(2026, 10, 1), date(2026, 10, 12)),
        )

    def test_un_mois_complet_se_compare_au_mois_precedent_complet(self):
        self.assertEqual(
            services.periode_de_comparaison(date(2026, 11, 1), date(2026, 11, 30)),
            (date(2026, 10, 1), date(2026, 10, 31)),
        )
        self.assertEqual(
            services.periode_de_comparaison(date(2026, 3, 1), date(2026, 3, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )

    def test_le_30_mars_se_compare_au_28_fevrier(self):
        self.assertEqual(
            services.periode_de_comparaison(date(2026, 3, 1), date(2026, 3, 30)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )

    def test_pas_de_comparaison_hors_d_un_mois_unique(self):
        self.assertIsNone(services.periode_de_comparaison(date(2026, 10, 1), date(2026, 11, 12)))
        self.assertIsNone(services.periode_de_comparaison(date(2026, 11, 5), date(2026, 11, 12)))

    def test_le_mois_en_cours_est_provisoire(self):
        message = services.etat_provisoire(date(2026, 11, 1), date(2026, 11, 12), aujourdhui=date(2026, 11, 12))

        self.assertIn("jour 12 sur 30", message)

    def test_le_mois_dernier_est_a_confirmer_en_debut_de_mois(self):
        self.assertIn(
            "retard",
            services.etat_provisoire(date(2026, 10, 1), date(2026, 10, 31), aujourdhui=date(2026, 11, 5)),
        )
        self.assertEqual(
            services.etat_provisoire(date(2026, 10, 1), date(2026, 10, 31), aujourdhui=date(2026, 11, 20)), ""
        )


class ComparaisonEtEcranTest(BaseRapports):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)

    def test_la_variation_compare_au_mois_precedent(self):
        debut, fin = date(2026, 11, 1), date(2026, 11, 12)
        for jour in (date(2026, 10, 3), date(2026, 10, 20)):  # le 20 octobre est hors de la comparaison
            Prescription.objects.create(
                agent=self.agent, prestataire=self.pharmacie, numero_ordonnance=f"O-{jour}",
                montant_total=10000, date_emission=jour, justificatif="x.jpg",
            )
        for numero in ("N-1", "N-2"):
            Prescription.objects.create(
                agent=self.agent, prestataire=self.pharmacie, numero_ordonnance=numero,
                montant_total=10000, date_emission=date(2026, 11, 4), justificatif="x.jpg",
            )

        synthese = services.activite_globale(debut, fin)
        resultat = services.comparaison(debut, fin, synthese)

        self.assertEqual(resultat["variations"]["nombre_actes"], {"avant": 1, "pourcentage": 100})
        self.assertIsNone(resultat["variations"]["part_mutuelle"]["pourcentage"])

    def test_l_ecran_s_ouvre_sur_le_mois_en_cours_avec_les_raccourcis(self):
        self.prescription(self.agent, 12000)

        reponse = self.client.get(reverse("backoffice:rapports"))

        self.assertEqual(reponse.context["debut"], date.today().replace(day=1))
        actifs = [r["cle"] for r in reponse.context["raccourcis"] if r["actif"]]
        self.assertEqual(actifs, ["mois"])
        self.assertContains(reponse, "Mois dernier")
        self.assertContains(reponse, "chiffres provisoires")
        self.assertContains(reponse, 'class="variation"')

    def test_l_evolution_couvre_toujours_douze_mois(self):
        reponse = self.client.get(
            reverse("backoffice:rapports"), {"debut": "2026-01-01", "fin": "2026-01-31"}
        )

        evolution = next(t for t in reponse.context["tableaux"] if t["cle"] == "evolution")
        self.assertEqual(len(evolution["lignes"]), 12)
        self.assertFalse(evolution["suit_la_periode"])

    def test_un_intervalle_libre_n_active_aucun_raccourci_ni_comparaison(self):
        reponse = self.client.get(
            reverse("backoffice:rapports"), {"debut": "2026-01-05", "fin": "2026-02-10"}
        )

        self.assertFalse(any(r["actif"] for r in reponse.context["raccourcis"]))
        self.assertIsNone(reponse.context["comparaison"])


class FrequenceAnalyseTest(BaseRapports):
    """Les colonnes d'analyse de la fréquence par agent."""

    def setUp(self):
        super().setUp()
        enfant = AyantDroit.objects.create(
            agent=self.agent, nom="Zahra", prenom="Ali",
            date_naissance=date(2015, 1, 1), lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE, justificatif="a.jpg",
            statut_verification=StatutVerification.VALIDE,
        )
        self.prescription(self.agent, 6000, statut=StatutPrescription.VALIDEE, jours=3)
        self.prescription(self.agent, 4000, ayant_droit=enfant, prestataire=self.clinique, jours=1)
        self.prescription(self.agent, 2000, ayant_droit=enfant, statut=StatutPrescription.REJETEE)
        self.prescription(self.autre_agent, 8000)

    def test_detail_de_l_agent_le_plus_consommateur(self):
        premier = services.frequence_par_agent(*self.periode())[0]

        self.assertEqual(premier["rang"], 1)
        self.assertEqual(premier["matricule"], "A0001")
        self.assertEqual(premier["nombre"], 3)
        self.assertEqual((premier["actes_agent"], premier["actes_ayants_droit"]), (1, 2))
        self.assertEqual(premier["ayants_droit_soignes"], 1)
        self.assertEqual(premier["prestataires"], 2)
        self.assertEqual((premier["validees"], premier["en_attente"], premier["rejetees"]), (1, 1, 1))
        self.assertEqual(premier["part_mutuelle"], 4800)  # 80 % des seuls 6 000 validés
        self.assertEqual(premier["tranche"], "3 à 5 actes")
        self.assertEqual(premier["premier_acte"], date.today() - timedelta(days=3))
        self.assertEqual(premier["dernier_acte"], date.today())

    def test_parts_indice_et_cumul(self):
        premier, second = services.frequence_par_agent(*self.periode())

        self.assertEqual(premier["part_actes"], 75.0)
        self.assertEqual(premier["indice"], 1.5)  # 3 actes pour une moyenne de 2
        self.assertEqual(premier["part_montant"], 60.0)  # 12 000 sur 20 000
        self.assertEqual(second["part_montant_cumulee"], 100.0)


class ExportFrequenceExcelTest(BaseRapports):
    """Le rapport de fréquence s'exporte en classeur Excel mis en forme."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.prescription(self.agent, 12000, statut=StatutPrescription.VALIDEE)
        self.prescription(self.autre_agent, 3000)

    def _classeur(self):
        import zipfile

        reponse = self.client.get(reverse("backoffice:rapports_export_un", args=["frequence"]))
        self.assertEqual(
            reponse["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        self.assertIn(".xlsx", reponse["Content-Disposition"])
        archive = zipfile.ZipFile(io.BytesIO(reponse.content))
        return {nom: archive.read(nom).decode("utf-8") for nom in archive.namelist()}

    def test_trois_onglets_bien_nommes(self):
        classeur = self._classeur()["xl/workbook.xml"]

        for nom in ("Fréquence des consultations par", "Synthèse", "Sens des colonnes"):
            self.assertIn(nom, classeur)

    def test_le_tableau_est_filtrable_fige_et_formate(self):
        feuille = self._classeur()["xl/worksheets/sheet1.xml"]

        self.assertIn('state="frozen"', feuille)
        self.assertIn("<autoFilter ref=", feuille)
        self.assertIn("A0001", feuille)
        # Montants en nombres (pas en texte), triables et sommables.
        self.assertIn("<v>12000</v>", feuille)
        self.assertIn('orientation="landscape"', feuille)

    def test_les_totaux_sont_hors_du_filtre(self):
        import re

        feuille = self._classeur()["xl/worksheets/sheet1.xml"]
        derniere_filtree = int(re.search(r'<autoFilter ref="A\d+:[A-Z]+(\d+)"', feuille).group(1))
        ligne_total = int(re.search(r'<c r="A(\d+)" s="\d+" t="inlineStr"><is><t xml:space="preserve">Total<', feuille).group(1))

        self.assertGreater(ligne_total, derniere_filtree + 1)
        self.assertIn("<v>15000</v>", feuille)  # coût total des deux agents

    def test_la_synthese_reprend_la_repartition(self):
        synthese = self._classeur()["xl/worksheets/sheet2.xml"]

        self.assertIn("Coût total des soins (KMF)", synthese)
        self.assertIn("Répartition des agents par assiduité", synthese)

    def test_le_csv_reste_disponible(self):
        reponse = self.client.get(
            reverse("backoffice:rapports_export_un", args=["frequence"]) + "?format=csv"
        )

        self.assertEqual(reponse["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Part des actes (%)", reponse.content.decode("utf-8-sig"))

    def test_l_ecran_garde_six_colonnes_et_propose_les_deux_formats(self):
        reponse = self.client.get(reverse("backoffice:rapports"))
        tableau = next(t for t in reponse.context["tableaux"] if t["cle"] == "frequence")

        self.assertEqual(len(tableau["colonnes"]), 6)
        self.assertContains(reponse, "Exporter (Excel)")
        self.assertContains(reponse, "format=csv")


class ClasseurXlsxTest(TestCase):
    def test_lettres_de_colonnes(self):
        from backoffice.xlsx import lettre_colonne

        self.assertEqual([lettre_colonne(i) for i in (0, 25, 26, 27, 701, 702)], ["A", "Z", "AA", "AB", "ZZ", "AAA"])

    def test_le_texte_est_echappe(self):
        from backoffice.xlsx import Feuille

        feuille = Feuille("Essai")
        feuille.ajouter(["<Dupont & fils>"])

        self.assertIn("&lt;Dupont &amp; fils&gt;", feuille.xml())
