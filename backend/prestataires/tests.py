import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from prestataires.models import Prestataire, StatutPrestataire, TypePrestataire


def fichier_csv(contenu):
    chemin = Path(tempfile.mkdtemp()) / "reseau.csv"
    chemin.write_text(contenu, encoding="utf-8")
    return str(chemin)


def importer(contenu, **options):
    sortie = StringIO()
    call_command("importer_prestataires", fichier_csv(contenu), stdout=sortie, **options)
    return sortie.getvalue()


class ImportPrestatairesTest(TestCase):
    def test_import_simple(self):
        importer("type,nom,ville,taux\npharmacie,Pharmacie A,Moroni,80\n")

        prestataire = Prestataire.objects.get(nom="Pharmacie A")
        self.assertEqual(prestataire.type_prestataire, TypePrestataire.PHARMACIE)
        self.assertEqual(prestataire.ville, "Moroni")
        self.assertEqual(prestataire.statut, StatutPrestataire.ACTIF)

    def test_le_point_virgule_et_les_libelles_francais_sont_acceptes(self):
        """Les fichiers produits par Excel en français utilisent « ; » et des
        libellés en toutes lettres."""
        importer("type;nom;ville\nÉtablissement;Clinique B;Mutsamudu\nmédecin;Dr C;Fomboni\n")

        self.assertEqual(
            Prestataire.objects.get(nom="Clinique B").type_prestataire, TypePrestataire.ETABLISSEMENT
        )
        self.assertEqual(Prestataire.objects.get(nom="Dr C").type_prestataire, TypePrestataire.PRATICIEN)

    def test_rejouer_le_fichier_met_a_jour_sans_dupliquer(self):
        contenu = "type,nom,ville,taux\npharmacie,Pharmacie A,Moroni,80\n"
        importer(contenu)
        importer("type,nom,ville,taux\npharmacie,Pharmacie A,Moroni,65\n")

        self.assertEqual(Prestataire.objects.filter(nom="Pharmacie A").count(), 1)
        self.assertEqual(Prestataire.objects.get(nom="Pharmacie A").taux_prise_en_charge, 65)

    def test_dry_run_n_ecrit_rien(self):
        sortie = importer("type,nom,ville\npharmacie,Pharmacie A,Moroni\n", dry_run=True)

        self.assertEqual(Prestataire.objects.count(), 0)
        self.assertIn("SIMULATION", sortie)

    def test_un_fichier_en_erreur_n_importe_aucune_ligne(self):
        """Tout ou rien : on ne veut pas d'un réseau à moitié chargé."""
        contenu = (
            "type,nom,ville,taux\n"
            "pharmacie,Pharmacie A,Moroni,80\n"
            "inconnu,Pharmacie B,Moroni,80\n"
        )

        with self.assertRaises(CommandError):
            importer(contenu)

        self.assertEqual(Prestataire.objects.count(), 0)

    def test_les_lignes_invalides_sont_signalees_avec_leur_numero(self):
        sortie = importer(
            "type,nom,ville,taux\npharmacie,Pharmacie A,Moroni,150\npharmacie,,Moroni,80\n",
            dry_run=True,
        )

        self.assertIn("ligne 2", sortie)
        self.assertIn("ligne 3", sortie)
        self.assertIn("nom vide", sortie)

    def test_une_colonne_obligatoire_absente_arrete_l_import(self):
        with self.assertRaises(CommandError):
            importer("nom,ville\nPharmacie A,Moroni\n")

    def test_le_taux_par_defaut_s_applique_si_la_colonne_est_absente(self):
        importer("type,nom\npharmacie,Pharmacie A\n")

        self.assertEqual(Prestataire.objects.get(nom="Pharmacie A").taux_prise_en_charge, 80)
