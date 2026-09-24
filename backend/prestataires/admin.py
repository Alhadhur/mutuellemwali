from django.contrib import admin

from .models import Prestataire


@admin.register(Prestataire)
class PrestataireAdmin(admin.ModelAdmin):
    list_display = ["code", "nom", "type_prestataire", "ville", "taux_prise_en_charge", "statut"]
    list_filter = ["type_prestataire", "statut", "ville"]
    search_fields = ["code", "nom", "ville"]
    readonly_fields = ["code", "date_creation"]
    actions = ["suspendre", "activer"]

    @admin.action(description="Suspendre les prestataires sélectionnés")
    def suspendre(self, request, queryset):
        updated = queryset.update(statut="SUSPENDU")
        self.message_user(request, f"{updated} prestataire(s) suspendu(s).")

    @admin.action(description="Réactiver les prestataires sélectionnés")
    def activer(self, request, queryset):
        updated = queryset.update(statut="ACTIF")
        self.message_user(request, f"{updated} prestataire(s) réactivé(s).")
