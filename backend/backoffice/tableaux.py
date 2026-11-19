"""Définition des tableaux d'anomalies, déclarée une seule fois.

L'écran et l'export lisent cette même définition : ajouter une famille
d'anomalies ou une colonne se fait ici, et les deux suivent. C'est le même
parti pris que le menu latéral et que les listes du back-office.
"""
from dataclasses import dataclass
from typing import Callable

from django.utils.html import format_html

from anomalies import services
from rapports import services as rapports

from .affichage import milliers


@dataclass(frozen=True)
class Tableau:
    cle: str
    titre: str
    description: str
    source: Callable
    colonnes: tuple[tuple[str, object], ...]
    # Certaines familles ne dépendent pas de la période choisie (une file
    # d'attente, un justificatif périmé) : l'écran le signale au lecteur.
    suit_la_periode: bool = True
    # Une famille par agent (fréquence des consultations…) grandit avec
    # l'effectif : l'écran n'en montre que les N premiers (déjà triés par
    # pertinence côté source) et renvoie à l'export pour la liste complète.
    # L'export, lui, ignore toujours cette limite — voir RapportsView.
    limite_ecran: int | None = None
    # Colonnes de l'écran, quand celles de l'export sont trop nombreuses pour
    # tenir dans la fenêtre : regroupées deux à deux (l'info principale, le
    # détail en gris dessous). L'export garde toujours `colonnes`, une valeur
    # par colonne, exploitable dans un tableur.
    colonnes_ecran: tuple[tuple[str, object], ...] | None = None
    # Export en classeur Excel mis en forme (voir exports.reponse_xlsx), le
    # CSV restant disponible avec ?format=csv.
    export_excel: bool = False
    # Colonnes totalisées en bas du classeur (clés des lignes).
    colonnes_totalisees: tuple[str, ...] = ()
    # Sens de chaque colonne, repris dans l'onglet « Synthèse » du classeur.
    definitions: tuple[tuple[str, str], ...] = ()
    # Onglet « Synthèse » du classeur : chiffres propres à ce rapport (suite
    # de (libellé, valeur), calculée à partir des lignes) — à défaut, la
    # synthèse d'activité de la période — et autres rapports joints (clés).
    synthese_export: Callable | None = None
    annexes_export: tuple[str, ...] = ()

    @property
    def colonnes_affichees(self):
        return self.colonnes_ecran or self.colonnes

    def lignes(self, debut, fin):
        return self.source(debut, fin) if self.suit_la_periode else self.source()


def _volumes_anormaux(debut, fin):
    """Seuls les prestataires réellement au-dessus du seuil : la fonction
    sous-jacente renvoie tout le réseau, pour pouvoir afficher la moyenne."""
    return [v for v in services.prestataires_volume_anormal(debut, fin) if v["anormal"]]


