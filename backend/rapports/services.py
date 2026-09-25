"""Rapports d'activité de la mutuelle.

Ces rapports répondent à une question différente de celle des anomalies : ils
servent à **piloter**, pas à détecter. Ils décrivent ce que la mutuelle a
réellement produit sur une période — combien d'actes, pour qui, chez qui, à
quel coût, et en combien de temps le service a traité les dossiers.

Comme pour les anomalies, chaque rapport renvoie une liste de dictionnaires :
l'écran et l'export CSV lisent la même fonction.
"""
from collections import Counter
from datetime import date, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from beneficiaires.models import Agent
from prescriptions.models import HistoriqueStatut, Prescription, StatutPrescription
from prestataires.models import TypePrestataire

# Tranches d'assiduité : un agent qui consulte deux fois dans le mois n'a rien
# d'anormal, un agent qui consulte dix fois mérite un regard.
TRANCHES_FREQUENCE = (
    ("Aucun acte", 0, 0),
    ("1 à 2 actes", 1, 2),
    ("3 à 5 actes", 3, 5),
    ("6 à 9 actes", 6, 9),
    ("10 actes et plus", 10, None),
)


def _prescriptions(debut, fin, validees_seulement=False):
    """Base commune à tous les rapports.

    Par défaut, **toutes** les prescriptions de la période sont comptées :
    l'activité du service inclut ce qu'il a rejeté. Les rapports financiers
    passent `validees_seulement` pour ne mesurer que l'argent réellement engagé.
    """
    queryset = Prescription.objects.filter(date_emission__gte=debut, date_emission__lte=fin)
    if validees_seulement:
        queryset = queryset.filter(statut=StatutPrescription.VALIDEE)
    return queryset


def activite_globale(debut, fin):
    """La photo de la période, en une poignée de chiffres."""
    toutes = _prescriptions(debut, fin)
    validees = _prescriptions(debut, fin, validees_seulement=True)

    cout_total = toutes.aggregate(total=Sum("montant_total"))["total"] or 0
    part_mutuelle = validees.aggregate(total=Sum("montant_rembourse"))["total"] or 0
    cout_valide = validees.aggregate(total=Sum("montant_total"))["total"] or 0
    nombre = toutes.count()

    return {
        "nombre_actes": nombre,
        "nombre_agents_consommateurs": toutes.values("agent").distinct().count(),
        "nombre_agents_actifs": Agent.objects.filter(actif=True).count(),
        "cout_total_soins": cout_total,
        "part_mutuelle": part_mutuelle,
        # Ce que les agents ont réglé au guichet sur les dossiers validés.
        "part_agents": max(0, cout_valide - part_mutuelle),
        "panier_moyen": round(cout_total / nombre) if nombre else 0,
        "nombre_valides": validees.count(),
        "nombre_rejetes": toutes.filter(statut=StatutPrescription.REJETEE).count(),
        "nombre_en_controle": toutes.filter(statut=StatutPrescription.EN_CONTROLE).count(),
    }


def frequence_par_agent(debut, fin):
    """Nombre d'actes par agent, du plus consommateur au moins consommateur."""
    lignes = (
        _prescriptions(debut, fin)
        .values(
            "agent",
            "agent__utilisateur__matricule",
            "agent__utilisateur__nom",
            "agent__utilisateur__prenom",
            "agent__site",
        )
        .annotate(nombre=Count("id"), montant=Sum("montant_total"))
        .order_by("-nombre", "-montant")
    )
    return [
        {
            "matricule": ligne["agent__utilisateur__matricule"],
            "agent": f"{ligne['agent__utilisateur__prenom']} {ligne['agent__utilisateur__nom']}".strip(),
            "site": ligne["agent__site"],
            "nombre": ligne["nombre"],
            "montant": ligne["montant"] or 0,
            "panier_moyen": round((ligne["montant"] or 0) / ligne["nombre"]),
        }
        for ligne in lignes
    ]


