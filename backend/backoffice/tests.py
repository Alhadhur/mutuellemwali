from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, StatutVerification, TypeJustificatif
from facturation.models import Facture, StatutFacture, StatutLigne
from parametrage.models import NatureSoin, Parametrage, TrancheQuota
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, StatutPrestataire, TarifPrestataire, TypePrestataire


def fichier_csv(contenu, nom="fichier.csv", encodage="utf-8"):
    return SimpleUploadedFile(nom, contenu.encode(encodage), content_type="text/csv")


class BaseBackoffice(TestCase):
    def setUp(self):
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.superuser = Utilisateur.objects.create_superuser("SUPER1", "x", nom="Super", prenom="Admin")
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

    def test_la_recherche_filtre_ses_propres_prescriptions(self):
        """Utile quand l'historique de l'agent s'allonge : retrouver une
        prescription par son numéro, son prestataire ou sa nature."""
        Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-2",
            montant_total=2000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )
        self.client.force_login(self.compte_agent)

        reponse = self.client.get(reverse("backoffice:mon_tableau_de_bord"), {"recherche": "ORD-2"})

        self.assertContains(reponse, "ORD-2")
        self.assertNotContains(reponse, "ORD-1")

    def test_la_recherche_sans_resultat_affiche_un_message(self):
        self.client.force_login(self.compte_agent)

        reponse = self.client.get(reverse("backoffice:mon_tableau_de_bord"), {"recherche": "INTROUVABLE"})

        self.assertNotContains(reponse, "ORD-1")
        self.assertContains(reponse, "Aucune prescription ne correspond")

    def test_les_prescriptions_se_paginent_au_dela_de_15(self):
        for i in range(16):
            Prescription.objects.create(
                agent=self.agent,
                prestataire=self.prestataire,
                numero_ordonnance=f"ORD-PAGE-{i}",
                montant_total=1000,
                date_emission=date.today(),
                justificatif="x.jpg",
            )
        self.client.force_login(self.compte_agent)

        reponse = self.client.get(reverse("backoffice:mon_tableau_de_bord"))

        self.assertContains(reponse, "Page 1 sur 2")
        self.assertContains(reponse, "Suivant")


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

        prescription = Prescription.objects.exclude(pk=self.prescription.pk).get()
        self.assertEqual(prescription.agent, self.agent)
        self.assertEqual(prescription.soumis_par, self.compte_agent)
        self.assertTrue(prescription.numero_ordonnance)
        self.assertRedirects(reponse, reverse("backoffice:mon_tableau_de_bord"))

    def test_l_agent_peut_saisir_pour_un_de_ses_ayants_droit(self):
        self.client.force_login(self.compte_agent)

        self.client.post(reverse("backoffice:ma_prescription_creer"), self._donnees(ayant_droit=self.ayant_droit.pk))

        prescription = Prescription.objects.exclude(pk=self.prescription.pk).get()
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

        self.assertEqual(Prescription.objects.count(), 1)  # seulement celle de BaseBackoffice.setUp


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

    def test_les_prescriptions_se_filtrent_par_prestataire(self):
        autre_prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Autre Pharmacie", taux_prise_en_charge=80
        )
        Prescription.objects.create(
            agent=self.agent,
            prestataire=autre_prestataire,
            numero_ordonnance="ORD-AUTRE",
            montant_total=3000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        reponse = self.client.get(reverse("backoffice:prescriptions"), {"prestataire": self.prestataire.pk})

        self.assertContains(reponse, "ORD-1")
        self.assertNotContains(reponse, "ORD-AUTRE")

    def test_les_prescriptions_se_filtrent_par_nature(self):
        nature = NatureSoin.objects.get(libelle="Consultation")
        self.prescription.nature = nature
        self.prescription.save()
        Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-SANS-NATURE",
            montant_total=3000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        reponse = self.client.get(reverse("backoffice:prescriptions"), {"nature": nature.pk})

        self.assertContains(reponse, "ORD-1")
        self.assertNotContains(reponse, "ORD-SANS-NATURE")

    def test_les_prescriptions_se_filtrent_par_periode(self):
        Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-ANCIENNE",
            montant_total=3000,
            date_emission=date(2020, 1, 1),
            justificatif="x.jpg",
        )

        reponse = self.client.get(reverse("backoffice:prescriptions"), {"date_min": date.today().isoformat()})

        self.assertContains(reponse, "ORD-1")
        self.assertNotContains(reponse, "ORD-ANCIENNE")

    def test_les_prescriptions_se_filtrent_par_agent(self):
        """Depuis la fiche d'un agent, on doit pouvoir retrouver uniquement
        ses prescriptions plutôt que le top 20 figé de la fiche."""
        autre_compte = Utilisateur.objects.create_user("A0002", "x", nom="Autre", prenom="Agent", role=Role.AGENT)
        autre_agent = Agent.objects.create(
            utilisateur=autre_compte, site="Moroni", date_naissance=date(1988, 1, 1), date_embauche=date(2019, 1, 1)
        )
        Prescription.objects.create(
            agent=autre_agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-AUTRE-AGENT",
            montant_total=3000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        reponse = self.client.get(reverse("backoffice:prescriptions"), {"agent": self.agent.pk})

        self.assertContains(reponse, "ORD-1")
        self.assertNotContains(reponse, "ORD-AUTRE-AGENT")
        self.assertContains(reponse, self.agent.matricule)

    def test_la_fiche_agent_propose_un_lien_vers_toutes_ses_prescriptions(self):
        reponse = self.client.get(reverse("backoffice:agent_detail", args=[self.agent.pk]))

        self.assertContains(reponse, f'{reverse("backoffice:prescriptions")}?agent={self.agent.pk}')

    def test_la_liste_des_prescriptions_distingue_agent_et_ayant_droit(self):
        ayant_droit = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Fils",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
        )
        Prescription.objects.create(
            agent=self.agent,
            ayant_droit=ayant_droit,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-ENFANT",
            montant_total=5000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        reponse = self.client.get(reverse("backoffice:prescriptions"))

        self.assertContains(reponse, self.agent.matricule)
        self.assertContains(reponse, "Fils Zahra (Enfant)")

    def test_la_fiche_prescription_affiche_l_ayant_droit_en_plus_de_l_agent(self):
        ayant_droit = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Fils",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
        )
        self.prescription.ayant_droit = ayant_droit
        self.prescription.save()

        reponse = self.client.get(reverse("backoffice:prescription_detail", args=[self.prescription.pk]))

        self.assertContains(reponse, self.agent.matricule)
        self.assertContains(reponse, "Fils")
        self.assertContains(reponse, "Zahra")
        self.assertContains(reponse, "Enfant")


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


