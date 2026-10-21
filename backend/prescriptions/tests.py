import tempfile
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, StatutVerification, TypeJustificatif
from parametrage.models import NatureSoin
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, TypePrestataire


def fichier_csv(contenu):
    chemin = Path(tempfile.mkdtemp()) / "historique.csv"
    chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


class BasePrescriptions(TestCase):
    def setUp(self):
        compte = Utilisateur.objects.create_user("A0001", "x", nom="Zahra", prenom="Fatima", role=Role.AGENT)
        self.agent = Agent.objects.create(
            utilisateur=compte,
            site="Moroni",
            date_naissance=date(1990, 1, 1),
            date_embauche=date(2018, 6, 1),
        )
        self.prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Pharmacie Centrale", taux_prise_en_charge=80
        )

    def importer(self, contenu, **options):
        sortie = StringIO()
        call_command("importer_prescriptions", fichier_csv(contenu), stdout=sortie, **options)
        return sortie.getvalue()


class ImportHistoriqueTest(BasePrescriptions):
    def entete(self):
        return "agent,prestataire,numero_ordonnance,montant_total,date_emission,statut,montant_rembourse\n"

    def test_le_statut_et_le_montant_du_fichier_font_foi(self):
        self.importer(self.entete() + "A0001,PHA-0001,ORD-1,12000,01/03/2026,Validée,9600\n")

        prescription = Prescription.objects.get(numero_ordonnance="ORD-1")
        self.assertEqual(prescription.statut, StatutPrescription.VALIDEE)
        self.assertEqual(prescription.montant_rembourse, 9600)

    def test_la_detection_ne_reecrit_pas_un_historique_arbitre(self):
        """Deux lignes identiques à 2 jours d'écart : la règle basculerait
        normalement en contrôle, mais l'arbitrage passé fait foi."""
        self.importer(
            self.entete()
            + "A0001,PHA-0001,ORD-1,12000,01/03/2026,Validée,9600\n"
            + "A0001,PHA-0001,ORD-1,12000,03/03/2026,Validée,9600\n"
        )

        statuts = set(Prescription.objects.values_list("statut", flat=True))
        self.assertEqual(statuts, {StatutPrescription.VALIDEE})
        self.assertEqual(Prescription.objects.exclude(motif_signalement="").count(), 0)

    def test_la_reprise_est_tracee_dans_l_historique(self):
        self.importer(self.entete() + "A0001,PHA-0001,ORD-1,12000,01/03/2026,Validée,9600\n")

        trace = Prescription.objects.get(numero_ordonnance="ORD-1").historique.first()
        self.assertIn("import", trace.commentaire.lower())

    def test_le_prestataire_se_retrouve_par_son_nom(self):
        self.importer(self.entete() + "A0001,Pharmacie Centrale,ORD-1,12000,01/03/2026,Validée,9600\n")

        self.assertEqual(Prescription.objects.get(numero_ordonnance="ORD-1").prestataire, self.prestataire)

    def test_le_remboursement_est_calcule_si_absent_du_fichier(self):
        self.importer(
            "agent,prestataire,numero_ordonnance,montant_total,date_emission\n"
            "A0001,PHA-0001,ORD-1,10000,01/03/2026\n"
        )

        self.assertEqual(Prescription.objects.get(numero_ordonnance="ORD-1").montant_rembourse, 8000)

    def test_les_montants_decimaux_sont_arrondis_au_franc(self):
        self.importer(self.entete() + "A0001,PHA-0001,ORD-1,\"12 000,60\",01/03/2026,Validée,9600\n")

        self.assertEqual(Prescription.objects.get(numero_ordonnance="ORD-1").montant_total, 12001)

    def test_un_agent_inconnu_bloque_tout_l_import(self):
        contenu = (
            self.entete()
            + "A0001,PHA-0001,ORD-1,12000,01/03/2026,Validée,9600\n"
            + "A9999,PHA-0001,ORD-2,12000,01/03/2026,Validée,9600\n"
        )

        with self.assertRaises(CommandError):
            self.importer(contenu)

        self.assertEqual(Prescription.objects.count(), 0)

    def test_dry_run_n_ecrit_rien(self):
        sortie = self.importer(
            self.entete() + "A0001,PHA-0001,ORD-1,12000,01/03/2026,Validée,9600\n", dry_run=True
        )

        self.assertEqual(Prescription.objects.count(), 0)
        self.assertIn("SIMULATION", sortie)

    def test_une_date_illisible_est_signalee(self):
        sortie = self.importer(
            self.entete() + "A0001,PHA-0001,ORD-1,12000,le 3 mars,Validée,9600\n", dry_run=True
        )

        self.assertIn("date", sortie)
        self.assertIn("ligne 2", sortie)


