# Outil de contrôle de la fraude — Mutuelle de santé

Prototype **Phase 1** du cahier des charges : back-office Django (registre
agents/ayants droit, réseau de prestataires, prescriptions + détection de
doublons, tableau de bord anomalies) et application mobile Flutter pour les
agents (profil, ayants droit, soumission de prescriptions avec photo).

## Structure du dépôt

```
mutuelle_sante/
├── backend/          Back-office Django + API REST (DRF + JWT)
├── mobile/           Application mobile Flutter (agents)
└── setup_mysql.sql   Script de création de la base MySQL
```

## 1. Back-office Django

### Installation (déjà faite dans cet environnement)

```bash
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### Base de données

MySQL 8.0, créée via `setup_mysql.sql` (base `mutuelle_sante`, utilisateur
`mutuelle_app`). Les identifiants sont dans `backend/.env` (non versionné —
**à changer avant toute mise en production**).

```bash
sudo mysql < setup_mysql.sql   # une seule fois
cd backend
./venv/bin/python manage.py migrate
```

### Lancer le serveur

```bash
cd backend
./venv/bin/python manage.py runserver 0.0.0.0:8000
```

- **Back-office (RH / Direction)** : http://127.0.0.1:8000/backoffice/
- API REST (consommée par l'app mobile) : http://127.0.0.1:8000/api/
- Admin Django brut, conservé comme filet de secours technique : http://127.0.0.1:8000/admin/

Le back-office est construit sur des écrans métier dédiés (app `backoffice`),
et non sur les pages génériques de l'admin Django :

| Écran | URL |
|---|---|
| Tableau de bord anomalies | `/backoffice/` |
| Agents (liste, fiche, saisie) | `/backoffice/agents/` |
| Ayants droit (+ validation du justificatif) | `/backoffice/ayants-droit/` |
| Prescriptions (saisie papier, historique, doublons, changement de statut) | `/backoffice/prescriptions/` |
| Prestataires (+ suspension / réactivation) | `/backoffice/prestataires/` |
| Factures prestataires (+ rapprochement, validation) | `/backoffice/factures/` |
| Utilisateurs (+ mot de passe) | `/backoffice/utilisateurs/` |
| Paramètres de la mutuelle (cotisation, âge limite) | `/backoffice/parametrage/` |
| Barème des quotas par composition familiale | `/backoffice/bareme/` |

Toutes ces pages partagent le même menu latéral, défini dans
[`backend/config/menu.py`](backend/config/menu.py). **Ajouter une entrée = une
ligne dans `MENU`** : elle apparaît aussitôt partout. Chaque entrée déclare les
rôles qui la voient, ou est marquée `disponible=False` pour annoncer une
fonctionnalité à venir avec la pastille « Bientôt ».

Les listes reposent sur un template unique piloté par l'attribut `colonnes` de
la vue : **ajouter un écran de liste ne demande pas d'écrire un template**.

### Phase 2 — Charger le réseau réel et valider les règles

**1. Préparer le fichier.** Partez de [`modele_reseau_prestataires.csv`](modele_reseau_prestataires.csv).
Seules `type` et `nom` sont obligatoires ; `ville`, `adresse`, `telephone`,
`taux` (défaut 80) et `statut` (défaut actif) sont facultatifs. Le séparateur
(`,` ou `;`) est détecté automatiquement, les libellés français sont acceptés
(`Pharmacie`, `Établissement`, `Clinique`, `Médecin`…), et les fichiers Excel
enregistrés en UTF-8 passent tels quels.

**2. Simuler, puis importer.**

```bash
cd backend
./venv/bin/python manage.py importer_prestataires reseau.csv --dry-run   # contrôle
./venv/bin/python manage.py importer_prestataires reseau.csv             # application
```

L'import est **tout ou rien** : si une seule ligne est invalide, rien n'est
écrit et chaque erreur est signalée avec son numéro de ligne. Il est aussi
**idempotent** : rejouer le fichier met à jour les fiches existantes
(rapprochement sur `code`, sinon sur nom + ville) au lieu de créer des doublons.

**3. Reprendre l'historique des prescriptions.**

Colonnes obligatoires : `agent` (matricule), `prestataire` (code ou nom),
`numero_ordonnance`, `montant_total`, `date_emission`. Facultatives :
`ayant_droit` (« Prénom Nom », rattaché à cet agent), `statut` et
`montant_rembourse`. Les dates sont acceptées en `JJ/MM/AAAA` comme en
`AAAA-MM-JJ`, et les montants décimaux sont arrondis au franc.

```bash
# Confronter d'abord les règles actuelles à l'historique, sans rien écrire
./venv/bin/python manage.py importer_prescriptions historique.csv --mode rejouer

