from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Utilisateur

admin.site.site_header = "Mutuelle santé — Back-office"
admin.site.site_title = "Mutuelle santé"
admin.site.index_title = "Contrôle de la fraude sur la mutuelle de santé"
admin.site.index_template = "admin/index_backoffice.html"


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    model = Utilisateur
    ordering = ["matricule"]
    list_display = ["matricule", "prenom", "nom", "role", "region", "is_active", "is_staff"]
    list_filter = ["role", "region", "is_active", "is_staff"]
    search_fields = ["matricule", "nom", "prenom", "email", "telephone", "region"]

    fieldsets = (
        (None, {"fields": ("matricule", "password")}),
        ("Informations personnelles", {"fields": ("nom", "prenom", "email", "telephone", "role", "region", "photo")}),
        ("Droits d'accès", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_creation")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "matricule",
                    "nom",
                    "prenom",
                    "email",
                    "telephone",
                    "role",
                    "region",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    readonly_fields = ["date_creation", "last_login"]
