"""Rapports d'activité de la mutuelle.

Ces rapports répondent à une question différente de celle des anomalies : ils
servent à **piloter**, pas à détecter. Ils décrivent ce que la mutuelle a
réellement produit sur une période — combien d'actes, pour qui, chez qui, à
quel coût, et en combien de temps le service a traité les dossiers.

Comme pour les anomalies, chaque rapport renvoie une liste de dictionnaires :
l'écran et l'export CSV lisent la même fonction.
"""
from calendar import monthrange
from collections import Counter
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
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
    # Estimation : calculée à la saisie, elle peut encore baisser si un
    # dossier en attente est rejeté ou corrigé.
    part_mutuelle_en_attente = (
        toutes.filter(statut__in=(StatutPrescription.SOUMISE, StatutPrescription.EN_CONTROLE)).aggregate(
            total=Sum("montant_rembourse")
        )["total"]
        or 0
    )

    return {
        "nombre_actes": nombre,
        "nombre_agents_consommateurs": toutes.values("agent").distinct().count(),
        "nombre_agents_actifs": Agent.objects.filter(actif=True).count(),
        "cout_total_soins": cout_total,
        "part_mutuelle": part_mutuelle,
        "part_mutuelle_en_attente": part_mutuelle_en_attente,
        # Ce que les agents ont réglé au guichet sur les dossiers validés.
        "part_agents": max(0, cout_valide - part_mutuelle),
        "panier_moyen": round(cout_total / nombre) if nombre else 0,
        "nombre_valides": validees.count(),
        "nombre_rejetes": toutes.filter(statut=StatutPrescription.REJETEE).count(),
        "nombre_en_controle": toutes.filter(statut=StatutPrescription.EN_CONTROLE).count(),
    }


def tranche_frequence(nombre):
    for libelle, mini, maxi in TRANCHES_FREQUENCE:
        if nombre >= mini and (maxi is None or nombre <= maxi):
            return libelle
    return ""


def frequence_par_agent(debut, fin):
    """Nombre d'actes par agent, du plus consommateur au moins consommateur.

    Au-delà du simple compte, chaque ligne porte de quoi l'analyser dans un
    tableur : qui a été soigné (l'agent ou ses ayants droit), chez combien de
    prestataires, où en sont les dossiers, et le poids de l'agent dans
    l'ensemble (part, part cumulée, indice par rapport à la moyenne)."""
    from django.db.models import Max, Min

    lignes = list(
        _prescriptions(debut, fin)
        .values(
            "agent",
            "agent__utilisateur__matricule",
            "agent__utilisateur__nom",
            "agent__utilisateur__prenom",
            "agent__site",
        )
        .annotate(
            nombre=Count("id"),
            montant=Sum("montant_total"),
            actes_agent=Count("id", filter=Q(ayant_droit__isnull=True)),
            actes_ayants_droit=Count("id", filter=Q(ayant_droit__isnull=False)),
            ayants_droit_soignes=Count("ayant_droit", distinct=True),
            prestataires=Count("prestataire", distinct=True),
            part_mutuelle=Sum("montant_rembourse", filter=Q(statut=StatutPrescription.VALIDEE)),
            validees=Count("id", filter=Q(statut=StatutPrescription.VALIDEE)),
            rejetees=Count("id", filter=Q(statut=StatutPrescription.REJETEE)),
            en_attente=Count(
                "id", filter=Q(statut__in=(StatutPrescription.SOUMISE, StatutPrescription.EN_CONTROLE))
            ),
            premier_acte=Min("date_emission"),
            dernier_acte=Max("date_emission"),
        )
        .order_by("-nombre", "-montant", "agent__utilisateur__matricule")
    )
    total_actes = sum(ligne["nombre"] for ligne in lignes)
    total_montant = sum(ligne["montant"] or 0 for ligne in lignes)
    moyenne_actes = total_actes / len(lignes) if lignes else 0

    def part(valeur, total):
        return round(100 * valeur / total, 1) if total else 0.0

    resultats, cumul = [], 0
    for rang, ligne in enumerate(lignes, start=1):
        montant = ligne["montant"] or 0
        cumul += montant
        resultats.append(
            {
                "rang": rang,
                "matricule": ligne["agent__utilisateur__matricule"],
                "agent": f"{ligne['agent__utilisateur__prenom']} {ligne['agent__utilisateur__nom']}".strip(),
                "site": ligne["agent__site"],
                "nombre": ligne["nombre"],
                "actes_agent": ligne["actes_agent"],
                "actes_ayants_droit": ligne["actes_ayants_droit"],
                "ayants_droit_soignes": ligne["ayants_droit_soignes"],
                "prestataires": ligne["prestataires"],
                "tranche": tranche_frequence(ligne["nombre"]),
                # 2,0 = deux fois plus d'actes que l'agent consommateur moyen.
                "indice": round(ligne["nombre"] / moyenne_actes, 2) if moyenne_actes else 0.0,
                "part_actes": part(ligne["nombre"], total_actes),
                "montant": montant,
                "panier_moyen": round(montant / ligne["nombre"]),
                "part_montant": part(montant, total_montant),
                # Lecture « Pareto » : combien d'agents font 80 % du coût.
                "part_montant_cumulee": part(cumul, total_montant),
                "part_mutuelle": ligne["part_mutuelle"] or 0,
                "validees": ligne["validees"],
                "en_attente": ligne["en_attente"],
                "rejetees": ligne["rejetees"],
                "premier_acte": ligne["premier_acte"],
                "dernier_acte": ligne["dernier_acte"],
            }
        )
    return resultats


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


