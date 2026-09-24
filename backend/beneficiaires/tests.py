from datetime import date

from django.test import TestCase

from accounts.models import Role, Utilisateur
from beneficiaires.models import (
    Agent,
    AyantDroit,
    LienParente,
    StatutVerification,
    TypeJustificatif,
)
from parametrage.models import Parametrage, TrancheQuota
from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire, TypePrestataire


class BaseFamille(TestCase):
    def setUp(self):
        compte = Utilisateur.objects.create_user("A0001", "x", nom="T", prenom="A", role=Role.AGENT)
        self.agent = Agent.objects.create(
            utilisateur=compte,
            site="Moroni",
            date_naissance=date(1985, 1, 1),
            date_embauche=date(2015, 1, 1),
        )

    def ajouter(self, lien, annees=10, statut=StatutVerification.VALIDE):
        return AyantDroit.objects.create(
            agent=self.agent,
            nom="X",
            prenom="Y",
            lien_parente=lien,
            type_justificatif=TypeJustificatif.ACTE_NAISSANCE,
            justificatif="x.jpg",
            date_naissance=date(date.today().year - annees, 1, 1),
            statut_verification=statut,
        )

    def relire(self):
        return Agent.objects.get(pk=self.agent.pk)


class BaremeQuotaTest(BaseFamille):
    """Le barème est chargé par la migration initiale du paramétrage."""

    def test_agent_seul(self):
        self.assertEqual(self.relire().quota_effectif, 21300)

    def test_avec_conjoint_sans_enfant(self):
        self.ajouter(LienParente.CONJOINT)

        self.assertEqual(self.relire().quota_effectif, 25100)

    def test_un_enfant_sans_conjoint(self):
        self.ajouter(LienParente.ENFANT)

        self.assertEqual(self.relire().quota_effectif, 25100)

    def test_les_tranches_suivent_le_nombre_d_enfants(self):
        attendus = {2: 33700, 3: 37400, 4: 37400, 5: 39300, 6: 39300}
        for nombre in range(1, 7):
            self.ajouter(LienParente.ENFANT)
            if nombre in attendus:
                self.assertEqual(
                    self.relire().quota_effectif, attendus[nombre], msg=f"{nombre} enfants"
                )

    def test_le_bareme_est_modifiable_sans_toucher_au_code(self):
        TrancheQuota.objects.filter(enfants_min=0, enfants_max=0, partenaire="SANS").update(montant=99999)

        self.assertEqual(self.relire().quota_effectif, 99999)

    def test_repli_sur_le_quota_par_defaut_si_aucune_tranche_ne_correspond(self):
        TrancheQuota.objects.all().delete()
        parametres = Parametrage.charger()
        parametres.quota_mensuel_defaut = 12345
        parametres.save()

        self.assertEqual(self.relire().quota_effectif, 12345)


class CompositionCouverteTest(BaseFamille):
    def test_un_ayant_droit_non_valide_ne_compte_pas(self):
        self.ajouter(LienParente.ENFANT, statut=StatutVerification.EN_ATTENTE)
        self.ajouter(LienParente.ENFANT, statut=StatutVerification.REJETE)

        self.assertEqual(self.relire().nombre_enfants, 0)

    def test_un_enfant_au_dela_de_l_age_limite_ne_compte_pas(self):
        """Il n'est plus couvert : il ne doit ni ouvrir de droits, ni être
        facturé à l'agent."""
        self.ajouter(LienParente.ENFANT, annees=25)

        self.assertEqual(self.relire().nombre_enfants, 0)

    def test_un_enfant_sous_la_limite_compte(self):
        self.ajouter(LienParente.ENFANT, annees=17)

        self.assertEqual(self.relire().nombre_enfants, 1)


