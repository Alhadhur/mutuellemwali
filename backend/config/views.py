"""Vues techniques rattachées à la configuration du projet."""
from django.http import HttpResponse


def sante(request):
    """Sonde de disponibilité interrogée par l'hébergeur.

    Volontairement sans accès à la base : elle répond à la question « le
    processus répond-il ? ». Y ajouter une requête ferait redémarrer le service
    à chaque incident de base, alors que celle-ci est supervisée séparément.
    """
    return HttpResponse("ok", content_type="text/plain")
