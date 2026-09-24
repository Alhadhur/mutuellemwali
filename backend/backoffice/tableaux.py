"""Définition des tableaux d'anomalies, déclarée une seule fois.

L'écran et l'export lisent cette même définition : ajouter une famille
d'anomalies ou une colonne se fait ici, et les deux suivent. C'est le même
parti pris que le menu latéral et que les listes du back-office.
"""
from dataclasses import dataclass
from typing import Callable

from anomalies import services
from rapports import services as rapports


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
            "Agents dont l'enveloppe du cycle en cours est presque épuisée. "
            "Lecture sur le cycle courant, indépendamment de la période choisie."
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
            ("Matricule", "matricule"),
            ("Agent", "agent"),
            ("Site", "site"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
        ),
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
        description="Volume et coût par mois, pour lire une tendance plutôt qu'un instantané.",
        source=rapports.evolution_mensuelle,
        colonnes=(
            ("Mois", "mois"),
            ("Actes", "nombre"),
            ("Coût total (KMF)", "montant"),
            ("Panier moyen (KMF)", "panier_moyen"),
        ),
    ),
)

RAPPORTS_PAR_CLE = {tableau.cle: tableau for tableau in RAPPORTS}