def distribution_frequence(debut, fin):
    """Répartition des agents par tranche d'assiduité.

    Le classement par agent dit *qui* consulte le plus ; cette distribution dit
    si la consommation est étalée sur l'effectif ou concentrée sur quelques-uns.
    C'est cette seconde lecture qui alerte.
    """
    actes_par_agent = Counter(
        {ligne["agent"]: ligne["nombre"] for ligne in _prescriptions(debut, fin).values("agent").annotate(nombre=Count("id"))}
    )
    agents_actifs = set(Agent.objects.filter(actif=True).values_list("pk", flat=True))
    # Les agents sans aucun acte n'apparaissent pas dans les prescriptions :
    # sans cette ligne, la tranche « aucun acte » serait toujours vide.
    for pk in agents_actifs:
        actes_par_agent.setdefault(pk, 0)

    total_agents = len(actes_par_agent) or 1
    resultats = []
    for libelle, mini, maxi in TRANCHES_FREQUENCE:
        effectif = sum(
            1 for nombre in actes_par_agent.values() if nombre >= mini and (maxi is None or nombre <= maxi)
        )
        resultats.append(
            {
                "tranche": libelle,
                "agents": effectif,
                "part": round(100 * effectif / total_agents, 1),
            }
        )
    return resultats


def consommation_par_prestataire(debut, fin):
    lignes = (
        _prescriptions(debut, fin)
        .values("prestataire__code", "prestataire__nom", "prestataire__type_prestataire", "prestataire__ville")
        .annotate(nombre=Count("id"), montant=Sum("montant_total"))
        .order_by("-montant")
    )
    total = sum(ligne["montant"] or 0 for ligne in lignes) or 1
    libelles = dict(TypePrestataire.choices)
    return [
        {
            "code": ligne["prestataire__code"],
            "prestataire": ligne["prestataire__nom"],
            "type": libelles.get(ligne["prestataire__type_prestataire"], ""),
            "ville": ligne["prestataire__ville"],
            "nombre": ligne["nombre"],
            "montant": ligne["montant"] or 0,
            "panier_moyen": round((ligne["montant"] or 0) / ligne["nombre"]),
            "part_reseau": round(100 * (ligne["montant"] or 0) / total, 1),
        }
        for ligne in lignes
    ]


def consommation_par_nature(debut, fin):
    """Répartition par type de soin.

    Les prescriptions reprises d'un historique antérieur à la mise en place du
    champ n'ont pas de nature : elles sont regroupées sous « Non renseignée »
    plutôt que d'être écartées, pour que les totaux restent justes.
    """
    lignes = (
        _prescriptions(debut, fin)
        .values("nature__libelle")
        .annotate(nombre=Count("id"), montant=Sum("montant_total"))
        .order_by("-montant")
    )
    total = sum(ligne["montant"] or 0 for ligne in lignes) or 1
    return [
        {
            "nature": ligne["nature__libelle"] or "Non renseignée",
            "nombre": ligne["nombre"],
            "montant": ligne["montant"] or 0,
            "panier_moyen": round((ligne["montant"] or 0) / ligne["nombre"]),
            "part": round(100 * (ligne["montant"] or 0) / total, 1),
        }
        for ligne in lignes
    ]


def consommation_par_region(debut, fin):
    lignes = (
        _prescriptions(debut, fin)
        .values("agent__site", "agent__utilisateur__region")
        .annotate(nombre=Count("id"), montant=Sum("montant_total"), agents=Count("agent", distinct=True))
        .order_by("-montant")
    )
    return [
        {
            "region": ligne["agent__utilisateur__region"] or "Non renseignée",
            "site": ligne["agent__site"] or "Non renseigné",
            "agents": ligne["agents"],
            "nombre": ligne["nombre"],
            "montant": ligne["montant"] or 0,
        }
        for ligne in lignes
    ]


def repartition_agent_ayants_droit(debut, fin):
    """Ce que consomment les agents eux-mêmes, par rapport à leurs ayants droit."""
    base = _prescriptions(debut, fin)
    agent_seul = base.filter(ayant_droit__isnull=True).aggregate(nombre=Count("id"), montant=Sum("montant_total"))
    familles = base.filter(ayant_droit__isnull=False).aggregate(nombre=Count("id"), montant=Sum("montant_total"))

    total = (agent_seul["montant"] or 0) + (familles["montant"] or 0) or 1
    return [
        {
            "beneficiaire": "L'agent lui-même",
            "nombre": agent_seul["nombre"],
            "montant": agent_seul["montant"] or 0,
            "part": round(100 * (agent_seul["montant"] or 0) / total, 1),
        },
        {
            "beneficiaire": "Ayants droit",
            "nombre": familles["nombre"],
            "montant": familles["montant"] or 0,
            "part": round(100 * (familles["montant"] or 0) / total, 1),
        },
    ]