# Puis charger l'historique tel qu'il a été arbitré
./venv/bin/python manage.py importer_prescriptions historique.csv --dry-run
./venv/bin/python manage.py importer_prescriptions historique.csv
```

Le mode `conserver` (défaut) **n'applique pas la détection** : les statuts et
montants du fichier font foi, car ils résultent de décisions déjà prises. Chaque
ligne reprise est tracée dans l'historique comme « Reprise d'historique ».

Le mode `rejouer` n'écrit rien : il applique les règles actuelles à chaque ligne
et compare le verdict au statut réel. C'est la mesure qui compte, car elle
distingue les **fausses alertes** (charge de travail inutile) des **fraudes non
détectées** (les cas qui justifient d'ajouter un critère).

**4. Rapprocher les factures mensuelles des prestataires.**

Chaque prestataire envoie mensuellement une facture détaillant les soins
dispensés. Colonnes attendues : `date`, `matricule`, `beneficiaire`, `nature`
(texte libre), `montant`.

**Quel montant ?** Un soin coûte 100 % : l'agent règle 20 % au guichet, la
mutuelle prend en charge les 80 % restants (le taux est celui de la convention
du prestataire). La colonne `montant` peut porter l'un ou l'autre, `--montant`
indique lequel :

| Option | La colonne `montant` porte |
|---|---|
| `--montant reclame` *(défaut)* | La part réclamée à la mutuelle (les 80 %) |
| `--montant total` | Le coût complet du soin (les 100 %) |

Le montant manquant est déduit du taux. Un fichier fournissant explicitement
`montant_soin` **et** `montant_reclame` prime sur cette déduction — c'est la
forme à privilégier, car elle permet de vérifier que **le taux a bien été
appliqué** : un prestataire qui réclamerait 100 % d'un soin conventionné à 80 %
facturerait à la mutuelle la part que l'agent a déjà payée.

```bash
./venv/bin/python manage.py importer_facture facture.csv \
    --prestataire PHA-0001 --numero F-2026-03 --mois 3 --annee 2026 \
    --total 450000 --dry-run
