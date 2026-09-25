"""Menu latéral du back-office, défini une seule fois et rendu par toutes les
pages de `backoffice/templates`.

Ajouter une fonctionnalité = ajouter une `Entree` ci-dessous. Une entrée dont
`url_name` est vide et `disponible` est False s'affiche grisée avec la pastille
« Bientôt », pour annoncer une fonctionnalité prévue au cahier des charges.
"""
from dataclasses import dataclass

from django.urls import reverse

from accounts.models import Role


@dataclass(frozen=True)
class Entree:
    libelle: str
    url_name: str = ""
    icone: str = ""
    roles: tuple[str, ...] = (Role.RH, Role.DIRECTION)
    disponible: bool = True


@dataclass(frozen=True)
class Section:
    titre: str
    entrees: tuple[Entree, ...]


MENU: tuple[Section, ...] = (
    Section(
        "Mon espace",
        (Entree("Mon tableau de bord", "backoffice:mon_tableau_de_bord", "🏠", roles=(Role.AGENT,)),),
    ),
    Section(
        "Pilotage",
        (
            Entree("Tableau de bord", "backoffice:tableau_de_bord", "📊"),
            Entree("Anomalies", "backoffice:anomalies", "🚩"),
            Entree("Rapports d'activité", "backoffice:rapports", "📈"),
        ),
    ),
    Section(
        "Registre",
        (
            Entree("Agents", "backoffice:agents", "👤"),
            Entree("Ayants droit", "backoffice:ayants_droit", "👪"),
            Entree("Utilisateurs", "backoffice:utilisateurs", "🔑", roles=(Role.RH,)),
        ),
    ),
    Section(
        "Remboursements",
        (
            Entree("Prescriptions", "backoffice:prescriptions", "🧾"),
            Entree("Prestataires", "backoffice:prestataires", "🏥"),
            Entree("Factures prestataires", "backoffice:factures", "🧮"),
        ),
    ),
    Section(
        "Configuration",
        (
            Entree("Paramètres de la mutuelle", "backoffice:parametrage", "⚙️", roles=(Role.RH,)),
            Entree("Barème des quotas", "backoffice:bareme", "📐", roles=(Role.RH,)),
            Entree("Natures de soin", "backoffice:natures", "🩺", roles=(Role.RH,)),
        ),
    ),
)


def _accessible(entree: Entree, utilisateur) -> bool:
    """Une entrée annoncée reste visible pour tous ; une entrée réelle n'est
    montrée qu'aux rôles qui peuvent réellement l'ouvrir."""
    if not entree.disponible:
        return True
    return utilisateur.is_superuser or utilisateur.role in entree.roles


def construire(utilisateur, chemin_courant: str) -> list[dict]:
    sections = []
    for section in MENU:
        entrees = []
        for entree in section.entrees:
            if not _accessible(entree, utilisateur):
                continue
            entrees.append(
                {
                    "libelle": entree.libelle,
                    "icone": entree.icone,
                    "url": reverse(entree.url_name) if entree.url_name else "",
                    "disponible": entree.disponible,
                    "active": False,
                }
            )
        if entrees:
            sections.append({"titre": section.titre, "entrees": entrees})

    # Toutes les URLs partagent le préfixe du back-office : seule la plus
    # spécifique qui corresponde est marquée active, sinon le tableau de bord
    # le serait sur chaque page.
    candidates = [
        entree
        for section in sections
        for entree in section["entrees"]
        if entree["url"] and chemin_courant.startswith(entree["url"])
    ]
    if candidates:
        max(candidates, key=lambda entree: len(entree["url"]))["active"] = True

    return sections
