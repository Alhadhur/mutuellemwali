"""Back-office métier : écrans de consultation et de saisie propres au projet,
en remplacement des pages génériques de l'admin Django.

Les listes partagent un même template piloté par `colonnes` : chaque entrée est
soit un nom d'attribut/méthode du modèle, soit un appelable recevant l'objet.
"""

from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from accounts.models import Role, Utilisateur
from beneficiaires.models import Agent, AyantDroit, LienParente, StatutVerification, TypeJustificatif
from facturation.models import Facture, StatutFacture
from parametrage.models import NatureSoin, Parametrage, TrancheQuota
from prescriptions.models import STATUTS_MANUELS, Prescription, StatutPrescription
from prestataires.models import Prestataire, StatutPrestataire, TarifPrestataire

from . import exports, forms, imports, tableaux


def valeur(objet, source):
    if callable(source):
        return source(objet)
    attribut = getattr(objet, source)
    return attribut() if callable(attribut) else attribut


class AccesBackoffice(LoginRequiredMixin, UserPassesTestMixin):
    """Consultation réservée au service mutuelle (RH) et à la direction."""

    def test_func(self):
        utilisateur = self.request.user
        return utilisateur.is_authenticated and (
            utilisateur.role in (Role.RH, Role.DIRECTION) or utilisateur.is_superuser
        )


class AccesModification(AccesBackoffice):
    """La direction consulte ; seul le service mutuelle modifie."""

    def test_func(self):
        utilisateur = self.request.user
        return utilisateur.is_authenticated and (
            utilisateur.role == Role.RH or utilisateur.is_superuser
        )


class AccesAgent(LoginRequiredMixin, UserPassesTestMixin):
    """Le tableau de bord agent, réservé à l'intéressé — pas de fiche Agent,
    pas d'accès (même règle que EstAgent côté API mobile)."""

    def test_func(self):
        utilisateur = self.request.user
        return utilisateur.is_authenticated and utilisateur.role == Role.AGENT and hasattr(utilisateur, "agent")


class ListeBase(AccesBackoffice, ListView):
    template_name = "backoffice/liste.html"
    paginate_by = 25
    titre = ""
    colonnes = ()
    url_creation = ""
    url_detail = ""
    url_export = ""
    url_import = ""
    libelle_creation = ""
    champs_recherche = ()

    def get_queryset(self):
        queryset = super().get_queryset()
        recherche = self.request.GET.get("recherche", "").strip()
        if recherche and self.champs_recherche:
            filtre = Q()
            for champ in self.champs_recherche:
                filtre |= Q(**{f"{champ}__icontains": recherche})
            queryset = queryset.filter(filtre)
        return queryset

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = self.titre
        contexte["entetes"] = [libelle for libelle, _ in self.colonnes]
        contexte["lignes"] = [
            {
                "objet": objet,
                "cellules": [valeur(objet, source) for _, source in self.colonnes],
                "url": reverse(self.url_detail, args=[objet.pk]) if self.url_detail else "",
            }
            for objet in contexte["object_list"]
        ]
        contexte["url_creation"] = reverse(self.url_creation) if self.url_creation else ""
        contexte["url_export"] = reverse(self.url_export) if self.url_export else ""
        contexte["url_import"] = reverse(self.url_import) if self.url_import else ""
        contexte["libelle_creation"] = self.libelle_creation
        contexte["recherche"] = self.request.GET.get("recherche", "")
        contexte["avec_recherche"] = bool(self.champs_recherche)
        contexte["peut_modifier"] = self.request.user.role == Role.RH or self.request.user.is_superuser
        # Reste des filtres (hors pagination), pour que « page suivante » ne
        # perde pas ce que la barre de filtres avait posé.
        parametres = self.request.GET.copy()
        parametres.pop("page", None)
        contexte["querystring_filtres"] = parametres.urlencode()
        return contexte


def styliser(form):
    """Pose les classes CSS sur les widgets depuis un point unique, plutôt que
    de les répéter dans chaque formulaire."""
    for champ in form.fields.values():
        widget = champ.widget
        if isinstance(widget, django_forms.CheckboxInput):
            classe = "controle-case"
        elif isinstance(widget, django_forms.ClearableFileInput):
            classe = "controle-fichier"
        elif isinstance(widget, django_forms.Select):
            classe = "controle controle-liste"
        else:
            classe = "controle"
        widget.attrs["class"] = f"{widget.attrs.get('class', '')} {classe}".strip()
    return form


class FormulaireBase(AccesModification):
    template_name = "backoffice/formulaire.html"
    titre = ""

    def get_form(self, form_class=None):
        return styliser(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = self.titre
        contexte["url_retour"] = self.success_url
        return contexte

    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, f"{self.titre} : enregistrement effectué.")
        return reponse


class ImportCSVBase(AccesModification, TemplateView):
    """Import CSV en deux temps : aperçu (transaction annulée), puis
    confirmation (transaction conservée) à partir du même fichier, gardé en
    session entre les deux requêtes.

    Une sous-classe déclare `colonnes_attendues` et `importer_ligne`, qui
    retourne `(objet, cree)` ou lève `imports.LigneInvalide` — même contrat
    que les commandes manage.py `importer_*`.
    """

    template_name = "backoffice/import.html"
    titre = ""
    aide = ""
    colonnes_attendues = frozenset()
    alias = {}
    url_liste = ""
    cle_session = ""

    def importer_ligne(self, ligne):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = self.titre
        contexte["aide"] = self.aide
        contexte["url_retour"] = reverse(self.url_liste)
        contexte.setdefault("form", styliser(forms.ImportCSVForm()))
        return contexte

    def post(self, request, *args, **kwargs):
        if request.POST.get("confirmer"):
            return self._confirmer(request)
        return self._analyser(request)

    def _analyser(self, request):
        form = styliser(forms.ImportCSVForm(request.POST, request.FILES))
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        contenu = request.FILES["fichier"].read().decode("utf-8-sig")
        rapport = imports.executer(
            contenu, self.colonnes_attendues, self.importer_ligne, ecrire=False, alias=self.alias
        )
        if not rapport["erreurs"]:
            request.session[self.cle_session] = contenu
        return self.render_to_response(self.get_context_data(rapport=rapport))

    def _confirmer(self, request):
        contenu = request.session.pop(self.cle_session, None)
        if not contenu:
            messages.error(request, "Le fichier analysé a expiré : réimportez-le.")
            return redirect(self.url_liste)

        rapport = imports.executer(
            contenu, self.colonnes_attendues, self.importer_ligne, ecrire=True, alias=self.alias
        )
        if rapport["erreurs"]:
            messages.error(request, "Le fichier a changé entre l'analyse et la confirmation : réimportez-le.")
            return redirect(self.url_liste)

        messages.success(
            request, f"{self.titre} : {rapport['crees']} création(s), {rapport['maj']} mise(s) à jour."
        )
        return redirect(self.url_liste)


# --- Mon profil -------------------------------------------------------------
# Accessible à tout utilisateur connecté, quel que soit son rôle : contrairement
# aux écrans « Utilisateurs », ce n'est pas de l'administration, on n'agit que
# sur son propre compte (matricule, rôle et activation restent en lecture seule).