def montants_dus_par_prestataire(debut, fin):
    """Part mutuelle due à chaque prestataire sur la période, en séparant ce
    qui est acquis (validé) de ce qui est encore une estimation (soumis ou en
    contrôle, montant calculé à la saisie et susceptible d'être rejeté ou
    corrigé). Les rejets ne sont pas dus et sont écartés. Les totaux sont
    dans la synthèse (voir activite_globale)."""
    en_attente = Q(statut__in=(StatutPrescription.SOUMISE, StatutPrescription.EN_CONTROLE))
    valide = Q(statut=StatutPrescription.VALIDEE)
    lignes = (
        _prescriptions(debut, fin)
        .exclude(statut=StatutPrescription.REJETEE)
        .values("prestataire__code", "prestataire__nom")
        .annotate(
            actes_valides=Count("id", filter=valide),
            du_valide=Sum("montant_rembourse", filter=valide),
            actes_en_attente=Count("id", filter=en_attente),
            du_en_attente=Sum("montant_rembourse", filter=en_attente),
        )
    )
    resultats = [
        {
            "code": ligne["prestataire__code"],
            "prestataire": ligne["prestataire__nom"],
            "actes_valides": ligne["actes_valides"],
            "du_valide": ligne["du_valide"] or 0,
            "actes_en_attente": ligne["actes_en_attente"],
            "du_en_attente": ligne["du_en_attente"] or 0,
        }
        for ligne in lignes
    ]
    for ligne in resultats:
        ligne["du_estime"] = ligne["du_valide"] + ligne["du_en_attente"]
    resultats.sort(key=lambda ligne: -ligne["du_estime"])
    return resultats


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


def consommation_quotas_par_agent():
    """Quota consommé et restant de chaque agent actif sur le cycle en cours.

    Même règle que la fiche de l'agent (Agent.solde_quota) : seules les
    prescriptions **validées** entament l'enveloppe, à hauteur de la part
    mutuelle, soins des ayants droit compris. Les dossiers encore en attente
    sont montrés à part, avec le solde qu'il resterait s'ils étaient tous
    validés : c'est ce qui permet d'anticiper un dépassement.

    Trié du plus consommé (en %) au moins consommé."""
    from django.db.models import Max

    from anomalies.services import _etat_quotas_agents
    from parametrage.models import Parametrage

    parametres = Parametrage.charger()
    debut, fin = parametres.periode()
    seuil = parametres.seuil_alerte_quota
    en_attente = (StatutPrescription.SOUMISE, StatutPrescription.EN_CONTROLE)
    detail = {
        ligne["agent"]: ligne
        for ligne in Prescription.objects.filter(
            date_emission__gte=debut, date_emission__lte=fin, agent__actif=True
        )
        .values("agent")
        .annotate(
            consomme_agent=Sum(
                "montant_rembourse", filter=Q(statut=StatutPrescription.VALIDEE, ayant_droit__isnull=True)
            ),
            consomme_ayants_droit=Sum(
                "montant_rembourse", filter=Q(statut=StatutPrescription.VALIDEE, ayant_droit__isnull=False)
            ),
            actes_valides=Count("id", filter=Q(statut=StatutPrescription.VALIDEE)),
            attente=Sum("montant_rembourse", filter=Q(statut__in=en_attente)),
            actes_en_attente=Count("id", filter=Q(statut__in=en_attente)),
            dernier_valide=Max("date_emission", filter=Q(statut=StatutPrescription.VALIDEE)),
        )
    }

    resultats = []
    for etat in _etat_quotas_agents():
        agent, quota, solde = etat["agent"], etat["quota"], etat["solde"]
        ligne = detail.get(agent.pk, {})
        consomme = quota - solde
        attente = ligne.get("attente") or 0
        part_consommee = round(100 * consomme / quota, 1) if quota else 0.0
        if consomme == 0:
            etat_quota = "Non entamé"
        elif solde < 0:
            etat_quota = "Dépassé"
        elif quota and 100 * solde / quota <= seuil:
            etat_quota = "Seuil d'alerte atteint"
        elif solde - attente < 0:
            etat_quota = "Dépassement probable (dossiers en attente)"
        else:
            etat_quota = "Dans l'enveloppe"
        composition = ["agent"]
        if etat["avec_conjoint"]:
            composition.append("conjoint")
        if etat["nombre_enfants"]:
            composition.append(f"{etat['nombre_enfants']} enfant(s)")
        resultats.append(
            {
                "matricule": agent.matricule,
                "agent": agent.utilisateur.get_full_name(),
                "site": agent.site,
                "composition": " + ".join(composition),
                "quota_mensuel": etat["quota_mensuel"],
                "quota": quota,
                "consomme": consomme,
                "consomme_agent": ligne.get("consomme_agent") or 0,
                "consomme_ayants_droit": ligne.get("consomme_ayants_droit") or 0,
                "solde": solde,
                "part_consommee": part_consommee,
                # Borné à 0 : au-delà, l'état « Dépassé » et le restant
                # négatif en KMF disent déjà de combien.
                "part_restante": max(0.0, round(100 - part_consommee, 1)) if quota else 0.0,
                "etat": etat_quota,
                "actes_valides": ligne.get("actes_valides") or 0,
                "dernier_valide": ligne.get("dernier_valide"),
                "attente": attente,
                "actes_en_attente": ligne.get("actes_en_attente") or 0,
                "solde_apres_attente": solde - attente,
            }
        )
    resultats.sort(key=lambda r: (-r["part_consommee"], r["matricule"]))
    return resultats


