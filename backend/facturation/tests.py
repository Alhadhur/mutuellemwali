import tempfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, TypeJustificatif
from facturation.models import Facture, LigneFacture, StatutFacture, StatutLigne
from parametrage.models import NatureSoin
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, TarifPrestataire, TypePrestataire


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

    def ligne(self, facture, jour, montant, matricule="A0001", reclame=None, nature="Consultation",
              beneficiaire="Fatima Zahra"):
        """`montant` est le coût total du soin ; la part réclamée vaut par
        défaut ce que le taux du prestataire autorise."""
        return LigneFacture.objects.create(
            facture=facture,
            date_soin=jour,
            matricule=matricule,
            nom_beneficiaire=beneficiaire,
            nature=nature,
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

    def test_le_tarif_par_nature_de_soin_prime_sur_le_taux_general(self):
        """Une fois ce prestataire tarifé en détail pour une nature donnée, le
        rapprochement doit comparer à ce taux-là, pas au taux général — sinon
        une ligne correctement facturée au tarif détaillé ressortirait à tort
        comme un taux mal appliqué (voir Prestataire.taux_pour)."""
        chirurgie = NatureSoin.objects.get(libelle="Chirurgie")
        TarifPrestataire.objects.create(
            prestataire=self.prestataire, nature_soin=chirurgie, taux_prise_en_charge=60
        )
        Prescription.objects.create(
            agent=self.agent,
            prestataire=self.prestataire,
            nature=chirurgie,
            numero_ordonnance="ORD-CHIR",
            montant_total=100000,
            date_emission=date(2026, 3, 5),
            justificatif="x.jpg",
        )
        facture = self.facture(total=60000)
        # Le prestataire réclame exactement les 60 % de son tarif détaillé
        # « Chirurgie » ; son taux général (80 %) attendrait 80000.
        ligne = LigneFacture.objects.create(
            facture=facture,
            date_soin=date(2026, 3, 5),
            matricule="A0001",
            nom_beneficiaire="Fatima Zahra",
            nature="Chirurgie",
            montant_soin=100000,
            montant_reclame=60000,
        )

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)
        self.assertEqual(ligne.montant_reclame_attendu, 60000)
        self.assertEqual(ligne.ecart_taux, 0)

    def test_une_nature_absente_des_tarifs_detailles_est_signalee(self):
        """Un prestataire détaillé (au moins un tarif par nature) facture une
        nature qu'il n'a jamais tarifée : il ne devrait pas la proposer."""
        chirurgie = NatureSoin.objects.get(libelle="Chirurgie")
        TarifPrestataire.objects.create(
            prestataire=self.prestataire, nature_soin=chirurgie, taux_prise_en_charge=60
        )
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        # Le montant concorde exactement : sans le contrôle de nature, cette
        # ligne ressortirait à tort comme concordante.
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, nature="Hospitalisation")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.NATURE_NON_COUVERTE)

    def test_un_prestataire_non_detaille_n_est_jamais_signale_pour_sa_nature(self):
        """Sans aucun tarif par nature, le prestataire n'est pas restreint :
        n'importe quel intitulé de nature reste acceptable."""
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, nature="Chirurgie exotique")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)

    def test_un_beneficiaire_different_est_signale(self):
        """Matricule, date et montant concordent, mais le nom facturé ne
        désigne pas le même bénéficiaire que la prescription."""
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, beneficiaire="Ahmed Ali")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.BENEFICIAIRE_DIFFERENT)

    def test_le_nom_facture_dans_un_ordre_different_n_est_pas_signale(self):
        """« Zahra Fatima » plutôt que « Fatima Zahra » : une simple
        inversion nom/prénom ne doit pas être un faux positif."""
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, beneficiaire="Zahra Fatima")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)

    def test_le_beneficiaire_attendu_est_celui_de_l_ayant_droit_rapproche(self):
        """Quand la prescription concerne un ayant droit, c'est son nom à lui
        qui fait foi, pas celui de l'agent porteur du quota."""
        ayant_droit = AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Amine",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
        )
        Prescription.objects.create(
            agent=self.agent,
            ayant_droit=ayant_droit,
            prestataire=self.prestataire,
            numero_ordonnance="ORD-ENFANT",
            montant_total=12000,
            date_emission=date(2026, 3, 5),
            justificatif="x.jpg",
        )
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, beneficiaire="Amine Zahra")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)

    def test_un_nom_de_famille_seul_n_est_pas_signale(self):
        """En pratique, un prestataire n'écrit souvent que le nom ou le
        prénom, jamais les deux : ça ne doit pas être traité comme un
        bénéficiaire différent."""
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000, beneficiaire="Zahra")

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)


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