class NaturesDuPrestataireTest(BaseBackoffice):
    """Sur la saisie d'une prescription, les natures proposées doivent se
    restreindre à celles réellement tarifées chez le prestataire choisi,
    plutôt que d'afficher toute la liste — comme la détection d'anomalies à
    la facturation (voir Prestataire.propose_nature)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.consultation = NatureSoin.objects.get(libelle="Consultation")
        self.hospitalisation = NatureSoin.objects.get(libelle="Hospitalisation")

    def test_un_prestataire_detaille_ne_propose_que_ses_natures_tarifees(self):
        TarifPrestataire.objects.create(
            prestataire=self.prestataire, nature_soin=self.consultation, taux_prise_en_charge=90
        )

        reponse = self.client.get(reverse("backoffice:recherche_natures_prestataire", args=[self.prestataire.pk]))

        resultats = reponse.json()["resultats"]
        self.assertEqual([r["id"] for r in resultats], [self.consultation.pk])

    def test_un_prestataire_non_detaille_propose_toutes_les_natures(self):
        """Pas encore de tarif par nature chez ce prestataire : aucune
        restriction, sinon la saisie serait bloquée par défaut."""
        reponse = self.client.get(reverse("backoffice:recherche_natures_prestataire", args=[self.prestataire.pk]))

        resultats = reponse.json()["resultats"]
        self.assertIn(self.consultation.pk, [r["id"] for r in resultats])
        self.assertIn(self.hospitalisation.pk, [r["id"] for r in resultats])

    def test_une_nature_desactivee_n_est_pas_proposee(self):
        self.hospitalisation.active = False
        self.hospitalisation.save()

        reponse = self.client.get(reverse("backoffice:recherche_natures_prestataire", args=[self.prestataire.pk]))

        self.assertNotIn(self.hospitalisation.pk, [r["id"] for r in reponse.json()["resultats"]])


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


class PrescriptionModifierTest(BaseBackoffice):
    """Une erreur de saisie doit pouvoir être corrigée tant que la
    prescription n'a pas encore été décidée — comme pour la suppression."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)
        self.nature = NatureSoin.objects.get(libelle="Consultation")

    def _donnees(self, **extra):
        donnees = {
            "agent": self.agent.pk,
            "prestataire": self.prestataire.pk,
            "nature": self.nature.pk,
            "montant_total": "15000",
            "date_emission": "2026-01-05",
        }
        donnees.update(extra)
        return donnees

    def test_une_prescription_soumise_se_modifie(self):
        reponse = self.client.post(
            reverse("backoffice:prescription_modifier", args=[self.prescription.pk]), self._donnees()
        )

        self.assertRedirects(reponse, reverse("backoffice:prescription_detail", args=[self.prescription.pk]))
        self.prescription.refresh_from_db()
        # Généré à la création, pas modifiable depuis ce formulaire.
        self.assertEqual(self.prescription.numero_ordonnance, "ORD-1")
        self.assertEqual(self.prescription.montant_total, 15000)
        self.assertEqual(self.prescription.montant_rembourse, 12000)

    def test_une_prescription_validee_ne_se_modifie_pas(self):
        self.prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=self.rh)

        reponse = self.client.post(
            reverse("backoffice:prescription_modifier", args=[self.prescription.pk]), self._donnees()
        )

        self.assertRedirects(reponse, reverse("backoffice:prescription_detail", args=[self.prescription.pk]))
        self.prescription.refresh_from_db()
        self.assertEqual(self.prescription.numero_ordonnance, "ORD-1")

    def test_la_direction_ne_peut_pas_ouvrir_le_formulaire(self):
        self.client.force_login(self.direction)

        reponse = self.client.get(reverse("backoffice:prescription_modifier", args=[self.prescription.pk]))

        self.assertEqual(reponse.status_code, 403)

    def test_le_lien_annuler_pointe_vers_la_fiche_et_non_vers_none(self):
        """FormulaireBase fixe « Annuler » sur self.success_url, un attribut
        de classe absent ici (la destination dépend de l'objet édité) : sans
        le correctif, url_retour vaut None et le lien pointe vers "None",
        d'où un 404 au clic."""
        reponse = self.client.get(reverse("backoffice:prescription_modifier", args=[self.prescription.pk]))

        self.assertContains(
            reponse, reverse("backoffice:prescription_detail", args=[self.prescription.pk])
        )
        self.assertNotContains(reponse, 'href="None"')


