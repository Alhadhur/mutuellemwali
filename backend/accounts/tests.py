"""Tests du compte administrateur créé au déploiement.

Cette commande s'exécute à chaque mise en ligne : le point délicat n'est pas
la création, c'est de ne **rien** faire quand le compte existe déjà.
"""
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from accounts.models import Role, Utilisateur


def executer(**variables):
    with patch.dict("os.environ", variables, clear=False):
        call_command("creer_admin_initial")


class CreerAdminInitialTest(TestCase):
    def test_le_compte_est_cree_avec_les_droits_complets(self):
        executer(ADMIN_MATRICULE="adm001", ADMIN_MOT_DE_PASSE="MotDePasseSolide2026!")

        compte = Utilisateur.objects.get(matricule="ADM001")
        self.assertTrue(compte.is_superuser)
        self.assertTrue(compte.is_staff)
        self.assertEqual(compte.role, Role.RH)
        self.assertTrue(compte.check_password("MotDePasseSolide2026!"))

    def test_le_matricule_est_normalise_en_majuscules(self):
        """Le matricule sert d'identifiant de connexion : une casse différente
        empêcherait de se connecter."""
        executer(ADMIN_MATRICULE="  adm002  ", ADMIN_MOT_DE_PASSE="x")

        self.assertTrue(Utilisateur.objects.filter(matricule="ADM002").exists())

    def test_un_mot_de_passe_change_depuis_l_interface_n_est_pas_ecrase(self):
        """La commande tourne à chaque déploiement : si elle réappliquait le
        mot de passe initial, tout changement fait ensuite serait annulé."""
        executer(ADMIN_MATRICULE="ADM003", ADMIN_MOT_DE_PASSE="MotDePasseInitial2026!")
        compte = Utilisateur.objects.get(matricule="ADM003")
        compte.set_password("NouveauMotDePasse2026!")
        compte.save()

        executer(ADMIN_MATRICULE="ADM003", ADMIN_MOT_DE_PASSE="MotDePasseInitial2026!")

        compte.refresh_from_db()
        self.assertTrue(compte.check_password("NouveauMotDePasse2026!"))
        self.assertEqual(Utilisateur.objects.filter(matricule="ADM003").count(), 1)

    def test_sans_variables_aucun_compte_n_est_cree(self):
        """Un déploiement sans ces variables ne doit pas échouer, ni créer un
        compte avec un mot de passe deviné."""
        executer(ADMIN_MATRICULE="", ADMIN_MOT_DE_PASSE="")

        self.assertEqual(Utilisateur.objects.count(), 0)

    def test_un_mot_de_passe_absent_n_ouvre_pas_de_compte(self):
        executer(ADMIN_MATRICULE="ADM004", ADMIN_MOT_DE_PASSE="")

        self.assertFalse(Utilisateur.objects.filter(matricule="ADM004").exists())
