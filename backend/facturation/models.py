"""Factures mensuelles des prestataires conventionnés.

L'intérêt de ces factures n'est pas comptable mais de contrôle : confrontée aux
prescriptions déclarées, une facture fait ressortir trois anomalies que rien
d'autre ne révèle —

* une ligne facturée **sans prescription** : le prestataire facture un soin que
  personne n'a déclaré ;
* une prescription **non facturée** : l'agent a déclaré un soin que le
  prestataire ne réclame pas, cas typique de la fausse ordonnance ;
* un **écart de montant** entre ce qui est déclaré et ce qui est facturé.
"""
import unicodedata
from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone

from prescriptions.models import Prescription, StatutPrescription
from prestataires.models import Prestataire


def _mots_normalises(texte):
    """Ensemble des mots d'un nom, insensible aux accents et à la casse —
    sert à comparer deux noms indépendamment de l'ordre (« Nom Prénom » vs
    « Prénom Nom »)."""
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte or "") if not unicodedata.combining(c))
    return set(sans_accents.lower().split())

def _noms_correspondent(nom_facture, nom_attendu):
    """Voir LigneFacture.beneficiaire_correspond : un nom vide ne contredit
    rien, et l'un des deux noms peut n'être qu'une partie de l'autre."""
    mots_factures = _mots_normalises(nom_facture)
    mots_attendus = _mots_normalises(nom_attendu)
    if not mots_factures or not mots_attendus:
        return True
    return mots_factures <= mots_attendus or mots_attendus <= mots_factures


def _apparier(lignes, prescriptions):
    """Associe les lignes d'un même agent et d'une même date à ses
    prescriptions de ce jour-là, chacune servant au plus une fois.

    Toutes les paires possibles sont classées, puis retenues de la plus sûre
    à la moins sûre — le résultat ne dépend donc pas de l'ordre des lignes :
    1. même bénéficiaire (l'agent ou tel ayant droit) — l'identité du patient
       compte plus qu'un montant mal reporté ;
    2. montant exact ;
    3. prescription encore en jeu avant une prescription rejetée ;
    4. montant le plus proche.
    Retourne {pk de ligne: prescription}."""
    paires = []
    for ligne in lignes:
        for prescription in prescriptions:
            paires.append(
                (
                    not _noms_correspondent(ligne.nom_beneficiaire, prescription.nom_beneficiaire),
                    prescription.montant_total != ligne.montant_soin,
                    prescription.statut == StatutPrescription.REJETEE,
                    abs(prescription.montant_total - ligne.montant_soin),
                    ligne.pk,
                    prescription.pk,
                    ligne,
                    prescription,
                )
            )
    paires.sort(key=lambda paire: paire[:6])

    attributions, prises = {}, set()
    for *_, ligne, prescription in paires:
        if ligne.pk in attributions or prescription.pk in prises:
            continue
        attributions[ligne.pk] = prescription
        prises.add(prescription.pk)
    return attributions


