import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mutuelle_sante_mobile/main.dart';

void main() {
  testWidgets('sans session enregistrée, l\'app ouvre l\'écran de connexion',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});

    await tester.pumpWidget(const MutuelleSanteApp());

    // Le temps de lire le jeton stocké, l'app affiche un indicateur d'attente.
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Se connecter'), findsOneWidget);
    expect(find.text('Matricule'), findsOneWidget);
  });
}
