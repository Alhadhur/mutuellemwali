import 'package:flutter_test/flutter_test.dart';

import 'package:mutuelle_sante_mobile/services/api_config.dart';

void main() {
  test('sans définition de build, l\'adresse reste locale', () {
    // Les tests s'exécutent sans --dart-define : on doit retomber sur le
    // serveur de développement, jamais sur une adresse de production.
    expect(ApiConfig.estProduction, isFalse);
    expect(ApiConfig.baseUrl, startsWith('http://'));
    expect(ApiConfig.baseUrl, endsWith('/api'));
  });

  test('l\'adresse ne pointe pas vers un domaine distant par défaut', () {
    expect(ApiConfig.baseUrl, isNot(contains('onrender.com')));
  });
}