class PrescriptionRejeteeTest(BaseFacturation):
    """Une facture ne renverse jamais un rejet décidé par la mutuelle."""

    def test_une_ligne_qui_correspond_a_une_prescription_rejetee_est_signalee(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        prescription.changer_statut(StatutPrescription.REJETEE)
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.statut, StatutLigne.PRESCRIPTION_REJETEE)
        self.assertEqual(ligne.prescription, prescription)
        self.assertEqual(facture.synthese()["prescriptions_rejetees"], 1)

    def test_valider_la_facture_ne_revalide_pas_une_prescription_rejetee(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        prescription.changer_statut(StatutPrescription.REJETEE)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        facture.rapprocher()

        facture.valider(self.rh)

        prescription.refresh_from_db()
        self.assertEqual(prescription.statut, StatutPrescription.REJETEE)

    def test_un_rejet_posterieur_au_rapprochement_est_respecte(self):
        """Ligne concordante au rapprochement, prescription rejetée ensuite :
        la validation de la facture ne doit pas l'écraser."""
        prescription = self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        facture.rapprocher()
        prescription.changer_statut(StatutPrescription.REJETEE)

        facture.valider(self.rh)

        prescription.refresh_from_db()
        self.assertEqual(prescription.statut, StatutPrescription.REJETEE)

    def test_une_prescription_en_jeu_passe_avant_une_prescription_rejetee(self):
        rejetee = self.declarer(date(2026, 3, 5), 12000, numero="ORD-R")
        rejetee.changer_statut(StatutPrescription.REJETEE)
        valable = self.declarer(date(2026, 3, 5), 12000, numero="ORD-V")
        facture = self.facture()
        ligne = self.ligne(facture, date(2026, 3, 5), 12000)

        facture.rapprocher()

        ligne.refresh_from_db()
        self.assertEqual(ligne.prescription, valable)
        self.assertEqual(ligne.statut, StatutLigne.CONCORDANTE)

    def test_une_prescription_rejetee_non_facturee_n_est_pas_une_alerte(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        prescription.changer_statut(StatutPrescription.REJETEE)
        facture = self.facture()

        facture.rapprocher()

        self.assertEqual(facture.synthese()["non_facturees"], 0)


class PrescriptionEnControleTest(BaseFacturation):
    """Une ligne concordante ne lève pas l'alerte d'une prescription en
    contrôle : la validation de la facture la laisse de côté."""

    def test_valider_la_facture_laisse_en_controle_une_prescription_signalee(self):
        prescription = self.declarer(date(2026, 3, 5), 12000)
        prescription.changer_statut(StatutPrescription.EN_CONTROLE)
        autre = self.declarer(date(2026, 3, 6), 8000, numero="ORD-2")
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        self.ligne(facture, date(2026, 3, 6), 8000)
        facture.rapprocher()

        self.assertEqual(facture.lignes_concordantes_en_controle().count(), 1)
        validees = facture.valider(self.rh)

        self.assertEqual(validees, 1)
        prescription.refresh_from_db()
        autre.refresh_from_db()
        self.assertEqual(prescription.statut, StatutPrescription.EN_CONTROLE)
        self.assertEqual(autre.statut, StatutPrescription.VALIDEE)


class ResumeRapprochementTest(BaseFacturation):
    def test_le_resume_cite_toutes_les_categories_et_leur_somme_fait_le_total(self):
        self.declarer(date(2026, 3, 5), 12000)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 12000)
        self.ligne(facture, date(2026, 3, 6), 9000)
        self.ligne(facture, date(2026, 3, 7), 5000, matricule="INCONNU")
        facture.rapprocher()

        resume = facture.resume_rapprochement()

        self.assertEqual(
            resume,
            "3 ligne(s) — 1 concordante(s), 1 sans prescription, 1 matricule(s) inconnu(s). "
            "Côté mutuelle : 0 prescription(s) déclarée(s) non facturée(s).",
        )


class TauxParNatureTest(BaseFacturation):
    """Un hôpital tarifé par nature : le montant manquant d'une ligne se
    déduit au taux de sa nature — celui que le rapprochement vérifie —, pas
    au taux général (voir Prestataire.taux_pour_libelle)."""

    def setUp(self):
        super().setUp()
        self.hospitalisation = NatureSoin.objects.get(libelle="Hospitalisation")
        TarifPrestataire.objects.create(
            prestataire=self.prestataire, nature_soin=self.hospitalisation, taux_prise_en_charge=50
        )

    def test_le_taux_suit_la_nature_ecrite_sans_tenir_compte_des_accents_ni_de_la_casse(self):
        self.assertEqual(self.prestataire.taux_pour_libelle("HOSPITALISATION"), 50)
        self.assertEqual(self.prestataire.taux_pour_libelle("Consultation"), 80)
        self.assertEqual(self.prestataire.taux_pour_libelle(""), 80)

    def test_l_import_deduit_le_cout_total_au_taux_de_la_nature(self):
        sortie = StringIO()
        call_command(
            "importer_facture",
            fichier_csv("date;matricule;beneficiaire;nature;montant\n05/03/2026;A0001;Fatima Zahra;Hospitalisation;50000\n"),
            stdout=sortie,
            prestataire=self.prestataire.code,
            numero="F-H",
            mois=3,
            annee=2026,
            total=50000,
        )

        ligne = LigneFacture.objects.get(facture__numero="F-H")
        self.assertEqual(ligne.montant_reclame, 50000)
        self.assertEqual(ligne.montant_soin, 100000)

    def test_une_ligne_sans_prescription_est_controlee_au_taux_de_sa_nature(self):
        ligne = self.ligne(self.facture(), date(2026, 3, 5), 100000, reclame=50000, nature="Hospitalisation")

        self.assertEqual(ligne.montant_reclame_attendu, 50000)
        self.assertEqual(ligne.ecart_taux, 0)

    def test_une_ligne_au_taux_de_sa_nature_n_est_pas_un_ecart_de_taux(self):
        prescription = self.declarer(date(2026, 3, 5), 100000)
        Prescription.objects.filter(pk=prescription.pk).update(nature=self.hospitalisation)
        facture = self.facture()
        self.ligne(facture, date(2026, 3, 5), 100000, reclame=50000, nature="Hospitalisation")

        facture.rapprocher()

        self.assertEqual(facture.lignes.get().statut, StatutLigne.CONCORDANTE)


class ExplicationEcartTest(BaseFacturation):
    """L'écart entre le total annoncé et la somme des lignes se décompose en
    corrections faites depuis la réception et en copies probables."""

    def test_le_montant_d_origine_est_memorise_a_la_creation(self):
        ligne = self.ligne(self.facture(), date(2026, 3, 5), 10000)

        self.assertEqual(ligne.montant_soin_initial, 10000)
        self.assertEqual(ligne.montant_reclame_initial, 8000)

    def test_une_correction_garde_le_montant_d_origine(self):
        ligne = self.ligne(self.facture(), date(2026, 3, 5), 10000)
        ligne.montant_reclame = 7000
        ligne.save()

        ligne.refresh_from_db()
        self.assertEqual(ligne.montant_reclame_initial, 8000)
        self.assertEqual(ligne.correction_reclame, -1000)

    def test_l_ecart_s_explique_par_une_correction(self):
        facture = self.facture(total=16000)
        self.ligne(facture, date(2026, 3, 5), 10000)
        corrigee = self.ligne(facture, date(2026, 3, 6), 10000)
        corrigee.montant_reclame = 7000
        corrigee.corrigee_le = corrigee.facture.date_creation
        corrigee.save()

        explication = facture.explication_ecart()

        self.assertEqual(explication["ecart"], 1000)
        self.assertEqual(explication["ecart_initial"], 0)
        self.assertEqual(explication["nombre_corrigees"], 1)
        self.assertEqual(explication["effet_corrections"], -1000)

    def test_une_ligne_repetee_est_un_doublon_probable(self):
        facture = self.facture(total=8000)
        originale = self.ligne(facture, date(2026, 3, 5), 10000)
        copie = self.ligne(facture, date(2026, 3, 5), 10000, beneficiaire="zahra FATIMA")
        self.ligne(facture, date(2026, 3, 5), 12000)  # autre montant : pas une copie

        self.assertEqual(facture.ids_doublons(), {copie.pk})
        self.assertNotIn(originale.pk, facture.ids_doublons())
        explication = facture.explication_ecart()
        self.assertEqual(explication["montant_doublons"], 8000)
        self.assertEqual(explication["reste"], explication["ecart"] + 8000)

    def test_sans_correction_ni_doublon_l_ecart_reste_d_origine(self):
        facture = self.facture(total=20000)
        self.ligne(facture, date(2026, 3, 5), 10000)

        explication = facture.explication_ecart()

        self.assertEqual(explication["ecart"], 12000)
        self.assertEqual(explication["ecart_initial"], 12000)
        self.assertEqual(explication["nombre_corrigees"], 0)
        self.assertEqual(explication["nombre_doublons"], 0)


class RapprochementMemeJourTest(BaseFacturation):
    """Plusieurs soins du même agent (ou de ses ayants droit) le même jour :
    chaque ligne doit trouver sa propre prescription, quel que soit l'ordre
    des lignes sur la facture — et non la première prescription venue."""

    JOUR = date(2026, 3, 5)

    def creer_enfant(self):
        return AyantDroit.objects.create(
            agent=self.agent,
            nom="Zahra",
            prenom="Amine",
            lien_parente=LienParente.ENFANT,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
        )

    def test_une_ligne_exacte_garde_sa_prescription_meme_si_une_ligne_en_ecart_passe_avant(self):
        p_10000 = self.declarer(self.JOUR, 10000, numero="ORD-A")
        p_15000 = self.declarer(self.JOUR, 15000, numero="ORD-B")
        facture = self.facture()
        en_ecart = self.ligne(facture, self.JOUR, 12000)  # saisie en premier
        exacte = self.ligne(facture, self.JOUR, 10000)

        facture.rapprocher()

        exacte.refresh_from_db()
        en_ecart.refresh_from_db()
        self.assertEqual(exacte.prescription, p_10000)
        self.assertEqual(exacte.statut, StatutLigne.CONCORDANTE)
        self.assertEqual(en_ecart.prescription, p_15000)
        self.assertEqual(en_ecart.statut, StatutLigne.ECART_MONTANT)

    def test_a_defaut_de_montant_exact_le_plus_proche_l_emporte(self):
        p_11000 = self.declarer(self.JOUR, 11000, numero="ORD-A")
        p_19000 = self.declarer(self.JOUR, 19000, numero="ORD-B")
        facture = self.facture()
        ligne_20000 = self.ligne(facture, self.JOUR, 20000)
        ligne_10000 = self.ligne(facture, self.JOUR, 10000)

        facture.rapprocher()

        ligne_20000.refresh_from_db()
        ligne_10000.refresh_from_db()
        self.assertEqual(ligne_20000.prescription, p_19000)
        self.assertEqual(ligne_10000.prescription, p_11000)

    def test_l_agent_et_son_enfant_le_meme_jour_ne_sont_pas_croises(self):
        enfant = self.creer_enfant()
        p_agent = self.declarer(self.JOUR, 10000, numero="ORD-AGENT")
        p_enfant = self.declarer(self.JOUR, 9000, numero="ORD-ENFANT")
        Prescription.objects.filter(pk=p_enfant.pk).update(ayant_droit=enfant)
        facture = self.facture()
        ligne_enfant = self.ligne(facture, self.JOUR, 9500, beneficiaire="Amine Zahra")
        ligne_agent = self.ligne(facture, self.JOUR, 10000, beneficiaire="Fatima Zahra")

        facture.rapprocher()

        ligne_enfant.refresh_from_db()
        ligne_agent.refresh_from_db()
        self.assertEqual(ligne_agent.prescription, p_agent)
        self.assertEqual(ligne_agent.statut, StatutLigne.CONCORDANTE)
        self.assertEqual(ligne_enfant.prescription, p_enfant)
        self.assertEqual(ligne_enfant.statut, StatutLigne.ECART_MONTANT)

    def test_le_bon_beneficiaire_passe_avant_le_montant_exact(self):
        """Le prestataire a mal reporté le montant de l'enfant, et ce montant
        tombe pile sur celui de l'agent : la ligne reste celle de l'enfant."""
        enfant = self.creer_enfant()
        self.declarer(self.JOUR, 10000, numero="ORD-AGENT")
        p_enfant = self.declarer(self.JOUR, 9000, numero="ORD-ENFANT")
        Prescription.objects.filter(pk=p_enfant.pk).update(ayant_droit=enfant)
        facture = self.facture()
        ligne_enfant = self.ligne(facture, self.JOUR, 10000, beneficiaire="Amine Zahra")

        facture.rapprocher()

        ligne_enfant.refresh_from_db()
        self.assertEqual(ligne_enfant.prescription, p_enfant)
        self.assertEqual(ligne_enfant.statut, StatutLigne.ECART_MONTANT)

    def test_le_resultat_ne_depend_pas_de_l_ordre_de_saisie(self):
        self.declarer(self.JOUR, 10000, numero="ORD-A")
        self.declarer(self.JOUR, 15000, numero="ORD-B")
        resultats = []
        for montants in ((12000, 10000), (10000, 12000)):
            facture = self.facture(numero=f"F-{montants[0]}")
            for montant in montants:
                self.ligne(facture, self.JOUR, montant)
            facture.rapprocher()
            resultats.append(
                sorted((l.montant_soin, l.prescription.numero_ordonnance) for l in facture.lignes.all())
            )

        self.assertEqual(resultats[0], resultats[1])
