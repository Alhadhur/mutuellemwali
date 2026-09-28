import 'package:flutter/material.dart';

/// Clavier numérique + puces de progression pour la saisie d'un code PIN.
///
/// Composant contrôlé : [valeur] et [onChanged] appartiennent à l'appelant,
/// pour qu'il puisse imposer un état (ex. figer l'affichage en rouge un
/// instant après un code refusé) sans que le widget ne réinitialise la
/// saisie de son côté.
class PinEntryPad extends StatelessWidget {
  final int longueur;
  final String valeur;
  final ValueChanged<String> onChanged;
  final bool enErreur;
  final Widget? actionSupplementaire;

  const PinEntryPad({
    super.key,
    this.longueur = 4,
    required this.valeur,
    required this.onChanged,
    this.enErreur = false,
    this.actionSupplementaire,
  });

  void _ajouter(String chiffre) {
    if (valeur.length >= longueur) return;
    onChanged(valeur + chiffre);
  }

  void _effacer() {
    if (valeur.isEmpty) return;
    onChanged(valeur.substring(0, valeur.length - 1));
  }

  static const _lignes = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
  ];

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    final couleurPuce = enErreur ? Colors.red : accent;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: List.generate(longueur, (i) {
            final rempli = i < valeur.length;
            return AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              margin: const EdgeInsets.symmetric(horizontal: 8),
              width: 16,
              height: 16,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: rempli ? couleurPuce : Colors.transparent,
                border: Border.all(color: couleurPuce, width: 1.5),
              ),
            );
          }),
        ),
        const SizedBox(height: 28),
        for (final ligne in _lignes)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [for (final chiffre in ligne) _Touche(chiffre, () => _ajouter(chiffre))],
            ),
          ),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(
              width: 72,
              height: 72,
              child: actionSupplementaire,
            ),
            _Touche('0', () => _ajouter('0')),
            SizedBox(
              width: 72,
              height: 72,
              child: IconButton(
                onPressed: _effacer,
                icon: const Icon(Icons.backspace_outlined),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _Touche extends StatelessWidget {
  final String chiffre;
  final VoidCallback onTap;

  const _Touche(this.chiffre, this.onTap);

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 72,
      height: 72,
      child: Material(
        color: Colors.transparent,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onTap,
          child: Center(
            child: Text(chiffre, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w500)),
          ),
        ),
      ),
    );
  }
}
