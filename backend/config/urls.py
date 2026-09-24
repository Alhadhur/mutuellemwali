from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from config.media import FichierProtege
from config.views import sante

urlpatterns = [
    # Sonde de disponibilité de l'hébergeur : ni session, ni base, ni
    # redirection HTTPS (voir SECURE_REDIRECT_EXEMPT).
    path("sante/", sante, name="sante"),

    path("admin/", admin.site.urls),
    path("backoffice/", include("backoffice.urls")),
    path("dashboard/", RedirectView.as_view(pattern_name="backoffice:tableau_de_bord")),
    path("api/", include("api.urls")),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", auth_views.LoginView.as_view(template_name="registration/login.html")),

    # Les fichiers déposés passent par une vue qui contrôle les droits, en
    # développement comme en production : ce sont des données de santé.
    path("media/<path:chemin>", FichierProtege.as_view(), name="fichier_protege"),
]