class PrescriptionSupprimerTest(BaseBackoffice):
    """Suppression réservée au superuser (voir AccesSuperuser) : RH garde la
    création/modification des prescriptions, pas l'effacement d'une pièce
    déjà soumise."""

    def test_une_prescription_soumise_se_supprime(self):
        self.client.force_login(self.superuser)

        reponse = self.client.post(reverse("backoffice:prescription_supprimer", args=[self.prescription.pk]))

        self.assertRedirects(reponse, reverse("backoffice:prescriptions"))
        self.assertFalse(Prescription.objects.filter(pk=self.prescription.pk).exists())

    def test_une_prescription_validee_ne_se_supprime_pas(self):
        self.client.force_login(self.superuser)
        self.prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=self.superuser)

        reponse = self.client.post(reverse("backoffice:prescription_supprimer", args=[self.prescription.pk]))

        self.assertRedirects(reponse, reverse("backoffice:prescription_detail", args=[self.prescription.pk]))
        self.assertTrue(Prescription.objects.filter(pk=self.prescription.pk).exists())

    def test_le_rh_ne_peut_pas_supprimer(self):
        self.client.force_login(self.rh)

        reponse = self.client.post(reverse("backoffice:prescription_supprimer", args=[self.prescription.pk]))

        self.assertEqual(reponse.status_code, 403)
        self.assertTrue(Prescription.objects.filter(pk=self.prescription.pk).exists())


