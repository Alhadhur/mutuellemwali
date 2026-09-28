// Vérifie le verrouillage (code PIN) de bout en bout, contre le vrai
// stockage sécurisé de la plateforme et un vrai back-end Django local —
// contrairement aux tests de widgets, qui tournent sans ces deux-là.
//
// Nécessite : un serveur Django accessible à l'adresse renvoyée par
// ApiConfig.baseUrl, et un compte de test « TESTPIN » (voir la procédure
// utilisée pour ce test : accounts.Utilisateur + beneficiaires.Agent).
//
// Exécution : flutter test integration_test/verrouillage_test.dart -d linux
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:mutuelle_sante_mobile/main.dart';
import 'package:mutuelle_sante_mobile/services/api_service.dart';
import 'package:mutuelle_sante_mobile/services/lock_service.dart';

Future<void> _saisirPin(WidgetTester tester, String pin) async {
  for (final chiffre in pin.split('')) {
    await tester.tap(find.text(chiffre).first);
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  tearDown(() async {
    await ApiService.instance.logout();
    await LockService.instance.clearPin();
  });

  testWidgets('connexion -> configuration du PIN -> verrouillage au relancement',
      (tester) async {
    await tester.pumpWidget(const MutuelleYatruApp());
    await tester.pumpAndSettle(const Duration(seconds: 2));

    expect(find.text('🛡️ Mutuelle Yatru'), findsOneWidget);

    await tester.enterText(find.byType(TextField).at(0), 'TESTPIN');
    await tester.enterText(find.byType(TextField).at(1), 'TestPin2026!');
    await tester.tap(find.text('Se connecter'));
    await tester.pumpAndSettle(const Duration(seconds: 3));

    // Aucun PIN encore configuré pour ce compte tout neuf : l'app doit le
    // proposer avant d'ouvrir le tableau de bord.
    expect(find.text('Choisissez un code PIN à 4 chiffres'), findsOneWidget);

    await _saisirPin(tester, '1234');
    await tester.pumpAndSettle();
    expect(find.text('Confirmez votre code PIN'), findsOneWidget);

    await _saisirPin(tester, '1234');
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // Ni empreinte ni Face ID sur ce poste de développement Linux : la
    // boîte de dialogue biométrique doit être sautée sans planter, et
    // l'app doit atterrir directement sur le tableau de bord.
    expect(find.text('Empreinte digitale'), findsNothing);
    expect(find.text('Mon profil'), findsOneWidget);
    expect(find.byIcon(Icons.receipt_long_outlined), findsOneWidget);

    // Simule un relancement à froid : la session et le PIN, eux, persistent
    // réellement (jeton en SharedPreferences, PIN haché dans le stockage
    // sécurisé). `pumpWidget` seul ne suffit pas à le simuler : Flutter
    // réutilise le State existant tant que le type du widget racine ne
    // change pas (donc _StartupGateState.initState() ne serait jamais
    // rejoué) — il faut d'abord démonter l'arbre avec un widget vide.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.pumpWidget(const MutuelleYatruApp());
    await tester.pumpAndSettle(const Duration(seconds: 2));

    expect(find.text('Saisissez votre code PIN'), findsOneWidget);
    expect(find.text('Mon profil'), findsNothing);

    // Code faux : refusé, avec un message clair, sans planter.
    await _saisirPin(tester, '0000');
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Code incorrect'), findsOneWidget);
    await tester.pumpAndSettle(const Duration(seconds: 1));

    // Code correct : déverrouille et révèle le tableau de bord.
    await _saisirPin(tester, '1234');
    await tester.pumpAndSettle(const Duration(seconds: 1));
    expect(find.text('Mon profil'), findsOneWidget);
  });
}