```

L'import charge les lignes puis lance le rapprochement avec les prescriptions
déclarées sur la période. Il fait ressortir quatre situations :

| Situation | Ce qu'elle révèle |
|---|---|
| **Concordante** | Le soin déclaré et le soin facturé coïncident (agent, date, montant). |
| **Écart de montant** | Le coût du soin facturé diffère de celui déclaré par l'agent. |
| **Taux mal appliqué** | Le coût concorde, mais le prestataire réclame plus que son taux ne l'autorise. |
| **Facturée sans prescription** | Le prestataire facture un soin que personne n'a déclaré. |
| **Déclarée non facturée** | L'agent a déclaré un soin que le prestataire ne réclame pas — cas typique de l'ordonnance fabriquée. |

Le total réclamé en tête de facture est également comparé à la somme réclamée
sur les lignes. **L'import ne valide rien** : le dossier est présenté au service
mutuelle dans `/backoffice/factures/`, qui arbitre. En validant la facture, le
RH confirme d'un coup les prescriptions dont la ligne concorde exactement ; la
référence de la facture est inscrite dans leur historique.

**5. Mesurer les règles de détection sur les données réelles.**

```bash
./venv/bin/python manage.py analyser_detection --fenetres 1,3,5,7,10
```

La commande sépare les deux critères, qui n'ont pas la même force : un même
numéro d'ordonnance est un signal quasi certain, alors qu'un même montant chez
le même prestataire peut simplement traduire un traitement chronique renouvelé.
Elle compare aussi l'effet de la fenêtre (`FENETRE_DOUBLON_JOURS`, actuellement
±5 jours) sur le volume d'alertes, et liste les couples agent/prestataire/montant
qui reviennent souvent — les faux positifs les plus probables.

### Tests

```bash
cd backend
./venv/bin/python manage.py test          # nécessite les droits sur test_mutuelle_sante
```

Si la création de la base de test est refusée, rejouez `sudo mysql < setup_mysql.sql`
(le script accorde désormais les droits sur `test_mutuelle_sante`).

Un compte administrateur a été créé :
- **Matricule** : `ADMIN001`
- **Mot de passe** : `Admin2026!`

⚠️ À changer immédiatement (`./venv/bin/python manage.py changepassword ADMIN001`).

### Données de démonstration

Un jeu de données pilote (3 agents, 3 prestataires, un doublon volontaire) est
disponible dans le script de seed fourni pendant le développement. Pour
repartir sur une base vierge, videz simplement les tables via l'admin ou
`./venv/bin/python manage.py flush`.

### Modules livrés (Phase 1)

| Module | Où le trouver |
|---|---|
| Registre agents / ayants droit | app `beneficiaires`, admin Django |
| Réseau de prestataires conventionnés | app `prestataires` (pharmacies, établissements, praticiens) |
| Prescriptions + détection de doublons | app `prescriptions` (règle : même agent + même prestataire + même n° ordonnance OU montant identique à ±5 jours) |
| Historique horodaté des statuts | modèle `HistoriqueStatut`, visible en admin et via l'API |
| Anomalies + export | app `anomalies` (agrégations) affichée par `/backoffice/anomalies/` — écarts de facturation, prestataires en écart répété, prescriptions en contrôle, volumes anormaux, agents proches du quota, justificatifs expirés. Export CSV par famille ou global. |
| Rapports d'activité | app `rapports` affichée par `/backoffice/rapports/` — fréquence des consultations par agent, assiduité, natures de soin, prestataires, régions, quotas, activité du service, évolution mensuelle. Export CSV. |
| Écrans métier du back-office | app `backoffice` — listes, fiches et formulaires dédiés, en remplacement des pages génériques de l'admin Django |
| Paramétrage RH / Direction | app `parametrage` — quota, âge limite, cotisations, barème, **natures de soin** et **seuils de détection des anomalies**, tous modifiables depuis le back-office |
| Menu latéral du back-office | [`config/menu.py`](backend/config/menu.py) — défini une seule fois, rendu à l'identique dans l'admin Django et le tableau de bord |
| Facturation prestataires | app `facturation` — factures mensuelles rapprochées avec les prescriptions déclarées |
| API REST + JWT | app `api`, consommée par l'app mobile |

### Règles métier implémentées

- **Détection de doublon** : à la création d'une prescription, si une autre
  prescription du même agent, chez le même prestataire, porte le même numéro
  d'ordonnance ou un montant identique à ±5 jours, la prescription est posée
  automatiquement en statut `EN_CONTROLE` — jamais directement `VALIDEE`.
- **Prestataire suspendu** : toute prescription rattachée à un prestataire
  suspendu est également mise en contrôle (montant remboursable = 0 tant
  qu'elle n'est pas traitée manuellement).
- **Devise** : tous les montants sont exprimés en **KMF**, sans décimale (champs
  entiers en base, saisie et affichage sans centimes).
- **Quota mensuel, enveloppe familiale** : le quota est porté par l'**agent** et
  partagé avec l'ensemble de ses ayants droit — les soins de l'agent et ceux de
  sa famille puisent dans la même enveloppe, remise à zéro chaque mois. La
  consommation propre à chaque ayant droit reste consultable, à titre indicatif.
- **Cycle de consommation paramétrable** : le barème donne un montant
  **mensuel** ; l'enveloppe réellement ouverte vaut ce montant **multiplié par
  la durée du cycle** (`duree_cycle_mois`, 1 par défaut, réglable à 2 ou 3).
  Un agent seul disposera donc de 21 300 KMF sur 1 mois, 42 600 sur 2 mois ou
  63 900 sur 3 mois. À l'échéance, **le quota repart au montant plein et le
  reliquat non consommé est perdu** — il n'y a pas de report. Les cycles sont
  calés sur l'année civile, si bien que le renouvellement tombe toujours au
  1er janvier :

  | Durée | Cycles |
  |---|---|
  | 1 mois | janvier, février, … |
  | 2 mois | janv-févr, mars-avril, mai-juin, … |
  | 3 mois | janv-mars, avril-juin, juil-sept, oct-déc |

- **Le quota découle de la composition familiale**, via un barème éditable dans
  `/backoffice/bareme/` (aucune saisie de quota sur la fiche agent). Les tranches
  sont évaluées dans l'ordre et **la première qui correspond l'emporte**, ce qui
  permet d'insérer un cas particulier avant une règle plus générale. Barème
  initial :

  Les montants du barème sont **mensuels**, quelle que soit la durée du cycle.

  | Conjoint | Enfants | Quota mensuel |
  |---|---|---|
  | sans | 0 | 21 300 KMF |
  | avec | 0 | 25 100 KMF |
  | peu importe | 1 | 25 100 KMF |
  | peu importe | 2 | 33 700 KMF |
  | peu importe | 3 à 4 | 37 400 KMF |
  | peu importe | 5 et plus | 39 300 KMF |

- **Cotisation** : un montant de base couvre l'agent et les ayants droit inclus
  (par défaut 1 conjoint et 3 enfants). Au-delà, chaque conjoint ou enfant
  supplémentaire est facturé (2 000 KMF par défaut). Base, seuils inclus et
  coûts unitaires se règlent dans `/backoffice/parametrage/`. **La cotisation
  reste due chaque mois**, indépendamment de la durée du cycle de quota.
- **Ne comptent que les ayants droit réellement couverts** : un dossier non
  validé, ou un enfant ayant dépassé l'âge limite, n'ouvre aucun droit et n'est
  pas facturé à l'agent.
- **Limite d'âge des enfants** : un ayant droit de lien `ENFANT` n'est plus
  couvert à partir de l'âge limite paramétré (**18 ans** par défaut). Le calcul
  se fait à la volée depuis `date_naissance` et est signalé dans l'admin comme
  dans l'app mobile.
- **Calcul du remboursement** : `montant_rembourse = montant_total × taux applicable`, arrondi à
  l'entier KMF le plus proche. Le taux est celui du **tarif détaillé** pour la nature de soin de la
  prescription chez ce prestataire (`TarifPrestataire`) s'il existe — une consultation et une
  chirurgie dans le même hôpital peuvent ainsi être remboursées à des taux différents — sinon le
  taux général du prestataire s'applique, comme avant l'ajout de ces tarifs. Gérable depuis la fiche
  du prestataire (`/backoffice/prestataires/<id>/`) ; l'app mobile ne propose à l'agent que les
  natures réellement tarifées chez le prestataire choisi, tant qu'au moins une l'est.
- **Validation jamais automatique à la soumission** : une prescription ne peut
  pas devenir `VALIDEE` ou `REJETEE` d'elle-même. Deux chemins seulement y
  mènent, tous deux déclenchés par une action humaine : l'arbitrage individuel
  par le service mutuelle, ou **la validation d'une facture prestataire**, qui
  confirme d'un coup les prescriptions dont la ligne facturée concorde
  exactement (voir ci-dessous). Les lignes en écart ne valident rien.
- **Justificatifs expirés** : calculés à la volée (`est_expire`) et listés
  dans le tableau de bord anomalies.

### Rôles

| Rôle | Accès |
|---|---|
| `AGENT` | API mobile uniquement : son profil, ses ayants droit, ses prescriptions |
| `RH` | Back-office complet (admin) + tableau de bord anomalies |
| `DIRECTION` | Tableau de bord anomalies (lecture) |
| `PRESTATAIRE` | Réservé pour une phase ultérieure (saisie directe par les prestataires) |

## 2. Application mobile Flutter (agents)

```bash
cd mobile
flutter pub get
flutter run            # sur un appareil/émulateur connecté
flutter build apk      # génère un APK Android
flutter build web       # génère une version web (build/web)
```

### Configuration de l'adresse du serveur

Le fichier [`mobile/lib/services/api_config.dart`](mobile/lib/services/api_config.dart)
détermine l'URL du back-office :
- Émulateur Android → `http://10.0.2.2:8000/api` (résolu automatiquement)
- Web / Linux / appareil physique → adapter l'IP réelle du serveur (une
  adresse `127.0.0.1` ne fonctionne pas depuis un téléphone séparé).