class CycleQuotaTest(BaseFamille):
    """Le quota du barème se consomme sur un cycle de N mois, puis repart au
    montant plein : le reliquat n'est pas reporté."""

    def setUp(self):
        super().setUp()
        self.prestataire = Prestataire.objects.create(
            type_prestataire=TypePrestataire.PHARMACIE, nom="Pharmacie", taux_prise_en_charge=100
        )

    def regler_cycle(self, mois):
        parametres = Parametrage.charger()
        parametres.duree_cycle_mois = mois
        parametres.save()

    def soigner(self, jour, montant):
        prescription = Prescription(
            agent=self.agent,
            prestataire=self.prestataire,
            numero_ordonnance=f"ORD-{jour}",
            montant_total=montant,
            date_emission=jour,
            justificatif="x.jpg",
        )
        prescription.save()
        prescription.changer_statut(StatutPrescription.VALIDEE)

    def test_l_enveloppe_vaut_le_montant_mensuel_multiplie_par_la_duree(self):
        agent = self.relire()
        mensuel = agent.quota_mensuel

        for duree in (1, 2, 3):
            self.regler_cycle(duree)

            self.assertEqual(self.relire().quota_effectif, mensuel * duree, msg=f"cycle de {duree} mois")

    def test_le_bareme_reste_un_montant_mensuel(self):
        """Changer la durée du cycle ne modifie pas le barème lui-même."""
        self.regler_cycle(3)

        self.assertEqual(self.relire().quota_mensuel, 21300)

    def test_les_cycles_se_calent_sur_l_annee_civile(self):
        self.regler_cycle(2)

        self.assertEqual(
            Parametrage.charger().periode(date(2026, 3, 15)),
            (date(2026, 3, 1), date(2026, 4, 30)),
        )

    def test_un_cycle_de_trois_mois_donne_des_trimestres(self):
        self.regler_cycle(3)

        self.assertEqual(
            Parametrage.charger().periode(date(2026, 5, 9)),
            (date(2026, 4, 1), date(2026, 6, 30)),
        )

    def test_la_consommation_se_cumule_sur_tout_le_cycle(self):
        self.regler_cycle(2)
        self.soigner(date(2026, 3, 10), 10000)
        self.soigner(date(2026, 4, 20), 5000)

        self.assertEqual(self.relire().consommation_periode(date(2026, 4, 25)), 15000)

    def test_le_quota_repart_au_montant_plein_au_cycle_suivant(self):
        """Le reliquat non consommé est perdu, il ne se reporte pas."""
        self.regler_cycle(2)
        self.soigner(date(2026, 3, 10), 10000)
        agent = self.relire()

        self.assertEqual(agent.consommation_periode(date(2026, 5, 2)), 0)
        self.assertEqual(agent.solde_quota(date(2026, 5, 2)), agent.quota_effectif)

    def test_le_renouvellement_tombe_toujours_au_1er_janvier(self):
        self.regler_cycle(3)
        debut, _ = Parametrage.charger().periode(date(2026, 1, 5))

        self.assertEqual(debut, date(2026, 1, 1))


class CotisationTest(BaseFamille):
    def setUp(self):
        super().setUp()
        parametres = Parametrage.charger()
        parametres.cotisation_base = 5000
        parametres.save()

    def test_la_famille_incluse_ne_paie_que_la_base(self):
        """1 conjoint et 3 enfants sont compris dans la base."""
        self.ajouter(LienParente.CONJOINT)
        for _ in range(3):
            self.ajouter(LienParente.ENFANT)

        self.assertEqual(self.relire().cotisation_mensuelle, 5000)

    def test_chaque_enfant_au_dela_est_facture(self):
        for _ in range(5):
            self.ajouter(LienParente.ENFANT)

        self.assertEqual(self.relire().cotisation_mensuelle, 5000 + 2 * 2000)

    def test_chaque_conjoint_au_dela_est_facture(self):
        self.ajouter(LienParente.CONJOINT)
        self.ajouter(LienParente.CONJOINT)

        self.assertEqual(self.relire().cotisation_mensuelle, 5000 + 2000)

    def test_les_montants_sont_parametrables(self):
        parametres = Parametrage.charger()
        parametres.cotisation_base = 1000
        parametres.enfants_inclus = 1
        parametres.cout_enfant_supplementaire = 500
        parametres.save()
        for _ in range(3):
            self.ajouter(LienParente.ENFANT)

        self.assertEqual(self.relire().cotisation_mensuelle, 1000 + 2 * 500)

    def test_le_detail_justifie_le_montant(self):
        for _ in range(4):
            self.ajouter(LienParente.ENFANT)

        detail = self.relire().detail_cotisation

        self.assertEqual(detail[0], ("Cotisation de base", 5000))
        self.assertEqual(sum(montant for _, montant in detail), self.relire().cotisation_mensuelle)