class CorrigerAnneesPrescriptionsTest(BasePrescriptions):
    """Commande de rattrapage pour les prescriptions déjà enregistrées avec
    une année sur 2 chiffres avant l'ajout de la validation (voir
    Prescription.clean) — la corruption est reproduite ici via update()
    direct, puisque clean() en bloquerait désormais la création normale."""

    def setUp(self):
        super().setUp()
        corrompue = Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-26",
            montant_total=10000,
            date_emission=date(2026, 10, 5),
            justificatif="x.jpg",
        )
        Prescription.objects.filter(pk=corrompue.pk).update(date_emission=date(26, 10, 5))
        self.corrompue_pk = corrompue.pk

        self.normale = Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-OK",
            montant_total=5000,
            date_emission=date(2026, 9, 1),
            justificatif="x.jpg",
        )

    def test_sans_option_n_ecrit_rien(self):
        sortie = StringIO()
        call_command("corriger_annees_prescriptions", stdout=sortie)

        corrompue = Prescription.objects.get(pk=self.corrompue_pk)
        self.assertEqual(corrompue.date_emission.year, 26)
        self.assertIn("ORD-26", sortie.getvalue())
        self.assertIn("Aperçu seul", sortie.getvalue())

    def test_avec_appliquer_corrige_l_annee(self):
        call_command("corriger_annees_prescriptions", "--appliquer", stdout=StringIO())

        corrompue = Prescription.objects.get(pk=self.corrompue_pk)
        self.assertEqual(corrompue.date_emission, date(2026, 10, 5))

    def test_la_prescription_normale_n_est_pas_touchee(self):
        call_command("corriger_annees_prescriptions", "--appliquer", stdout=StringIO())

        self.normale.refresh_from_db()
        self.assertEqual(self.normale.date_emission, date(2026, 9, 1))

    def test_rien_a_corriger_si_aucune_annee_suspecte(self):
        Prescription.objects.filter(pk=self.corrompue_pk).update(date_emission=date(2026, 10, 5))

        sortie = StringIO()
        call_command("corriger_annees_prescriptions", "--appliquer", stdout=sortie)

        self.assertIn("Aucune date suspecte", sortie.getvalue())


