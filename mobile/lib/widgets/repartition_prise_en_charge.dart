import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/models.dart';

/// Montre à l'agent ce que la mutuelle prendra en charge et ce qui restera à
/// sa charge.
///
/// Sa raison d'être est de lever l'ambiguïté sur le montant à saisir : c'est
/// le coût **total** du soin qui est attendu, pas la part réglée au guichet.
class RepartitionPriseEnCharge extends StatelessWidget {
  final Prestataire? prestataire;
  final NatureSoin? natureSoin;
  final String montantSaisi;

  const RepartitionPriseEnCharge({
    super.key,
    required this.prestataire,
    this.natureSoin,
    required this.montantSaisi,
  });

  @override
  Widget build(BuildContext context) {
    final montant = int.tryParse(montantSaisi.trim());
    final cadre = BoxDecoration(
      color: Colors.grey.shade100,
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: Colors.grey.shade300),
    );

    if (prestataire == null || montant == null || montant <= 0) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: cadre,
        child: Text(
          'Choisissez un prestataire et saisissez le coût pour voir la répartition.',
          style: TextStyle(color: Colors.grey.shade600, fontSize: 12.5),
        ),
      );
    }

    // Le taux détaillé de la nature choisie prime sur le taux général du
    // prestataire, quand ce prestataire en a un pour cette nature.
    final taux = natureSoin?.tauxPriseEnCharge ?? prestataire!.tauxPriseEnCharge;
    final partMutuelle = (montant * taux / 100).round();
    final partAgent = montant - partMutuelle;
    final format = NumberFormat.decimalPatternDigits(locale: 'fr_FR', decimalDigits: 0);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: cadre,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Ligne(
            libelle: 'Pris en charge (${taux.toStringAsFixed(0)} %)',
            montant: '${format.format(partMutuelle)} KMF',
          ),
          const SizedBox(height: 6),
          _Ligne(libelle: 'À votre charge', montant: '${format.format(partAgent)} KMF'),
        ],
      ),
    );
  }
}

class _Ligne extends StatelessWidget {
  final String libelle;
  final String montant;

  const _Ligne({required this.libelle, required this.montant});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(libelle, style: const TextStyle(fontSize: 13)),
        Text(montant, style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.bold)),
      ],
    );
  }
}