TABLEAUX: tuple[Tableau, ...] = (
    Tableau(
        cle="facturation",
        titre="Écarts de facturation",
        description=(
            "Lignes facturées par un prestataire qui ne concordent pas avec les "
            "prescriptions déclarées par les agents. Deux sources indépendantes "
            "qui divergent : c'est le signal le plus solide du dispositif."
        ),
        source=services.ecarts_de_facturation,
        colonnes=(
            ("Prestataire", lambda o: o.facture.prestataire.nom),
            ("Facture", lambda o: o.facture.numero),
            ("Date du soin", "date_soin"),
            ("Matricule", "matricule"),
            ("Bénéficiaire", "nom_beneficiaire"),
            ("Nature déclarée", "nature"),
            ("Coût facturé", "montant_soin"),
            ("Réclamé", "montant_reclame"),
            ("Réclamé attendu", "montant_reclame_attendu"),
            ("Écart de taux", "ecart_taux"),
            ("Anomalie", "get_statut_display"),
        ),
        colonnes_ecran=(
            (
                "Facture",
                lambda o: format_html(
                    '{}<span class="sous-ligne">{}</span>', o.facture.numero, o.facture.prestataire.nom
                ),
            ),
            ("Date du soin", "date_soin"),
            (
                "Agent / bénéficiaire",
                lambda o: format_html('{}<span class="sous-ligne">{}</span>', o.matricule, o.nom_beneficiaire),
            ),
            ("Nature déclarée", "nature"),
            ("Coût facturé", "montant_soin"),
            (
                "Réclamé",
                lambda o: format_html(
                    '{}<span class="sous-ligne insecable">attendu {}</span>',
                    milliers(o.montant_reclame),
                    milliers(o.montant_reclame_attendu),
                ),
            ),
            ("Anomalie", "get_statut_display"),
        ),
    ),
    Tableau(
        cle="prestataires_ecarts",
        titre="Prestataires en écart répété",
        description=(
            "Les mêmes écarts regroupés par prestataire. Un écart isolé est une "
            "erreur de saisie ; un taux d'anomalie élevé sur de nombreuses lignes "
            "est une piste à instruire."
        ),
        source=services.synthese_ecarts_par_prestataire,
        colonnes=(
            ("Prestataire", lambda o: o["prestataire"].nom),
            ("Code", lambda o: o["prestataire"].code),
            ("Lignes facturées", "lignes_total"),
            ("Lignes en anomalie", "lignes_anormales"),
            ("Taux d'anomalie (%)", "taux_anomalie"),
            ("Total réclamé (KMF)", "montant_reclame"),
            ("Dont surfacturation (KMF)", "surfacturation"),
        ),
    ),
    Tableau(
        cle="controle",
        titre="Prescriptions en contrôle",
        description=(
            "Prescriptions mises de côté par la détection de doublons et en "
            "attente d'une décision humaine."
        ),
        source=services.prescriptions_en_controle,
        suit_la_periode=False,
        colonnes=(
            ("N° ordonnance", "numero_ordonnance"),
            ("Matricule", lambda o: o.agent.matricule),
            ("Bénéficiaire", lambda o: str(o.beneficiaire())),
            ("Prestataire", lambda o: o.prestataire.nom),
            ("Nature", lambda o: o.nature.libelle if o.nature_id else ""),
            ("Coût du soin (KMF)", "montant_total"),
            ("Date d'émission", "date_emission"),
            ("Motif du signalement", "motif_signalement"),
        ),
    ),
    Tableau(
        cle="volumes",
        titre="Prestataires au volume anormal",
        description=(
            "Prestataires dont le nombre de prescriptions dépasse nettement la "
            "moyenne du réseau sur la période. La comparaison est relative au "
            "réseau, pas à un seuil absolu."
        ),
        source=_volumes_anormaux,
        colonnes=(
            ("Code", "prestataire__code"),
            ("Prestataire", "prestataire__nom"),
            ("Prescriptions", "nombre"),
            ("Moyenne du réseau", "moyenne_reseau"),
            ("Montant total (KMF)", "montant"),
        ),
    ),
    Tableau(
        cle="quota",
        titre="Agents proches de leur quota",
        description=(
            "Agents dont l'enveloppe du cycle en cours est presque épuisée, sans "
            "toutefois être dépassée (voir « Agents ayant dépassé leur quota » "
            "pour ceux-là). Lecture sur le cycle courant, indépendamment de la "
            "période choisie."
        ),
        source=services.agents_proche_quota,
        suit_la_periode=False,
        colonnes=(
            ("Matricule", lambda o: o["agent"].matricule),
            ("Agent", lambda o: o["agent"].utilisateur.get_full_name()),
            ("Site", lambda o: o["agent"].site),
            ("Enveloppe du cycle (KMF)", "quota"),
            ("Consommé (KMF)", "consomme"),
            ("Solde (KMF)", "solde"),
            ("Reste (%)", "pourcentage_restant"),
        ),
    ),
    Tableau(
        cle="quota_depasse",
        titre="Agents ayant dépassé leur quota",
        description=(
            "Agents dont la consommation du cycle en cours excède l'enveloppe "
            "disponible (solde négatif) — un signal plus grave qu'une simple "
            "approche du seuil. Lecture sur le cycle courant, indépendamment de "
            "la période choisie."
        ),
        source=services.agents_depasse_quota,
        suit_la_periode=False,
        colonnes=(
            ("Matricule", lambda o: o["agent"].matricule),
            ("Agent", lambda o: o["agent"].utilisateur.get_full_name()),
            ("Site", lambda o: o["agent"].site),
            ("Enveloppe du cycle (KMF)", "quota"),
            ("Consommé (KMF)", "consomme"),
            ("Dépassement (KMF)", "depassement"),
        ),
    ),
    Tableau(
        cle="justificatifs",
        titre="Justificatifs expirés",
        description=(
            "Ayants droit dont la pièce justificative a dépassé sa date de "
            "validité. Un justificatif périmé le reste tant qu'il n'est pas "
            "renouvelé : la période ne s'applique pas."
        ),
        source=services.ayants_droit_justificatif_expire,
        suit_la_periode=False,
        colonnes=(
            ("Matricule agent", lambda o: o.agent.matricule),
            ("Ayant droit", lambda o: f"{o.prenom} {o.nom}"),
            ("Lien", "get_lien_parente_display"),
            ("Type de justificatif", "get_type_justificatif_display"),
            ("Validité échue le", "date_validite"),
            ("Statut de vérification", "get_statut_verification_display"),
        ),
    ),
)

