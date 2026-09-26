from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, StatutVerification, TypeJustificatif
from facturation.models import Facture, StatutLigne
from parametrage.models import NatureSoin, Parametrage
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, StatutPrestataire, TypePrestataire


def fichier_csv(contenu, nom="fichier.csv"):
    return SimpleUploadedFile(nom, contenu.encode("utf-8"), content_type="text/csv")


class BaseBackoffice(TestCase):
    def setUp(self):
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.direction = Utilisateur.objects.create_user(
            "DIR1", "x", nom="Dir", prenom="Controle", role=Role.DIRECTION
        )
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
        self.prescription = Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-1",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )


class AccesTest(BaseBackoffice):
    def test_un_agent_n_accede_pas_au_backoffice(self):
        self.client.force_login(self.compte_agent)

        self.assertEqual(self.client.get(reverse("backoffice:agents")).status_code, 403)

    def test_la_direction_consulte_mais_ne_modifie_pas(self):
        self.client.force_login(self.direction)

        self.assertEqual(self.client.get(reverse("backoffice:agents")).status_code, 200)
        self.assertEqual(self.client.get(reverse("backoffice:agent_creer")).status_code, 403)

    def test_un_visiteur_non_connecte_est_redirige(self):
        reponse = self.client.get(reverse("backoffice:agents"))

        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/login/", reponse.url)


class TableauDeBordAgentTest(BaseBackoffice):
    """En attendant l'usage officiel de l'application mobile, un agent qui se
    connecte au back-office doit avoir un endroit à lui plutôt qu'un 403."""

    def test_un_agent_est_redirige_vers_son_propre_tableau_de_bord(self):
        self.client.force_login(self.compte_agent)

        reponse = self.client.get(reverse("backoffice:tableau_de_bord"), follow=True)

        self.assertEqual(reponse.redirect_chain[-1][0], reverse("backoffice:mon_tableau_de_bord"))

    def test_le_rh_n_est_pas_redirige(self):
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:tableau_de_bord"))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Tableau de bord anomalies")

    def test_le_tableau_de_bord_agent_n_affiche_que_ses_propres_donnees(self):
        autre_compte = Utilisateur.objects.create_user("A0002", "x", nom="Autre", prenom="Personne", role=Role.AGENT)
        autre_agent = Agent.objects.create(utilisateur=autre_compte, site="Moroni")
        Prescription.objects.create(
            agent=autre_agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-AUTRE",
            montant_total=5000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )
        self.client.force_login(self.compte_agent)

        reponse = self.client.get(reverse("backoffice:mon_tableau_de_bord"))

        self.assertContains(reponse, "ORD-1")
        self.assertNotContains(reponse, "ORD-AUTRE")

    def test_un_utilisateur_sans_fiche_agent_est_bloque(self):
        self.client.force_login(self.direction)

        reponse = self.client.get(reverse("backoffice:mon_tableau_de_bord"))

        self.assertEqual(reponse.status_code, 403)


class MaPrescriptionCreerTest(BaseBackoffice):
    """L'agent peut saisir sa propre ordonnance depuis son tableau de bord,
    en attendant l'usage officiel de l'application mobile — mais seulement la
    sienne, pour ses propres ayants droit."""

    def setUp(self):
        super().setUp()
        self.nature = NatureSoin.objects.get(libelle="Consultation")
        self.ayant_droit = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Fils",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
        )
        autre_compte = Utilisateur.objects.create_user("A0002", "x", nom="Autre", prenom="Personne", role=Role.AGENT)
        self.autre_agent = Agent.objects.create(utilisateur=autre_compte, site="Moroni")

    def _donnees(self, **extra):
        donnees = {
            "prestataire": self.prestataire.pk,
            "nature": self.nature.pk,
            "numero_ordonnance": "H-42",
            "montant_total": "10000",
            "date_emission": "2026-01-05",
        }
        donnees.update(extra)
        return donnees

    def test_un_non_agent_ne_peut_pas_acceder_au_formulaire(self):
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:ma_prescription_creer"))

        self.assertEqual(reponse.status_code, 403)

    def test_l_agent_cree_sa_propre_prescription(self):
        self.client.force_login(self.compte_agent)

        reponse = self.client.post(reverse("backoffice:ma_prescription_creer"), self._donnees())

        prescription = Prescription.objects.get(numero_ordonnance="H-42")
        self.assertEqual(prescription.agent, self.agent)
        self.assertEqual(prescription.soumis_par, self.compte_agent)
        self.assertRedirects(reponse, reverse("backoffice:mon_tableau_de_bord"))

    def test_l_agent_peut_saisir_pour_un_de_ses_ayants_droit(self):
        self.client.force_login(self.compte_agent)

        self.client.post(reverse("backoffice:ma_prescription_creer"), self._donnees(ayant_droit=self.ayant_droit.pk))

        prescription = Prescription.objects.get(numero_ordonnance="H-42")
        self.assertEqual(prescription.ayant_droit, self.ayant_droit)

    def test_l_agent_ne_peut_pas_saisir_pour_l_ayant_droit_d_un_autre(self):
        autre_ayant_droit = AyantDroit.objects.create(
            agent=self.autre_agent,
            nom="Etranger",
            prenom="Ayant",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
        )
        self.client.force_login(self.compte_agent)

        self.client.post(
            reverse("backoffice:ma_prescription_creer"), self._donnees(ayant_droit=autre_ayant_droit.pk)
        )

        self.assertFalse(Prescription.objects.filter(numero_ordonnance="H-42").exists())


