import 'package:flutter/material.dart';

import '../services/lock_service.dart';
import 'pin_setup_screen.dart';

/// Réglages de verrouillage local : activer/modifier le code PIN, et
/// activer la biométrie en complément une fois le PIN configuré.
class SecuriteScreen extends StatefulWidget {
  const SecuriteScreen({super.key});

  @override
  State<SecuriteScreen> createState() => _SecuriteScreenState();
}

class _SecuriteScreenState extends State<SecuriteScreen> {
  bool _chargement = true;
  bool _pinActif = false;
  bool _biometrieDisponible = false;
  bool _biometrieActive = false;

  @override
  void initState() {
    super.initState();
    _charger();
  }

  Future<void> _charger() async {
    final pinActif = await LockService.instance.hasPin;
    final biometrieDisponible = await LockService.instance.biometricsAvailable;
    final biometrieActive = await LockService.instance.isBiometricEnabled;
    if (!mounted) return;
    setState(() {
      _pinActif = pinActif;
      _biometrieDisponible = biometrieDisponible;
      _biometrieActive = biometrieActive;
      _chargement = false;
    });
  }

  Future<void> _configurerPin() async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PinSetupScreen()));
    _charger();
  }

  Future<void> _desactiverPin() async {
    final confirme = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Désactiver le verrouillage ?'),
        content: const Text("L'application ne demandera plus de code à l'ouverture."),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Annuler')),
          TextButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Désactiver')),
        ],
      ),
    );
    if (confirme == true) {
      await LockService.instance.clearPin();
      _charger();
    }
  }

  Future<void> _basculerBiometrie(bool valeur) async {
    await LockService.instance.setBiometricEnabled(valeur);
    setState(() => _biometrieActive = valeur);
  }

  @override
  Widget build(BuildContext context) {
    if (_chargement) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Sécurité')),
      body: ListView(
        children: [
          SwitchListTile(
            secondary: const Icon(Icons.pin_outlined),
            title: const Text('Code PIN'),
            subtitle: Text(_pinActif ? 'Activé' : 'Désactivé'),
            value: _pinActif,
            onChanged: (valeur) => valeur ? _configurerPin() : _desactiverPin(),
          ),
          if (_pinActif) ...[
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Modifier le code PIN'),
              onTap: _configurerPin,
            ),
            if (_biometrieDisponible)
              SwitchListTile(
                secondary: const Icon(Icons.fingerprint),
                title: const Text('Empreinte digitale / Face ID'),
                subtitle: const Text('En complément du code PIN'),
                value: _biometrieActive,
                onChanged: _basculerBiometrie,
              ),
          ],
        ],
      ),
    );
  }
}
