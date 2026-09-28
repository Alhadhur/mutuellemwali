import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mutuelle_sante_mobile/widgets/pin_pad.dart';

Future<void> afficher(
  WidgetTester tester, {
  required String valeur,
  required ValueChanged<String> onChanged,
  bool enErreur = false,
  Widget? actionSupplementaire,
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: PinEntryPad(
        valeur: valeur,
        onChanged: onChanged,
        enErreur: enErreur,
        actionSupplementaire: actionSupplementaire,
      ),
    ),
  ));
}

void main() {
  testWidgets('appuyer sur un chiffre ajoute au code en cours', (tester) async {
    String? recu;
    await afficher(tester, valeur: '1', onChanged: (v) => recu = v);

    await tester.tap(find.text('2'));
    await tester.pump();

    expect(recu, '12');
  });

  testWidgets('le code plein n\'accepte plus de chiffre', (tester) async {
    var appele = false;
    await afficher(tester, valeur: '1234', onChanged: (_) => appele = true);

    await tester.tap(find.text('5'));
    await tester.pump();

    expect(appele, isFalse);
  });

  testWidgets('la touche effacer retire le dernier chiffre', (tester) async {
    String? recu;
    await afficher(tester, valeur: '123', onChanged: (v) => recu = v);

    await tester.tap(find.byIcon(Icons.backspace_outlined));
    await tester.pump();

    expect(recu, '12');
  });

  testWidgets('effacer un code déjà vide ne déclenche rien', (tester) async {
    var appele = false;
    await afficher(tester, valeur: '', onChanged: (_) => appele = true);

    await tester.tap(find.byIcon(Icons.backspace_outlined));
    await tester.pump();

    expect(appele, isFalse);
  });

  testWidgets('l\'action supplémentaire (empreinte) s\'affiche si fournie', (tester) async {
    await afficher(
      tester,
      valeur: '',
      onChanged: (_) {},
      actionSupplementaire: const Icon(Icons.fingerprint),
    );

    expect(find.byIcon(Icons.fingerprint), findsOneWidget);
  });
}