### Fonctionnalités

- Connexion par matricule + mot de passe (JWT, rafraîchi automatiquement).
- **Mon profil** : quota mensuel de la famille, consommation du mois (agent +
  ayants droit), solde restant (KMF).
- **Mes ayants droit** : statut de vérification, consommation du mois, âge,
  alerte justificatif expiré et alerte limite d'âge atteinte.
- **Mes prescriptions** : historique avec statut (soumise / en contrôle /
  validée / rejetée) et motif de signalement le cas échéant.
- **Soumission** : photo (caméra ou galerie), prestataire, **nature du soin**,
  bénéficiaire, numéro d'ordonnance, coût total, date — avec l'affichage de la
  répartition 80/20 pendant la saisie. Envoyé à l'API qui applique
  immédiatement la détection de doublon.

## 3. Mise en ligne sur Render

L'infrastructure est décrite dans [`render.yaml`](render.yaml) : Render lit ce
fichier et crée lui-même le service web, la base PostgreSQL et le disque des
justificatifs. Rien n'est à cliquer, hormis les secrets.

### Ce qui change par rapport au poste de développement

| | Développement | Render |
|---|---|---|
| Base | MySQL local (`DB_*` dans `.env`) | PostgreSQL, via `DATABASE_URL` |
| Statiques | servis par Django en mode debug | WhiteNoise, versionnés et compressés |
| Justificatifs | `backend/media/` | disque persistant monté sur `/var/data/media` |
| Serveur | `runserver` | gunicorn, 2 processus |

