import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mutuelle_sante_mobile/models/models.dart';
import 'package:mutuelle_sante_mobile/widgets/repartition_prise_en_charge.dart';

/// `intl` sépare les milliers en français par une espace fine insécable
/// (U+202F), pas par une espace ordinaire : les libellés attendus doivent
/// employer le même caractère que celui réellement affiché.
String kmf(String montant) => '${montant.replaceAll(' ', '\u202f')} KMF';

Prestataire prestataire({double taux = 80}) => Prestataire(
      id: 1,
      code: 'PHA-0001',
      nom: 'Pharmacie Centrale',
      typePrestataire: 'PHARMACIE',
      typePrestataireDisplay: 'Pharmacie',
      ville: 'Moroni',
      tauxPriseEnCharge: taux,
    );

Future<void> afficher(
  WidgetTester tester, {
  Prestataire? chez,
  required String montant,
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: RepartitionPriseEnCharge(prestataire: chez, montantSaisi: montant),
    ),
  ));
}

void main() {
  testWidgets('la part mutuelle et la part agent sont affichées', (tester) async {
    await afficher(tester, chez: prestataire(), montant: '12000');

    expect(find.text('Pris en charge (80 %)'), findsOneWidget);
    expect(find.text(kmf('9 600')), findsOneWidget);
    expect(find.text('À votre charge'), findsOneWidget);
    expect(find.text(kmf('2 400')), findsOneWidget);
  });

  testWidgets('la répartition suit le taux du prestataire', (tester) async {
    await afficher(tester, chez: prestataire(taux: 65), montant: '10000');

    expect(find.text('Pris en charge (65 %)'), findsOneWidget);
    expect(find.text(kmf('6 500')), findsOneWidget);
    expect(find.text(kmf('3 500')), findsOneWidget);
  });

  testWidgets('le total des deux parts fait le coût du soin', (tester) async {
    await afficher(tester, chez: prestataire(taux: 70), montant: '9999');

    // 70 % de 9999 = 6999,3 arrondi à 6999 ; le reste revient à l'agent.
    expect(find.text(kmf('6 999')), findsOneWidget);
    expect(find.text(kmf('3 000')), findsOneWidget);
  });

  testWidgets('sans prestataire choisi, un message explique quoi faire', (tester) async {
    await afficher(tester, chez: null, montant: '12000');

    expect(
      find.text('Choisissez un prestataire et saisissez le coût pour voir la répartition.'),
      findsOneWidget,
    );
  });

  testWidgets('sans montant saisi, rien n\'est calculé', (tester) async {
    await afficher(tester, chez: prestataire(), montant: '');

    expect(find.textContaining('Pris en charge'), findsNothing);
  });

  testWidgets('un montant invalide ne fait pas planter l\'écran', (tester) async {
    await afficher(tester, chez: prestataire(), montant: 'abc');

    expect(find.textContaining('Pris en charge'), findsNothing);
  });
}