def synthese_quotas(lignes):
    """Chiffres d'ensemble du rapport par agent, pour l'onglet Synthèse."""
    enveloppe = sum(ligne["quota"] for ligne in lignes)
    consomme = sum(ligne["consomme"] for ligne in lignes)
    etats = Counter(ligne["etat"] for ligne in lignes)
    return (
        ("Agents actifs", len(lignes)),
        ("Enveloppe totale du cycle (KMF)", enveloppe),
        ("Consommé (KMF)", consomme),
        ("Restant (KMF)", enveloppe - consomme),
        ("Part consommée (%)", round(100 * consomme / enveloppe, 1) if enveloppe else 0.0),
        ("En attente de validation (KMF)", sum(ligne["attente"] for ligne in lignes)),
        ("Agents ayant dépassé leur quota", etats["Dépassé"]),
        ("Agents au seuil d'alerte", etats["Seuil d'alerte atteint"]),
        ("Agents en dépassement probable", etats["Dépassement probable (dossiers en attente)"]),
        ("Agents n'ayant pas entamé leur quota", etats["Non entamé"]),
    )


def cycle_de_quota():
    """Bornes du cycle de quota en cours, pour les titres d'écran et d'export."""
    from parametrage.models import Parametrage

    return Parametrage.charger().periode()


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


def evolution_recente(nombre_mois=6):
    """Les `nombre_mois` derniers mois, mois courant inclus, même sans aucun
    acte enregistré — contrairement à `evolution_mensuelle`, qui ne renvoie
    que les mois où une prescription existe. Pensé pour un raccourci de
    tableau de bord : un mois sans activité doit apparaître à zéro, pas
    disparaître du graphique."""
    aujourdhui = timezone.localdate()

    cles = []
    reference = aujourdhui.replace(day=1)
    for _ in range(nombre_mois):
        cles.append((reference.year, reference.month))
        reference = (reference - timedelta(days=1)).replace(day=1)
    cles.reverse()

    mois_par_cle = {
        cle: {"mois": f"{cle[1]:02d}/{cle[0]}", "nombre": 0, "montant": 0} for cle in cles
    }

    debut = date(cles[0][0], cles[0][1], 1)
    for ligne in evolution_mensuelle(debut, aujourdhui):
        mois_txt, annee_txt = ligne["mois"].split("/")
        cle = (int(annee_txt), int(mois_txt))
        if cle in mois_par_cle:
            mois_par_cle[cle]["nombre"] = ligne["nombre"]
            mois_par_cle[cle]["montant"] = ligne["montant"]

    for ligne in mois_par_cle.values():
        ligne["panier_moyen"] = round(ligne["montant"] / ligne["nombre"]) if ligne["nombre"] else 0
    return [mois_par_cle[cle] for cle in cles]


