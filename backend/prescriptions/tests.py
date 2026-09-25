import tempfile
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent
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
            "numero_ordonnance": "ORD-PAPIER-1",
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

        prescription = Prescription.objects.get(numero_ordonnance="ORD-PAPIER-1")
        self.assertFalse(prescription.justificatif)

    def test_la_saisie_enregistre_l_auteur_et_calcule_le_remboursement(self):
        self.client.post("/backoffice/prescriptions/nouvelle/", self.donnees())

        prescription = Prescription.objects.get(numero_ordonnance="ORD-PAPIER-1")
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

        saisie = Prescription.objects.filter(numero_ordonnance="ORD-PAPIER-1").latest("date_creation")
        self.assertEqual(saisie.statut, StatutPrescription.EN_CONTROLE)
        self.assertIn("Doublon", saisie.motif_signalement)
