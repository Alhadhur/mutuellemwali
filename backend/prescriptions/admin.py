from django.contrib import admin
from django.utils.html import format_html

from .models import HistoriqueStatut, Prescription, StatutPrescription


class HistoriqueStatutInline(admin.TabularInline):
    model = HistoriqueStatut
    extra = 0
    readonly_fields = ["ancien_statut", "nouveau_statut", "utilisateur", "commentaire", "date_changement"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


COULEURS_STATUT = {
    StatutPrescription.SOUMISE: "#2980b9",
    StatutPrescription.EN_CONTROLE: "#e67e22",
    StatutPrescription.VALIDEE: "#27ae60",
    StatutPrescription.REJETEE: "#c0392b",
}


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = [
        "numero_ordonnance",
        "agent",
        "beneficiaire_display",
        "prestataire",
        "montant_total",
        "montant_rembourse",
        "date_emission",
        "statut_badge",
    ]
    list_filter = ["statut", "prestataire__type_prestataire", "prestataire"]
    search_fields = ["numero_ordonnance", "agent__utilisateur__matricule", "agent__utilisateur__nom"]
    readonly_fields = ["montant_rembourse", "motif_signalement", "date_creation", "date_maj"]
    autocomplete_fields = ["agent", "ayant_droit", "prestataire"]
    inlines = [HistoriqueStatutInline]
    actions = ["valider", "rejeter", "remettre_en_controle"]

    def beneficiaire_display(self, obj):
        return str(obj.beneficiaire())

    beneficiaire_display.short_description = "Bénéficiaire"

    def statut_badge(self, obj):
        couleur = COULEURS_STATUT.get(obj.statut, "#7f8c8d")
        return format_html(
            '<span style="color:white;background:{};padding:2px 8px;border-radius:10px;font-size:11px;">{}</span>',
            couleur,
            obj.get_statut_display(),
        )

    statut_badge.short_description = "Statut"

    @admin.action(description="Valider les prescriptions sélectionnées")
    def valider(self, request, queryset):
        count = 0
        for prescription in queryset:
            prescription.changer_statut(StatutPrescription.VALIDEE, utilisateur=request.user, commentaire="Validation manuelle (admin).")
            count += 1
        self.message_user(request, f"{count} prescription(s) validée(s).")

    @admin.action(description="Rejeter les prescriptions sélectionnées")
    def rejeter(self, request, queryset):
        count = 0
        for prescription in queryset:
            prescription.changer_statut(StatutPrescription.REJETEE, utilisateur=request.user, commentaire="Rejet manuel (admin).")
            count += 1
        self.message_user(request, f"{count} prescription(s) rejetée(s).")

    @admin.action(description="Remettre en contrôle")
    def remettre_en_controle(self, request, queryset):
        count = 0
        for prescription in queryset:
            prescription.changer_statut(StatutPrescription.EN_CONTROLE, utilisateur=request.user, commentaire="Remise en contrôle (admin).")
            count += 1
        self.message_user(request, f"{count} prescription(s) remise(s) en contrôle.")