class PrescriptionDetailActionsTest(BaseBackoffice):
    """Le lien « Modifier » de la fiche ne doit pas dépendre du droit de
    supprimer (réservé au superuser) : le RH modifie, seule la suppression
    lui reste fermée."""

    def _url_modifier(self):
        return reverse("backoffice:prescription_modifier", args=[self.prescription.pk])

    def test_le_rh_voit_le_lien_modifier_sur_une_prescription_soumise(self):
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:prescription_detail", args=[self.prescription.pk]))

        self.assertContains(reponse, self._url_modifier())

    def test_le_lien_modifier_disparait_une_fois_la_prescription_decidee(self):
        self.prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=self.rh)
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:prescription_detail", args=[self.prescription.pk]))

        self.assertNotContains(reponse, self._url_modifier())

    def test_le_rh_garde_la_main_sur_le_changement_de_statut_meme_decidee(self):
        """Valider/rejeter/remettre en contrôle reste possible à tout moment
        pour corriger une décision — contrairement à l'édition des champs et
        à la suppression."""
        self.prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=self.rh)
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:prescription_detail", args=[self.prescription.pk]))

        self.assertContains(reponse, reverse("backoffice:prescription_statut", args=[self.prescription.pk]))

    def test_le_bandeau_d_alerte_disparait_une_fois_la_prescription_tranchee(self):
        """Le motif est écrit une fois, à la détection, et ne se recalcule
        jamais : une fois la décision prise (ou la pièce en cause
        supprimée), le bandeau ne doit pas continuer à citer une alerte
        devenue obsolète — la raison reste consultable dans l'historique."""
        self.prescription.motif_signalement = "Doublon potentiel détecté avec ORD-AUTRE."
        self.prescription.statut = StatutPrescription.EN_CONTROLE
        self.prescription.save(update_fields=["motif_signalement", "statut"])
        self.client.force_login(self.rh)

        avant = self.client.get(reverse("backoffice:prescription_detail", args=[self.prescription.pk]))
        self.assertContains(avant, "Doublon potentiel")

        self.prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=self.rh)
        apres = self.client.get(reverse("backoffice:prescription_detail", args=[self.prescription.pk]))
        self.assertNotContains(apres, "Doublon potentiel")


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
        # Vient d'atteindre l'âge limite cette année civile : encore couvert
        # jusqu'au 31 décembre (convention de la mutuelle), donc absent du
        # filtre « limite d'âge dépassée ».
        self.enfant_limite_cette_annee = AyantDroit.objects.create(
            agent=self.agent,
            nom="LimiteCetteAnnee",
            prenom="Enfant",
            date_naissance=aujourdhui.replace(year=aujourdhui.year - 18),
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
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
        self.assertNotContains(reponse, "Enfant LimiteCetteAnnee")

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


class FactureSupprimerTest(BaseBackoffice):
    """Suppression réservée au superuser (voir AccesSuperuser) : RH garde la
    création/modification des factures, pas l'effacement d'une pièce déjà
    soumise."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.superuser)
        self.facture = Facture.objects.create(
            prestataire=self.prestataire, numero="F-1", mois=1, annee=2026, montant_total_declare=1000
        )

    def test_une_facture_non_validee_se_supprime(self):
        reponse = self.client.post(reverse("backoffice:facture_supprimer", args=[self.facture.pk]))

        self.assertRedirects(reponse, reverse("backoffice:factures"))
        self.assertFalse(Facture.objects.filter(pk=self.facture.pk).exists())

    def test_une_facture_validee_ne_se_supprime_pas(self):
        self.facture.statut = StatutFacture.VALIDEE
        self.facture.save()

        reponse = self.client.post(reverse("backoffice:facture_supprimer", args=[self.facture.pk]))

        self.assertRedirects(reponse, reverse("backoffice:facture_detail", args=[self.facture.pk]))
        self.assertTrue(Facture.objects.filter(pk=self.facture.pk).exists())

    def test_la_direction_ne_peut_pas_supprimer(self):
        self.client.force_login(self.direction)

        reponse = self.client.post(reverse("backoffice:facture_supprimer", args=[self.facture.pk]))

        self.assertEqual(reponse.status_code, 403)
        self.assertTrue(Facture.objects.filter(pk=self.facture.pk).exists())

    def test_le_rh_ne_peut_pas_supprimer(self):
        self.client.force_login(self.rh)

        reponse = self.client.post(reverse("backoffice:facture_supprimer", args=[self.facture.pk]))

        self.assertEqual(reponse.status_code, 403)
        self.assertTrue(Facture.objects.filter(pk=self.facture.pk).exists())


class FactureListeFiltresTest(BaseBackoffice):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rh)

    def test_les_factures_se_filtrent_par_statut(self):
        Facture.objects.create(
            prestataire=self.prestataire, numero="F-1", mois=1, annee=2026, montant_total_declare=1000,
            statut=StatutFacture.VALIDEE,
        )
        Facture.objects.create(prestataire=self.prestataire, numero="F-2", mois=1, annee=2026, montant_total_declare=2000)

        reponse = self.client.get(reverse("backoffice:factures"), {"statut": StatutFacture.VALIDEE})

        self.assertContains(reponse, "F-1")
        self.assertNotContains(reponse, "F-2")

    def test_les_factures_se_filtrent_par_prestataire(self):
        autre_prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Autre Pharmacie", taux_prise_en_charge=80
        )
        Facture.objects.create(prestataire=self.prestataire, numero="F-1", mois=1, annee=2026, montant_total_declare=1000)
        Facture.objects.create(prestataire=autre_prestataire, numero="F-2", mois=1, annee=2026, montant_total_declare=2000)

        reponse = self.client.get(reverse("backoffice:factures"), {"prestataire": self.prestataire.pk})

        self.assertContains(reponse, "F-1")
        self.assertNotContains(reponse, "F-2")

    def test_les_factures_se_filtrent_par_mois_et_annee(self):
        Facture.objects.create(prestataire=self.prestataire, numero="F-1", mois=1, annee=2026, montant_total_declare=1000)
        Facture.objects.create(prestataire=self.prestataire, numero="F-2", mois=2, annee=2026, montant_total_declare=2000)

        reponse = self.client.get(reverse("backoffice:factures"), {"mois": "1", "annee": "2026"})

        self.assertContains(reponse, "F-1")
        self.assertNotContains(reponse, "F-2")


class UtilisateurTest(BaseBackoffice):
    def test_creer_un_compte_enregistre_un_mot_de_passe_utilisable(self):
        self.client.force_login(self.superuser)

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
        self.client.force_login(self.superuser)

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
        self.client.force_login(self.superuser)

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

    def test_un_rh_ne_peut_pas_creer_de_compte(self):
        """La gestion des comptes — en particulier promouvoir quelqu'un en RH
        ou DIRECTION — est réservée au superuser : un RH seul ne doit pas
        pouvoir s'auto-attribuer des collègues."""
        self.client.force_login(self.rh)

        reponse = self.client.post(
            reverse("backoffice:utilisateur_creer"),
            {
                "matricule": "A0012",
                "nom": "Test",
                "prenom": "Promu",
                "role": Role.RH,
                "is_active": "on",
                "mot_de_passe": "MotDePasse2026!",
                "confirmation": "MotDePasse2026!",
            },
        )

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Utilisateur.objects.filter(matricule="A0012").exists())

    def test_un_rh_ne_peut_pas_modifier_un_compte_ni_son_mot_de_passe(self):
        self.client.force_login(self.rh)

        reponse_modifier = self.client.get(reverse("backoffice:utilisateur_modifier", args=[self.direction.pk]))
        reponse_mot_de_passe = self.client.post(
            reverse("backoffice:utilisateur_mot_de_passe", args=[self.direction.pk]),
            {"mot_de_passe": "Nouveau2026!", "confirmation": "Nouveau2026!"},
        )

        self.assertEqual(reponse_modifier.status_code, 403)
        self.assertEqual(reponse_mot_de_passe.status_code, 403)

    def test_un_rh_voit_la_liste_sans_les_actions_de_gestion(self):
        """RH garde la consultation (lecture) de l'annuaire des comptes, mais
        pas de lien « Ouvrir » qui mènerait à un formulaire de modification
        réservé au superuser (sinon : clic, puis 403)."""
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:utilisateurs"))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, self.rh.matricule)
        self.assertNotContains(reponse, "Nouveau compte")
        self.assertNotContains(reponse, "Ouvrir")