Le choix du moteur se fait au démarrage, d'après la présence de `DATABASE_URL` :
**le code est identique dans les deux cas**, il n'y a pas de branche
« production » à maintenir.

### 1. Créer les services

1. Sur render.com : **New → Blueprint**, puis choisir le dépôt
   `Alhadhur/mutuellemwali`.
2. Render détecte `render.yaml` et propose le service et la base. Valider.
3. Renseigner les variables marquées à remplir à la main :

| Variable | Valeur |
|---|---|
| `ADMIN_MATRICULE` | le matricule du premier compte administrateur |
| `ADMIN_MOT_DE_PASSE` | un mot de passe solide, **utilisé une seule fois** |
| `ALLOWED_HOSTS` | à laisser vide, sauf domaine personnalisé |
| `CSRF_TRUSTED_ORIGINS` | idem |
| `CORS_ALLOWED_ORIGINS` | uniquement si l'application mobile est servie sur le web |

`SECRET_KEY` est générée par Render ; elle n'a pas à être saisie ni conservée.

Le compte administrateur est créé au premier déploiement puis **plus jamais
touché** : un mot de passe changé depuis l'interface n'est pas réécrit au
déploiement suivant. Le changer dès la première connexion, puis vider
`ADMIN_MOT_DE_PASSE` dans le tableau de bord.

### 2. Reprendre les données existantes

Depuis le poste de développement, avec la base MySQL en service :

```bash
cd backend
./venv/bin/python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    --exclude sessions.session --exclude admin.logentry \
    --indent 2 -o donnees_a_reprendre.json
```

Puis, depuis un shell Render (onglet **Shell** du service) après avoir téléversé
le fichier, ou en local en pointant `DATABASE_URL` sur la base Render :

```bash
DATABASE_URL="<External Database URL fournie par Render>" \
    ./venv/bin/python manage.py loaddata donnees_a_reprendre.json
```

Le fichier contient des données nominatives : il est exclu du dépôt par
`.gitignore`, et doit être supprimé une fois la reprise faite.

Les justificatifs déjà déposés (`backend/media/`) sont à recopier séparément
vers le disque monté, l'export JSON ne contient que les chemins.

### 3. Pointer l'application mobile sur le serveur

L'adresse n'est plus dans le code : elle est fournie à la compilation, ce qui
évite de livrer un binaire pointant sur un poste de développement.

```bash
cd mobile
flutter build apk --release \
    --dart-define=API_BASE_URL=https://<votre-service>.onrender.com/api
```

### Points de vigilance

- **Le plan gratuit ne convient pas à un usage réel.** La base PostgreSQL
  gratuite est supprimée au bout de 30 jours, et un service gratuit s'endort
  après 15 minutes sans trafic — le premier appel de la matinée attendrait
  environ une minute. Le disque persistant exige de toute façon un plan payant.
- **Le disque n'est pas la base.** Render sauvegarde automatiquement la base de
  données, pas le disque. Prévoir une copie régulière des justificatifs.
- **HSTS** (`SECURE_HSTS_SECONDS`) est laissé à 0 par défaut. Ne l'activer
  qu'une fois le domaine définitivement en HTTPS : un navigateur mémorise la
  consigne pour toute la durée indiquée.
- **Données de santé.** L'application héberge des ordonnances et des actes de
  naissance nominatifs. Le choix de la région (`frankfurt` dans `render.yaml`),
  la durée de conservation et les accès relèvent d'une décision de la mutuelle,
  pas d'un réglage technique.

## 4. Prochaines étapes (suite du cahier des charges)

- **Phase 2** : peupler le réseau de pharmacies/établissements réels,
  valider les règles de détection sur des données réelles.
- **Phase 3** : workflow de validation complet côté mobile (notifications de
  statut, upload facture + ordonnance séparés).
- **Phase 4** *(fait)* : écran des anomalies avec export CSV, rapports
  d'activité, et seuils de détection configurables depuis le back-office.
  Reste à faire si besoin : les graphiques.
- **Phase 5** : déploiement aux 2 000+ agents. La mise en ligne sur Render est
  décrite en section 3 (`DEBUG=False`, HTTPS, cookies sécurisés et disque
  persistant sont déjà configurés). Restent à traiter : la sauvegarde régulière
  du disque des justificatifs, le dimensionnement du plan, et éventuellement
  l'authentification par SMS mentionnée au cahier des charges.
