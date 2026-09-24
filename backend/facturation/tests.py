import tempfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent
from facturation.models import Facture, LigneFacture, StatutFacture, StatutLigne
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, TypePrestataire


def fichier_csv(contenu):
    chemin = Path(tempfile.mkdtemp()) / "facture.csv"
    chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


class BaseFacturation(TestCase):
    def setUp(self):
        self.rh = Utilisateur.objects.create_user("RH1", "x", nom="Rh", prenom="Service", role=Role.RH)
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

    def declarer(self, jour, montant, numero="ORD-1"):
        return Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance=numero,
            montant_total=montant,
            date_emission=jour,
            justificatif="x.jpg",
        )

    def facture(self, total=20000, numero="F-1"):
        return Facture.objects.create(
            prestataire=self.prestataire,
            numero=numero,
            mois=3,
            annee=2026,
            montant_total_declare=total,
        )

    def ligne(self, facture, jour, montant, matricule="A0001", reclame=None):
        """`montant` est le coût total du soin ; la part réclamée vaut par
        défaut ce que le taux du prestataire autorise."""
        return LigneFacture.objects.create(
            facture=facture,
            date_soin=jour,
            matricule=matricule,
            nom_beneficiaire="Fatima Zahra",
            nature="Consultation",
            montant_soin=montant,
            montant_reclame=round(montant * 80 / 100) if reclame is None else reclame,
        )


class RapprochementTest(BaseFacturation):
    def test_une_ligne_identique_est_concordante(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)
        self.assertEqual(ligne.prescription, prescription)

    def test_un_montant_different_est_signale_sans_rompre_le_lien(self):
        self.declarer(date(2026, 3, 8), 9000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 8), 8000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.ECART_MONTANT)
        self.assertEqual(ligne.ecart_montant, -1000)

    def test_un_soin_facture_sans_prescription_est_signale(self):
        """Le prestataire facture un soin que personne n'a déclaré."""
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 12), 15000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.SANS_PRESCRIPTION)
        self.assertIsNone(ligne.prescription)

    def test_un_matricule_inconnu_est_signale(self):
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 12), 15000, matricule="A9999")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.AGENT_INCONNU)

    def test_une_prescription_absente_de_la_facture_remonte(self):
        """L'anomalie la plus grave : un soin déclaré que le prestataire ne
        réclame pas."""
        self.declarer(date(2026, 3, 25), 30000, numero="ORD-FANTOME")
        facture = self.facture()

        facture.rapprocher()

        non_facturees = facture.prescriptions_non_facturees()
        self.assertEqual([p.numero_ordonnance for p in non_facturees], ["ORD-FANTOME"])

    def test_une_prescription_ne_sert_qu_une_seule_ligne(self):
        """Deux lignes identiques ne peuvent pas se rapprocher de la même
        prescription : la seconde doit ressortir comme non déclarée."""
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        self.ligne(facture, date(2026, 3, 5), 12000)

        facture.rapprocher()

        statuts = sorted(facture.lignes.values_list("statut", flat=True))
        self.assertEqual(statuts, [StatutLigne.CONCORDANTE, StatutLigne.SANS_PRESCRIPTION])

    def test_les_soins_hors_periode_ne_sont_pas_rapproches(self):
        self.declarer(date(2026, 4, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.SANS_PRESCRIPTION)

    def test_un_prestataire_qui_reclame_plus_que_son_taux_est_signale(self):
        """Le coût du soin concorde, mais le prestataire réclame 100 % au lieu
        des 80 % de sa convention : les 20 % de l'agent sont facturés deux fois."""
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, reclame=12000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.ECART_TAUX)
        self.assertEqual(ligne.montant_reclame_attendu, 9600)
        self.assertEqual(ligne.ecart_taux, 2400)

    def test_une_ligne_au_bon_taux_reste_concordante(self):
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, reclame=9600)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)
        self.assertEqual(ligne.ecart_taux, 0)

    def test_une_ligne_au_mauvais_taux_n_est_pas_validee(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000, reclame=12000)
        facture.rapprocher()

        facture.valider(self.rh)

        prescription.refresh_from_db()
        self.assertEqual(prescription.statut, StatutPrescription.SOUMISE)

    def test_l_ecart_entre_total_annonce_et_somme_des_lignes(self):
        facture = self.facture(total=25000)
        self.ligne(facture, date(2026, 3, 5), 12000)
        self.ligne(facture, date(2026, 3, 8), 8000)

        # 80 % de 12000 et de 8000 : le prestataire réclame 16000 au total.
        self.assertEqual(facture.montant_total_lignes, 16000)
        self.assertEqual(facture.ecart_total, 9000)


