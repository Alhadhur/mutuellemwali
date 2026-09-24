from rest_framework.permissions import BasePermission


class EstAgent(BasePermission):
    message = "Réservé aux comptes agent."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "AGENT"
            and hasattr(request.user, "agent")
        )
