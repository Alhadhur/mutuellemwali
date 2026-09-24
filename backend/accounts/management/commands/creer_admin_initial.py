"""Crée le compte administrateur du premier déploiement.

Sur une base neuve, personne ne peut ouvrir le back-office : il n'existe aucun
compte. Cette commande comble ce trou à partir de variables d'environnement,
sans jamais écrire de mot de passe dans le dépôt.

Elle est appelée à chaque déploiement et ne fait rien si le compte existe
déjà : le mot de passe d'un compte en service n'est jamais réécrit, sinon un
changement fait depuis l'interface serait annulé au déploiement suivant.
"""
import os

from django.core.management.base import BaseCommand

from accounts.models import Role, Utilisateur


class Command(BaseCommand):
    help = "Crée le compte administrateur initial d'après ADMIN_MATRICULE et ADMIN_MOT_DE_PASSE."

    def handle(self, *args, **options):
        matricule = os.environ.get("ADMIN_MATRICULE", "").strip().upper()
        mot_de_passe = os.environ.get("ADMIN_MOT_DE_PASSE", "")

        if not matricule or not mot_de_passe:
            self.stdout.write(
                "ADMIN_MATRICULE ou ADMIN_MOT_DE_PASSE absent : aucun compte créé."
            )
            return

        if Utilisateur.objects.filter(matricule=matricule).exists():
            self.stdout.write(f"Le compte {matricule} existe déjà : rien à faire.")
            return

        Utilisateur.objects.create_superuser(
            matricule=matricule,
            password=mot_de_passe,
            nom=os.environ.get("ADMIN_NOM", "Administrateur"),
            prenom=os.environ.get("ADMIN_PRENOM", "Système"),
            email=os.environ.get("ADMIN_EMAIL", ""),
            role=Role.RH,
        )
        self.stdout.write(self.style.SUCCESS(f"Compte administrateur {matricule} créé."))