class RejeuDesReglesTest(BasePrescriptions):
    def test_le_mode_rejouer_n_ecrit_jamais(self):
        self.importer(
            "agent,prestataire,numero_ordonnance,montant_total,date_emission,statut\n"
            "A0001,PHA-0001,ORD-1,12000,01/03/2026,Validée\n",
            mode="rejouer",
        )

        self.assertEqual(Prescription.objects.count(), 0)

    def test_il_signale_les_fraudes_que_les_regles_laissent_passer(self):
        """Une ligne rejetée que rien ne rapproche d'une autre : la règle
        actuelle ne l'aurait pas détectée."""
        sortie = self.importer(
            "agent,prestataire,numero_ordonnance,montant_total,date_emission,statut\n"
            "A0001,PHA-0001,ORD-9,250000,10/03/2026,Rejetée\n",
            mode="rejouer",
        )

        self.assertIn("Fraudes NON détectées", sortie)
        self.assertIn("ORD-9", sortie)

    def test_il_signale_les_alertes_injustifiees(self):
        """Même montant à 2 jours d'écart, mais validé : la règle produirait
        une alerte inutile."""
        sortie = self.importer(
            "agent,prestataire,numero_ordonnance,montant_total,date_emission,statut\n"
            "A0001,PHA-0001,ORD-1,8000,05/03/2026,Validée\n"
            "A0001,PHA-0001,ORD-2,8000,07/03/2026,Validée\n",
            mode="rejouer",
        )

        self.assertIn("ALERTES QUI SERAIENT INJUSTIFIÉES", sortie)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SaisieManuelleTest(BasePrescriptions):
    """Ordonnance papier saisie par le service mutuelle depuis le back-office.

    Le scan est facultatif en phase de démarrage : les vérifications se font
    alors manuellement, sur pièce papier, en attendant l'usage officiel de
    l'application mobile."""

    def setUp(self):
        super().setUp()
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.client.force_login(self.rh)

    def donnees(self, **surcharges):
        valeurs = {
            "agent": self.agent.pk,
            "ayant_droit": "",
            "prestataire": self.prestataire.pk,
            "nature": NatureSoin.objects.get(libelle="Consultation").pk,
            "montant_total": "10000",
            "date_emission": date.today().isoformat(),
            "justificatif": SimpleUploadedFile("scan.jpg", b"contenu", content_type="image/jpeg"),
        }
        valeurs.update(surcharges)
        return valeurs

    def test_le_justificatif_est_facultatif(self):
        donnees = self.donnees()
        del donnees["justificatif"]

        self.client.post("/backoffice/prescriptions/nouvelle/", donnees)

        prescription = Prescription.objects.get()
        self.assertFalse(prescription.justificatif)

    def test_le_numero_d_ordonnance_est_genere_automatiquement(self):
        """Le champ n'est plus saisi : il n'a donc plus à être fiable ou
        cohérent d'un prestataire à l'autre, contrairement au numéro inscrit
        sur le papier qu'il remplace."""
        self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees())

        prescription = Prescription.objects.get()
        annee = date.today().year
        self.assertEqual(prescription.numero_ordonnance, f"ORD-{annee}-000001")

    def test_la_saisie_enregistre_l_auteur_et_calcule_le_remboursement(self):
        self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees())

        prescription = Prescription.objects.get()
        self.assertEqual(prescription.soumis_par, self.rh)
        self.assertEqual(prescription.montant_rembourse, 8000)
        self.assertEqual(prescription.statut, StatutPrescription.SOUMISE)

    def test_la_detection_s_applique_comme_pour_une_soumission_mobile(self):
        Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-PAPIER-1",
            montant_total=10000,
            date_emission=date.today() - timedelta(days=1),
            justificatif="x.jpg",
        )

        self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees())

        saisie = Prescription.objects.latest("date_creation")
        self.assertEqual(saisie.statut, StatutPrescription.EN_CONTROLE)
        self.assertIn("Doublon", saisie.motif_signalement)
        # Le bandeau d'alerte de la fiche ne montre ce motif que tant que la
        # prescription reste « En contrôle » (voir PrescriptionDetail) : la
        # raison du signalement doit donc aussi vivre dans l'historique, pour
        # rester consultable une fois la décision prise et le bandeau disparu.
        self.assertIn("Doublon", saisie.historique.first().commentaire)


class DateEmissionTest(BasePrescriptions):
    """Le champ date d'émission est un <input type="date"> du navigateur :
    si l'année n'est pas complétée sur 4 chiffres avant l'envoi, rien ne
    bloquait jusqu'ici une date aussi improbable (26 au lieu de 2026) — la
    prescription restait alors invisible de tous les rapports filtrés par
    période, tout en paraissant normale dans la liste brute."""

    def setUp(self):
        super().setUp()
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.client.force_login(self.rh)

    def donnees(self, **surcharges):
        valeurs = {
            "agent": self.agent.pk,
            "ayant_droit": "",
            "prestataire": self.prestataire.pk,
            "nature": NatureSoin.objects.get(libelle="Consultation").pk,
            "montant_total": "10000",
            "date_emission": "0026-10-05",
            "justificatif": SimpleUploadedFile("scan.jpg", b"contenu", content_type="image/jpeg"),
        }
        valeurs.update(surcharges)
        return valeurs

    def test_une_annee_sur_deux_chiffres_est_refusee_a_la_saisie(self):
        reponse = self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees())

        self.assertEqual(reponse.status_code, 200)  # réaffiche le formulaire, pas de redirection
        self.assertContains(reponse, "Année improbable")
        self.assertEqual(Prescription.objects.count(), 0)

    def test_une_annee_normale_est_acceptee(self):
        self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees(date_emission="2026-10-05"))

        self.assertEqual(Prescription.objects.count(), 1)

    def test_clean_rejette_directement_une_annee_sur_deux_chiffres(self):
        prescription = Prescription(
            agent=self.agent,
            prestataire=self.prestataire,
            montant_total=10000,
            date_emission=date(26, 10, 5),
        )

        with self.assertRaises(ValidationError) as erreur:
            prescription.full_clean()
        self.assertIn("date_emission", erreur.exception.message_dict)