MOIS = [
    (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"),
    (5, "Mai"), (6, "Juin"), (7, "Juillet"), (8, "Août"),
    (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
]


class StatutFacture(models.TextChoices):
    RECUE = "RECUE", "Reçue"
    RAPPROCHEE = "RAPPROCHEE", "Rapprochée"
    VALIDEE = "VALIDEE", "Validée"
    CONTESTEE = "CONTESTEE", "Contestée"


class StatutLigne(models.TextChoices):
    A_RAPPROCHER = "A_RAPPROCHER", "À rapprocher"
    CONCORDANTE = "CONCORDANTE", "Concordante"
    ECART_MONTANT = "ECART_MONTANT", "Écart de montant"
    ECART_TAUX = "ECART_TAUX", "Taux mal appliqué"
    SANS_PRESCRIPTION = "SANS_PRESCRIPTION", "Aucune prescription déclarée"
    AGENT_INCONNU = "AGENT_INCONNU", "Matricule inconnu"
    NATURE_NON_COUVERTE = "NATURE_NON_COUVERTE", "Nature non couverte par ce prestataire"
    BENEFICIAIRE_DIFFERENT = "BENEFICIAIRE_DIFFERENT", "Bénéficiaire différent de la prescription"
    PRESCRIPTION_REJETEE = "PRESCRIPTION_REJETEE", "Prescription rejetée par la mutuelle"


class Facture(models.Model):
    prestataire = models.ForeignKey(Prestataire, on_delete=models.PROTECT, related_name="factures")
    numero = models.CharField(max_length=60, verbose_name="N° de facture")
    mois = models.PositiveSmallIntegerField(choices=MOIS, verbose_name="Mois facturé")
    annee = models.PositiveSmallIntegerField(verbose_name="Année")

    date_reception = models.DateField(default=timezone.localdate)
    montant_total_declare = models.PositiveIntegerField(
        verbose_name="Total réclamé à la mutuelle (KMF)",
        help_text="Total figurant sur la facture ; comparé à la somme réclamée sur les lignes.",
    )
    fichier = models.FileField(upload_to="factures/", blank=True)

    statut = models.CharField(max_length=20, choices=StatutFacture.choices, default=StatutFacture.RECUE)
    commentaire = models.TextField(blank=True)

    saisie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures_saisies"
    )
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="factures_validees"
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Facture prestataire"
        verbose_name_plural = "Factures prestataires"
        ordering = ["-annee", "-mois", "prestataire"]
        constraints = [
            models.UniqueConstraint(
                fields=["prestataire", "numero"], name="numero_facture_unique_par_prestataire"
            )
        ]

    def __str__(self):
        return f"{self.numero} — {self.prestataire.nom} ({self.get_mois_display()} {self.annee})"

    @property
    def montant_total_lignes(self):
        return self.lignes.aggregate(models.Sum("montant_reclame"))["montant_reclame__sum"] or 0

    @property
    def ecart_total(self):
        """Différence entre le total annoncé et la somme réelle des lignes."""
        return self.montant_total_declare - self.montant_total_lignes

    def ids_doublons(self):
        """Lignes qui en répètent une autre (même matricule, date,
        bénéficiaire et montants) — la première occurrence n'est pas comptée,
        seules ses copies le sont."""
        vues, copies = set(), set()
        for ligne in self.lignes.order_by("pk"):
            cle = ligne.cle_doublon()
            if cle in vues:
                copies.add(ligne.pk)
            vues.add(cle)
        return copies

    def explication_ecart(self):
        """Décompose l'écart entre le total annoncé et la somme des lignes.

        Le total seul ne désigne aucune ligne : on isole ce qui l'explique
        (corrections faites depuis la réception, copies probables) et ce qui
        reste — ligne manquante, ou total de l'en-tête mal saisi."""
        lignes = list(self.lignes.all())
        doublons = self.ids_doublons()
        somme = sum(ligne.montant_reclame for ligne in lignes)
        somme_initiale = sum(
            ligne.montant_reclame if ligne.montant_reclame_initial is None else ligne.montant_reclame_initial
            for ligne in lignes
        )
        corrigees = [ligne for ligne in lignes if ligne.montants_corriges]
        montant_doublons = sum(ligne.montant_reclame for ligne in lignes if ligne.pk in doublons)
        ecart = self.montant_total_declare - somme
        reste = ecart + montant_doublons
        return {
            "ecart": ecart,
            "somme_initiale": somme_initiale,
            "ecart_initial": self.montant_total_declare - somme_initiale,
            "nombre_corrigees": len(corrigees),
            "effet_corrections": somme - somme_initiale,
            "nombre_doublons": len(doublons),
            "montant_doublons": montant_doublons,
            # Ce qui resterait si les copies probables étaient retirées.
            "reste": reste,
        }

    @property
    def periode(self):
        from calendar import monthrange

        return date(self.annee, self.mois, 1), date(self.annee, self.mois, monthrange(self.annee, self.mois)[1])

    def prescriptions_de_la_periode(self):
        debut, fin = self.periode
        return Prescription.objects.filter(
            prestataire=self.prestataire, date_emission__gte=debut, date_emission__lte=fin
        ).select_related("agent__utilisateur", "ayant_droit")

    def prescriptions_non_facturees(self):
        """Soins déclarés par les agents que le prestataire ne facture pas.

        C'est l'anomalie la plus grave : elle peut révéler une ordonnance
        fabriquée de toutes pièces."""
        rapprochees = self.lignes.exclude(prescription__isnull=True).values_list("prescription_id", flat=True)
        # Une prescription rejetée qui n'est pas facturée est dans l'ordre
        # des choses : elle ne doit pas grossir cette alerte.
        return (
            self.prescriptions_de_la_periode()
            .exclude(pk__in=rapprochees)
            .exclude(statut=StatutPrescription.REJETEE)
        )

    def rapprocher(self):
        """Confronte chaque ligne aux prescriptions de la période.

        N'écrit aucun statut de prescription : le rapprochement éclaire la
        décision, il ne la prend pas.

        Les lignes sont appariées par groupe (même agent, même date), et non
        une par une dans l'ordre de la facture : sinon une ligne en écart
        saisie avant une ligne exacte lui prenait sa prescription, et l'agent
        et son ayant droit soignés le même jour se trouvaient croisés."""
        from collections import defaultdict

        from beneficiaires.models import Agent

        agents = {}
        groupes = defaultdict(list)
        for ligne in self.lignes.all():
            cle_matricule = ligne.matricule.strip().upper()
            if cle_matricule not in agents:
                agents[cle_matricule] = Agent.objects.filter(utilisateur__matricule__iexact=cle_matricule).first()
            agent = agents[cle_matricule]
            if not agent:
                ligne.prescription = None
                ligne.statut = StatutLigne.AGENT_INCONNU
                ligne.save()
                continue
            groupes[(agent.pk, ligne.date_soin)].append(ligne)

        prescriptions = defaultdict(list)
        for prescription in self.prescriptions_de_la_periode():
            prescriptions[(prescription.agent_id, prescription.date_emission)].append(prescription)

        for cle, lignes in groupes.items():
            attributions = _apparier(lignes, prescriptions.get(cle, []))
            for ligne in lignes:
                ligne.prescription = attributions.get(ligne.pk)
                ligne.statut = self._statut_apres_rapprochement(ligne)
                ligne.save()

        self.statut = StatutFacture.RAPPROCHEE
        self.save()

    def _statut_apres_rapprochement(self, ligne):
        prescription = ligne.prescription
        if prescription is None:
            return StatutLigne.SANS_PRESCRIPTION
        if prescription.statut == StatutPrescription.REJETEE:
            # Le prestataire facture un soin que la mutuelle a refusé de
            # prendre en charge : à arbitrer, jamais à valider d'office.
            return StatutLigne.PRESCRIPTION_REJETEE
        if not self.prestataire.propose_nature(ligne.nature):
            # Le prestataire a des tarifs détaillés mais aucun ne correspond
            # à cette nature : il facture un soin qu'il n'est pas censé
            # proposer — plus grave qu'un simple écart de montant ou de taux.
            return StatutLigne.NATURE_NON_COUVERTE
        if not ligne.beneficiaire_correspond():
            # Matricule et date concordent, mais le nom écrit par le
            # prestataire ne désigne pas le même bénéficiaire :
            # potentiellement le mauvais ayant droit, ou pire.
            return StatutLigne.BENEFICIAIRE_DIFFERENT
        if prescription.montant_total == ligne.montant_soin:
            # Le coût du soin concorde : reste à vérifier que le prestataire
            # ne réclame pas plus que son taux ne l'autorise.
            return StatutLigne.CONCORDANTE if ligne.ecart_taux == 0 else StatutLigne.ECART_TAUX
        return StatutLigne.ECART_MONTANT

    def synthese(self):
        lignes = self.lignes.all()
        return {
            "nombre_lignes": lignes.count(),
            "concordantes": lignes.filter(statut=StatutLigne.CONCORDANTE).count(),
            "ecarts_montant": lignes.filter(statut=StatutLigne.ECART_MONTANT).count(),
            "ecarts_taux": lignes.filter(statut=StatutLigne.ECART_TAUX).count(),
            "sans_prescription": lignes.filter(statut=StatutLigne.SANS_PRESCRIPTION).count(),
            "agents_inconnus": lignes.filter(statut=StatutLigne.AGENT_INCONNU).count(),
            "prescriptions_rejetees": lignes.filter(statut=StatutLigne.PRESCRIPTION_REJETEE).count(),
            "natures_non_couvertes": lignes.filter(statut=StatutLigne.NATURE_NON_COUVERTE).count(),
            "beneficiaires_differents": lignes.filter(statut=StatutLigne.BENEFICIAIRE_DIFFERENT).count(),
            "non_facturees": self.prescriptions_non_facturees().count(),
            "ecart_total": self.ecart_total,
        }

    def resume_rapprochement(self):
        """Résultat du rapprochement en une phrase, toutes catégories de
        lignes comprises (seules celles qui comptent au moins une ligne sont
        citées) : leur somme fait le nombre de lignes de la facture."""
        synthese = self.synthese()
        categories = [
            (synthese["concordantes"], "concordante(s)"),
            (synthese["ecarts_montant"], "écart(s) de montant"),
            (synthese["ecarts_taux"], "taux mal appliqué(s)"),
            (synthese["sans_prescription"], "sans prescription"),
            (synthese["agents_inconnus"], "matricule(s) inconnu(s)"),
            (synthese["beneficiaires_differents"], "bénéficiaire(s) différent(s)"),
            (synthese["natures_non_couvertes"], "nature(s) non couverte(s) par ce prestataire"),
            (synthese["prescriptions_rejetees"], "prescription(s) rejetée(s) facturée(s)"),
        ]
        detail = ", ".join(f"{nombre} {libelle}" for nombre, libelle in categories if nombre)
        return (
            f"{synthese['nombre_lignes']} ligne(s) — {detail or 'aucune ligne'}. "
            f"Côté mutuelle : {synthese['non_facturees']} prescription(s) déclarée(s) non facturée(s)."
        )

    def lignes_concordantes_en_controle(self):
        """Lignes concordantes que la validation de la facture laisse de
        côté, faute d'avoir levé l'alerte de leur prescription."""
        return self.lignes.filter(
            statut=StatutLigne.CONCORDANTE, prescription__statut=StatutPrescription.EN_CONTROLE
        )

    def lignes_concordantes_a_valider(self):
        """Lignes concordantes dont la prescription attend encore une
        décision : ce que « Valider » (ligne ou lot) fera passer en
        « Validée »."""
        return self.lignes.filter(
            statut=StatutLigne.CONCORDANTE, prescription__statut=StatutPrescription.SOUMISE
        ).select_related("prescription")

    def valider_concordantes(self, utilisateur, lignes=None):
        """Valide les prescriptions des lignes concordantes — toutes, ou
        seulement `lignes` — sans clôturer la facture : le reste (écarts,
        lignes sans prescription) peut continuer d'être traité, puis validé
        à son tour quand il concorde.

        Seules les prescriptions encore « Soumise » sont concernées : une
        prescription rejetée n'est jamais revalidée par une facture (le rejet
        est une décision de la mutuelle, la facture ne la renverse pas), et
        une prescription « En contrôle » porte une alerte (doublon, agent
        suspendu, couverture…) que la facture ne lève pas — elle se traite
        sur sa fiche (voir lignes_concordantes_en_controle)."""
        a_valider = self.lignes_concordantes_a_valider()
        if lignes is not None:
            a_valider = a_valider.filter(pk__in=[ligne.pk for ligne in lignes])
        validees = 0
        for ligne in a_valider:
            ligne.prescription.changer_statut(
                StatutPrescription.VALIDEE,
                utilisateur=utilisateur,
                commentaire=f"Confirmée par la facture {self.numero} du prestataire.",
            )
            validees += 1
        return validees

    def valider(self, utilisateur):
        """Le service mutuelle valide et clôt la facture : les prescriptions
        des lignes concordantes encore à valider passent en « Validée »
        (mêmes règles que valider_concordantes), puis la facture est
        verrouillée. Les lignes en écart ne valident rien."""
        validees = self.valider_concordantes(utilisateur)
        self.statut = StatutFacture.VALIDEE
        self.validee_par = utilisateur
        self.date_validation = timezone.now()
        self.save()
        return validees


class LigneFacture(models.Model):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name="lignes")

    date_soin = models.DateField()
    matricule = models.CharField(max_length=20, help_text="Matricule de l'agent, tel qu'indiqué sur la facture.")
    nom_beneficiaire = models.CharField(max_length=150)
    nature = models.CharField(max_length=255, verbose_name="Nature du soin")

    montant_soin = models.PositiveIntegerField(
        verbose_name="Coût total du soin (KMF)",
        help_text="Les 100 % : part agent comprise.",
    )
    montant_reclame = models.PositiveIntegerField(
        verbose_name="Montant réclamé à la mutuelle (KMF)",
        help_text="La part prise en charge, soit le coût total × taux du prestataire.",
    )

    prescription = models.ForeignKey(
        Prescription, on_delete=models.SET_NULL, null=True, blank=True, related_name="lignes_facture"
    )
    statut = models.CharField(max_length=30, choices=StatutLigne.choices, default=StatutLigne.A_RAPPROCHER)
    commentaire = models.TextField(blank=True)

    # Montants tels que reçus (import ou première saisie) : une correction
    # ultérieure ne doit pas effacer ce que le prestataire a réellement
    # facturé — c'est ce qui permet d'expliquer l'écart avec le total annoncé.
    montant_soin_initial = models.PositiveIntegerField(null=True, blank=True, editable=False)
    montant_reclame_initial = models.PositiveIntegerField(null=True, blank=True, editable=False)
    corrigee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lignes_facture_corrigees", editable=False,
    )
    corrigee_le = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"
        ordering = ["date_soin", "matricule"]

    def __str__(self):
        return f"{self.date_soin} — {self.matricule} — {self.montant_soin} KMF"

    def save(self, *args, **kwargs):
        if self.montant_soin_initial is None:
            self.montant_soin_initial = self.montant_soin
        if self.montant_reclame_initial is None:
            self.montant_reclame_initial = self.montant_reclame
        super().save(*args, **kwargs)

    @property
    def correction_reclame(self):
        """Variation du montant réclamé due aux corrections (0 si aucune)."""
        if self.montant_reclame_initial is None:
            return 0
        return self.montant_reclame - self.montant_reclame_initial

    @property
    def montants_corriges(self):
        return self.corrigee_le is not None and (
            self.montant_reclame != self.montant_reclame_initial
            or self.montant_soin != self.montant_soin_initial
        )

    def cle_doublon(self):
        """Deux lignes de même clé dans une facture désignent probablement le
        même soin facturé deux fois."""
        return (
            self.matricule.strip().upper(),
            self.date_soin,
            frozenset(_mots_normalises(self.nom_beneficiaire)),
            self.montant_soin,
            self.montant_reclame,
        )

    def motif_verrouillage(self):
        """Pourquoi la ligne ne peut plus être corrigée ni supprimée — chaîne
        vide si elle le peut encore.

        Une facture validée est close : ses lignes sont la trace de la
        décision. Une ligne concordante dont la prescription est déjà
        « Validée » a servi de preuve à cette validation (valider_concordantes) :
        la changer effacerait la justification d'une décision déjà prise.
        """
        if self.facture.statut == StatutFacture.VALIDEE:
            return "la facture est validée"
        if (
            self.statut == StatutLigne.CONCORDANTE
            and self.prescription_id
            and self.prescription.statut == StatutPrescription.VALIDEE
        ):
            return "elle a servi à valider la prescription " + self.prescription.numero_ordonnance
        return ""

    def remettre_a_rapprocher(self):
        """Après une correction, l'ancien résultat du rapprochement ne vaut
        plus : la ligne repart « À rapprocher », sans prescription liée."""
        self.statut = StatutLigne.A_RAPPROCHER
        self.prescription = None

    @property
    def ecart_montant(self):
        if not self.prescription:
            return None
        return self.montant_soin - self.prescription.montant_total

    @property
    def montant_reclame_attendu(self):
        """Ce que le prestataire devrait réclamer, au taux applicable.

        Le taux suit celui de la prescription rapprochée (tarif détaillé pour
        sa nature de soin s'il existe, sinon taux général du prestataire —
        voir Prestataire.taux_pour). Sans prescription rapprochée, c'est la
        nature écrite sur la ligne qui donne le taux — la même que pour
        déduire le montant manquant à la saisie ou à l'import.
        """
        from decimal import ROUND_HALF_UP, Decimal

        prestataire = self.facture.prestataire
        if self.prescription_id and self.prescription.nature_id:
            taux = prestataire.taux_pour(self.prescription.nature)
        else:
            # Sans prescription (ou prescription historique sans nature) :
            # la nature écrite sur la ligne, comme lors de sa saisie.
            taux = prestataire.taux_pour_libelle(self.nature)
        montant = Decimal(self.montant_soin) * taux / Decimal("100")
        return int(montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def ecart_taux(self):
        return self.montant_reclame - self.montant_reclame_attendu

    def beneficiaire_correspond(self):
        """Le nom écrit par le prestataire désigne-t-il bien le bénéficiaire
        de la prescription rapprochée ? Sans prescription liée, rien à
        comparer — le rapprochement ne connaît alors aucun bénéficiaire de
        référence.

        En pratique, les prestataires n'écrivent souvent que le nom **ou**
        le prénom, jamais les deux : exiger une égalité stricte des mots
        signalerait presque toutes les lignes en « faux » écart. On accepte
        donc qu'un des deux noms soit un sous-ensemble de l'autre (tous ses
        mots se retrouvent dans l'autre nom) — un nom qui introduit un mot
        absent de l'autre reste, lui, un vrai désaccord."""
        if not self.prescription_id:
            return True
        return _noms_correspondent(self.nom_beneficiaire, self.prescription.nom_beneficiaire)
