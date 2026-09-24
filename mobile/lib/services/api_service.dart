import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/models.dart';
import 'api_config.dart';

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

/// Client HTTP centralisé : gère le login JWT, le rafraîchissement de token,
/// et les appels vers l'API du back-office.
class ApiService {
  ApiService._internal();
  static final ApiService instance = ApiService._internal();

  String? _accessToken;
  String? _refreshToken;

  String get _baseUrl => ApiConfig.baseUrl;

  Future<void> _loadTokens() async {
    if (_accessToken != null) return;
    final prefs = await SharedPreferences.getInstance();
    _accessToken = prefs.getString('access_token');
    _refreshToken = prefs.getString('refresh_token');
  }

  Future<void> _saveTokens(String access, String refresh) async {
    _accessToken = access;
    _refreshToken = refresh;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('access_token', access);
    await prefs.setString('refresh_token', refresh);
  }

  Future<bool> get isLoggedIn async {
    await _loadTokens();
    return _accessToken != null;
  }

  Future<void> logout() async {
    _accessToken = null;
    _refreshToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('access_token');
    await prefs.remove('refresh_token');
  }

  Future<void> login(String matricule, String password) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/token/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'matricule': matricule, 'password': password}),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      await _saveTokens(data['access'], data['refresh']);
    } else {
      throw ApiException('Matricule ou mot de passe incorrect.');
    }
  }

  Future<bool> _refreshAccessToken() async {
    if (_refreshToken == null) return false;
    final response = await http.post(
      Uri.parse('$_baseUrl/token/refresh/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh': _refreshToken}),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      _accessToken = data['access'];
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('access_token', _accessToken!);
      return true;
    }
    return false;
  }

  Future<http.Response> _authorizedRequest(
    Future<http.Response> Function(Map<String, String> headers) request,
  ) async {
    await _loadTokens();
    var headers = {'Authorization': 'Bearer $_accessToken'};
    var response = await request(headers);
    if (response.statusCode == 401 && await _refreshAccessToken()) {
      headers = {'Authorization': 'Bearer $_accessToken'};
      response = await request(headers);
    }
    return response;
  }

  Future<Utilisateur> getMoi() async {
    final response = await _authorizedRequest(
      (headers) => http.get(Uri.parse('$_baseUrl/me/'), headers: headers),
    );
    _ensureOk(response);
    return Utilisateur.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
  }

  Future<AgentProfil> getProfilAgent() async {
    final response = await _authorizedRequest(
      (headers) => http.get(Uri.parse('$_baseUrl/agent/profil/'), headers: headers),
    );
    _ensureOk(response);
    return AgentProfil.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
  }

  Future<List<Prestataire>> getPrestataires() async {
    final response = await _authorizedRequest(
      (headers) => http.get(Uri.parse('$_baseUrl/prestataires/'), headers: headers),
    );
    _ensureOk(response);
    final data = jsonDecode(utf8.decode(response.bodyBytes));
    return (data['results'] as List).map((e) => Prestataire.fromJson(e)).toList();
  }

  Future<List<NatureSoin>> getNaturesDeSoin() async {
    final response = await _authorizedRequest(
      (headers) => http.get(Uri.parse('$_baseUrl/natures-de-soin/'), headers: headers),
    );
    _ensureOk(response);
    final data = jsonDecode(utf8.decode(response.bodyBytes));
    return (data['results'] as List).map((e) => NatureSoin.fromJson(e)).toList();
  }

  Future<List<Prescription>> getPrescriptions() async {
    final response = await _authorizedRequest(
      (headers) => http.get(Uri.parse('$_baseUrl/prescriptions/'), headers: headers),
    );
    _ensureOk(response);
    final data = jsonDecode(utf8.decode(response.bodyBytes));
    return (data['results'] as List).map((e) => Prescription.fromJson(e)).toList();
  }

  Future<Prescription> soumettrePrescription({
    required int prestataireId,
    int? ayantDroitId,
    required int natureId,
    required String numeroOrdonnance,
    required int montantTotal,
    required DateTime dateEmission,
    required File justificatif,
  }) async {
    await _loadTokens();

    Future<http.Response> envoyer(Map<String, String> headers) async {
      final request = http.MultipartRequest('POST', Uri.parse('$_baseUrl/prescriptions/'));
      request.headers.addAll(headers);
      request.fields['prestataire'] = prestataireId.toString();
      if (ayantDroitId != null) request.fields['ayant_droit'] = ayantDroitId.toString();
      request.fields['nature'] = natureId.toString();
      request.fields['numero_ordonnance'] = numeroOrdonnance;
      request.fields['montant_total'] = montantTotal.toString();
      request.fields['date_emission'] =
          '${dateEmission.year.toString().padLeft(4, '0')}-${dateEmission.month.toString().padLeft(2, '0')}-${dateEmission.day.toString().padLeft(2, '0')}';
      request.files.add(await http.MultipartFile.fromPath('justificatif', justificatif.path));
      final streamed = await request.send();
      return http.Response.fromStream(streamed);
    }

    final response = await _authorizedRequest(envoyer);
    if (response.statusCode == 201) {
      return Prescription.fromJson(jsonDecode(utf8.decode(response.bodyBytes)));
    }
    final body = jsonDecode(utf8.decode(response.bodyBytes));
    throw ApiException(_formatErrors(body));
  }

  String _formatErrors(dynamic body) {
    if (body is Map) {
      return body.entries.map((e) => '${e.key} : ${e.value is List ? (e.value as List).join(", ") : e.value}').join('\n');
    }
    return 'Erreur inconnue.';
  }

  void _ensureOk(http.Response response) {
    if (response.statusCode == 401) {
      throw ApiException('Session expirée, merci de vous reconnecter.');
    }
    if (response.statusCode >= 400) {
      throw ApiException('Erreur serveur (${response.statusCode}).');
    }
  }
}
