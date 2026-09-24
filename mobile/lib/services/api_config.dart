import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;

/// Adresse du back-office Django. À adapter selon la cible :
///  - Émulateur Android : 10.0.2.2 pointe vers le "localhost" de la machine hôte.
///  - Web / Linux / appareil physique sur le même réseau : utiliser l'IP réelle
///    du serveur (Wi-Fi de la machine de dev : 192.168.100.114) — un
///    émulateur/téléphone ne peut pas résoudre "127.0.0.1" vers la machine
///    hôte. Si l'IP de la machine change, mettre à jour _lanIp ci-dessous.
class ApiConfig {
  static const String _lanIp = '192.168.100.114';

  static String get baseUrl {
    if (kIsWeb) return 'http://$_lanIp:8000/api';
    try {
      if (Platform.isAndroid) return 'http://10.0.2.2:8000/api';
    } catch (_) {
      // Platform indisponible (tests) -> fallback ci-dessous.
    }
    return 'http://$_lanIp:8000/api';
  }
}
