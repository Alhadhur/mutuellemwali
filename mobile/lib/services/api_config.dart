/// Adresse du back-office Django.
///
/// En production, l'URL est fournie à la compilation, ce qui évite de modifier
/// le code — et donc de risquer de livrer un binaire pointant sur un poste de
/// développement :
///
///   flutter build apk --release \
///     --dart-define=API_BASE_URL=https://mutuelle-sante.onrender.com/api
///
/// Sans cette définition, l'application retombe sur l'IP réelle de la machine
/// de développement (_lanIp) : un appareil, qu'il s'agisse d'un émulateur ou
/// d'un vrai téléphone sur le même réseau, ne peut pas résoudre 127.0.0.1 vers
/// l'hôte. Si l'IP change, mettre à jour _lanIp ci-dessous. (L'alias spécial
/// 10.0.2.2 de l'émulateur Android n'est pas utilisé : il ne fonctionne que
/// dans l'émulateur, jamais sur un vrai téléphone, et la machine hôte est de
/// toute façon déjà joignable depuis l'émulateur via son IP réelle.)
class ApiConfig {
  static const String _lanIp = '192.168.100.114';

  /// Renseignée au moment du build ; vide en développement.
  static const String _urlCompilee = String.fromEnvironment('API_BASE_URL');

  /// Vrai lorsque l'application vise un serveur distant plutôt que le poste
  /// de développement : utile pour n'autoriser certaines traces qu'en local.
  static bool get estProduction => _urlCompilee.isNotEmpty;

  static String get baseUrl {
    if (_urlCompilee.isNotEmpty) return _urlCompilee;
    return 'http://$_lanIp:8000/api';
  }
}
