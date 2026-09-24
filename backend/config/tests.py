from unittest.mock import patch

from django.test import RequestFactory, TestCase

from accounts.models import Role, Utilisateur
from config import menu


def libelles(sections):
    return [entree["libelle"] for section in sections for entree in section["entrees"]]


class MenuBackofficeTest(TestCase):
    def test_le_service_mutuelle_voit_toutes_les_entrees(self):
        rh = Utilisateur.objects.create_user("RH1", "x", nom="A", prenom="B", role=Role.RH)

        vues = libelles(menu.construire(rh, "/backoffice/"))

        self.assertIn("Tableau de bord", vues)
        self.assertIn("Agents", vues)
        self.assertIn("Utilisateurs", vues)
        self.assertIn("Paramètres de la mutuelle", vues)

    def test_la_direction_ne_voit_pas_les_ecrans_reserves_au_service_mutuelle(self):
        direction = Utilisateur.objects.create_user(
            "DIR1", "x", nom="A", prenom="B", role=Role.DIRECTION
        )

        vues = libelles(menu.construire(direction, "/backoffice/"))

        self.assertIn("Tableau de bord", vues)
        self.assertIn("Agents", vues)
        self.assertNotIn("Utilisateurs", vues)
        self.assertNotIn("Paramètres de la mutuelle", vues)

    def test_une_fonctionnalite_a_venir_reste_annoncee_sans_lien(self):
        """Le mécanisme est testé sur un menu fictif, et non sur le menu réel :
        sinon le test casserait chaque fois qu'une fonctionnalité annoncée est
        effectivement livrée — ce qui est une bonne nouvelle, pas une panne.
        """
        rh = Utilisateur.objects.create_user("RH2", "x", nom="A", prenom="B", role=Role.RH)
        menu_fictif = (
            menu.Section(
                "Essai",
                (
                    menu.Entree("Livré", "backoffice:agents", "✅"),
                    menu.Entree("À venir", icone="🕒", disponible=False),
                ),
            ),
        )

        with patch.object(menu, "MENU", menu_fictif):
            entrees = [e for s in menu.construire(rh, "/backoffice/") for e in s["entrees"]]

        a_venir = [e for e in entrees if not e["disponible"]]
        self.assertEqual([e["libelle"] for e in a_venir], ["À venir"])
        self.assertTrue(all(e["url"] == "" for e in a_venir))

    def test_une_entree_annoncee_reste_visible_pour_tous_les_roles(self):
        """Une fonctionnalité à venir s'adresse à tout le monde : la restreindre
        par rôle la rendrait invisible avant même d'exister."""
        direction = Utilisateur.objects.create_user("DIR2", "x", nom="A", prenom="B", role=Role.DIRECTION)
        menu_fictif = (
            menu.Section(
                "Essai",
                (menu.Entree("Réservé RH, à venir", icone="🕒", roles=(Role.RH,), disponible=False),),
            ),
        )

        with patch.object(menu, "MENU", menu_fictif):
            entrees = [e for s in menu.construire(direction, "/backoffice/") for e in s["entrees"]]

        self.assertEqual([e["libelle"] for e in entrees], ["Réservé RH, à venir"])

    def test_seule_l_entree_la_plus_specifique_est_active(self):
        """Toutes les URLs commencent par /backoffice/ : sans cette règle, le
        tableau de bord serait marqué actif sur chaque page."""
        rh = Utilisateur.objects.create_user("RH3", "x", nom="A", prenom="B", role=Role.RH)

        sections = menu.construire(rh, "/backoffice/agents/1/modifier/")
        actives = [e["libelle"] for s in sections for e in s["entrees"] if e["active"]]

        self.assertEqual(actives, ["Agents"])

    def test_le_tableau_de_bord_est_actif_sur_sa_propre_page(self):
        rh = Utilisateur.objects.create_user("RH4", "x", nom="A", prenom="B", role=Role.RH)

        sections = menu.construire(rh, "/backoffice/")
        actives = [e["libelle"] for s in sections for e in s["entrees"] if e["active"]]

        self.assertEqual(actives, ["Tableau de bord"])

    def test_le_menu_est_absent_pour_un_visiteur_non_connecte(self):
        from django.contrib.auth.models import AnonymousUser

        from config.context_processors import menu_backoffice

        requete = RequestFactory().get("/backoffice/")
        requete.user = AnonymousUser()

        self.assertEqual(menu_backoffice(requete), {})