class ParametrageTest(BaseBackoffice):
    """Ces réglages s'appliquent à toute la mutuelle : RH consulte, seul le
    superuser modifie (voir AccesSuperuser et ParametrageModifier)."""

    def test_le_formulaire_met_a_jour_la_ligne_unique(self):
        self.client.force_login(self.superuser)

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
        self.client.force_login(self.superuser)

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

    def test_le_rh_consulte_mais_ne_peut_pas_modifier(self):
        self.client.force_login(self.rh)
        quota_avant = Parametrage.charger().quota_mensuel_defaut

        reponse_lecture = self.client.get(reverse("backoffice:parametrage"))
        reponse_ecriture = self.client.post(
            reverse("backoffice:parametrage"),
            {
                "cotisation_base": "5000",
                "conjoints_inclus": "1",
                "enfants_inclus": "3",
                "cout_conjoint_supplementaire": "2000",
                "cout_enfant_supplementaire": "2000",
                "age_limite_enfant": "18",
                "duree_cycle_mois": "1",
                "quota_mensuel_defaut": "999999",
                "fenetre_analyse_jours": "90",
                "seuil_volume_ecart_type": "0.50",
                "seuil_alerte_quota": "25",
            },
        )

        self.assertEqual(reponse_lecture.status_code, 200)
        self.assertEqual(reponse_ecriture.status_code, 403)
        self.assertEqual(Parametrage.charger().quota_mensuel_defaut, quota_avant)


