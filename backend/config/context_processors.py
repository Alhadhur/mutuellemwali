from . import menu


def menu_backoffice(request):
    utilisateur = getattr(request, "user", None)
    if utilisateur is None or not utilisateur.is_authenticated:
        return {}
    return {"menu_backoffice": menu.construire(utilisateur, request.path)}
