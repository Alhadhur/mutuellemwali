import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';

/// Verrouillage local de l'application : un code PIN à 4 chiffres, et un
/// déverrouillage biométrique facultatif qui vient en complément du PIN
/// (jamais à sa place), pour rester utilisable si l'empreinte échoue ou
/// n'est plus enregistrée sur l'appareil.
///
/// Ne protège que l'accès à l'app sur ce téléphone : la session (jeton API)
/// reste gérée séparément par [ApiService]. Le PIN est haché avec un sel
/// propre à l'installation avant stockage, pour ne jamais le garder en
/// clair même dans le stockage sécurisé du système.
class LockService {
  LockService._internal();
  static final LockService instance = LockService._internal();

  static const _storage = FlutterSecureStorage();
  static const _clePinHash = 'verrouillage_pin_hash';
  static const _cleSel = 'verrouillage_pin_sel';
  static const _cleBiometrie = 'verrouillage_biometrie_active';

  final LocalAuthentication _auth = LocalAuthentication();

  Future<bool> get hasPin async => (await _storage.read(key: _clePinHash)) != null;

  Future<void> setPin(String pin) async {
    final sel = _genererSel();
    await _storage.write(key: _cleSel, value: sel);
    await _storage.write(key: _clePinHash, value: _hacher(pin, sel));
  }

  Future<bool> verifyPin(String pin) async {
    final sel = await _storage.read(key: _cleSel);
    final hash = await _storage.read(key: _clePinHash);
    if (sel == null || hash == null) return false;
    return _hacher(pin, sel) == hash;
  }

  /// Retire le PIN et désactive la biométrie : à appeler à la déconnexion,
  /// pour qu'un autre agent qui se connecterait ensuite sur cet appareil ne
  /// se retrouve pas avec le verrouillage du précédent.
  Future<void> clearPin() async {
    await _storage.delete(key: _clePinHash);
    await _storage.delete(key: _cleSel);
    await _storage.delete(key: _cleBiometrie);
  }

  Future<bool> get isBiometricEnabled async => (await _storage.read(key: _cleBiometrie)) == 'oui';

  Future<void> setBiometricEnabled(bool active) async {
    await _storage.write(key: _cleBiometrie, value: active ? 'oui' : 'non');
  }

  /// L'appareil sait-il vérifier une empreinte/un visage, et au moins un
  /// moyen est-il enrôlé ? Sert à proposer (ou non) l'option biométrique.
  Future<bool> get biometricsAvailable async {
    try {
      return await _auth.isDeviceSupported() && await _auth.canCheckBiometrics;
    } catch (_) {
      return false;
    }
  }

  Future<bool> authenticateWithBiometrics() async {
    try {
      return await _auth.authenticate(
        localizedReason: 'Déverrouillez Mutuelle Yatru',
        options: const AuthenticationOptions(biometricOnly: true, stickyAuth: true),
      );
    } catch (_) {
      return false;
    }
  }

  String _genererSel() {
    final aleatoire = Random.secure();
    return List.generate(16, (_) => aleatoire.nextInt(256))
        .map((octet) => octet.toRadixString(16).padLeft(2, '0'))
        .join();
  }

  String _hacher(String pin, String sel) => sha256.convert(utf8.encode('$sel:$pin')).toString();
}
