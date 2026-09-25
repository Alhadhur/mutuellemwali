class Utilisateur {
  final String matricule;
  final String nom;
  final String prenom;
  final String role;
  final String roleDisplay;
  final String region;
  final String? photoUrl;

  Utilisateur({
    required this.matricule,
    required this.nom,
    required this.prenom,
    required this.role,
    required this.roleDisplay,
    required this.region,
    required this.photoUrl,
  });

  String get nomComplet => '$prenom $nom'.trim();

  String get initiales {
    final p = prenom.isNotEmpty ? prenom[0] : '';
    final n = nom.isNotEmpty ? nom[0] : '';
    return '$p$n'.toUpperCase();
  }

  factory Utilisateur.fromJson(Map<String, dynamic> json) => Utilisateur(
        matricule: json['matricule'],
        nom: json['nom'],
        prenom: json['prenom'],
        role: json['role'],
        roleDisplay: json['role_display'],
        region: json['region'] ?? '',
        photoUrl: json['photo'],
      );
}

class MonCompte {
  final String matricule;
  final String nom;
  final String prenom;
  final String email;
  final String telephone;
  final String region;
  final String roleDisplay;

  MonCompte({
    required this.matricule,
    required this.nom,
    required this.prenom,
    required this.email,
    required this.telephone,
    required this.region,
    required this.roleDisplay,
  });

  factory MonCompte.fromJson(Map<String, dynamic> json) => MonCompte(
        matricule: json['matricule'],
        nom: json['nom'],
        prenom: json['prenom'],
        email: json['email'] ?? '',
        telephone: json['telephone'] ?? '',
        region: json['region'] ?? '',
        roleDisplay: json['role_display'] ?? '',
      );
}

class AyantDroit {
  final int id;
  final String nom;
  final String prenom;
  final String lienParenteDisplay;
  final String statutVerification;
  final String statutVerificationDisplay;
  final String? dateValidite;
  final int consommationPeriode;
  final bool estExpire;
  final int? age;
  final int? ageLimite;
  final bool limiteAgeDepassee;

  AyantDroit({
    required this.id,
    required this.nom,
    required this.prenom,
    required this.lienParenteDisplay,
    required this.statutVerification,
    required this.statutVerificationDisplay,
    required this.dateValidite,
    required this.consommationPeriode,
    required this.estExpire,
    required this.age,
    required this.ageLimite,
    required this.limiteAgeDepassee,
  });

  factory AyantDroit.fromJson(Map<String, dynamic> json) => AyantDroit(
        id: json['id'],
        nom: json['nom'],
        prenom: json['prenom'],
        lienParenteDisplay: json['lien_parente_display'],
        statutVerification: json['statut_verification'],
        statutVerificationDisplay: json['statut_verification_display'],
        dateValidite: json['date_validite'],
        consommationPeriode: int.parse(json['consommation_periode'].toString()),
        estExpire: json['est_expire'] ?? false,
        age: json['age'],
        ageLimite: json['age_limite'],
        limiteAgeDepassee: json['limite_age_depassee'] ?? false,
      );
}

class AgentProfil {
  final String matricule;
  final String nom;
  final String prenom;
  final String site;
  final int quota;
  final int soldeQuota;
  final int consommationPeriode;
  final String periodeDebut;
  final String periodeFin;
  final List<AyantDroit> ayantsDroit;

  AgentProfil({
    required this.matricule,
    required this.nom,
    required this.prenom,
    required this.site,
    required this.quota,
    required this.soldeQuota,
    required this.consommationPeriode,
    required this.periodeDebut,
    required this.periodeFin,
    required this.ayantsDroit,
  });

  factory AgentProfil.fromJson(Map<String, dynamic> json) => AgentProfil(
        matricule: json['matricule'],
        nom: json['nom'],
        prenom: json['prenom'],
        site: json['site'],
        quota: int.parse(json['quota'].toString()),
        soldeQuota: int.parse(json['solde_quota'].toString()),
        consommationPeriode: int.parse(json['consommation_periode'].toString()),
        periodeDebut: json['periode_debut'] ?? '',
        periodeFin: json['periode_fin'] ?? '',
        ayantsDroit: (json['ayants_droit'] as List).map((e) => AyantDroit.fromJson(e)).toList(),
      );
}