PAR_CLE = {tableau.cle: tableau for tableau in TABLEAUX}


# --- Rapports d'activité ---------------------------------------------------
# Même structure que les anomalies, pour un besoin différent : décrire
# l'activité de la mutuelle plutôt que signaler ce qui cloche.

RAPPORTS: tuple[Tableau, ...] = (
    Tableau(
        cle="frequence",
        titre="Fréquence des consultations par agent",
        description=(
            "Nombre d'actes de chaque agent sur la période, du plus consommateur "
            "au moins consommateur. Lecture de pilotage, mais aussi première piste "
            "quand un agent se détache nettement du reste."
        ),
        source=rapports.frequence_par_agent,
        colonnes=(
            ("Rang", "rang"),
            ("Matricule", "matricule"),
            ("Agent", "agent"),
            ("Site", "site"),
            ("Actes", "nombre"),
            ("dont l'agent", "actes_agent"),
            ("dont ayants droit", "actes_ayants_droit"),
            ("Ayants droit soignés", "ayants_droit_soignes"),
            ("Prestataires différents", "prestataires"),
            ("Tranche d'assiduité", "tranche"),
            ("Indice / moyenne", "indice"),
            ("Part des actes (%)", "part_actes"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
            ("Part du coût (%)", "part_montant"),
            ("Part du coût cumulée (%)", "part_montant_cumulee"),
            ("Part mutuelle validée (KMF)", "part_mutuelle"),
            ("Validés", "validees"),
            ("En attente", "en_attente"),
            ("Rejetés", "rejetees"),
            ("Premier acte", "premier_acte"),
            ("Dernier acte", "dernier_acte"),
        ),
        colonnes_ecran=(
            ("Matricule", "matricule"),
            ("Agent", "agent"),
            ("Site", "site"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
        ),
        export_excel=True,
        colonnes_totalisees=(
            "nombre", "actes_agent", "actes_ayants_droit", "montant", "part_mutuelle",
            "validees", "en_attente", "rejetees",
        ),
        definitions=(
            ("Rang", "Classement par nombre d'actes, puis par coût."),
            ("Actes", "Prescriptions de la période, quel que soit leur statut (rejets compris)."),
            ("dont l'agent / dont ayants droit", "Qui a été soigné : l'agent lui-même, ou son conjoint et ses enfants."),
            ("Ayants droit soignés", "Nombre de personnes différentes de la famille soignées."),
            ("Prestataires différents", "Nombre d'établissements consultés : un chiffre élevé peut signaler un « nomadisme » médical."),
            ("Tranche d'assiduité", "Même découpage que l'onglet Synthèse."),
            ("Indice / moyenne", "Actes de l'agent ÷ moyenne des agents consommateurs. 2,00 = deux fois plus que la moyenne."),
            ("Part des actes / du coût (%)", "Poids de l'agent dans l'ensemble de la période."),
            ("Part du coût cumulée (%)", "Lecture Pareto : en filtrant ≤ 80, on voit combien d'agents font 80 % du coût."),
            ("Part mutuelle validée", "Remboursement des seuls dossiers validés."),
            ("Validés / En attente / Rejetés", "État des dossiers ; « en attente » regroupe soumis et en contrôle."),
        ),
        annexes_export=("distribution",),
        limite_ecran=20,
    ),
    Tableau(
        cle="distribution",
        titre="Répartition des agents par assiduité",
        description=(
            "Combien d'agents dans chaque tranche d'actes. Le classement dit qui "
            "consulte le plus ; cette répartition dit si la consommation est étalée "
            "sur l'effectif ou concentrée sur quelques dossiers."
        ),
        source=rapports.distribution_frequence,
        colonnes=(
            ("Tranche", "tranche"),
            ("Agents", "agents"),
            ("Part de l'effectif (%)", "part"),
        ),
    ),
    Tableau(
        cle="nature",
        titre="Répartition par nature de soin",
        description=(
            "Ce que couvre réellement la mutuelle, par type de prestation. Les "
            "prescriptions antérieures à la mise en place du champ apparaissent "
            "sous « Non renseignée »."
        ),
        source=rapports.consommation_par_nature,
        colonnes=(
            ("Nature du soin", "nature"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
            ("Part du coût (%)", "part"),
        ),
    ),
    Tableau(
        cle="prestataires",
        titre="Consommation par prestataire",
        description=(
            "Volume et poids de chaque prestataire dans le réseau. Base utile "
            "au moment de renégocier une convention."
        ),
        source=rapports.consommation_par_prestataire,
        colonnes=(
            ("Code", "code"),
            ("Prestataire", "prestataire"),
            ("Type", "type"),
            ("Ville", "ville"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
            ("Part du réseau (%)", "part_reseau"),
        ),
    ),
    Tableau(
        cle="montants_dus",
        titre="Montants dus aux prestataires",
        description=(
            "Part mutuelle à régler à chaque prestataire. « Validé » est acquis ; "
            "« En attente » (soumis ou en contrôle) est une estimation calculée à la "
            "saisie, qui peut encore baisser si une prescription est rejetée ou "
            "corrigée. Les prescriptions rejetées ne sont pas comptées."
        ),
        source=rapports.montants_dus_par_prestataire,
        colonnes=(
            ("Prestataire", "prestataire"),
            ("Actes validés", "actes_valides"),
            ("Dû validé", "du_valide"),
            ("Actes en attente", "actes_en_attente"),
            ("Dû en attente", "du_en_attente"),
            ("Total estimé", "du_estime"),
        ),
    ),
    Tableau(
        cle="regions",
        titre="Consommation par région et par site",
        description="Où se consomme la couverture, et par combien d'agents.",
        source=rapports.consommation_par_region,
        colonnes=(
            ("Région", "region"),
            ("Site", "site"),
            ("Agents concernés", "agents"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
        ),
    ),
    Tableau(
        cle="beneficiaires",
        titre="Agent ou ayants droit",
        description="Part de la consommation revenant à l'agent lui-même, et part revenant à sa famille.",
        source=rapports.repartition_agent_ayants_droit,
        colonnes=(
            ("Bénéficiaire", "beneficiaire"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Part (%)", "part"),
        ),
    ),
    Tableau(
        cle="quotas",
        titre="Utilisation des quotas",
        description=(
            "Répartition des agents selon la part d'enveloppe consommée sur le "
            "cycle en cours. Dit si le barème est bien calibré. Indépendant de "
            "la période choisie."
        ),
        source=rapports.utilisation_des_quotas,
        suit_la_periode=False,
        colonnes=(
            ("Tranche de consommation", "tranche"),
            ("Agents", "agents"),
            ("Part de l'effectif (%)", "part"),
        ),
    ),
    Tableau(
        cle="quotas_agents",
        titre="Consommation des quotas par agent",
        description=(
            "Pour chaque agent actif : enveloppe du cycle en cours, part consommée "
            "par les prescriptions validées (soins des ayants droit compris) et "
            "solde restant, du plus consommé au moins consommé. Les dossiers en "
            "attente sont montrés à part, avec le solde après leur validation."
        ),
        source=rapports.consommation_quotas_par_agent,
        suit_la_periode=False,
        limite_ecran=20,
        colonnes=(
            ("Matricule", "matricule"),
            ("Agent", "agent"),
            ("Site", "site"),
            ("Famille couverte", "composition"),
            ("Quota mensuel (KMF)", "quota_mensuel"),
            ("Enveloppe du cycle (KMF)", "quota"),
            ("Consommé (KMF)", "consomme"),
            ("dont l'agent (KMF)", "consomme_agent"),
            ("dont ayants droit (KMF)", "consomme_ayants_droit"),
            ("Restant (KMF)", "solde"),
            ("Consommé (%)", "part_consommee"),
            ("Restant (%)", "part_restante"),
            ("État", "etat"),
            ("Actes validés", "actes_valides"),
            ("Dernier acte validé", "dernier_valide"),
            ("En attente de validation (KMF)", "attente"),
            ("Dossiers en attente", "actes_en_attente"),
            ("Restant si tout est validé (KMF)", "solde_apres_attente"),
        ),
        colonnes_ecran=(
            ("Agent", lambda o: format_html('{}<span class="sous-ligne">{}</span>', o["agent"], o["matricule"])),
            ("Enveloppe (KMF)", "quota"),
            ("Consommé (KMF)", "consomme"),
            ("Restant (KMF)", "solde"),
            ("Consommé (%)", "part_consommee"),
            ("En attente (KMF)", "attente"),
            ("État", "etat"),
        ),
        export_excel=True,
        colonnes_totalisees=(
            "quota", "consomme", "consomme_agent", "consomme_ayants_droit", "solde",
            "actes_valides", "attente", "actes_en_attente", "solde_apres_attente",
        ),
        synthese_export=lambda lignes: rapports.synthese_quotas(lignes),
        annexes_export=("quotas",),
        definitions=(
            ("Famille couverte", "Ayants droit vérifiés et encore couverts, qui fixent la tranche du barème."),
            ("Enveloppe du cycle", "Quota mensuel du barème × durée du cycle ; partagée par toute la famille."),
            ("Consommé", "Part mutuelle des prescriptions validées du cycle, soins des ayants droit compris."),
            ("Restant", "Enveloppe − consommé. Négatif : quota dépassé."),
            ("État", "Non entamé, Dans l'enveloppe, Seuil d'alerte atteint (restant sous le seuil du paramétrage), "
                     "Dépassé, ou Dépassement probable si les dossiers en attente étaient validés."),
            ("En attente de validation", "Part mutuelle estimée des dossiers soumis ou en contrôle : ne compte pas "
                                         "encore dans le consommé."),
            ("Restant si tout est validé", "Restant − en attente : le solde à prévoir."),
        ),
    ),
    Tableau(
        cle="service",
        titre="Activité du service mutuelle",
        description=(
            "Dossiers traités, taux de rejet et délai moyen entre la soumission "
            "et la décision. Ce rapport mesure le travail du service, pas celui "
            "des agents."
        ),
        source=rapports.activite_du_service,
        colonnes=(
            ("Traité par", "utilisateur"),
            ("Dossiers traités", "traitees"),
            ("Validés", "validees"),
            ("Rejetés", "rejetees"),
            ("Taux de rejet (%)", "taux_rejet"),
            ("Délai moyen (jours)", "delai_moyen_jours"),
        ),
    ),
    Tableau(
        cle="evolution",
        titre="Évolution mois par mois",
        description=(
            "Volume et coût des 12 derniers mois, mois en cours compris, pour lire une tendance "
            "plutôt qu'un instantané."
        ),
        source=rapports.evolution_douze_mois,
        suit_la_periode=False,
        colonnes=(
            ("Mois", "mois"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
        ),
    ),
)

RAPPORTS_PAR_CLE = {tableau.cle: tableau for tableau in RAPPORTS}
