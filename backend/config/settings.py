"""
Configuration Django — Outil de contrôle de la fraude sur la mutuelle de santé.
"""
from datetime import timedelta
from pathlib import Path

import dj_database_url
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

# Render expose le domaine attribué au service dans cette variable : l'ajouter
# évite d'avoir à recopier l'URL à la main après chaque création de service.
RENDER_HOSTNAME = config("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_HOSTNAME)

# Django exige l'origine complète (avec le schéma) pour valider un POST.
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
if RENDER_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOSTNAME}")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Tiers
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # Apps métier
    "parametrage",
    "facturation",
    "backoffice",
    "accounts",
    "beneficiaires",
    "prestataires",
    "prescriptions",
    "anomalies",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sert les fichiers statiques sans serveur web séparé devant Django.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.menu_backoffice",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Base de données.
#
# Deux modes, sans changement de code :
#  - DATABASE_URL défini (Render) : l'URL décrit le moteur et les accès. Render
#    fournit cette variable automatiquement lorsqu'une base est rattachée.
#  - sinon : les variables DB_* du poste de développement (MySQL local).
DATABASE_URL = config("DATABASE_URL", default="")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            # Render impose TLS sur ses bases managées.
            ssl_require=config("DB_SSL_REQUIRE", default=True, cast=bool),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST", default="127.0.0.1"),
            "PORT": config("DB_PORT", default="3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }

AUTH_USER_MODEL = "accounts.Utilisateur"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
# Fuseau de la mutuelle. Les dates et heures sont stockées en UTC (USE_TZ)
# et converties à l'affichage : le serveur peut donc être hébergé ailleurs.
TIME_ZONE = "Indian/Comoro"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
# En production, pointe vers le disque persistant monté sur le service : le
# système de fichiers d'une instance Render est réinitialisé à chaque
# déploiement, un justificatif écrit ailleurs serait définitivement perdu.
MEDIA_ROOT = config("MEDIA_ROOT", default=str(BASE_DIR / "media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Noms de fichiers versionnés + compression : les navigateurs peuvent
        # mettre en cache indéfiniment sans risque de servir une version périmée.
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Back-office (dashboard anomalies + login)
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "backoffice:tableau_de_bord"
LOGOUT_REDIRECT_URL = "login"


# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "USER_ID_FIELD": "matricule",
    "USER_ID_CLAIM": "matricule",
}

# CORS — l'app mobile Flutter (web/dev) doit pouvoir appeler l'API.
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CORS_ALLOW_ALL_ORIGINS = DEBUG


# --- Sécurité en production -------------------------------------------------
# Ces réglages ne s'activent que hors DEBUG : le développement local, qui tourne
# en HTTP, n'est pas gêné. L'application traite des données de santé nominatives,
# elles ne doivent jamais transiter en clair.
if not DEBUG:
    # Render termine le TLS en amont et transmet le schéma d'origine dans cet
    # en-tête ; sans cela Django croirait toutes les requêtes en HTTP et
    # bouclerait sur la redirection.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    # La sonde de l'hébergeur arrive en HTTP : sans exemption, elle recevrait
    # une redirection et le service serait déclaré indisponible.
    SECURE_REDIRECT_EXEMPT = [r"^sante/$"]

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_EXPIRE_AT_BROWSER_CLOSE = True

    # HSTS : à n'activer qu'une fois le domaine définitivement en HTTPS, car un
    # navigateur mémorise la consigne pour la durée indiquée.
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
