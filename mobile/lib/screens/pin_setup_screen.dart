import 'package:flutter/material.dart';

import '../services/lock_service.dart';
import '../widgets/pin_pad.dart';

/// Création ou changement du code PIN, en deux temps (saisie puis
/// confirmation). Utilisé juste après la connexion (skippable via
/// [peutPasser]) et depuis l'écran Sécurité (non skippable, puisque
/// l'utilisateur l'a ouvert lui-même).
///
/// Retourne `true` via [Navigator.pop] si un code a été défini, `false`
/// sinon (annulé ou passé).
class PinSetupScreen extends StatefulWidget {
  final bool peutPasser;

  const PinSetupScreen({super.key, this.peutPasser = false});

  @override
  State<PinSetupScreen> createState() => _PinSetupScreenState();
}

class _PinSetupScreenState extends State<PinSetupScreen> {
  String _premierPin = '';
  String _saisie = '';
  bool _confirmation = false;
  bool _enErreur = false;

  void _changerSaisie(String valeur) {
    setState(() => _saisie = valeur);
    if (valeur.length == 4) _valider(valeur);
  }

  Future<void> _valider(String pin) async {
    if (!_confirmation) {
      setState(() {
        _premierPin = pin;
        _confirmation = true;
        _saisie = '';
      });
      return;
    }
    if (pin != _premierPin) {
      setState(() => _enErreur = true);
      await Future.delayed(const Duration(milliseconds: 400));
      if (!mounted) return;
      setState(() {
        _confirmation = false;
        _premierPin = '';
        _saisie = '';
        _enErreur = false;
      });
      return;
    }

    await LockService.instance.setPin(pin);
    if (!mounted) return;
    await _proposerBiometrie();
    if (mounted) Navigator.of(context).pop(true);
  }

  Future<void> _proposerBiometrie() async {
    final disponible = await LockService.instance.biometricsAvailable;
    if (!disponible || !mounted) return;
    final accepte = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Empreinte digitale'),
        content: const Text(
          "Voulez-vous aussi pouvoir déverrouiller l'application avec votre empreinte digitale ou Face ID ?",
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Non merci')),
          TextButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Activer')),
        ],
      ),
    );
    await LockService.instance.setBiometricEnabled(accepte ?? false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Code PIN'),
        automaticallyImplyLeading: !widget.peutPasser,
        actions: [
          if (widget.peutPasser)
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Plus tard'),
            ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.pin_outlined, size: 36, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 12),
              Text(
                _confirmation ? 'Confirmez votre code PIN' : 'Choisissez un code PIN à 4 chiffres',
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 6),
              Text(
                _enErreur
                    ? 'Les deux codes ne correspondent pas, recommencez.'
                    : "Il vous sera demandé à chaque ouverture de l'application.",
                style: TextStyle(fontSize: 13, color: _enErreur ? Colors.red : Colors.grey.shade600),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              PinEntryPad(valeur: _saisie, onChanged: _changerSaisie, enErreur: _enErreur),
            ],
          ),
        ),
      ),
    );
  }
}