class BaremeAccesTest(BaseBackoffice):
    """Le barème s'applique à toute la mutuelle : RH consulte, seul le
    superuser crée/modifie/supprime une tranche (voir AccesSuperuser)."""

    def setUp(self):
        super().setUp()
        self.tranche = TrancheQuota.objects.create(libelle="Sans famille", montant=10000)

    def _donnees(self, **extra):
        donnees = {"ordre": "10", "libelle": "Nouvelle tranche", "partenaire": "INDIFFERENT", "enfants_min": "0", "montant": "20000"}
        donnees.update(extra)
        return donnees

    def test_le_rh_consulte_la_liste_sans_les_actions_de_gestion(self):
        """Pas de lien « Ouvrir » non plus : il mènerait au formulaire de
        modification, réservé au superuser (sinon clic → 403)."""
        self.client.force_login(self.rh)

        reponse = self.client.get(reverse("backoffice:bareme"))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Sans famille")
        self.assertNotContains(reponse, "Nouvelle tranche")
        self.assertNotContains(reponse, "Ouvrir")

    def test_le_rh_ne_peut_ni_creer_ni_modifier_ni_supprimer(self):
        self.client.force_login(self.rh)

        reponse_creer = self.client.post(reverse("backoffice:bareme_creer"), self._donnees())
        reponse_modifier = self.client.post(
            reverse("backoffice:bareme_modifier", args=[self.tranche.pk]), self._donnees()
        )
        reponse_supprimer = self.client.post(reverse("backoffice:bareme_supprimer", args=[self.tranche.pk]))

        self.assertEqual(reponse_creer.status_code, 403)
        self.assertEqual(reponse_modifier.status_code, 403)
        self.assertEqual(reponse_supprimer.status_code, 403)
        self.assertFalse(TrancheQuota.objects.filter(libelle="Nouvelle tranche").exists())
        self.assertTrue(TrancheQuota.objects.filter(pk=self.tranche.pk).exists())

    def test_le_superuser_peut_creer_modifier_et_supprimer(self):
        self.client.force_login(self.superuser)

        self.client.post(reverse("backoffice:bareme_creer"), self._donnees())
        self.assertTrue(TrancheQuota.objects.filter(libelle="Nouvelle tranche").exists())

        self.client.post(reverse("backoffice:bareme_modifier", args=[self.tranche.pk]), self._donnees(libelle="Renommée"))
        self.tranche.refresh_from_db()
        self.assertEqual(self.tranche.libelle, "Renommée")

        self.client.post(reverse("backoffice:bareme_supprimer", args=[self.tranche.pk]))
        self.assertFalse(TrancheQuota.objects.filter(pk=self.tranche.pk).exists())


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
        """Import réservé au superuser (voir AccesSuperuser) : une ligne peut
        y porter un rôle RH/DIRECTION, même gate que la création manuelle."""
        self.client.force_login(self.superuser)
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

    def test_import_utilisateurs_accepte_un_fichier_excel_en_windows_1252(self):
        """Excel en français, sur Windows, enregistre parfois le CSV en
        Windows-1252 plutôt qu'en UTF-8 : un « é » y casserait sinon la
        lecture avec une erreur 500 illisible."""
        self.client.force_login(self.superuser)
        contenu = "Matricule;Nom;Prénom\n157;RAMADANE;SAID MLIMI\n"
        reponse = self.client.post(
            reverse("backoffice:utilisateur_import"), {"fichier": fichier_csv(contenu, encodage="cp1252")}
        )

        self.assertEqual(reponse.status_code, 200)
        self.client.post(reverse("backoffice:utilisateur_import"), {"confirmer": "1"})

        self.assertTrue(Utilisateur.objects.filter(matricule="157").exists())

    def test_import_utilisateurs_signale_un_encodage_illisible_sans_lever_d_erreur(self):
        self.client.force_login(self.superuser)
        # 0x81 n'est un octet valide ni en UTF-8 ni en Windows-1252.
        reponse = self.client.post(
            reverse("backoffice:utilisateur_import"),
            {"fichier": SimpleUploadedFile("fichier.csv", b"Matricule\x81;Nom\n158;X\n", content_type="text/csv")},
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "encodage non reconnu")

    def test_un_rh_ne_peut_pas_importer_des_utilisateurs(self):
        reponse = self.client.post(
            reverse("backoffice:utilisateur_import"),
            {"fichier": fichier_csv("Matricule;Nom;Prénom\n159;X;Y\n")},
        )

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Utilisateur.objects.filter(matricule="159").exists())

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

    def _donnees_facture(self, numero, contenu, encodage="utf-8"):
        return {
            "prestataire": self.prestataire.pk,
            "numero": numero,
            "mois": str(self.prescription.date_emission.month),
            "annee": str(self.prescription.date_emission.year),
            "montant_total_declare": "8000",
            "montant_colonne": "total",
            "fichier_csv": fichier_csv(contenu, encodage=encodage),
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

    def test_import_facture_accepte_un_fichier_excel_en_windows_1252(self):
        jour = self.prescription.date_emission.isoformat()
        contenu = f"date;matricule;beneficiaire;nature;montant\n{jour};A0001;Fatima Zahra;Consultation;10000\n"
        reponse = self.client.post(
            reverse("backoffice:facture_import"), self._donnees_facture("F-1", contenu, encodage="cp1252")
        )

        self.assertNotContains(reponse, "encodage non reconnu")
        self.client.post(reverse("backoffice:facture_import"), {"confirmer": "1"})

        self.assertTrue(Facture.objects.filter(numero="F-1").exists())