class ListesTest(BaseBackoffice):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)

    def test_la_liste_des_agents_affiche_le_quota_issu_du_bareme(self):
        """Agent sans ayant droit : la tranche « sans conjoint, sans enfant »."""
        reponse = self.client.get(reverse("backoffice:agents"))

        self.assertContains(reponse, f"{self.agent.quota_effectif} KMF")
        self.assertContains(reponse, self.agent.matricule)

    def test_la_recherche_filtre_les_resultats(self):
        reponse = self.client.get(reverse("backoffice:agents"), {"recherche": "introuvable"})

        self.assertNotContains(reponse, self.agent.matricule)

    def test_les_prescriptions_se_filtrent_par_statut(self):
        reponse = self.client.get(reverse("backoffice:prescriptions"), {"statut": StatutPrescription.VALIDEE})

        self.assertNotContains(reponse, "ORD-1")


class RechercheAgentTest(BaseBackoffice):
    """Les écrans de saisie ne peuvent pas afficher deux mille agents dans une
    liste déroulante : le choix de l'agent passe par une recherche."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)

    def test_recherche_par_matricule(self):
        reponse = self.client.get(reverse("backoffice:recherche_agents"), {"q": "A0001"})

        resultats = reponse.json()["resultats"]
        self.assertEqual([r["matricule"] for r in resultats], ["A0001"])

    def test_recherche_par_nom(self):
        """« Zahra » est le nom de famille du compte A0001."""
        reponse = self.client.get(reverse("backoffice:recherche_agents"), {"q": "Zahra"})

        self.assertEqual([r["matricule"] for r in reponse.json()["resultats"]], ["A0001"])

    def test_recherche_par_prenom(self):
        """« Fatima » est le prénom du compte A0001."""
        reponse = self.client.get(reverse("backoffice:recherche_agents"), {"q": "Fatima"})

        self.assertEqual([r["matricule"] for r in reponse.json()["resultats"]], ["A0001"])

    def test_la_recherche_est_insensible_a_la_casse(self):
        reponse = self.client.get(reverse("backoffice:recherche_agents"), {"q": "fatima"})

        self.assertEqual(len(reponse.json()["resultats"]), 1)

    def test_les_ecrans_de_saisie_utilisent_la_recherche(self):
        """Prescription et ayant droit partagent le même champ de recherche ;
        la liste déroulante complète ne doit plus être proposée à l'écran."""
        for url in ("backoffice:ayant_droit_creer", "backoffice:prescription_creer"):
            with self.subTest(url=url):
                reponse = self.client.get(reverse(url))

                self.assertContains(reponse, 'id="recherche-agent"')
                self.assertContains(reponse, "recherche/agents/")
                self.assertContains(reponse, 'class="agent-masque"')

    def test_l_agent_deja_rattache_reste_selectionne_a_la_modification(self):
        enfant = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Ali",
            date_naissance=date(2015, 3, 2),
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="acte.jpg",
        )

        reponse = self.client.get(reverse("backoffice:ayant_droit_modifier", args=[enfant.pk]))

        self.assertContains(reponse, f'value="{self.agent.pk}" selected')

    def test_un_agent_inactif_n_est_pas_proposé(self):
        self.agent.actif = False
        self.agent.save()

        reponse = self.client.get(reverse("backoffice:recherche_agents"), {"q": "A0001"})

        self.assertEqual(reponse.json()["resultats"], [])

    def test_un_agent_n_accede_pas_a_la_recherche(self):
        self.client.force_login(self.compte_agent)

        self.assertEqual(self.client.get(reverse("backoffice:recherche_agents")).status_code, 403)