class ValidationFactureTest(BaseFacturation):
    def test_valider_ne_confirme_que_les_lignes_concordantes(self):
        concordante = self.declarer(date(2026, 3, 5), 12000, numero="ORD-OK")
        en_ecart = self.declarer(date(2026, 3, 8), 9000, numero="ORD-ECART")
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        self.ligne(facture, date(2026, 3, 8), 8000)
        facture.rapprocher()

        validees = facture.valider(self.rh)

        concordante.refresh_from_db()
        en_ecart.refresh_from_db()
        self.assertEqual(validees, 1)
        self.assertEqual(concordante.statut, StatutPrescription.VALIDEE)
        self.assertEqual(en_ecart.statut, StatutPrescription.SOUMISE)

    def test_la_validation_est_tracee_avec_la_reference_de_facture(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        facture.rapprocher()

        facture.valider(self.rh)

        trace = prescription.historique.last()
        self.assertEqual(trace.utilisateur, self.rh)
        self.assertIn(facture.numero, trace.commentaire)

    def test_la_facture_conserve_qui_l_a_validee(self):
        facture = self.facture()
        facture.rapprocher()

        facture.valider(self.rh)

        self.assertEqual(facture.statut, StatutFacture.VALIDEE)
        self.assertEqual(facture.validee_par, self.rh)
        self.assertIsNotNone(facture.date_validation)

    def test_valider_avant_rapprochement_est_refuse_par_la_vue(self):
        facture = self.facture()
        self.client.force_login(self.rh)

        self.client.post(f"/backoffice/factures/{facture.pk}/valider/")

        facture.refresh_from_db()
        self.assertEqual(facture.statut, StatutFacture.RECUE)


class ImportFactureTest(BaseFacturation):
    def importer(self, contenu, **options):
        valeurs = {
            "prestataire": "PHA-0001",
            "numero": "F-2026-03",
            "mois": 3,
            "annee": 2026,
            "total": 20000,
        }
        valeurs.update(options)
        sortie = StringIO()
        call_command("importer_facture", fichier_csv(contenu), stdout=sortie, **valeurs)
        return sortie.getvalue()

    def entete(self):
        return "date;matricule;beneficiaire;nature;montant\n"

    def test_import_et_rapprochement_en_une_passe(self):
        """Le prestataire réclame 9600, soit 80 % d'un soin à 12000."""
        self.declarer(date(2026, 3, 5), 12000)

        self.importer(self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;9600\n")

        facture = Facture.objects.get(numero="F-2026-03")
        self.assertEqual(facture.statut, StatutFacture.RAPPROCHEE)
        self.assertEqual(facture.lignes.first().statut, StatutLigne.CONCORDANTE)

    def test_l_import_ne_valide_aucune_prescription(self):
        """La décision reste au service mutuelle, au vu des écarts."""
        prescription = self.declarer(date(2026, 3, 5), 12000)

        self.importer(self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;9600\n")

        prescription.refresh_from_db()
        self.assertEqual(prescription.statut, StatutPrescription.SOUMISE)

    def test_la_simulation_rend_compte_des_anomalies(self):
        """Le rapport est produit avant l'annulation de la transaction : sans
        cela une simulation n'afficherait que des zéros, et ne servirait à rien."""
        sortie = self.importer(
            self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;9600\n", dry_run=True
        )

        self.assertIn("Lignes lues      : 1", sortie)
        self.assertIn("Facturées sans prescription   :    1", sortie)

    def test_dry_run_n_ecrit_rien(self):
        sortie = self.importer(
            self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;9600\n", dry_run=True
        )

        self.assertEqual(Facture.objects.count(), 0)
        self.assertIn("SIMULATION", sortie)

    def test_une_ligne_invalide_annule_toute_la_facture(self):
        contenu = (
            self.entete()
            + "05/03/2026;A0001;Fatima Zahra;Consultation;12000\n"
            + "le 8 mars;A0001;Fatima Zahra;Consultation;8000\n"
        )

        with self.assertRaises(CommandError):
            self.importer(contenu)

        self.assertEqual(Facture.objects.count(), 0)
        self.assertEqual(LigneFacture.objects.count(), 0)

    def test_deux_fois_la_meme_facture_est_refuse(self):
        contenu = self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;12000\n"
        self.importer(contenu)

        with self.assertRaises(CommandError):
            self.importer(contenu)

        self.assertEqual(Facture.objects.count(), 1)

    def test_la_colonne_montant_peut_porter_le_cout_total(self):
        self.declarer(date(2026, 3, 5), 12000)

        self.importer(
            self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;12000\n", montant="total"
        )

        ligne = Facture.objects.get(numero="F-2026-03").lignes.first()
        self.assertEqual(ligne.montant_soin, 12000)
        self.assertEqual(ligne.montant_reclame, 9600)
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)

    def test_le_cout_total_se_deduit_de_la_part_reclamee(self):
        """Le fichier ne porte que les 80 % : le coût du soin s'en déduit."""
        self.importer(self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;9600\n")

        ligne = Facture.objects.get(numero="F-2026-03").lignes.first()
        self.assertEqual(ligne.montant_soin, 12000)
        self.assertEqual(ligne.montant_reclame, 9600)

    def test_un_fichier_portant_les_deux_colonnes_prime_sur_la_deduction(self):
        self.declarer(date(2026, 3, 5), 12000)

        self.importer(
            "date;matricule;beneficiaire;nature;montant_soin;montant_reclame\n"
            "05/03/2026;A0001;Fatima Zahra;Consultation;12000;12000\n"
        )

        ligne = Facture.objects.get(numero="F-2026-03").lignes.first()
        self.assertEqual(ligne.statut, StatutLigne.ECART_TAUX)

    def test_un_prestataire_inconnu_est_refuse(self):
        with self.assertRaises(CommandError):
            self.importer(
                self.entete() + "05/03/2026;A0001;Fatima Zahra;Consultation;12000\n",
                prestataire="INEXISTANT",
            )
