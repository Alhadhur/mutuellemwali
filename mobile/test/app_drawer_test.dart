import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mutuelle_sante_mobile/models/models.dart';
import 'package:mutuelle_sante_mobile/widgets/app_drawer.dart';

final _agent = Utilisateur(
  matricule: 'A0001',
  nom: 'Zahra',
  prenom: 'Fatima',
  role: 'AGENT',
  roleDisplay: 'Agent (bénéficiaire)',
  region: 'Ngazidja',
  photoUrl: null,
);

/// Monte le menu dans un Scaffold et l'ouvre, en renvoyant les onglets choisis.
Future<List<int>> _ouvrirMenu(
  WidgetTester tester, {
  Utilisateur? utilisateur,
  List<SectionMenu>? sections,
  VoidCallback? action,
}) async {
  final choisis = <int>[];
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      drawer: AppDrawer(
        utilisateur: utilisateur,
        ongletCourant: 0,
        onOngletChoisi: choisis.add,
        sections: sections ??
            [
              const SectionMenu(titre: 'Mon dossier', entrees: [
                EntreeMenu(icone: Icons.person_outline, libelle: 'Mon profil', ongletIndex: 0),
                EntreeMenu(icone: Icons.receipt_long_outlined, libelle: 'Mes prescriptions', ongletIndex: 2),
                EntreeMenu(icone: Icons.notifications_none, libelle: 'Notifications de statut', disponible: false),
              ]),
              SectionMenu(titre: 'Compte', entrees: [
                EntreeMenu(icone: Icons.logout, libelle: 'Se déconnecter', action: action ?? () {}),
              ]),
            ],
      ),
      body: const SizedBox(),
    ),
  ));
  tester.state<ScaffoldState>(find.byType(Scaffold)).openDrawer();
  await tester.pumpAndSettle();
  return choisis;
}

void main() {
  testWidgets("l'en-tête affiche l'identité de l'agent", (tester) async {
    await _ouvrirMenu(tester, utilisateur: _agent);

    expect(find.text('Fatima Zahra'), findsOneWidget);
    expect(find.text('Matricule A0001 · Ngazidja'), findsOneWidget);
    expect(find.text('FZ'), findsOneWidget); // initiales, faute de photo
  });

  testWidgets("l'en-tête reste affiché quand l'identité n'est pas chargée", (tester) async {
    await _ouvrirMenu(tester, utilisateur: null);

    expect(find.text('Chargement…'), findsOneWidget);
    expect(find.text('Mon profil'), findsOneWidget);
  });

  testWidgets('les sections et leurs entrées sont listées', (tester) async {
    await _ouvrirMenu(tester, utilisateur: _agent);

    expect(find.text('MON DOSSIER'), findsOneWidget);
    expect(find.text('COMPTE'), findsOneWidget);
    expect(find.text('Mon profil'), findsOneWidget);
    expect(find.text('Mes prescriptions'), findsOneWidget);
    expect(find.text('Se déconnecter'), findsOneWidget);
  });

  testWidgets('choisir une entrée bascule sur son onglet et ferme le menu', (tester) async {
    final choisis = await _ouvrirMenu(tester, utilisateur: _agent);

    await tester.tap(find.text('Mes prescriptions'));
    await tester.pumpAndSettle();

    expect(choisis, [2]);
    expect(find.text('Mon profil'), findsNothing); // menu refermé
  });

  testWidgets('une entrée action déclenche son callback', (tester) async {
    var deconnexions = 0;
    await _ouvrirMenu(tester, utilisateur: _agent, action: () => deconnexions++);

    await tester.tap(find.text('Se déconnecter'));
    await tester.pumpAndSettle();

    expect(deconnexions, 1);
  });

  testWidgets('une fonctionnalité à venir est signalée et non cliquable', (tester) async {
    final choisis = await _ouvrirMenu(tester, utilisateur: _agent);

    expect(find.text('Bientôt'), findsOneWidget);

    await tester.tap(find.text('Notifications de statut'));
    await tester.pumpAndSettle();

    expect(choisis, isEmpty);
    expect(find.text('Mon profil'), findsOneWidget); // menu toujours ouvert
  });
}