class AyantsDroitDeLAgentTest(BaseBackoffice):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.enfant = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Amine",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
        )

    def test_seuls_les_ayants_droit_de_l_agent_sont_renvoyes(self):
        autre_compte = Utilisateur.objects.create_user("A0002", "x", nom="B", prenom="C", role=Role.AGENT)
        autre_agent = Agent.objects.create(
            utilisateur=autre_compte,
            site="Moroni",
            date_naissance=date(1990, 1, 1),
            date_embauche=date(2018, 6, 1),
        )
        AyantDroit.objects.create(
            agent=autre_agent,
            nom="Autre",
            prenom="Personne",
            lien_parente=LienParente.CONJOINT,
            type_justificatif=TypeJustificatif.ACTE_MARIAGE,
            justificatif="x.jpg",
        )

        reponse = self.client.get(reverse("backoffice:recherche_ayants_droit", args=[self.agent.pk]))

        resultats = reponse.json()["resultats"]
        self.assertEqual([r["id"] for r in resultats], [self.enfant.pk])

    def test_un_ayant_droit_non_couvert_est_signale(self):
        self.enfant.statut_verification = StatutVerification.EN_ATTENTE
        self.enfant.save()

        reponse = self.client.get(reverse("backoffice:recherche_ayants_droit", args=[self.agent.pk]))

        self.assertFalse(reponse.json()["resultats"][0]["couvert"])


class ChangementStatutTest(BaseBackoffice):
    def test_valider_une_prescription_trace_l_auteur_et_le_commentaire(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:prescription_statut", args=[self.prescription.pk]),
            {"statut": StatutPrescription.VALIDEE, "commentaire": "Contrôle effectué"},
        )

        self.prescription.refresh_from_db()
        trace = self.prescription.historique.last()
        self.assertEqual(self.prescription.statut, StatutPrescription.VALIDEE)
        self.assertEqual(trace.utilisateur, self.rh)
        self.assertEqual(trace.commentaire, "Contrôle effectué")

    def test_un_statut_inconnu_est_refuse(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:prescription_statut", args=[self.prescription.pk]),
            {"statut": "N_IMPORTE_QUOI"},
        )

        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.statut, StatutPrescription.SOUMISE)


class AyantDroitTest(BaseBackoffice):
    def setUp(self):
        super().setUp()
        self.ayant_droit = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Amine",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
        )

    def test_valider_trace_l_auteur_et_la_date(self):
        self.client.force_login(self.rh)

        self.client.post(reverse("backoffice:ayant_droit_verifier", args=[self.ayant_droit.pk, "valider"]))

        self.ayant_droit.refresh_from_db()
        self.assertEqual(self.ayant_droit.statut_verification, StatutVerification.VALIDE)
        self.assertEqual(self.ayant_droit.verifie_par, self.rh)
        self.assertIsNotNone(self.ayant_droit.date_verification)


