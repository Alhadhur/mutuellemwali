import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

/// « Remboursé : 80 000 » — barré en rouge quand la prescription est rejetée :
/// le montant calculé à la saisie reste affiché pour mémoire, mais il ne sera
/// pas versé (même convention que le back-office).
class MontantRembourse extends StatelessWidget {
  const MontantRembourse({super.key, required this.montant, required this.rejetee});

  final int montant;
  final bool rejetee;

  static final _format = NumberFormat.decimalPatternDigits(locale: 'fr_FR', decimalDigits: 0);

  static const _rouge = Color(0xFFDC2626);

  @override
  Widget build(BuildContext context) {
    final texte = _format.format(montant);
    return Text.rich(
      TextSpan(
        text: 'Remboursé : ',
        children: [
          TextSpan(
            text: texte,
            style: rejetee
                ? const TextStyle(
                    color: _rouge,
                    decoration: TextDecoration.lineThrough,
                    decorationColor: _rouge,
                    decorationThickness: 2,
                  )
                : null,
          ),
        ],
      ),
      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
      semanticsLabel: rejetee ? 'Non remboursé, prescription rejetée' : 'Remboursé : $texte',
    );
  }
}
