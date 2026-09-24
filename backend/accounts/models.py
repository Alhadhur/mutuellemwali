from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class Role(models.TextChoices):
    AGENT = "AGENT", "Agent (bénéficiaire)"
    RH = "RH", "Service mutuelle / RH"
    DIRECTION = "DIRECTION", "Direction / contrôle"
    PRESTATAIRE = "PRESTATAIRE", "Prestataire conventionné"


class UtilisateurManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, matricule, password, **extra_fields):
        if not matricule:
            raise ValueError("Le matricule est obligatoire.")
        matricule = matricule.strip().upper()
        user = self.model(matricule=matricule, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, matricule, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", Role.AGENT)
        return self._create_user(matricule, password, **extra_fields)

    def create_superuser(self, matricule, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.RH)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superutilisateur doit avoir is_superuser=True.")
        return self._create_user(matricule, password, **extra_fields)


class Utilisateur(AbstractBaseUser, PermissionsMixin):
    """Compte de connexion, commun à tous les acteurs (agent, RH, direction,
    prestataire). Les données métier (fiche agent, fiche prestataire) sont
    portées par les modèles des apps correspondantes, liés en OneToOne.
    """

    matricule = models.CharField(max_length=20, unique=True)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    telephone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Téléphone",
        help_text="Numéro joignable, utilisé pour contacter le titulaire du compte.",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.AGENT)

    region = models.CharField(max_length=100, blank=True)
    photo = models.ImageField(upload_to="photos_utilisateurs/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True)

    objects = UtilisateurManager()

    USERNAME_FIELD = "matricule"
    REQUIRED_FIELDS = ["nom", "prenom"]

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ["matricule"]

    def __str__(self):
        return f"{self.matricule} — {self.prenom} {self.nom} ({self.get_role_display()})"

    def get_full_name(self):
        return f"{self.prenom} {self.nom}".strip()

    def get_short_name(self):
        return self.prenom
