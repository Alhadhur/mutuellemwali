"""Détection d'anomalies : agrégations partagées par le tableau de bord, la
page Anomalies et les exports.

Les seuils ne sont plus écrits en dur : ils viennent de `Parametrage`, pour que
le service mutuelle règle la sensibilité sans intervention technique.

Chaque famille d'anomalies expose la même forme — une liste de dictionnaires —
afin que l'écran et l'export lisent la **même** fonction. Une seule source, donc
pas de risque que le fichier exporté raconte autre chose que l'écran.
"""
from datetime import date, timedelta
from statistics import mean, pstdev

from django.db.models import Count, Sum

from beneficiaires.models import Agent, AyantDroit
from facturation.models import LigneFacture, StatutLigne
from parametrage.models import Parametrage
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire

# Statuts de ligne de facture qui constituent une anomalie : tout ce qui n'est
# ni concordant ni encore rapproché.
STATUTS_LIGNE_ANORMAUX = (
    StatutLigne.ECART_MONTANT,
    StatutLigne.ECART_TAUX,
    StatutLigne.SANS_PRESCRIPTION,
    StatutLigne.AGENT_INCONNU,
)


def periode_par_defaut():
    """Fenêtre d'analyse paramétrée, bornée à aujourd'hui."""
    fin = date.today()
    debut = fin - timedelta(days=Parametrage.charger().fenetre_analyse_jours)
    return debut, fin


def _bornes(debut=None, fin=None):
    if debut is None or fin is None:
        defaut_debut, defaut_fin = periode_par_defaut()
        debut = debut or defaut_debut
        fin = fin or defaut_fin
    return debut, fin


# --- Familles d'anomalies -------------------------------------------------


def prescriptions_en_controle(debut=None, fin=None):
    """Prescriptions que la détection de doublons a mises de côté.

    Contrairement aux autres familles, la période n'est **pas** appliquée par
    défaut : c'est une file d'attente de travail, et une prescription suspecte
    ne doit pas disparaître de l'écran parce qu'elle a vieilli. Le filtre ne
    s'applique que si l'appelant demande explicitement des bornes.
    """
    queryset = Prescription.objects.filter(statut=StatutPrescription.EN_CONTROLE)
    if debut is not None:
        queryset = queryset.filter(date_emission__gte=debut)
    if fin is not None:
        queryset = queryset.filter(date_emission__lte=fin)
    return queryset.select_related(
        "agent__utilisateur", "prestataire", "ayant_droit", "nature"
    ).order_by("-date_creation")


def pics_de_consommation(debut=None, fin=None):
    """Nombre et montant de prescriptions par jour sur la période."""
    debut, fin = _bornes(debut, fin)
    return list(
        Prescription.objects.filter(date_emission__gte=debut, date_emission__lte=fin)
        .values("date_emission")
        .annotate(nombre=Count("id"), montant=Sum("montant_total"))
        .order_by("date_emission")
    )


def prestataires_volume_anormal(debut=None, fin=None):
    """Prestataires dont le volume dépasse la moyenne du réseau de N
    écarts-types.

    Comparaison **relative** au réseau, et non à un seuil absolu : une pharmacie
    de Moroni et un praticien de Mutsamudu n'ont pas le même volume normal.
    """
    debut, fin = _bornes(debut, fin)
    seuil_ecart_type = float(Parametrage.charger().seuil_volume_ecart_type)

    volumes = list(
        Prescription.objects.filter(date_emission__gte=debut, date_emission__lte=fin)
        .values("prestataire", "prestataire__code", "prestataire__nom")
        .annotate(nombre=Count("id"), montant=Sum("montant_total"))
        .order_by("-nombre")
    )
    if not volumes:
        return []

    valeurs = [v["nombre"] for v in volumes]
    moyenne = mean(valeurs)
    ecart_type = pstdev(valeurs) if len(valeurs) > 1 else 0
    seuil = moyenne + seuil_ecart_type * ecart_type

    for v in volumes:
        v["moyenne_reseau"] = round(moyenne, 1)
        v["anormal"] = v["nombre"] > seuil and ecart_type > 0

    return volumes


