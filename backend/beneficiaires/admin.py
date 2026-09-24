from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import Agent, AyantDroit, StatutVerification


class AyantDroitInline(admin.TabularInline):
    model = AyantDroit
    extra = 0
    fields = ["nom", "prenom", "lien_parente", "statut_verification", "date_validite", "expire_badge"]
    readonly_fields = ["expire_badge"]
    show_change_link = True

    def expire_badge(self, obj):
        if obj.pk and obj.est_expire:
            return format_html('<span style="color:#c0392b;font-weight:bold;">⚠ Expiré</span>')
        return "—"

    expire_badge.short_description = "Justificatif"


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ["matricule", "nom_complet", "site", "quota_affiche", "solde_affiche", "actif"]
    list_filter = ["site", "actif"]
    search_fields = ["utilisateur__matricule", "utilisateur__nom", "utilisateur__prenom"]
    inlines = [AyantDroitInline]
    autocomplete_fields = ["utilisateur"]

    def nom_complet(self, obj):
        return obj.utilisateur.get_full_name()

    nom_complet.short_description = "Nom"

    def quota_affiche(self, obj):
        return f"{obj.quota_effectif} KMF"

    quota_affiche.short_description = "Quota du cycle (famille)"

    def solde_affiche(self, obj):
        return f"{obj.solde_quota()} KMF"

    solde_affiche.short_description = "Solde famille (cycle en cours)"


@admin.register(AyantDroit)
class AyantDroitAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "agent",
        "lien_parente",
        "age_badge",
        "statut_verification",
        "date_validite",
        "expire_badge",
    ]
    list_filter = ["statut_verification", "lien_parente", "type_justificatif"]
    search_fields = ["nom", "prenom", "agent__utilisateur__matricule"]
    actions = ["valider_ayants_droit", "rejeter_ayants_droit"]
    readonly_fields = ["date_creation", "date_maj"]

    def expire_badge(self, obj):
        if obj.est_expire:
            return format_html('<span style="color:#c0392b;font-weight:bold;">⚠ Expiré</span>')
        return "OK"

    expire_badge.short_description = "Justificatif"

    def age_badge(self, obj):
        if obj.age is None:
            return "—"
        if obj.limite_age_depassee:
            return format_html(
                '<span style="color:#c0392b;font-weight:bold;">{} ans ⚠ limite {} ans</span>',
                obj.age,
                obj.age_limite,
            )
        return f"{obj.age} ans"

    age_badge.short_description = "Âge"

    @admin.action(description="Valider les ayants droit sélectionnés")
    def valider_ayants_droit(self, request, queryset):
        updated = queryset.update(
            statut_verification=StatutVerification.VALIDE,
            verifie_par=request.user,
            date_verification=timezone.now(),
        )
        self.message_user(request, f"{updated} ayant(s) droit validé(s).")

    @admin.action(description="Rejeter les ayants droit sélectionnés")
    def rejeter_ayants_droit(self, request, queryset):
        updated = queryset.update(
            statut_verification=StatutVerification.REJETE,
            verifie_par=request.user,
            date_verification=timezone.now(),
        )
        self.message_user(request, f"{updated} ayant(s) droit rejeté(s).")
