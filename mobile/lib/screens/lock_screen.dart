import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/lock_service.dart';
import '../widgets/pin_pad.dart';
import 'login_screen.dart';

/// Écran de déverrouillage : affiché au lancement à froid quand une session
/// et un code PIN existent déjà (voir _StartupGate dans main.dart), et
/// poussé au-dessus de l'écran courant à chaque retour au premier plan
/// (voir MutuelleYatruApp) — dans les deux cas, [onUnlocked] indique au
/// point d'appel comment révéler ce qu'il y a en dessous.
class LockScreen extends StatefulWidget {
  final VoidCallback onUnlocked;

  const LockScreen({super.key, required this.onUnlocked});

  @override
  State<LockScreen> createState() => _LockScreenState();
}

class _LockScreenState extends State<LockScreen> {
  String _saisie = '';
  bool _enErreur = false;
  bool _biometrieDisponible = false;

  @override
  void initState() {
    super.initState();
    _preparerBiometrie();
  }

  Future<void> _preparerBiometrie() async {
    final active = await LockService.instance.isBiometricEnabled;
    final disponible = active && await LockService.instance.biometricsAvailable;
    if (!mounted) return;
    setState(() => _biometrieDisponible = disponible);
    if (disponible) _tenterBiometrie();
  }

  Future<void> _tenterBiometrie() async {
    final reussi = await LockService.instance.authenticateWithBiometrics();
    if (reussi && mounted) widget.onUnlocked();
  }

  void _changerSaisie(String valeur) {
    setState(() => _saisie = valeur);
    if (valeur.length == 4) _verifier(valeur);
  }

  Future<void> _verifier(String pin) async {
    final correct = await LockService.instance.verifyPin(pin);
    if (correct) {
      widget.onUnlocked();
      return;
    }
    setState(() => _enErreur = true);
    await Future.delayed(const Duration(milliseconds: 400));
    if (!mounted) return;
    setState(() {
      _saisie = '';
      _enErreur = false;
    });
  }

  Future<void> _seDeconnecter() async {
    await ApiService.instance.logout();
    await LockService.instance.clearPin();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    // Ni le bouton retour ni un geste ne doivent pouvoir révéler ce qu'il y
    // a en dessous sans code correct : le verrouillage serait sinon
    // contournable d'une simple pression.
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: const Color(0xFF111827),
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.lock_outline, color: Colors.white, size: 36),
                  const SizedBox(height: 10),
                  const Text(
                    'Mutuelle Yatru',
                    style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _enErreur ? 'Code incorrect' : 'Saisissez votre code PIN',
                    style: TextStyle(color: _enErreur ? Colors.redAccent : Colors.white70, fontSize: 13.5),
                  ),
                  const SizedBox(height: 24),
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 22),
                    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
                    child: PinEntryPad(
                      valeur: _saisie,
                      onChanged: _changerSaisie,
                      enErreur: _enErreur,
                      actionSupplementaire: _biometrieDisponible
                          ? IconButton(
                              iconSize: 28,
                              icon: const Icon(Icons.fingerprint),
                              onPressed: _tenterBiometrie,
                            )
                          : null,
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextButton(
                    onPressed: _seDeconnecter,
                    child: const Text('Code oublié ? Se reconnecter', style: TextStyle(color: Colors.white70)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