class DoublonBeneficiaireTest(BasePrescriptions):
    """Le contrôle de doublon doit distinguer les bénéficiaires : un agent
    qui soumet, le même jour chez le même prestataire, deux ordonnances de
    montant identique — une pour lui, une pour son enfant — ne doit pas être
    signalé comme doublon."""

    def setUp(self):
        super().setUp()
        self.enfant = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Enfant",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
        )

    def test_memes_agent_prestataire_montant_mais_beneficiaires_differents_n_est_pas_un_doublon(self):
        Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-1",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )
        pour_enfant = Prescription(
            agent=self.agent,
            ayant_droit=self.enfant,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-2",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        self.assertEqual(pour_enfant.detecter_doublons().count(), 0)

    def test_meme_beneficiaire_reste_detecte_comme_doublon(self):
        Prescription.objects.create(
            agent=self.agent,
            ayant_droit=self.enfant,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-1",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )
        autre_pour_enfant = Prescription(
            agent=self.agent,
            ayant_droit=self.enfant,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-2",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        self.assertEqual(autre_pour_enfant.detecter_doublons().count(), 1)

    def test_la_saisie_pour_un_ayant_droit_apres_celle_de_l_agent_n_est_pas_mise_en_controle(self):
        """Bout en bout, via le formulaire RH — pas seulement au niveau du
        modèle : les deux prescriptions doivent rester « Soumise »."""
        rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.client.force_login(rh)

        def donnees(ayant_droit):
            return {
                "agent": self.agent.pk,
                "ayant_droit": ayant_droit,
                "prestataire": self.prestataire.pk,
                "nature": NatureSoin.objects.get(libelle="Consultation").pk,
                "montant_total": "10000",
                "date_emission": date.today().isoformat(),
                "justificatif": SimpleUploadedFile("scan.jpg", b"contenu", content_type="image/jpeg"),
            }

        self.client.post("/backoffice/prescriptions/nouvelle/", donnees(""))
        self.client.post("/backoffice/prescriptions/nouvelle/", donnees(self.enfant.pk))

        self.assertEqual(
            list(Prescription.objects.values_list("statut", flat=True).order_by("date_creation")),
            [StatutPrescription.SOUMISE, StatutPrescription.SOUMISE],
        )


class AyantDroitHorsCouvertureTest(BasePrescriptions):
    """Un enfant qui a dépassé l'âge limite de couverture ne coûte plus rien
    à la mutuelle : une prescription qui lui est quand même soumise doit être
    bloquée (remboursement nul) et signalée, pas remboursée sans bruit."""

    def _ayant_droit(self, annees):
        return AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Enfant",
            date_naissance=date.today().replace(year=date.today().year - annees),
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            statut_verification=StatutVerification.VALIDE,
        )

    def test_une_prescription_pour_un_enfant_trop_age_n_est_pas_remboursee(self):
        ayant_droit = self._ayant_droit(20)

        prescription = Prescription.objects.create(
            agent=self.agent,
            ayant_droit=ayant_droit,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-1",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        self.assertEqual(prescription.montant_rembourse, 0)
        self.assertEqual(prescription.statut, StatutPrescription.EN_CONTROLE)
        self.assertIn("âge limite", prescription.motif_signalement)

    def test_une_prescription_pour_un_enfant_dans_la_limite_reste_normale(self):
        ayant_droit = self._ayant_droit(10)

        prescription = Prescription.objects.create(
            agent=self.agent,
            ayant_droit=ayant_droit,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-2",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        self.assertEqual(prescription.montant_rembourse, 8000)
        self.assertEqual(prescription.statut, StatutPrescription.SOUMISE)

    def test_reassigner_une_prescription_a_un_enfant_trop_age_annule_le_remboursement(self):
        """Le blocage s'applique aussi à une correction après coup (voir
        PrescriptionModifier), pas seulement à la saisie initiale."""
        ayant_droit = self._ayant_droit(20)
        prescription = Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-3",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )
        self.assertEqual(prescription.montant_rembourse, 8000)

        prescription.ayant_droit = ayant_droit
        prescription.save()

        self.assertEqual(prescription.montant_rembourse, 0)

    def test_un_enfant_qui_vient_d_atteindre_l_age_limite_reste_couvert_jusqu_a_fin_d_annee(self):
        """Convention de la mutuelle : la couverture continue jusqu'au 31
        décembre de l'année où l'enfant atteint l'âge limite, pas dès son
        anniversaire — même le jour même de ses 18 ans, il reste remboursé."""
        ayant_droit = self._ayant_droit(18)

        prescription = Prescription.objects.create(
            agent=self.agent,
            ayant_droit=ayant_droit,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-4",
            montant_total=10000,
            date_emission=date.today(),
            justificatif="x.jpg",
        )

        self.assertEqual(prescription.montant_rembourse, 8000)
        self.assertEqual(prescription.statut, StatutPrescription.SOUMISE)


class SuspensionSortieFinCouvertureTest(BasePrescriptions):
    """Fraude (suspension temporaire), départ de la mutuelle, divorce : dans
    les trois cas le dossier est conservé, mais les soins datés dans la
    période non couverte sont mis en contrôle sans remboursement."""

    def setUp(self):
        super().setUp()
        self.conjoint = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Ali",
            lien_parente=LienParente.CONJOINT,
            type_justificatif=TypeJustificatif.ACTE_MARIAGE,
            statut_verification=StatutVerification.VALIDE,
        )

    def soumettre(self, jour, ayant_droit=None, montant=10000):
        return Prescription.objects.create(
            agent=self.agent,
            ayant_droit=ayant_droit,
            prestataire=self.prestataire,
            montant_total=montant,
            date_emission=jour,
        )

    def test_un_agent_suspendu_n_est_pas_rembourse_ni_ses_ayants_droit(self):
        self.agent.suspendu_du = date(2026, 3, 1)
        self.agent.suspendu_jusqu_au = date(2026, 5, 31)
        self.agent.motif_suspension = "Fraude"
        self.agent.save()

        pour_lui = self.soumettre(date(2026, 4, 10))
        pour_conjoint = self.soumettre(date(2026, 4, 10), ayant_droit=self.conjoint, montant=7000)

        for prescription in (pour_lui, pour_conjoint):
            self.assertEqual(prescription.montant_rembourse, 0)
            self.assertEqual(prescription.statut, StatutPrescription.EN_CONTROLE)
            self.assertIn("Agent suspendu", prescription.motif_signalement)

    def test_la_suspension_ne_couvre_que_sa_periode(self):
        self.agent.suspendu_du = date(2026, 3, 1)
        self.agent.suspendu_jusqu_au = date(2026, 5, 31)
        self.agent.motif_suspension = "Fraude"
        self.agent.save()

        avant = self.soumettre(date(2026, 2, 27))
        apres = self.soumettre(date(2026, 6, 1), montant=9000)

        self.assertEqual(avant.montant_rembourse, 8000)
        self.assertEqual(apres.montant_rembourse, 7200)
        self.assertEqual(apres.statut, StatutPrescription.SOUMISE)

    def test_une_suspension_sans_echeance_court_jusqu_a_sa_levee(self):
        self.agent.suspendu_du = date(2026, 3, 1)
        self.agent.motif_suspension = "Fraude"
        self.agent.save()

        self.assertEqual(self.soumettre(date(2030, 1, 1)).montant_rembourse, 0)

    def test_un_agent_sorti_n_est_plus_rembourse_apres_sa_sortie(self):
        self.agent.actif = False
        self.agent.date_sortie = date(2026, 6, 30)
        self.agent.save()

        avant = self.soumettre(date(2026, 6, 15))
        apres = self.soumettre(date(2026, 7, 2), ayant_droit=self.conjoint, montant=9000)

        self.assertEqual(avant.montant_rembourse, 8000)
        self.assertEqual(apres.montant_rembourse, 0)
        self.assertIn("quitté la mutuelle", apres.motif_signalement)

    def test_un_partenaire_divorce_n_est_plus_couvert(self):
        self.conjoint.date_fin_couverture = date(2026, 6, 30)
        self.conjoint.motif_fin_couverture = "DIVORCE"
        self.conjoint.save()

        avant = self.soumettre(date(2026, 6, 15), ayant_droit=self.conjoint)
        apres = self.soumettre(date(2026, 7, 2), ayant_droit=self.conjoint, montant=9000)
        agent = self.soumettre(date(2026, 7, 2), montant=5000)

        self.assertEqual(avant.montant_rembourse, 8000)
        self.assertEqual(apres.montant_rembourse, 0)
        self.assertIn("divorce", apres.motif_signalement)
        self.assertEqual(agent.montant_rembourse, 4000)

    def test_un_partenaire_divorce_ne_compte_plus_dans_la_composition_familiale(self):
        self.assertEqual(self.agent.nombre_conjoints, 1)

        self.conjoint.date_fin_couverture = date.today() - timedelta(days=1)
        self.conjoint.motif_fin_couverture = "DIVORCE"
        self.conjoint.save()

        self.assertEqual(Agent.objects.get(pk=self.agent.pk).nombre_conjoints, 0)

    def test_les_saisies_incoherentes_sont_refusees(self):
        self.agent.actif = False
        self.agent.suspendu_jusqu_au = date(2026, 1, 1)
        with self.assertRaises(ValidationError) as erreur:
            self.agent.full_clean()
        self.assertIn("date_sortie", erreur.exception.message_dict)
        self.assertIn("suspendu_du", erreur.exception.message_dict)

        self.conjoint.date_fin_couverture = date(2026, 6, 30)
        with self.assertRaises(ValidationError) as erreur:
            self.conjoint.full_clean()
        self.assertIn("motif_fin_couverture", erreur.exception.message_dict)


class BlocageAgentSuspenduTest(BasePrescriptions):
    """Un agent suspendu est arrêté dès la soumission, avec un message clair,
    plutôt que de voir sa prescription passer en contrôle après coup."""

    def setUp(self):
        super().setUp()
        self.agent.suspendu_du = date.today() - timedelta(days=10)
        self.agent.motif_suspension = "Fraude"
        self.agent.save()
        self.nature = NatureSoin.objects.get(libelle="Consultation")

    def donnees(self, **surcharges):
        valeurs = {
            "ayant_droit": "",
            "prestataire": self.prestataire.pk,
            "nature": self.nature.pk,
            "montant_total": "10000",
            "date_emission": date.today().isoformat(),
        }
        valeurs.update(surcharges)
        return valeurs

    def test_la_saisie_rh_est_refusee(self):
        rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
        self.client.force_login(rh)

        reponse = self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees(agent=self.agent.pk))

        self.assertContains(reponse, "Dossier suspendu du")
        self.assertEqual(Prescription.objects.count(), 0)

    def test_l_auto_saisie_de_l_agent_est_refusee(self):
        self.client.force_login(self.agent.utilisateur)

        reponse = self.client.post("/backoffice/mon-tableau-de-bord/prescription/", self.donnees())

        self.assertContains(reponse, "Dossier suspendu du")
        self.assertNotContains(reponse, "Fraude")
        self.assertEqual(Prescription.objects.count(), 0)

    def test_une_prescription_existante_reste_corrigeable(self):
        prescription = Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            montant_total=10000,
            date_emission=date.today(),
        )
        prescription.montant_total = 9000

        prescription.clean()  # ne lève pas : le blocage ne vise que la création