def evolution_douze_mois():
    """Tendance du rapport d'activité : toujours les 12 derniers mois, mois
    en cours compris, quelle que soit la période choisie — sur un seul mois,
    une évolution n'aurait qu'une barre."""
    return evolution_recente(12)


def periode_par_defaut():
    """Le mois en cours, du 1er à aujourd'hui : la question la plus
    fréquente. Les autres périodes usuelles sont à un clic (voir
    raccourcis_periode)."""
    aujourdhui = timezone.localdate()
    return aujourdhui.replace(day=1), aujourdhui


def _decaler_mois(premier_du_mois, nombre):
    """Premier jour du mois situé `nombre` mois avant (négatif) ou après."""
    index = premier_du_mois.year * 12 + premier_du_mois.month - 1 + nombre
    return date(index // 12, index % 12 + 1, 1)


def _fin_de_mois(jour):
    return jour.replace(day=monthrange(jour.year, jour.month)[1])


def raccourcis_periode(aujourdhui=None):
    """Périodes proposées en un clic au-dessus du filtre : (clé, libellé,
    début, fin)."""
    aujourdhui = aujourdhui or timezone.localdate()
    debut_mois = aujourdhui.replace(day=1)
    debut_mois_dernier = _decaler_mois(debut_mois, -1)
    debut_trimestre = date(aujourdhui.year, 3 * ((aujourdhui.month - 1) // 3) + 1, 1)
    return [
        ("mois", "Ce mois", debut_mois, aujourdhui),
        ("mois_dernier", "Mois dernier", debut_mois_dernier, _fin_de_mois(debut_mois_dernier)),
        ("trimestre", "Ce trimestre", debut_trimestre, aujourdhui),
        ("annee", "Cette année", date(aujourdhui.year, 1, 1), aujourdhui),
        ("douze_mois", "12 derniers mois", _decaler_mois(debut_mois, -11), aujourdhui),
    ]


def periode_de_comparaison(debut, fin):
    """Même période, un mois plus tôt et à date égale — ou None si la période
    ne tient pas dans un seul mois à partir du 1er (trimestre, intervalle
    libre…), où « le mois précédent » n'a pas de sens.

    Du 1er au 12 novembre → du 1er au 12 octobre : comparer 12 jours à un
    mois entier ferait croire à une baisse. Un mois complet se compare au
    mois précédent complet (30 novembre → 31 octobre)."""
    if debut.day != 1 or (debut.year, debut.month) != (fin.year, fin.month) or fin < debut:
        return None
    debut_precedent = _decaler_mois(debut, -1)
    fin_mois_precedent = _fin_de_mois(debut_precedent)
    if fin == _fin_de_mois(fin):
        return debut_precedent, fin_mois_precedent
    return debut_precedent, debut_precedent.replace(day=min(fin.day, fin_mois_precedent.day))


INDICATEURS_COMPARES = ("nombre_actes", "nombre_agents_consommateurs", "cout_total_soins", "part_mutuelle")


def comparaison(debut, fin, synthese):
    """Variation en % des principaux indicateurs par rapport à la période de
    comparaison. Une variation vaut None quand la période précédente est à
    zéro (un pourcentage n'y aurait aucun sens)."""
    periode = periode_de_comparaison(debut, fin)
    if periode is None:
        return None
    precedente = activite_globale(*periode)
    variations = {}
    for cle in INDICATEURS_COMPARES:
        avant, maintenant = precedente[cle], synthese[cle]
        variations[cle] = {
            "avant": avant,
            "pourcentage": round((maintenant - avant) * 100 / avant) if avant else None,
        }
    return {"debut": periode[0], "fin": periode[1], "variations": variations}


def etat_provisoire(debut, fin, aujourdhui=None):
    """Message à afficher quand les chiffres peuvent encore bouger, sinon "".

    Le rapport classe chaque soin à la date de l'ordonnance : une ordonnance
    déclarée en retard fait encore évoluer le mois en cours, et pendant
    quelques jours le mois précédent."""
    aujourdhui = aujourdhui or timezone.localdate()
    debut_mois = aujourdhui.replace(day=1)
    if fin >= debut_mois:
        if debut == debut_mois and fin == aujourdhui:
            jours = monthrange(aujourdhui.year, aujourdhui.month)[1]
            return (
                f"Mois en cours — jour {aujourdhui.day} sur {jours} : chiffres provisoires, "
                "ils évolueront jusqu'à la fin du mois."
            )
        return "La période inclut le mois en cours : chiffres provisoires."
    if fin >= _decaler_mois(debut_mois, -1) and aujourdhui.day <= 10:
        return (
            "Le mois dernier peut encore recevoir des ordonnances déclarées en retard : "
            "chiffres à confirmer dans quelques jours."
        )
    return ""