class MonProfil(LoginRequiredMixin, UpdateView):
    model = Utilisateur
    form_class = forms.MonProfilForm
    template_name = "backoffice/formulaire.html"
    titre = "Mon profil"
    success_url = reverse_lazy("backoffice:mon_profil")

    def get_object(self, queryset=None):
        return self.request.user

    def get_form(self, form_class=None):
        return styliser(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = self.titre
        contexte["url_retour"] = self.success_url
        contexte["url_mon_mot_de_passe"] = reverse("backoffice:mon_mot_de_passe")
        return contexte

    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, "Profil mis à jour.")
        return reponse


class MonMotDePasse(LoginRequiredMixin, TemplateView):
    template_name = "backoffice/formulaire.html"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = "Changer mon mot de passe"
        contexte["form"] = styliser(kwargs.get("form") or forms.MonMotDePasseForm(self.request.user))
        contexte["url_retour"] = reverse("backoffice:mon_profil")
        return contexte

    def post(self, request):
        form = forms.MonMotDePasseForm(request.user, request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        request.user.set_password(form.cleaned_data["mot_de_passe"])
        request.user.save()
        # Sans ça, Django considère la session courante invalide dès que le
        # hash du mot de passe change, et déconnecte la personne qui vient
        # elle-même de le changer.
        update_session_auth_hash(request, request.user)
        messages.success(request, "Mot de passe mis à jour.")
        return redirect("backoffice:mon_profil")


class SupprimerBase(AccesModification, View):
    """Suppression définitive d'un référentiel (prestataire, nature de soin,
    tranche de barème…).

    Volontairement pas de vérification préalable ici : les FK `on_delete=
    PROTECT` des modèles qui utilisent réellement ces référentiels
    (Prescription, Facture…) suffisent à empêcher une suppression qui
    casserait l'historique, et le message ci-dessous l'explique plutôt que de
    laisser remonter une 500.
    """

    model = None
    url_liste = ""
    libelle = ""

    def post(self, request, pk):
        objet = get_object_or_404(self.model, pk=pk)
        description = str(objet)
        try:
            objet.delete()
        except ProtectedError:
            messages.error(
                request,
                f"{self.libelle} « {description} » ne peut pas être supprimé : "
                "des prescriptions ou factures existantes s'y réfèrent encore.",
            )
        else:
            messages.success(request, f"{self.libelle} « {description} » supprimé.")
        return redirect(self.url_liste)


class TableauDeBordView(AccesBackoffice, TemplateView):
    template_name = "backoffice/tableau_de_bord.html"

    def test_func(self):
        utilisateur = self.request.user
        return utilisateur.is_authenticated and (
            utilisateur.is_superuser or utilisateur.role in (Role.RH, Role.DIRECTION, Role.AGENT)
        )

    def get(self, request, *args, **kwargs):
        # Ce tableau de bord (anomalies) est celui du service mutuelle ; un
        # agent qui atterrit ici après connexion (LOGIN_REDIRECT_URL) part
        # sur le sien. is_superuser passe outre, pour un compte de test qui
        # cumulerait les deux rôles.
        if request.user.role == Role.AGENT and not request.user.is_superuser:
            return redirect("backoffice:mon_tableau_de_bord")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from anomalies import services
        from rapports import services as rapports_services

        contexte = super().get_context_data(**kwargs)
        contexte["indicateurs"] = services.indicateurs_globaux()
        contexte["en_controle"] = services.prescriptions_en_controle()
        contexte["pics"] = services.pics_de_consommation()
        contexte["prestataires_anormaux"] = services.prestataires_volume_anormal()
        contexte["agents_proche_quota"] = services.agents_proche_quota()
        contexte["justificatifs_expires"] = services.ayants_droit_justificatif_expire()

        tendance = rapports_services.evolution_recente(6)
        contexte["tendance_mensuelle"] = tendance
        contexte["mois_courant"] = tendance[-1]
        contexte["tendance_max"] = max((mois["montant"] for mois in tendance), default=0) or 1
        return contexte


class MonTableauDeBord(AccesAgent, TemplateView):
    """Web, en attendant l'usage officiel de l'application mobile par les
    agents (voir la décision sur le justificatif facultatif) : même contenu
    que l'écran « Mon profil » du mobile (quota, ayants droit, historique),
    mais un agent ne peut voir que le sien — pas celui des autres."""

    template_name = "backoffice/mon_tableau_de_bord.html"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        agent = self.request.user.agent
        debut, fin = agent.periode_courante()

        contexte["agent"] = agent
        contexte["quota"] = agent.quota_effectif
        contexte["consommation"] = agent.consommation_periode()
        contexte["solde"] = agent.solde_quota()
        contexte["periode_debut"] = debut
        contexte["periode_fin"] = fin
        contexte["cotisation"] = agent.cotisation_mensuelle
        contexte["ayants_droit"] = agent.ayants_droit.all()
        contexte["prescriptions"] = (
            agent.prescriptions.select_related("prestataire", "ayant_droit", "nature").order_by("-date_creation")[:30]
        )
        return contexte


class MaPrescriptionCreer(AccesAgent, CreateView):
    """Auto-saisie d'une ordonnance par l'agent lui-même, depuis son tableau
    de bord — même circuit qu'une saisie RH ou une soumission mobile : la
    détection de doublons s'applique et le statut reste soumis à une
    validation manuelle du service mutuelle."""

    model = Prescription
    form_class = forms.MaPrescriptionForm
    template_name = "backoffice/ma_prescription_form.html"
    titre = "Nouvelle prescription"

    def get_form(self, form_class=None):
        return styliser(super().get_form(form_class))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["agent"] = self.request.user.agent
        return kwargs

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = self.titre
        contexte["url_retour"] = reverse("backoffice:mon_tableau_de_bord")
        return contexte

    def form_valid(self, form):
        form.instance.agent = self.request.user.agent
        form.instance.soumis_par = self.request.user
        messages.success(self.request, f"{self.titre} : enregistrement effectué.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("backoffice:mon_tableau_de_bord")


# --- Agents ---------------------------------------------------------------


class AgentListe(ListeBase):
    model = Agent
    titre = "Agents"
    url_creation = "backoffice:agent_creer"
    libelle_creation = "Nouvel agent"
    url_detail = "backoffice:agent_detail"
    champs_recherche = ("utilisateur__matricule", "utilisateur__nom", "utilisateur__prenom", "site")
    colonnes = (
        ("Matricule", "matricule"),
        ("Nom", lambda o: o.utilisateur.get_full_name()),
        ("Site", "site"),
        ("Quota du cycle", lambda o: f"{o.quota_effectif} KMF ({o.quota_mensuel}/mois)"),
        ("Famille", lambda o: f"{o.nombre_conjoints} conj. · {o.nombre_enfants} enf."),
        ("Cotisation", lambda o: f"{o.cotisation_mensuelle} KMF"),
        ("Solde du cycle", lambda o: f"{o.solde_quota()} KMF"),
        ("Actif", "actif"),
    )

    def get_queryset(self):
        return super().get_queryset().select_related("utilisateur")


class AgentDetail(AccesBackoffice, DetailView):
    model = Agent
    template_name = "backoffice/agent_detail.html"
    context_object_name = "agent"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["ayants_droit"] = self.object.ayants_droit.all()
        contexte["prescriptions"] = self.object.prescriptions.select_related("prestataire")[:20]
        contexte["peut_modifier"] = self.request.user.role == Role.RH or self.request.user.is_superuser
        return contexte


class AgentCreer(FormulaireBase, CreateView):
    model = Agent
    form_class = forms.AgentForm
    titre = "Nouvel agent"
    success_url = reverse_lazy("backoffice:agents")


class AgentModifier(FormulaireBase, UpdateView):
    model = Agent
    form_class = forms.AgentForm
    titre = "Modifier l'agent"
    success_url = reverse_lazy("backoffice:agents")


# --- Ayants droit ---------------------------------------------------------


class AyantDroitListe(ListeBase):
    model = AyantDroit
    titre = "Ayants droit"
    template_name = "backoffice/ayant_droit_liste.html"
    url_creation = "backoffice:ayant_droit_creer"
    libelle_creation = "Nouvel ayant droit"
    url_detail = "backoffice:ayant_droit_modifier"
    url_export = "backoffice:ayant_droit_export"
    url_import = "backoffice:ayant_droit_import"
    champs_recherche = ("nom", "prenom", "agent__utilisateur__matricule")
    colonnes = (
        ("Nom", lambda o: f"{o.prenom} {o.nom}"),
        ("Agent", lambda o: o.agent.matricule),
        ("Lien", "get_lien_parente_display"),
        ("Âge", lambda o: "—" if o.age is None else f"{o.age} ans"),
        ("Statut", "get_statut_verification_display"),
        (
            "Alertes",
            lambda o: " ".join(
                filter(
                    None,
                    [
                        "Justificatif expiré" if o.est_expire else "",
                        "Limite d'âge dépassée" if o.limite_age_depassee else "",
                    ],
                )
            )
            or "—",
        ),
    )

    @staticmethod
    def _entier(brut):
        try:
            return int(brut)
        except (TypeError, ValueError):
            return None

    def get_queryset(self):
        queryset = super().get_queryset().select_related("agent__utilisateur")

        lien = self.request.GET.get("lien", "")
        if lien in LienParente.values:
            queryset = queryset.filter(lien_parente=lien)

        statut = self.request.GET.get("statut", "")
        if statut in StatutVerification.values:
            queryset = queryset.filter(statut_verification=statut)

        age_min = self._entier(self.request.GET.get("age_min"))
        age_max = self._entier(self.request.GET.get("age_max"))
        limite_depassee = self.request.GET.get("limite_depassee") == "1"
        justificatif_expire = self.request.GET.get("justificatif_expire") == "1"

        if age_min is None and age_max is None and not limite_depassee and not justificatif_expire:
            return queryset

        # Âge, limite d'âge et expiration du justificatif sont des propriétés
        # Python (calculées depuis date_naissance/date_validite), pas des
        # colonnes : impossible à filtrer côté SQL sans dupliquer la logique
        # métier. Le volume d'ayants droit reste modeste, on filtre donc en
        # mémoire — en ne chargeant qu'une fois le paramétrage plutôt que
        # via la propriété `limite_age_depassee` (qui le rechargerait à
        # chaque ligne).
        age_limite = Parametrage.charger().age_limite_enfant
        resultat = []
        for ayant_droit in queryset:
            if age_min is not None and (ayant_droit.age is None or ayant_droit.age < age_min):
                continue
            if age_max is not None and (ayant_droit.age is None or ayant_droit.age > age_max):
                continue
            if limite_depassee and not (
                ayant_droit.lien_parente == LienParente.ENFANT
                and ayant_droit.age is not None
                and ayant_droit.age >= age_limite
            ):
                continue
            if justificatif_expire and not ayant_droit.est_expire:
                continue
            resultat.append(ayant_droit)
        return resultat

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["filtre_lien"] = self.request.GET.get("lien", "")
        contexte["filtre_statut"] = self.request.GET.get("statut", "")
        contexte["filtre_age_min"] = self.request.GET.get("age_min", "")
        contexte["filtre_age_max"] = self.request.GET.get("age_max", "")
        contexte["filtre_limite_depassee"] = self.request.GET.get("limite_depassee") == "1"
        contexte["filtre_justificatif_expire"] = self.request.GET.get("justificatif_expire") == "1"
        contexte["liens"] = LienParente.choices
        contexte["statuts_verification"] = StatutVerification.choices
        return contexte


class AyantDroitCreer(FormulaireBase, CreateView):
    model = AyantDroit
    form_class = forms.AyantDroitForm
    template_name = "backoffice/ayant_droit_form.html"
    titre = "Nouvel ayant droit"
    success_url = reverse_lazy("backoffice:ayants_droit")


class AyantDroitModifier(FormulaireBase, UpdateView):
    model = AyantDroit
    form_class = forms.AyantDroitForm
    template_name = "backoffice/ayant_droit_form.html"
    titre = "Modifier l'ayant droit"
    success_url = reverse_lazy("backoffice:ayants_droit")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["ayant_droit"] = self.object
        return contexte


class AyantDroitExport(AccesBackoffice, View):
    def get(self, request):
        colonnes = (
            ("Agent", lambda o: o.agent.matricule),
            ("Nom", "nom"),
            ("Prénom", "prenom"),
            ("Date de naissance", "date_naissance"),
            ("Lien de parenté", "get_lien_parente_display"),
            ("Type de justificatif", "get_type_justificatif_display"),
            ("Justificatif", lambda o: o.justificatif.name.rsplit("/", 1)[-1] if o.justificatif else ""),
            ("Date de validité", "date_validite"),
            ("Statut de vérification", "get_statut_verification_display"),
        )
        return exports.reponse_csv(
            exports.nom_de_fichier("ayants-droit"),
            colonnes,
            AyantDroit.objects.select_related("agent__utilisateur"),
        )


LIENS_IMPORT = {valeur.lower(): valeur for valeur in LienParente.values}
LIENS_IMPORT.update({libelle.lower(): valeur for valeur, libelle in LienParente.choices})

JUSTIFICATIFS_IMPORT = {valeur.lower(): valeur for valeur in TypeJustificatif.values}
JUSTIFICATIFS_IMPORT.update({libelle.lower(): valeur for valeur, libelle in TypeJustificatif.choices})

STATUTS_VERIFICATION_IMPORT = {valeur.lower(): valeur for valeur in StatutVerification.values}
STATUTS_VERIFICATION_IMPORT.update({libelle.lower(): valeur for valeur, libelle in StatutVerification.choices})


class AyantDroitImport(ImportCSVBase):
    titre = "Importer des ayants droit"
    aide = (
        "Colonnes obligatoires : agent (matricule), nom, prenom, lien_parente "
        "(conjoint/enfant/autre). Facultatives : date_naissance (JJ/MM/AAAA), "
        "type_justificatif (acte_naissance/acte_mariage/certificat_scolarite/autre — "
        "« autre » par défaut), date_validite, statut_verification "
        "(en_attente/valide/rejete — « en attente » par défaut). Les en-têtes de "
        "l'export (« Date de naissance », « Type de justificatif », « Statut de "
        "vérification »…) sont aussi reconnus. Une ligne dont l'agent, le nom et le "
        "prénom correspondent déjà à un ayant droit le met à jour au lieu d'en créer "
        "un doublon. Le fichier du justificatif n'est jamais importé : chaque fiche "
        "créée doit le recevoir séparément, depuis la fiche, avant vérification."
    )
    colonnes_attendues = frozenset({"agent", "nom", "prenom", "lien_parente"})
    alias = {
        "date de naissance": "date_naissance",
        "lien de parente": "lien_parente",
        "type de justificatif": "type_justificatif",
        "date de validite": "date_validite",
        "statut de verification": "statut_verification",
    }
    url_liste = "backoffice:ayants_droit"
    cle_session = "import_ayants_droit_csv"

    def importer_ligne(self, ligne):
        matricule = ligne.get("agent", "").strip().upper()
        agent = Agent.objects.filter(utilisateur__matricule=matricule).first()
        if not agent:
            raise imports.LigneInvalide(f"agent « {matricule} » introuvable")

        nom = ligne.get("nom", "")
        prenom = ligne.get("prenom", "")
        if not nom or not prenom:
            raise imports.LigneInvalide("nom ou prénom vide")

        lien_brut = ligne.get("lien_parente", "").lower()
        lien = LIENS_IMPORT.get(lien_brut)
        if not lien:
            raise imports.LigneInvalide(f"lien de parenté « {ligne.get('lien_parente')} » inconnu")

        type_brut = ligne.get("type_justificatif", "").lower()
        if type_brut and type_brut not in JUSTIFICATIFS_IMPORT:
            raise imports.LigneInvalide(f"type de justificatif « {ligne.get('type_justificatif')} » inconnu")
        type_justificatif = JUSTIFICATIFS_IMPORT.get(type_brut, TypeJustificatif.AUTRE)

        statut_brut = ligne.get("statut_verification", "").lower()
        if statut_brut and statut_brut not in STATUTS_VERIFICATION_IMPORT:
            raise imports.LigneInvalide(f"statut de vérification « {ligne.get('statut_verification')} » inconnu")
        statut_verification = STATUTS_VERIFICATION_IMPORT.get(statut_brut, StatutVerification.EN_ATTENTE)

        champs = {
            "date_naissance": imports.date_ou_erreur(ligne.get("date_naissance", ""), "date_naissance"),
            "lien_parente": lien,
            "type_justificatif": type_justificatif,
            "date_validite": imports.date_ou_erreur(ligne.get("date_validite", ""), "date_validite"),
            "statut_verification": statut_verification,
        }

        existant = AyantDroit.objects.filter(agent=agent, nom__iexact=nom, prenom__iexact=prenom).first()
        if existant:
            for attribut, valeur in champs.items():
                setattr(existant, attribut, valeur)
            existant.save()
            return existant, False

        return AyantDroit.objects.create(agent=agent, nom=nom, prenom=prenom, **champs), True


class AyantDroitVerifier(AccesModification, View):
    """Valide ou rejette un ayant droit en traçant l'auteur et la date."""

    def post(self, request, pk, decision):
        ayant_droit = get_object_or_404(AyantDroit, pk=pk)
        statuts = {"valider": StatutVerification.VALIDE, "rejeter": StatutVerification.REJETE}
        if decision not in statuts:
            return redirect("backoffice:ayants_droit")

        ayant_droit.statut_verification = statuts[decision]
        ayant_droit.verifie_par = request.user
        ayant_droit.date_verification = timezone.now()
        ayant_droit.commentaire_verification = request.POST.get("commentaire", "")
        ayant_droit.save()
        messages.success(request, f"{ayant_droit.prenom} {ayant_droit.nom} : {statuts[decision].label.lower()}.")
        return redirect("backoffice:ayant_droit_modifier", pk=pk)


# --- Prescriptions --------------------------------------------------------


class PrescriptionListe(ListeBase):
    model = Prescription
    titre = "Prescriptions"
    url_detail = "backoffice:prescription_detail"
    url_creation = "backoffice:prescription_creer"
    libelle_creation = "Saisir une prescription"
    url_import = "backoffice:prescription_import"
    champs_recherche = ("numero_ordonnance", "agent__utilisateur__matricule", "prestataire__nom")
    colonnes = (
        ("N° ordonnance", "numero_ordonnance"),
        ("Bénéficiaire", lambda o: str(o.beneficiaire())),
        ("Prestataire", lambda o: o.prestataire.nom),
        ("Nature", lambda o: o.nature.libelle if o.nature_id else "—"),
        ("Montant", lambda o: f"{o.montant_total} KMF"),
        ("Remboursé", lambda o: f"{o.montant_rembourse} KMF"),
        ("Date", "date_emission"),
        ("Statut", "get_statut_display"),
    )

    def get_queryset(self):
        queryset = super().get_queryset().select_related("agent__utilisateur", "prestataire", "ayant_droit", "nature")
        statut = self.request.GET.get("statut", "")
        if statut:
            queryset = queryset.filter(statut=statut)
        return queryset

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["filtre_statut"] = self.request.GET.get("statut", "")
        contexte["statuts"] = StatutPrescription.choices
        return contexte


class RechercheAgents(AccesBackoffice, View):
    """Alimente le champ « agent » en recherche libre (prescription, ayant
    droit) : avec plusieurs milliers d'agents, une liste déroulante complète
    est inutilisable. La recherche porte sur le matricule, le nom et le
    prénom."""

    def get(self, request):
        recherche = request.GET.get("q", "").strip()
        agents = Agent.objects.select_related("utilisateur").filter(actif=True)
        if recherche:
            agents = agents.filter(
                Q(utilisateur__matricule__icontains=recherche)
                | Q(utilisateur__nom__icontains=recherche)
                | Q(utilisateur__prenom__icontains=recherche)
            )
        return JsonResponse(
            {
                "resultats": [
                    {
                        "id": agent.pk,
                        "matricule": agent.matricule,
                        "nom": agent.utilisateur.get_full_name(),
                        "site": agent.site,
                    }
                    for agent in agents[:20]
                ]
            }
        )


class AyantsDroitDeLAgent(AccesBackoffice, View):
    """Restreint le choix du bénéficiaire aux ayants droit de l'agent choisi.

    Les ayants droit non couverts (dossier non validé, ou enfant au-delà de
    l'âge limite) sont renvoyés mais signalés : au service mutuelle de décider,
    plutôt que de les masquer sans explication.
    """

    def get(self, request, pk):
        agent = get_object_or_404(Agent, pk=pk)
        couverts = {a.pk for a in agent.ayants_droit_couverts}
        return JsonResponse(
            {
                "resultats": [
                    {
                        "id": ayant_droit.pk,
                        "libelle": f"{ayant_droit.prenom} {ayant_droit.nom} ({ayant_droit.get_lien_parente_display()})",
                        "couvert": ayant_droit.pk in couverts,
                    }
                    for ayant_droit in agent.ayants_droit.all()
                ]
            }
        )


class PrescriptionCreer(FormulaireBase, CreateView):
    """Saisie d'une ordonnance papier par le service mutuelle. Elle suit le
    même circuit qu'une soumission mobile : la détection de doublons s'applique
    et le statut reste soumis à une validation manuelle."""

    model = Prescription
    form_class = forms.PrescriptionForm
    template_name = "backoffice/prescription_form.html"
    titre = "Saisir une prescription"
    success_url = reverse_lazy("backoffice:prescriptions")

    def form_valid(self, form):
        form.instance.soumis_par = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("backoffice:prescription_detail", args=[self.object.pk])


class PrescriptionDetail(AccesBackoffice, DetailView):
    model = Prescription
    template_name = "backoffice/prescription_detail.html"
    context_object_name = "prescription"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["historique"] = self.object.historique.select_related("utilisateur")
        contexte["doublons"] = self.object.detecter_doublons().select_related("prestataire")
        contexte["peut_modifier"] = self.request.user.role == Role.RH or self.request.user.is_superuser
        contexte["statuts"] = StatutPrescription.choices
        contexte["peut_supprimer"] = self.object.statut not in STATUTS_MANUELS
        return contexte


class PrescriptionSupprimer(AccesModification, View):
    """Suppression réservée aux prescriptions pas encore décidées : une fois
    validée ou rejetée, la décision doit rester tracée, quitte à corriger par
    un nouveau changement de statut plutôt que par un effacement."""

    def post(self, request, pk):
        prescription = get_object_or_404(Prescription, pk=pk)
        if prescription.statut in STATUTS_MANUELS:
            messages.error(
                request,
                "Impossible de supprimer une prescription déjà validée ou rejetée : "
                "cette décision doit rester tracée.",
            )
            return redirect("backoffice:prescription_detail", pk=pk)

        numero = prescription.numero_ordonnance
        prescription.delete()
        messages.success(request, f"Prescription {numero} supprimée.")
        return redirect("backoffice:prescriptions")


class PrescriptionImport(ImportCSVBase):
    """Reprise d'un historique déjà arbitré — pas une soumission normale : le
    statut et le montant remboursé du fichier font foi, la détection de
    doublons ne s'applique pas (voir importer_ligne, mode « conserver »)."""

    titre = "Importer un historique de prescriptions"
    aide = (
        "Colonnes obligatoires : agent (matricule), prestataire (code ou nom), "
        "numero_ordonnance, montant_total, date_emission. Facultatives : "
        "ayant_droit (« Prénom Nom », rattaché à cet agent), statut, "
        "montant_rembourse (recalculé au taux du prestataire si absent). Le "
        "statut et le montant remboursé du fichier font foi : la détection de "
        "doublons ne s'applique pas, ce n'est pas une nouvelle soumission mais "
        "la reprise d'une décision déjà prise."
    )
    colonnes_attendues = frozenset({"agent", "prestataire", "numero_ordonnance", "montant_total", "date_emission"})
    url_liste = "backoffice:prescriptions"
    cle_session = "import_prescriptions_csv"

    def importer_ligne(self, ligne):
        from prescriptions.management.commands.importer_prescriptions import LigneInvalide as ErreurCLI
        from prescriptions.management.commands.importer_prescriptions import importer_ligne as importer_cli

        try:
            return importer_cli(ligne)
        except ErreurCLI as erreur:
            raise imports.LigneInvalide(str(erreur))


class PrescriptionChangerStatut(AccesModification, View):
    """Seul point d'entrée pour valider/rejeter : passe par `changer_statut`
    afin que l'historique horodaté soit alimenté."""

    def post(self, request, pk):
        prescription = get_object_or_404(Prescription, pk=pk)
        nouveau_statut = request.POST.get("statut", "")
        if nouveau_statut not in StatutPrescription.values:
            messages.error(request, "Statut inconnu.")
            return redirect("backoffice:prescription_detail", pk=pk)

        prescription.changer_statut(
            nouveau_statut,
            utilisateur=request.user,
            commentaire=request.POST.get("commentaire", ""),
        )
        messages.success(request, f"Prescription {prescription.numero_ordonnance} : statut mis à jour.")
        return redirect("backoffice:prescription_detail", pk=pk)


# --- Factures prestataires ------------------------------------------------


class FactureListe(ListeBase):
    model = Facture
    titre = "Factures prestataires"
    url_creation = "backoffice:facture_creer"
    libelle_creation = "Nouvelle facture"
    url_detail = "backoffice:facture_detail"
    url_import = "backoffice:facture_import"
    champs_recherche = ("numero", "prestataire__nom", "prestataire__code")
    colonnes = (
        ("N° facture", "numero"),
        ("Prestataire", lambda o: o.prestataire.nom),
        ("Période", lambda o: f"{o.get_mois_display()} {o.annee}"),
        ("Montant annoncé", lambda o: f"{o.montant_total_declare} KMF"),
        ("Lignes", lambda o: o.lignes.count()),
        ("Statut", "get_statut_display"),
    )

    def get_queryset(self):
        return super().get_queryset().select_related("prestataire")


class FactureDetail(AccesBackoffice, DetailView):
    model = Facture
    template_name = "backoffice/facture_detail.html"
    context_object_name = "facture"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["lignes"] = self.object.lignes.select_related("prescription")
        contexte["non_facturees"] = self.object.prescriptions_non_facturees()
        contexte["synthese"] = self.object.synthese()
        contexte["peut_modifier"] = self.request.user.role == Role.RH or self.request.user.is_superuser
        return contexte


class FactureCreer(FormulaireBase, CreateView):
    model = Facture
    form_class = forms.FactureForm
    titre = "Nouvelle facture"
    success_url = reverse_lazy("backoffice:factures")

    def form_valid(self, form):
        form.instance.saisie_par = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("backoffice:facture_detail", args=[self.object.pk])


class FactureImport(AccesModification, TemplateView):
    """Entête + lignes en une fois, avec aperçu des erreurs avant écriture —
    contrairement à FactureCreer (entête seule) qui suppose ensuite un import
    CSV séparé en ligne de commande.

    Structurellement différent des autres imports (ImportCSVBase suppose un
    fichier qui produit directement des objets ; ici le fichier ne fournit que
    les lignes, l'entête vient du formulaire, et il faut créer les deux plus
    lancer le rapprochement) : vue dédiée plutôt qu'une sous-classe forcée.
    """

    template_name = "backoffice/import_facture.html"
    cle_session = "import_facture_csv"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = "Importer une facture prestataire"
        contexte["url_retour"] = reverse("backoffice:factures")
        contexte.setdefault("form", styliser(forms.ImportFactureForm()))
        return contexte

    def post(self, request, *args, **kwargs):
        if request.POST.get("confirmer"):
            return self._confirmer(request)
        return self._analyser(request)

    def _analyser(self, request):
        from facturation.management.commands.importer_facture import COLONNES_ATTENDUES
        from facturation.management.commands.importer_facture import LigneInvalide as ErreurCLI
        from facturation.management.commands.importer_facture import analyser_ligne

        form = styliser(forms.ImportFactureForm(request.POST, request.FILES))
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        donnees = form.cleaned_data
        contenu = request.FILES["fichier_csv"].read().decode("utf-8-sig")
        lignes = imports.lire_csv(contenu)

        erreurs = []
        if not lignes:
            erreurs = [(0, "le fichier ne contient aucune ligne de données")]
        else:
            manquantes = COLONNES_ATTENDUES - set(lignes[0])
            if manquantes:
                erreurs = [(0, f"colonnes obligatoires absentes : {', '.join(sorted(manquantes))}")]
            else:
                taux = donnees["prestataire"].taux_prise_en_charge
                for numero, ligne in enumerate(lignes, start=2):
                    try:
                        analyser_ligne(ligne, taux, donnees["montant_colonne"])
                    except ErreurCLI as erreur:
                        erreurs.append((numero, str(erreur)))

        rapport = {"erreurs": erreurs, "lignes_lues": len(lignes)}

        if not erreurs:
            request.session[self.cle_session] = {
                "contenu": contenu,
                "prestataire_id": donnees["prestataire"].pk,
                "numero": donnees["numero"],
                "mois": int(donnees["mois"]),
                "annee": donnees["annee"],
                "montant_total_declare": donnees["montant_total_declare"],
                "montant_colonne": donnees["montant_colonne"],
            }

        return self.render_to_response(self.get_context_data(form=form, rapport=rapport))

    def _confirmer(self, request):
        from facturation.management.commands.importer_facture import creer_facture_avec_lignes

        etat = request.session.pop(self.cle_session, None)
        if not etat:
            messages.error(request, "Le fichier analysé a expiré : réimportez-le.")
            return redirect("backoffice:factures")

        prestataire = get_object_or_404(Prestataire, pk=etat["prestataire_id"])
        if Facture.objects.filter(prestataire=prestataire, numero=etat["numero"]).exists():
            messages.error(request, "Cette facture a été enregistrée entre-temps : réimportez le fichier si besoin.")
            return redirect("backoffice:factures")

        lignes = imports.lire_csv(etat["contenu"])
        with transaction.atomic():
            facture, importees, erreurs = creer_facture_avec_lignes(
                prestataire,
                etat["numero"],
                etat["mois"],
                etat["annee"],
                etat["montant_total_declare"],
                lignes,
                etat["montant_colonne"],
            )
            if erreurs:
                transaction.set_rollback(True)
            else:
                facture.saisie_par = request.user
                facture.save()

        if erreurs:
            messages.error(request, "Le fichier a changé entre l'analyse et la confirmation : réimportez-le.")
            return redirect("backoffice:factures")

        synthese = facture.synthese()
        messages.success(
            request,
            f"Facture {facture.numero} importée ({importees} ligne(s)) : "
            f"{synthese['concordantes']} concordante(s), {synthese['ecarts_montant']} écart(s) de montant, "
            f"{synthese['ecarts_taux']} taux mal appliqué(s), {synthese['sans_prescription']} sans prescription, "
            f"{synthese['non_facturees']} prescription(s) non facturée(s).",
        )
        return redirect("backoffice:facture_detail", pk=facture.pk)


class FactureRapprocher(AccesModification, View):
    def post(self, request, pk):
        facture = get_object_or_404(Facture, pk=pk)
        facture.rapprocher()
        synthese = facture.synthese()
        messages.success(
            request,
            f"Rapprochement effectué : {synthese['concordantes']} ligne(s) concordante(s), "
            f"{synthese['ecarts_montant']} écart(s) de montant, "
            f"{synthese['sans_prescription']} sans prescription, "
            f"{synthese['non_facturees']} prescription(s) non facturée(s).",
        )
        return redirect("backoffice:facture_detail", pk=pk)


class FactureValider(AccesModification, View):
    """Seul point où une prescription passe en « Validée » sans arbitrage
    individuel : le RH valide la facture, et cette décision s'applique aux
    lignes dont le rapprochement est exact."""

    def post(self, request, pk):
        facture = get_object_or_404(Facture, pk=pk)
        if facture.statut == StatutFacture.RECUE:
            messages.error(request, "Lancez d'abord le rapprochement.")
            return redirect("backoffice:facture_detail", pk=pk)

        validees = facture.valider(request.user)
        messages.success(
            request,
            f"Facture validée. {validees} prescription(s) confirmée(s) par la facture et passée(s) en « Validée ».",
        )
        return redirect("backoffice:facture_detail", pk=pk)


class FactureContester(AccesModification, View):
    def post(self, request, pk):
        facture = get_object_or_404(Facture, pk=pk)
        facture.statut = StatutFacture.CONTESTEE
        facture.commentaire = request.POST.get("commentaire", "")
        facture.save()
        messages.success(request, f"Facture {facture.numero} marquée comme contestée.")
        return redirect("backoffice:facture_detail", pk=pk)


# --- Prestataires ---------------------------------------------------------


class PrestataireListe(ListeBase):
    model = Prestataire
    titre = "Prestataires conventionnés"
    url_creation = "backoffice:prestataire_creer"
    libelle_creation = "Nouveau prestataire"
    url_detail = "backoffice:prestataire_modifier"
    url_import = "backoffice:prestataire_import"
    champs_recherche = ("code", "nom", "ville")
    colonnes = (
        ("Code", "code"),
        ("Nom", "nom"),
        ("Type", "get_type_prestataire_display"),
        ("Ville", "ville"),
        ("Taux", lambda o: f"{o.taux_prise_en_charge} %"),
        ("Statut", "get_statut_display"),
    )


class PrestataireCreer(FormulaireBase, CreateView):
    model = Prestataire
    form_class = forms.PrestataireForm
    titre = "Nouveau prestataire"
    success_url = reverse_lazy("backoffice:prestataires")


class PrestataireModifier(FormulaireBase, UpdateView):
    model = Prestataire
    form_class = forms.PrestataireForm
    titre = "Modifier le prestataire"
    success_url = reverse_lazy("backoffice:prestataires")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["prestataire_tarifs"] = self.object.tarifs.select_related("nature_soin").all()
        contexte["form_tarif"] = styliser(forms.TarifPrestataireForm())
        contexte["url_tarif_ajouter"] = reverse("backoffice:prestataire_tarif_ajouter", args=[self.object.pk])
        contexte["url_supprimer"] = reverse("backoffice:prestataire_supprimer", args=[self.object.pk])
        return contexte


class PrestataireSupprimer(SupprimerBase):
    model = Prestataire
    url_liste = "backoffice:prestataires"
    libelle = "Prestataire"


class PrestataireImport(ImportCSVBase):
    titre = "Importer des prestataires"
    aide = (
        "Colonnes obligatoires : type (pharmacie/établissement/praticien), nom. "
        "Facultatives : ville, adresse, telephone, taux (80 par défaut si absent), "
        "statut (actif par défaut), code. Une ligne dont le code correspond à un "
        "prestataire existant — ou, à défaut de code, dont le nom et la ville "
        "correspondent — le met à jour au lieu d'en créer un doublon."
    )
    colonnes_attendues = frozenset({"type", "nom"})
    url_liste = "backoffice:prestataires"
    cle_session = "import_prestataires_csv"

    def importer_ligne(self, ligne):
        from prestataires.management.commands.importer_prestataires import LigneInvalide as ErreurCLI
        from prestataires.management.commands.importer_prestataires import importer_ligne as importer_cli

        try:
            return importer_cli(ligne)
        except ErreurCLI as erreur:
            raise imports.LigneInvalide(str(erreur))


class PrestataireTarifAjouter(AccesModification, View):
    """Ajoute ou met à jour (même nature = même ligne) un tarif détaillé.

    Tant qu'aucun tarif n'existe pour ce prestataire, le taux général
    continue de s'appliquer à toutes les prescriptions : ajouter le premier
    tarif ne change donc rien aux autres natures, seulement à celle-ci.
    """

    def post(self, request, pk):
        prestataire = get_object_or_404(Prestataire, pk=pk)
        form = forms.TarifPrestataireForm(request.POST)
        if form.is_valid():
            TarifPrestataire.objects.update_or_create(
                prestataire=prestataire,
                nature_soin=form.cleaned_data["nature_soin"],
                defaults={"taux_prise_en_charge": form.cleaned_data["taux_prise_en_charge"]},
            )
            messages.success(request, "Tarif enregistré.")
        else:
            erreurs = "; ".join(f"{champ} : {', '.join(liste)}" for champ, liste in form.errors.items())
            messages.error(request, f"Tarif invalide — {erreurs}")
        return redirect("backoffice:prestataire_modifier", pk=pk)


class PrestataireTarifSupprimer(AccesModification, View):
    def post(self, request, pk, tarif_pk):
        tarif = get_object_or_404(TarifPrestataire, pk=tarif_pk, prestataire_id=pk)
        tarif.delete()
        messages.success(request, "Tarif supprimé : ce prestataire revient au taux général pour cette nature.")
        return redirect("backoffice:prestataire_modifier", pk=pk)


class PrestataireBasculerStatut(AccesModification, View):
    def post(self, request, pk):
        prestataire = get_object_or_404(Prestataire, pk=pk)
        suspendu = prestataire.statut == StatutPrestataire.SUSPENDU
        prestataire.statut = StatutPrestataire.ACTIF if suspendu else StatutPrestataire.SUSPENDU
        prestataire.save()
        messages.success(request, f"{prestataire.nom} : {prestataire.get_statut_display().lower()}.")
        return redirect("backoffice:prestataires")


# --- Utilisateurs ---------------------------------------------------------


class UtilisateurListe(ListeBase):
    model = Utilisateur
    titre = "Utilisateurs"
    url_creation = "backoffice:utilisateur_creer"
    libelle_creation = "Nouveau compte"
    url_detail = "backoffice:utilisateur_modifier"
    url_export = "backoffice:utilisateur_export"
    url_import = "backoffice:utilisateur_import"
    champs_recherche = ("matricule", "nom", "prenom", "email", "telephone", "region")
    colonnes = (
        ("Matricule", "matricule"),
        ("Nom", "get_full_name"),
        ("Rôle", "get_role_display"),
        ("Téléphone", "telephone"),
        ("Région", "region"),
        ("Actif", "is_active"),
    )


class UtilisateurCreer(FormulaireBase, CreateView):
    model = Utilisateur
    form_class = forms.UtilisateurCreationForm
    titre = "Nouveau compte"
    success_url = reverse_lazy("backoffice:utilisateurs")


class UtilisateurModifier(FormulaireBase, UpdateView):
    model = Utilisateur
    form_class = forms.UtilisateurForm
    titre = "Modifier le compte"
    success_url = reverse_lazy("backoffice:utilisateurs")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["utilisateur_edite"] = self.object
        return contexte


class UtilisateurExport(AccesBackoffice, View):
    def get(self, request):
        colonnes = (
            ("Matricule", "matricule"),
            ("Nom", "nom"),
            ("Prénom", "prenom"),
            ("Email", "email"),
            ("Téléphone", "telephone"),
            ("Rôle", "get_role_display"),
            ("Région", "region"),
            ("Actif", "is_active"),
        )
        return exports.reponse_csv(exports.nom_de_fichier("utilisateurs"), colonnes, Utilisateur.objects.all())


ROLES_IMPORT = {valeur.lower(): valeur for valeur in Role.values}
ROLES_IMPORT.update({libelle.lower(): valeur for valeur, libelle in Role.choices})


def _actif_import(brut):
    if not brut:
        return True
    return brut.strip().lower() in ("oui", "vrai", "true", "1", "actif")


class UtilisateurImport(ImportCSVBase):
    titre = "Importer des utilisateurs"
    aide = (
        "Colonnes obligatoires : matricule, nom, prenom. Facultatives : email, "
        "telephone, role (agent/rh/direction/prestataire — agent par défaut), "
        "region, actif (oui/non — actif par défaut). Une ligne dont le matricule "
        "correspond déjà à un compte le met à jour au lieu d'en créer un doublon. "
        "Le mot de passe n'est jamais importé : chaque compte créé doit en recevoir "
        "un depuis sa fiche (« Définir un nouveau mot de passe ») avant de pouvoir "
        "se connecter."
    )
    colonnes_attendues = frozenset({"matricule", "nom", "prenom"})
    url_liste = "backoffice:utilisateurs"
    cle_session = "import_utilisateurs_csv"

    def importer_ligne(self, ligne):
        matricule = ligne.get("matricule", "").strip().upper()
        nom = ligne.get("nom", "")
        prenom = ligne.get("prenom", "")
        if not matricule:
            raise imports.LigneInvalide("matricule vide")
        if not nom or not prenom:
            raise imports.LigneInvalide("nom ou prénom vide")

        role_brut = ligne.get("role", "").lower()
        if role_brut and role_brut not in ROLES_IMPORT:
            raise imports.LigneInvalide(f"rôle « {ligne.get('role')} » inconnu")
        role = ROLES_IMPORT.get(role_brut, Role.AGENT)

        champs = {
            "nom": nom,
            "prenom": prenom,
            "email": ligne.get("email", ""),
            "telephone": ligne.get("telephone", ""),
            "role": role,
            "region": ligne.get("region", ""),
            "is_active": _actif_import(ligne.get("actif", "")),
        }

        existant = Utilisateur.objects.filter(matricule=matricule).first()
        if existant:
            for attribut, valeur in champs.items():
                setattr(existant, attribut, valeur)
            existant.save()
            return existant, False

        nouvel_utilisateur = Utilisateur(matricule=matricule, **champs)
        # Un compte importé n'a jamais de mot de passe utilisable : c'est au
        # service mutuelle de lui en attribuer un, depuis la fiche, pas au
        # fichier d'origine de le transporter en clair.
        nouvel_utilisateur.set_unusable_password()
        nouvel_utilisateur.save()
        return nouvel_utilisateur, True


class UtilisateurMotDePasse(AccesModification, TemplateView):
    template_name = "backoffice/formulaire.html"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        utilisateur = get_object_or_404(Utilisateur, pk=kwargs["pk"])
        contexte["titre"] = f"Mot de passe — {utilisateur.matricule}"
        contexte["form"] = styliser(kwargs.get("form") or forms.MotDePasseForm())
        contexte["url_retour"] = reverse("backoffice:utilisateur_modifier", args=[utilisateur.pk])
        return contexte

    def post(self, request, pk):
        utilisateur = get_object_or_404(Utilisateur, pk=pk)
        form = forms.MotDePasseForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(pk=pk, form=form))
        utilisateur.set_password(form.cleaned_data["mot_de_passe"])
        utilisateur.save()
        messages.success(request, f"Mot de passe de {utilisateur.matricule} mis à jour.")
        return redirect("backoffice:utilisateurs")


# --- Paramétrage ----------------------------------------------------------


class ParametrageModifier(FormulaireBase, UpdateView):
    model = Parametrage
    form_class = forms.ParametrageForm
    titre = "Paramètres de la mutuelle"
    success_url = reverse_lazy("backoffice:parametrage")

    def get_object(self, queryset=None):
        return Parametrage.charger()


class BaremeListe(ListeBase):
    model = TrancheQuota
    titre = "Barème des quotas"
    url_creation = "backoffice:bareme_creer"
    libelle_creation = "Nouvelle tranche"
    url_detail = "backoffice:bareme_modifier"
    colonnes = (
        ("Ordre", "ordre"),
        ("Libellé", "libelle"),
        ("Conjoint", "get_partenaire_display"),
        ("Enfants", lambda o: f"{o.enfants_min} et plus" if o.enfants_max is None
                    else (f"{o.enfants_min}" if o.enfants_min == o.enfants_max
                          else f"{o.enfants_min} à {o.enfants_max}")),
        ("Quota mensuel", lambda o: f"{o.montant} KMF"),
    )


class BaremeCreer(FormulaireBase, CreateView):
    model = TrancheQuota
    form_class = forms.TrancheQuotaForm
    titre = "Nouvelle tranche de quota"
    success_url = reverse_lazy("backoffice:bareme")


class BaremeModifier(FormulaireBase, UpdateView):
    model = TrancheQuota
    form_class = forms.TrancheQuotaForm
    titre = "Modifier la tranche"
    success_url = reverse_lazy("backoffice:bareme")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["url_supprimer"] = reverse("backoffice:bareme_supprimer", args=[self.object.pk])
        return contexte


class BaremeSupprimer(SupprimerBase):
    model = TrancheQuota
    url_liste = "backoffice:bareme"
    libelle = "Tranche de barème"


# --- Anomalies ------------------------------------------------------------


def _periode_demandee(requete):
    """Bornes choisies sur l'écran, avec repli sur la fenêtre paramétrée.

    Une date illisible est ignorée plutôt que de renvoyer une erreur : l'écran
    doit toujours afficher quelque chose.
    """
    from datetime import datetime

    from anomalies import services

    defaut_debut, defaut_fin = services.periode_par_defaut()

    def lire(nom, defaut):
        brut = requete.GET.get(nom, "")
        try:
            return datetime.strptime(brut, "%Y-%m-%d").date()
        except ValueError:
            return defaut

    return lire("debut", defaut_debut), lire("fin", defaut_fin)


class AnomaliesView(AccesBackoffice, TemplateView):
    """Toutes les familles d'anomalies sur un écran, avec leur export.

    Les tableaux sont décrits dans `tableaux.py` : l'écran et le fichier CSV
    lisent la même définition, et ne peuvent donc pas diverger.
    """

    template_name = "backoffice/anomalies.html"

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        debut, fin = _periode_demandee(self.request)

        contexte["debut"] = debut
        contexte["fin"] = fin
        contexte["tableaux"] = [
            {
                "cle": tableau.cle,
                "titre": tableau.titre,
                "description": tableau.description,
                "suit_la_periode": tableau.suit_la_periode,
                "colonnes": [libelle for libelle, _ in tableau.colonnes],
                "lignes": [
                    [exports.valeur(objet, extracteur) for _, extracteur in tableau.colonnes]
                    for objet in tableau.lignes(debut, fin)
                ],
            }
            for tableau in tableaux.TABLEAUX
        ]
        contexte["total"] = sum(len(t["lignes"]) for t in contexte["tableaux"])
        return contexte


class AnomaliesExport(AccesBackoffice, View):
    """Export CSV d'une famille d'anomalies, ou de toutes en un seul fichier."""

    def get(self, request, famille="tout"):
        debut, fin = _periode_demandee(request)
        entete = (
            ["Mutuelle santé — export des anomalies"],
            ["Période analysée", f"du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"],
            ["Édité le", f"{timezone.localdate():%d/%m/%Y}"],
            ["Édité par", request.user.get_full_name()],
        )

        if famille == "tout":
            sections = [
                (tableau.titre, tableau.colonnes, tableau.lignes(debut, fin))
                for tableau in tableaux.TABLEAUX
            ]
            return exports.reponse_csv_sections(
                exports.nom_de_fichier("anomalies", debut, fin), sections, entete
            )

        tableau = tableaux.PAR_CLE.get(famille)
        if tableau is None:
            raise Http404("Famille d'anomalies inconnue.")
        return exports.reponse_csv(
            exports.nom_de_fichier(f"anomalies-{tableau.cle}", debut, fin),
            tableau.colonnes,
            tableau.lignes(debut, fin),
            entete,
        )


# --- Rapports d'activité --------------------------------------------------


def _periode_rapport(requete):
    """Même lecture que pour les anomalies, mais sur douze mois par défaut :
    une activité se juge sur une saison complète."""
    from datetime import datetime

    from rapports import services as rapports_services

    defaut_debut, defaut_fin = rapports_services.periode_par_defaut()

    def lire(nom, defaut):
        try:
            return datetime.strptime(requete.GET.get(nom, ""), "%Y-%m-%d").date()
        except ValueError:
            return defaut

    return lire("debut", defaut_debut), lire("fin", defaut_fin)


class RapportsView(AccesBackoffice, TemplateView):
    """Rapports d'activité : ce que la mutuelle a produit sur la période.

    Volontairement séparé des anomalies : piloter et détecter ne se lisent pas
    dans le même écran ni avec la même fenêtre de temps.
    """

    template_name = "backoffice/rapports.html"

    def get_context_data(self, **kwargs):
        from rapports import services as rapports_services

        contexte = super().get_context_data(**kwargs)
        debut, fin = _periode_rapport(self.request)

        contexte["debut"] = debut
        contexte["fin"] = fin
        contexte["synthese"] = rapports_services.activite_globale(debut, fin)
        contexte["tableaux"] = [
            {
                "cle": tableau.cle,
                "titre": tableau.titre,
                "description": tableau.description,
                "suit_la_periode": tableau.suit_la_periode,
                "colonnes": [libelle for libelle, _ in tableau.colonnes],
                "lignes": [
                    [exports.valeur(objet, extracteur) for _, extracteur in tableau.colonnes]
                    for objet in tableau.lignes(debut, fin)
                ],
            }
            for tableau in tableaux.RAPPORTS
        ]
        return contexte


class RapportsExport(AccesBackoffice, View):
    """Export CSV d'un rapport, ou du dossier complet en un seul fichier."""

    def get(self, request, rapport="tout"):
        from rapports import services as rapports_services

        debut, fin = _periode_rapport(request)
        synthese = rapports_services.activite_globale(debut, fin)
        entete = (
            ["Mutuelle santé — rapport d'activité"],
            ["Période", f"du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"],
            ["Édité le", f"{timezone.localdate():%d/%m/%Y}"],
            ["Édité par", request.user.get_full_name()],
            [],
            ["Actes enregistrés", synthese["nombre_actes"]],
            ["Agents ayant consommé", synthese["nombre_agents_consommateurs"]],
            ["Coût total des soins (KMF)", synthese["cout_total_soins"]],
            ["Part mutuelle (KMF)", synthese["part_mutuelle"]],
            ["Part agents (KMF)", synthese["part_agents"]],
            ["Panier moyen (KMF)", synthese["panier_moyen"]],
        )

        if rapport == "tout":
            sections = [
                (tableau.titre, tableau.colonnes, tableau.lignes(debut, fin))
                for tableau in tableaux.RAPPORTS
            ]
            return exports.reponse_csv_sections(
                exports.nom_de_fichier("rapport-activite", debut, fin), sections, entete
            )

        tableau = tableaux.RAPPORTS_PAR_CLE.get(rapport)
        if tableau is None:
            raise Http404("Rapport inconnu.")
        return exports.reponse_csv(
            exports.nom_de_fichier(f"rapport-{tableau.cle}", debut, fin),
            tableau.colonnes,
            tableau.lignes(debut, fin),
            entete,
        )


class NatureSoinListe(ListeBase):
    model = NatureSoin
    titre = "Natures de soin"
    url_creation = "backoffice:nature_creer"
    libelle_creation = "Nouvelle nature"
    url_detail = "backoffice:nature_modifier"
    champs_recherche = ("libelle",)
    colonnes = (
        ("Ordre", "ordre"),
        ("Libellé", "libelle"),
        ("Proposée à la saisie", "active"),
        ("Prescriptions", lambda o: o.prescriptions.count()),
    )


class NatureSoinCreer(FormulaireBase, CreateView):
    model = NatureSoin
    form_class = forms.NatureSoinForm
    titre = "Nouvelle nature de soin"
    success_url = reverse_lazy("backoffice:natures")


class NatureSoinModifier(FormulaireBase, UpdateView):
    model = NatureSoin
    form_class = forms.NatureSoinForm
    titre = "Modifier la nature de soin"
    success_url = reverse_lazy("backoffice:natures")

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        contexte["url_supprimer"] = reverse("backoffice:nature_supprimer", args=[self.object.pk])
        return contexte


class NatureSoinSupprimer(SupprimerBase):
    model = NatureSoin
    url_liste = "backoffice:natures"
    libelle = "Nature de soin"
