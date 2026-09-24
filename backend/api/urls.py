from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.MoiView.as_view(), name="api-me"),
    path("agent/profil/", views.AgentProfilView.as_view(), name="api-agent-profil"),
    path("prestataires/", views.PrestataireListView.as_view(), name="api-prestataires"),
    path("natures-de-soin/", views.NatureSoinListView.as_view(), name="api-natures-de-soin"),
    path("prescriptions/", views.PrescriptionListCreateView.as_view(), name="api-prescriptions"),
    path("prescriptions/<int:pk>/", views.PrescriptionDetailView.as_view(), name="api-prescription-detail"),
]
