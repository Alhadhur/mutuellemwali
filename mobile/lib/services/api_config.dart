import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;

/// Adresse du back-office Django.
///
/// En production, l'URL est fournie à la compilation, ce qui évite de modifier
/// le code — et donc de risquer de livrer un binaire pointant sur un poste de
/// développement :
///
///   flutter build apk --release \
///     --dart-define=API_BASE_URL=https://mutuelle-sante.onrender.com/api
///
/// Sans cette définition, l'application retombe sur l'adresse locale :
///  - Émulateur Android : 10.0.2.2 désigne le « localhost » de la machine hôte.
///  - Web / Linux / téléphone sur le même réseau : l'IP réelle de la machine,
///    car un appareil ne peut pas résoudre 127.0.0.1 vers l'hôte. Si l'IP
///    change, mettre à jour _lanIp ci-dessous.
class ApiConfig {
  static const String _lanIp = '192.168.100.114';

  /// Renseignée au moment du build ; vide en développement.
  static const String _urlCompilee = String.fromEnvironment('API_BASE_URL');

  /// Vrai lorsque l'application vise un serveur distant plutôt que le poste
  /// de développement : utile pour n'autoriser certaines traces qu'en local.
  static bool get estProduction => _urlCompilee.isNotEmpty;

  static String get baseUrl {
    if (_urlCompilee.isNotEmpty) return _urlCompilee;

    if (kIsWeb) return 'http://$_lanIp:8000/api';
    try {
      if (Platform.isAndroid) return 'http://10.0.2.2:8000/api';
    } catch (_) {
      // Platform indisponible (tests) -> repli ci-dessous.
    }
    return 'http://$_lanIp:8000/api';
  }
}