class AyantDroitFiltresTest(BaseBackoffice):
    """Avec plusieurs milliers d'ayants droit, il faut pouvoir repérer d'un
    coup d'œil les enfants qui sortent de la couverture (limite d'âge) ou les
    justificatifs à renouveler (expirés), en plus des filtres attendus
    (lien, statut, âge)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        aujourdhui = timezone.localdate()

        self.enfant_jeune = AyantDroit.objects.create(
            agent=self.agent,
            nom="Jeune",
            prenom="Enfant",
            date_naissance=aujourdhui.replace(year=aujourdhui.year - 5),
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
        )
        self.enfant_majeur = AyantDroit.objects.create(
            agent=self.agent,
            nom="Majeur",
            prenom="Enfant",
            date_naissance=aujourdhui.replace(year=aujourdhui.year - 20),
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.EN_ATTENTE,
        )
        self.partenaire = AyantDroit.objects.create(
            agent=self.agent,
            nom="Partenaire",
            prenom="Un",
            date_naissance=aujourdhui.replace(year=aujourdhui.year - 30),
            lien_parente=LienParente.CONJOINT,
            type_justificatif=TypeJustificatif.ACTE_MARIAGE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
            date_validite=aujourdhui - timedelta(days=10),
        )

    def test_filtre_par_lien_de_parente(self):
        reponse = self.client.get(reverse("backoffice:ayants_droit"), {"lien": LienParente.CONJOINT})

        self.assertContains(reponse, "Un Partenaire")
        self.assertNotContains(reponse, "Enfant Jeune")
        self.assertNotContains(reponse, "Enfant Majeur")

    def test_filtre_par_statut_de_verification(self):
        reponse = self.client.get(reverse("backoffice:ayants_droit"), {"statut": StatutVerification.EN_ATTENTE})

        self.assertContains(reponse, "Enfant Majeur")
        self.assertNotContains(reponse, "Enfant Jeune")
        self.assertNotContains(reponse, "Un Partenaire")

    def test_filtre_par_age_minimum(self):
        reponse = self.client.get(reverse("backoffice:ayants_droit"), {"age_min": "15"})

        self.assertContains(reponse, "Enfant Majeur")
        self.assertContains(reponse, "Un Partenaire")
        self.assertNotContains(reponse, "Enfant Jeune")

    def test_filtre_par_age_maximum(self):
        reponse = self.client.get(reverse("backoffice:ayants_droit"), {"age_max": "10"})

        self.assertContains(reponse, "Enfant Jeune")
        self.assertNotContains(reponse, "Enfant Majeur")
        self.assertNotContains(reponse, "Un Partenaire")

    def test_filtre_limite_d_age_depassee_ne_retient_que_les_enfants_concernes(self):
        reponse = self.client.get(reverse("backoffice:ayants_droit"), {"limite_depassee": "1"})

        self.assertContains(reponse, "Enfant Majeur")
        self.assertNotContains(reponse, "Enfant Jeune")
        self.assertNotContains(reponse, "Un Partenaire")

    def test_filtre_justificatif_expire(self):
        reponse = self.client.get(reverse("backoffice:ayants_droit"), {"justificatif_expire": "1"})

        self.assertContains(reponse, "Un Partenaire")
        self.assertNotContains(reponse, "Enfant Jeune")
        self.assertNotContains(reponse, "Enfant Majeur")


class PrestataireTest(BaseBackoffice):
    def test_basculer_le_statut_suspend_puis_reactive(self):
        self.client.force_login(self.rh)
        url = reverse("backoffice:prestataire_statut", args=[self.prestataire.pk])

        self.client.post(url)
        self.prestataire.refresh_from_db()
        self.assertEqual(self.prestataire.statut, StatutPrestataire.SUSPENDU)

        self.client.post(url)
        self.prestataire.refresh_from_db()
        self.assertEqual(self.prestataire.statut, StatutPrestataire.ACTIF)


class UtilisateurTest(BaseBackoffice):
    def test_creer_un_compte_enregistre_un_mot_de_passe_utilisable(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:utilisateur_creer"),
            {
                "matricule": "A0009",
                "nom": "Test",
                "prenom": "Nouveau",
                "email": "",
                "role": Role.AGENT,
                "telephone": "+269 333 44 55",
                "region": "Ngazidja",
                "is_active": "on",
                "mot_de_passe": "MotDePasse2026!",
                "confirmation": "MotDePasse2026!",
            },
        )

        cree = Utilisateur.objects.get(matricule="A0009")
        self.assertTrue(cree.check_password("MotDePasse2026!"))
        self.assertEqual(cree.telephone, "+269 333 44 55")

    def test_le_telephone_reste_facultatif(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:utilisateur_creer"),
            {
                "matricule": "A0011",
                "nom": "Test",
                "prenom": "Sans numéro",
                "role": Role.AGENT,
                "is_active": "on",
                "mot_de_passe": "MotDePasse2026!",
                "confirmation": "MotDePasse2026!",
            },
        )

        self.assertEqual(Utilisateur.objects.get(matricule="A0011").telephone, "")

    def test_deux_mots_de_passe_differents_bloquent_la_creation(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:utilisateur_creer"),
            {
                "matricule": "A0010",
                "nom": "Test",
                "prenom": "Nouveau",
                "role": Role.AGENT,
                "mot_de_passe": "Un",
                "confirmation": "Deux",
            },
        )

        self.assertFalse(Utilisateur.objects.filter(matricule="A0010").exists())


class ParametrageTest(BaseBackoffice):
    def test_le_formulaire_met_a_jour_la_ligne_unique(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:parametrage"),
            {
                "cotisation_base": "5000",
                "conjoints_inclus": "1",
                "enfants_inclus": "3",
                "cout_conjoint_supplementaire": "2000",
                "cout_enfant_supplementaire": "2000",
                "age_limite_enfant": "18",
                "duree_cycle_mois": "2",
                "quota_mensuel_defaut": "75000",
                "fenetre_analyse_jours": "45",
                "seuil_volume_ecart_type": "2.00",
                "seuil_alerte_quota": "15",
            },
        )

        parametres = Parametrage.charger()
        self.assertEqual(parametres.quota_mensuel_defaut, 75000)
        self.assertEqual(Parametrage.objects.count(), 1)

    def test_les_seuils_de_detection_sont_reglables_sans_toucher_au_code(self):
        self.client.force_login(self.rh)

        self.client.post(
            reverse("backoffice:parametrage"),
            {
                "cotisation_base": "5000",
                "conjoints_inclus": "1",
                "enfants_inclus": "3",
                "cout_conjoint_supplementaire": "2000",
                "cout_enfant_supplementaire": "2000",
                "age_limite_enfant": "18",
                "duree_cycle_mois": "1",
                "quota_mensuel_defaut": "0",
                "fenetre_analyse_jours": "90",
                "seuil_volume_ecart_type": "0.50",
                "seuil_alerte_quota": "25",
            },
        )

        parametres = Parametrage.charger()
        self.assertEqual(parametres.fenetre_analyse_jours, 90)
        self.assertEqual(str(parametres.seuil_volume_ecart_type), "0.50")
        self.assertEqual(parametres.seuil_alerte_quota, 25)


class ImportsWebTest(BaseBackoffice):
    """Import CSV avec aperçu (upload → erreurs à l'écran → confirmation),
    pour les trois écrans qui n'avaient jusqu'ici qu'une commande manage.py :
    Prestataires, Prescriptions (historique) et Factures."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)

    # --- En-têtes accentués --------------------------------------------
    # Nos propres exports (UtilisateurExport, AyantDroitExport…) mettent des
    # en-têtes accentués (« Prénom », « Téléphone »…) pour rester lisibles à
    # l'écran ; l'import doit reconnaître ces mêmes en-têtes sans que
    # l'utilisateur ait à les retaper en ASCII.

    def test_import_utilisateurs_reconnait_les_en_tetes_accentues_de_l_export(self):
        contenu = (
            "Matricule;Nom;Prénom;Email;Téléphone;Rôle;Région;Actif\n"
            "156;RAMADANE;SAID MLIMI;;337 66 51;Agent (bénéficiaire);Moheli;oui\n"
        )
        self.client.post(reverse("backoffice:utilisateur_import"), {"fichier": fichier_csv(contenu)})

        self.client.post(reverse("backoffice:utilisateur_import"), {"confirmer": "1"})

        utilisateur = Utilisateur.objects.get(matricule="156")
        self.assertEqual(utilisateur.nom, "RAMADANE")
        self.assertEqual(utilisateur.prenom, "SAID MLIMI")
        self.assertEqual(utilisateur.telephone, "337 66 51")
        self.assertEqual(utilisateur.role, Role.AGENT)
        self.assertEqual(utilisateur.region, "Moheli")
        self.assertTrue(utilisateur.is_active)

    def test_import_ayants_droit_reconnait_les_en_tetes_de_l_export(self):
        contenu = (
            "Agent;Nom;Prénom;Date de naissance;lien_parente;Type de justificatif;"
            "Justificatif;Date de validité;Statut de vérification\n"
            "A0001;HOUFRA;RAMADANE;08/06/2009;Enfant;Acte de naissance;;;Validé\n"
        )
        self.client.post(reverse("backoffice:ayant_droit_import"), {"fichier": fichier_csv(contenu)})

        self.client.post(reverse("backoffice:ayant_droit_import"), {"confirmer": "1"})

        ayant_droit = AyantDroit.objects.get(agent=self.agent, nom="HOUFRA")
        self.assertEqual(ayant_droit.date_naissance, date(2009, 6, 8))
        self.assertEqual(ayant_droit.type_justificatif, TypeJustificatif.ACTE_NAISSANCE)
        self.assertEqual(ayant_droit.statut_verification, StatutVerification.VALIDE)

    # --- Prestataires -------------------------------------------------

    def test_import_prestataires_apercu_signale_l_erreur_sans_rien_ecrire(self):
        contenu = "type;nom;ville\nxxx;Sans Type;Moroni\n"
        self.client.post(reverse("backoffice:prestataire_import"), {"fichier": fichier_csv(contenu)})

        self.assertFalse(Prestataire.objects.filter(nom="Sans Type").exists())

    def test_import_prestataires_confirmation_ecrit(self):
        contenu = "type;nom;ville\npharmacie;Pharma Neuve;Moroni\n"
        self.client.post(reverse("backoffice:prestataire_import"), {"fichier": fichier_csv(contenu)})
        self.assertFalse(Prestataire.objects.filter(nom="Pharma Neuve").exists(), "l'aperçu ne doit rien écrire")

        self.client.post(reverse("backoffice:prestataire_import"), {"confirmer": "1"})

        self.assertTrue(Prestataire.objects.filter(nom="Pharma Neuve").exists())

    # --- Prescriptions (historique) ------------------------------------

    def test_import_prescriptions_apercu_signale_l_agent_introuvable(self):
        contenu = (
            "agent;prestataire;numero_ordonnance;montant_total;date_emission\n"
            "MATRICULE_INCONNU;Pharmacie Centrale;H-1;5000;2026-01-06\n"
        )
        self.client.post(reverse("backoffice:prescription_import"), {"fichier": fichier_csv(contenu)})

        self.assertFalse(Prescription.objects.filter(numero_ordonnance="H-1").exists())

    def test_import_prescriptions_confirmation_respecte_le_statut_du_fichier(self):
        contenu = (
            "agent;prestataire;numero_ordonnance;montant_total;date_emission;statut\n"
            "A0001;Pharmacie Centrale;H-1;10000;2026-01-05;validee\n"
        )
        self.client.post(reverse("backoffice:prescription_import"), {"fichier": fichier_csv(contenu)})

        self.client.post(reverse("backoffice:prescription_import"), {"confirmer": "1"})

        prescription = Prescription.objects.get(numero_ordonnance="H-1")
        self.assertEqual(prescription.statut, StatutPrescription.VALIDEE)
        self.assertEqual(prescription.montant_rembourse, 8000)

    # --- Factures --------------------------------------------------------

    def _donnees_facture(self, numero, contenu):
        return {
            "prestataire": self.prestataire.pk,
            "numero": numero,
            "mois": str(self.prescription.date_emission.month),
            "annee": str(self.prescription.date_emission.year),
            "montant_total_declare": "8000",
            "montant_colonne": "total",
            "fichier_csv": fichier_csv(contenu),
        }

    def test_import_facture_apercu_signale_une_date_illisible_sans_rien_ecrire(self):
        contenu = "date;matricule;beneficiaire;nature;montant\n;A0001;Fatima Zahra;Consultation;10000\n"
        self.client.post(reverse("backoffice:facture_import"), self._donnees_facture("F-1", contenu))

        self.assertFalse(Facture.objects.filter(numero="F-1").exists())

    def test_import_facture_confirmation_cree_l_entete_et_rapproche(self):
        # Même date que self.prescription (créée dans BaseBackoffice avec
        # date_emission=date.today()) : c'est ce qui permet au rapprochement
        # de la retrouver.
        jour = self.prescription.date_emission.isoformat()
        contenu = f"date;matricule;beneficiaire;nature;montant\n{jour};A0001;Fatima Zahra;Consultation;10000\n"
        self.client.post(reverse("backoffice:facture_import"), self._donnees_facture("F-1", contenu))

        self.client.post(reverse("backoffice:facture_import"), {"confirmer": "1"})

        facture = Facture.objects.get(numero="F-1")
        self.assertEqual(facture.prestataire, self.prestataire)
        self.assertEqual(facture.saisie_par, self.rh)
        # Correspond exactement à self.prescription (même agent, même
        # prestataire, même date, même montant) : le rapprochement doit
        # l'avoir déjà repérée sans intervention manuelle.
        ligne = facture.lignes.get()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)

    def test_import_facture_refuse_un_numero_deja_enregistre(self):
        contenu = "date;matricule;beneficiaire;nature;montant\n2026-01-05;A0001;Fatima Zahra;Consultation;10000\n"
        self.client.post(reverse("backoffice:facture_import"), self._donnees_facture("F-1", contenu))
        self.client.post(reverse("backoffice:facture_import"), {"confirmer": "1"})

        reponse = self.client.post(reverse("backoffice:facture_import"), self._donnees_facture("F-1", contenu))

        self.assertContains(reponse, "déjà enregistrée")
        self.assertEqual(Facture.objects.filter(numero="F-1").count(), 1)
