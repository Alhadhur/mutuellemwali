from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("", views.TableauDeBordView.as_view(), name="tableau_de_bord"),

    path("mon-profil/", views.MonProfil.as_view(), name="mon_profil"),
    path("mon-profil/mot-de-passe/", views.MonMotDePasse.as_view(), name="mon_mot_de_passe"),

    path("anomalies/", views.AnomaliesView.as_view(), name="anomalies"),
    path("anomalies/export/", views.AnomaliesExport.as_view(), name="anomalies_export"),
    path("anomalies/export/<str:famille>/", views.AnomaliesExport.as_view(), name="anomalies_export_famille"),

    path("rapports/", views.RapportsView.as_view(), name="rapports"),
    path("rapports/export/", views.RapportsExport.as_view(), name="rapports_export"),
    path("rapports/export/<str:rapport>/", views.RapportsExport.as_view(), name="rapports_export_un"),

    path("agents/", views.AgentListe.as_view(), name="agents"),
    path("agents/nouveau/", views.AgentCreer.as_view(), name="agent_creer"),
    path("agents/<int:pk>/", views.AgentDetail.as_view(), name="agent_detail"),
    path("agents/<int:pk>/modifier/", views.AgentModifier.as_view(), name="agent_modifier"),

    path("ayants-droit/", views.AyantDroitListe.as_view(), name="ayants_droit"),
    path("ayants-droit/nouveau/", views.AyantDroitCreer.as_view(), name="ayant_droit_creer"),
    path("ayants-droit/export/", views.AyantDroitExport.as_view(), name="ayant_droit_export"),
    path("ayants-droit/importer/", views.AyantDroitImport.as_view(), name="ayant_droit_import"),
    path("ayants-droit/<int:pk>/", views.AyantDroitModifier.as_view(), name="ayant_droit_modifier"),
    path("ayants-droit/<int:pk>/<str:decision>/", views.AyantDroitVerifier.as_view(), name="ayant_droit_verifier"),

    path("prescriptions/", views.PrescriptionListe.as_view(), name="prescriptions"),
    path("prescriptions/nouvelle/", views.PrescriptionCreer.as_view(), name="prescription_creer"),
    path("recherche/agents/", views.RechercheAgents.as_view(), name="recherche_agents"),
    path("recherche/agents/<int:pk>/ayants-droit/", views.AyantsDroitDeLAgent.as_view(), name="recherche_ayants_droit"),
    path("prescriptions/<int:pk>/", views.PrescriptionDetail.as_view(), name="prescription_detail"),
    path("prescriptions/<int:pk>/statut/", views.PrescriptionChangerStatut.as_view(), name="prescription_statut"),

    path("factures/", views.FactureListe.as_view(), name="factures"),
    path("factures/nouvelle/", views.FactureCreer.as_view(), name="facture_creer"),
    path("factures/<int:pk>/", views.FactureDetail.as_view(), name="facture_detail"),
    path("factures/<int:pk>/rapprocher/", views.FactureRapprocher.as_view(), name="facture_rapprocher"),
    path("factures/<int:pk>/valider/", views.FactureValider.as_view(), name="facture_valider"),
    path("factures/<int:pk>/contester/", views.FactureContester.as_view(), name="facture_contester"),

    path("prestataires/", views.PrestataireListe.as_view(), name="prestataires"),
    path("prestataires/nouveau/", views.PrestataireCreer.as_view(), name="prestataire_creer"),
    path("prestataires/<int:pk>/", views.PrestataireModifier.as_view(), name="prestataire_modifier"),
    path("prestataires/<int:pk>/statut/", views.PrestataireBasculerStatut.as_view(), name="prestataire_statut"),

    path("utilisateurs/", views.UtilisateurListe.as_view(), name="utilisateurs"),
    path("utilisateurs/nouveau/", views.UtilisateurCreer.as_view(), name="utilisateur_creer"),
    path("utilisateurs/export/", views.UtilisateurExport.as_view(), name="utilisateur_export"),
    path("utilisateurs/importer/", views.UtilisateurImport.as_view(), name="utilisateur_import"),
    path("utilisateurs/<int:pk>/", views.UtilisateurModifier.as_view(), name="utilisateur_modifier"),
    path("utilisateurs/<int:pk>/mot-de-passe/", views.UtilisateurMotDePasse.as_view(), name="utilisateur_mot_de_passe"),

    path("parametrage/", views.ParametrageModifier.as_view(), name="parametrage"),

    path("bareme/", views.BaremeListe.as_view(), name="bareme"),
    path("bareme/nouvelle/", views.BaremeCreer.as_view(), name="bareme_creer"),
    path("bareme/<int:pk>/", views.BaremeModifier.as_view(), name="bareme_modifier"),

    path("natures-de-soin/", views.NatureSoinListe.as_view(), name="natures"),
    path("natures-de-soin/nouvelle/", views.NatureSoinCreer.as_view(), name="nature_creer"),
    path("natures-de-soin/<int:pk>/", views.NatureSoinModifier.as_view(), name="nature_modifier"),
]