def utilisation_des_quotas(debut=None, fin=None):
    """Répartition des agents selon la part d'enveloppe consommée.

    Dit si le barème est calibré : beaucoup d'agents sous 25 % suggère des
    quotas trop larges, une majorité au-delà de 75 % l'inverse.
    """
    tranches = (("0 %", 0, 0), ("1 à 25 %", 1, 25), ("26 à 50 %", 26, 50),
                ("51 à 75 %", 51, 75), ("76 à 100 %", 76, 100), ("Au-delà de 100 %", 101, None))
    compteurs = {libelle: 0 for libelle, _, _ in tranches}

    agents = list(Agent.objects.filter(actif=True).select_related("utilisateur"))
    for agent in agents:
        quota = agent.quota_effectif
        if quota <= 0:
            continue
        consomme = round(100 * agent.consommation_periode() / quota)
        for libelle, mini, maxi in tranches:
            if consomme >= mini and (maxi is None or consomme <= maxi):
                compteurs[libelle] += 1
                break

    total = sum(compteurs.values()) or 1
    return [
        {"tranche": libelle, "agents": compteurs[libelle], "part": round(100 * compteurs[libelle] / total, 1)}
        for libelle, _, _ in tranches
    ]


def activite_du_service(debut, fin):
    """Ce que le service mutuelle a traité, et en combien de temps.

    Le délai se lit dans l'historique horodaté : entre la soumission et le
    premier passage à un statut définitif. Ce rapport mesure le travail du
    service, pas celui des agents.
    """
    decisions = (
        HistoriqueStatut.objects.filter(
            nouveau_statut__in=(StatutPrescription.VALIDEE, StatutPrescription.REJETEE),
            date_changement__date__gte=debut,
            date_changement__date__lte=fin,
        )
        .select_related("prescription", "utilisateur")
        .order_by("date_changement")
    )

    par_agent_traitant = {}
    for decision in decisions:
        cle = decision.utilisateur_id
        bilan = par_agent_traitant.setdefault(
            cle,
            {
                "utilisateur": decision.utilisateur.get_full_name() if decision.utilisateur else "Automatique / non tracé",
                "validees": 0,
                "rejetees": 0,
                "delais": [],
            },
        )
        if decision.nouveau_statut == StatutPrescription.VALIDEE:
            bilan["validees"] += 1
        else:
            bilan["rejetees"] += 1
        delai = (decision.date_changement.date() - decision.prescription.date_creation.date()).days
        bilan["delais"].append(max(0, delai))

    resultats = []
    for bilan in par_agent_traitant.values():
        traitees = bilan["validees"] + bilan["rejetees"]
        resultats.append(
            {
                "utilisateur": bilan["utilisateur"],
                "traitees": traitees,
                "validees": bilan["validees"],
                "rejetees": bilan["rejetees"],
                "taux_rejet": round(100 * bilan["rejetees"] / traitees, 1) if traitees else 0,
                "delai_moyen_jours": round(sum(bilan["delais"]) / len(bilan["delais"]), 1) if bilan["delais"] else 0,
            }
        )
    resultats.sort(key=lambda r: -r["traitees"])
    return resultats


def evolution_mensuelle(debut, fin):
    """Volume et coût mois par mois, pour lire une tendance."""
    lignes = (
        _prescriptions(debut, fin)
        .values("date_emission__year", "date_emission__month")
        .annotate(nombre=Count("id"), montant=Sum("montant_total"))
        .order_by("date_emission__year", "date_emission__month")
    )
    return [
        {
            "mois": f"{ligne['date_emission__month']:02d}/{ligne['date_emission__year']}",
            "nombre": ligne["nombre"],
            "montant": ligne["montant"] or 0,
            "panier_moyen": round((ligne["montant"] or 0) / ligne["nombre"]),
        }
        for ligne in lignes
    ]


def periode_par_defaut():
    """Les douze derniers mois : une activité se lit sur une saison complète,
    pas sur la fenêtre courte utilisée pour la détection d'anomalies."""
    fin = timezone.localdate()
    return fin - timedelta(days=365), fin
