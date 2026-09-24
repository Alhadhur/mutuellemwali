import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_service.dart';
import '../widgets/app_drawer.dart';
import 'login_screen.dart';
import 'profil_tab.dart';
import 'ayants_droit_tab.dart';
import 'prescriptions_tab.dart';
import 'prescription_form_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _index = 0;
  Utilisateur? _utilisateur;

  // Incrémenté après une soumission : remonte l'onglet pour qu'il recharge.
  int _versionPrescriptions = 0;

  static const _titres = ['Mon profil', 'Mes ayants droit', 'Mes prescriptions'];

  @override
  void initState() {
    super.initState();
    _chargerUtilisateur();
  }

  Future<void> _chargerUtilisateur() async {
    try {
      final utilisateur = await ApiService.instance.getMoi();
      if (mounted) setState(() => _utilisateur = utilisateur);
    } catch (_) {
      // Identité indisponible (réseau) : le menu reste utilisable sans en-tête.
    }
  }

  Future<void> _seDeconnecter() async {
    await ApiService.instance.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  Future<void> _nouvellePrescription() async {
    final cree = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const PrescriptionFormScreen()),
    );
    if (cree == true && mounted) {
      setState(() {
        _versionPrescriptions++;
        _index = 2;
      });
    }
  }

  List<SectionMenu> get _sections => [
        const SectionMenu(
          titre: 'Mon dossier',
          entrees: [
            EntreeMenu(icone: Icons.person_outline, libelle: 'Mon profil', ongletIndex: 0),
            EntreeMenu(icone: Icons.family_restroom_outlined, libelle: 'Mes ayants droit', ongletIndex: 1),
            EntreeMenu(icone: Icons.receipt_long_outlined, libelle: 'Mes prescriptions', ongletIndex: 2),
            EntreeMenu(
              icone: Icons.notifications_none,
              libelle: 'Notifications de statut',
              disponible: false,
            ),
          ],
        ),
        SectionMenu(
          titre: 'Démarches',
          entrees: [
            EntreeMenu(
              icone: Icons.add_a_photo_outlined,
              libelle: 'Nouvelle prescription',
              action: _nouvellePrescription,
            ),
          ],
        ),
        SectionMenu(
          titre: 'Compte',
          entrees: [
            EntreeMenu(icone: Icons.logout, libelle: 'Se déconnecter', action: _seDeconnecter),
          ],
        ),
      ];

  @override
  Widget build(BuildContext context) {
    final pages = [
      const ProfilTab(),
      const AyantsDroitTab(),
      PrescriptionsTab(key: ValueKey(_versionPrescriptions)),
    ];

    return Scaffold(
      appBar: AppBar(title: Text(_titres[_index])),
      drawer: AppDrawer(
        utilisateur: _utilisateur,
        ongletCourant: _index,
        onOngletChoisi: (i) => setState(() => _index = i),
        sections: _sections,
      ),
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.person_outline), selectedIcon: Icon(Icons.person), label: 'Profil'),
          NavigationDestination(icon: Icon(Icons.family_restroom_outlined), selectedIcon: Icon(Icons.family_restroom), label: 'Ayants droit'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), selectedIcon: Icon(Icons.receipt_long), label: 'Prescriptions'),
        ],
      ),
    );
  }
}