def agents_proche_quota(debut=None, fin=None):
    """Agents dont le solde du cycle en cours passe sous le seuil d'alerte.

    La période ne s'applique pas : le quota se lit toujours sur le cycle
    courant, borné par `Parametrage.periode()`.
    """
    seuil_pourcentage = Parametrage.charger().seuil_alerte_quota
    resultats = []
    for agent in Agent.objects.filter(actif=True).select_related("utilisateur"):
        quota = agent.quota_effectif
        if quota <= 0:
            continue
        solde = agent.solde_quota()
        pourcentage_restant = (solde / quota) * 100
        if pourcentage_restant <= seuil_pourcentage:
            resultats.append(
                {
                    "agent": agent,
                    "quota": quota,
                    "consomme": quota - solde,
                    "solde": solde,
                    "pourcentage_restant": round(pourcentage_restant, 1),
                }
            )
    resultats.sort(key=lambda r: r["pourcentage_restant"])
    return resultats


def ayants_droit_justificatif_expire(debut=None, fin=None):
    """Justificatifs périmés. Indépendant de la période : un justificatif
    expiré le reste tant qu'il n'est pas renouvelé."""
    return [
        a
        for a in AyantDroit.objects.select_related("agent__utilisateur").all()
        if a.est_expire and a.statut_verification != "REJETE"
    ]


def ecarts_de_facturation(debut=None, fin=None):
    """Lignes de facture qui ne concordent pas avec les prescriptions déclarées.

    C'est le signal le plus solide du dispositif : il croise **deux sources
    indépendantes** — ce que l'agent déclare et ce que le prestataire facture.
    Vues facture par facture, ces lignes se noient ; agrégées, elles font
    ressortir un prestataire qui dévie systématiquement.
    """
    debut, fin = _bornes(debut, fin)
    return list(
        LigneFacture.objects.filter(
            statut__in=STATUTS_LIGNE_ANORMAUX,
            date_soin__gte=debut,
            date_soin__lte=fin,
        )
        .select_related("facture__prestataire", "prescription")
        .order_by("facture__prestataire__nom", "date_soin")
    )


def synthese_ecarts_par_prestataire(debut=None, fin=None):
    """Les mêmes écarts, regroupés par prestataire : un écart isolé est une
    erreur de saisie, un écart répété est une piste."""
    debut, fin = _bornes(debut, fin)
    lignes = (
        LigneFacture.objects.filter(date_soin__gte=debut, date_soin__lte=fin)
        .select_related("facture__prestataire")
    )

    par_prestataire = {}
    for ligne in lignes:
        prestataire = ligne.facture.prestataire
        bilan = par_prestataire.setdefault(
            prestataire.pk,
            {
                "prestataire": prestataire,
                "lignes_total": 0,
                "lignes_anormales": 0,
                "montant_reclame": 0,
                "surfacturation": 0,
            },
        )
        bilan["lignes_total"] += 1
        bilan["montant_reclame"] += ligne.montant_reclame
        if ligne.statut in STATUTS_LIGNE_ANORMAUX:
            bilan["lignes_anormales"] += 1
            # Seul le trop-réclamé est compté : un prestataire qui réclame
            # moins que son dû n'est pas un problème de fraude.
            bilan["surfacturation"] += max(0, ligne.ecart_taux)

    resultats = [b for b in par_prestataire.values() if b["lignes_anormales"]]
    for bilan in resultats:
        bilan["taux_anomalie"] = round(100 * bilan["lignes_anormales"] / bilan["lignes_total"], 1)
    resultats.sort(key=lambda b: (-b["taux_anomalie"], -b["surfacturation"]))
    return resultats


# --- Indicateurs ----------------------------------------------------------


def indicateurs_globaux():
    return {
        "nb_prestataires_actifs": Prestataire.objects.filter(statut="ACTIF").count(),
        "nb_agents_actifs": Agent.objects.filter(actif=True).count(),
        "nb_prescriptions_en_controle": Prescription.objects.filter(statut=StatutPrescription.EN_CONTROLE).count(),
        "montant_rembourse_total_annee": Prescription.objects.filter(
            statut=StatutPrescription.VALIDEE, date_emission__year=date.today().year
        ).aggregate(total=Sum("montant_rembourse"))["total"]
        or 0,
    }
