"""Service des fichiers déposés (justificatifs, photos, factures).

En développement, Django sert `MEDIA_ROOT` sans contrôle : n'importe qui
connaissant l'URL peut ouvrir une ordonnance. C'est acceptable sur un poste
isolé, pas sur un serveur exposé — il s'agit de données de santé et d'état
civil.

Cette vue remplace ce service brut : elle exige une session, puis vérifie que
le demandeur a le droit de voir **ce fichier précis**. Un agent n'accède qu'aux
pièces de son propre dossier ; le service mutuelle et la direction accèdent à
tout, ce que leur métier suppose.

À l'échelle du projet (quelques milliers d'agents), faire transiter les fichiers
par Django est sans conséquence. Sur une volumétrie bien supérieure, il faudrait
passer à des URL signées à durée limitée servies par un stockage objet.
"""
from pathlib import PurePosixPath

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.views import View

from accounts.models import Role


def _appartient_a_l_agent(utilisateur, chemin):
    """Le fichier fait-il partie du dossier de cet agent ?

    La recherche porte sur le chemin stocké en base plutôt que sur le nom du
    fichier : deux agents peuvent déposer une pièce portant le même nom.
    """
    from beneficiaires.models import AyantDroit
    from prescriptions.models import Prescription

    agent = getattr(utilisateur, "agent", None)
    if agent is None:
        return False

    if Prescription.objects.filter(agent=agent, justificatif=chemin).exists():
        return True
    if AyantDroit.objects.filter(agent=agent).filter(justificatif=chemin).exists():
        return True
    if AyantDroit.objects.filter(agent=agent).filter(photo=chemin).exists():
        return True
    return utilisateur.photo and utilisateur.photo.name == chemin


class FichierProtege(LoginRequiredMixin, View):
    """Sert un fichier de `MEDIA_ROOT` après contrôle des droits."""

    def get(self, request, chemin):
        from django.conf import settings

        # Un chemin remontant l'arborescence permettrait de lire n'importe quel
        # fichier du serveur : on le rejette avant toute autre chose.
        chemin_relatif = PurePosixPath(chemin)
        if chemin_relatif.is_absolute() or ".." in chemin_relatif.parts:
            raise Http404

        utilisateur = request.user
        autorise = (
            utilisateur.is_superuser
            or utilisateur.role in (Role.RH, Role.DIRECTION)
            or _appartient_a_l_agent(utilisateur, str(chemin_relatif))
        )
        if not autorise:
            # 404 plutôt que 403 : répondre « interdit » confirmerait
            # l'existence du fichier à qui essaie des URL au hasard.
            raise Http404

        fichier = (settings.MEDIA_ROOT if isinstance(settings.MEDIA_ROOT, str) else str(settings.MEDIA_ROOT))
        chemin_complet = PurePosixPath(fichier) / chemin_relatif
        try:
            return FileResponse(open(chemin_complet, "rb"))
        except FileNotFoundError:
            raise Http404
