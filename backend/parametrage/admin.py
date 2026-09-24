from django.contrib import admin

from .models import Parametrage


@admin.register(Parametrage)
class ParametrageAdmin(admin.ModelAdmin):
    list_display = ["__str__", "quota_mensuel_defaut", "age_limite_enfant", "date_maj"]
    readonly_fields = ["date_maj"]
    fieldsets = (
        ("Remboursement", {"fields": ("quota_mensuel_defaut",)}),
        ("Ayants droit", {"fields": ("age_limite_enfant",)}),
        ("Suivi", {"fields": ("date_maj",)}),
    )

    def has_add_permission(self, request):
        return not Parametrage.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
