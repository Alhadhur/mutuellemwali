import 'package:flutter/material.dart';

Color couleurStatutPrescription(String statut) {
  switch (statut) {
    case 'SOUMISE':
      return const Color(0xFF2980B9);
    case 'EN_CONTROLE':
      return const Color(0xFFE67E22);
    case 'VALIDEE':
      return const Color(0xFF27AE60);
    case 'REJETEE':
      return const Color(0xFFC0392B);
    default:
      return Colors.grey;
  }
}

Color couleurStatutVerification(String statut) {
  switch (statut) {
    case 'EN_ATTENTE':
      return const Color(0xFFE67E22);
    case 'VALIDE':
      return const Color(0xFF27AE60);
    case 'REJETE':
      return const Color(0xFFC0392B);
    default:
      return Colors.grey;
  }
}

class StatusBadge extends StatelessWidget {
  final String label;
  final Color color;
  const StatusBadge({super.key, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(12)),
      child: Text(label, style: const TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w600)),
    );
  }
}
