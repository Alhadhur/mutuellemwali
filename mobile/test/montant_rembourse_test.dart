import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'package:mutuelle_sante_mobile/widgets/montant_rembourse.dart';

TextSpan montantAffiche(WidgetTester tester) {
  final texte = tester.widget<Text>(find.byType(Text));
  return (texte.textSpan! as TextSpan).children!.single as TextSpan;
}

Future<void> afficher(WidgetTester tester, {required bool rejetee}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(body: MontantRembourse(montant: 80000, rejetee: rejetee)),
  ));
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('une prescription rejetée affiche son montant barré', (tester) async {
    await afficher(tester, rejetee: true);

    expect(montantAffiche(tester).style?.decoration, TextDecoration.lineThrough);
    expect(find.bySemanticsLabel('Non remboursé, prescription rejetée'), findsOneWidget);
  });

  testWidgets('une prescription non rejetée affiche son montant normalement', (tester) async {
    await afficher(tester, rejetee: false);

    expect(montantAffiche(tester).style?.decoration, isNull);
    expect(montantAffiche(tester).text, contains('80'));
  });
}