class Prestataire {
  final int id;
  final String code;
  final String nom;
  final String typePrestataire;
  final String typePrestataireDisplay;
  final String ville;
  final double tauxPriseEnCharge;

  Prestataire({
    required this.id,
    required this.code,
    required this.nom,
    required this.typePrestataire,
    required this.typePrestataireDisplay,
    required this.ville,
    required this.tauxPriseEnCharge,
  });

  factory Prestataire.fromJson(Map<String, dynamic> json) => Prestataire(
        id: json['id'],
        code: json['code'],
        nom: json['nom'],
        typePrestataire: json['type_prestataire'],
        typePrestataireDisplay: json['type_prestataire_display'],
        ville: json['ville'] ?? '',
        tauxPriseEnCharge: double.parse(json['taux_prise_en_charge'].toString()),
      );
}

class NatureSoin {
  final int id;
  final String libelle;

  NatureSoin({required this.id, required this.libelle});

  factory NatureSoin.fromJson(Map<String, dynamic> json) =>
      NatureSoin(id: json['id'], libelle: json['libelle']);
}

class HistoriqueStatut {
  final String ancienStatut;
  final String nouveauStatut;
  final String nouveauStatutDisplay;
  final String commentaire;
  final String dateChangement;

  HistoriqueStatut({
    required this.ancienStatut,
    required this.nouveauStatut,
    required this.nouveauStatutDisplay,
    required this.commentaire,
    required this.dateChangement,
  });

  factory HistoriqueStatut.fromJson(Map<String, dynamic> json) => HistoriqueStatut(
        ancienStatut: json['ancien_statut'] ?? '',
        nouveauStatut: json['nouveau_statut'],
        nouveauStatutDisplay: json['nouveau_statut_display'] ?? json['nouveau_statut'],
        commentaire: json['commentaire'] ?? '',
        dateChangement: json['date_changement'] ?? '',
      );
}

class Prescription {
  final int id;
  final int? ayantDroit;
  final String beneficiaireNom;
  final int prestataire;
  final String prestataireNom;
  final String natureLibelle;
  final String numeroOrdonnance;
  final int montantTotal;
  final int montantRembourse;
  final String dateEmission;
  final String? justificatifUrl;
  final String statut;
  final String statutDisplay;
  final String motifSignalement;
  final String dateCreation;
  final List<HistoriqueStatut> historique;

  Prescription({
    required this.id,
    required this.ayantDroit,
    required this.beneficiaireNom,
    required this.prestataire,
    required this.prestataireNom,
    required this.natureLibelle,
    required this.numeroOrdonnance,
    required this.montantTotal,
    required this.montantRembourse,
    required this.dateEmission,
    required this.justificatifUrl,
    required this.statut,
    required this.statutDisplay,
    required this.motifSignalement,
    required this.dateCreation,
    required this.historique,
  });

  factory Prescription.fromJson(Map<String, dynamic> json) => Prescription(
        id: json['id'],
        ayantDroit: json['ayant_droit'],
        beneficiaireNom: json['beneficiaire_nom'] ?? '',
        prestataire: json['prestataire'],
        prestataireNom: json['prestataire_nom'] ?? '',
        natureLibelle: json['nature_libelle'] ?? '',
        numeroOrdonnance: json['numero_ordonnance'],
        montantTotal: int.parse(json['montant_total'].toString()),
        montantRembourse: int.parse(json['montant_rembourse'].toString()),
        dateEmission: json['date_emission'],
        justificatifUrl: json['justificatif'],
        statut: json['statut'],
        statutDisplay: json['statut_display'] ?? json['statut'],
        motifSignalement: json['motif_signalement'] ?? '',
        dateCreation: json['date_creation'] ?? '',
        historique: (json['historique'] as List? ?? [])
            .map((e) => HistoriqueStatut.fromJson(e))
            .toList(),
      );
}
