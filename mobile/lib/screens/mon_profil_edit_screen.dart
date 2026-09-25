import 'package:flutter/material.dart';

import '../models/models.dart';
import '../services/api_service.dart';

/// Écran en libre-service : modification des coordonnées du compte connecté
/// et changement de mot de passe. Accessible à tout utilisateur authentifié,
/// contrairement aux écrans d'administration du back-office.
class MonProfilEditScreen extends StatefulWidget {
  const MonProfilEditScreen({super.key});

  @override
  State<MonProfilEditScreen> createState() => _MonProfilEditScreenState();
}

class _MonProfilEditScreenState extends State<MonProfilEditScreen> {
  final _formKey = GlobalKey<FormState>();
  late Future<MonCompte> _futureCompte;
  final _nomCtrl = TextEditingController();
  final _prenomCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _telephoneCtrl = TextEditingController();
  final _regionCtrl = TextEditingController();
  String _matricule = '';
  String _roleDisplay = '';
  bool _enregistrement = false;

  @override
  void initState() {
    super.initState();
    _futureCompte = ApiService.instance.getMonCompte().then((compte) {
      _nomCtrl.text = compte.nom;
      _prenomCtrl.text = compte.prenom;
      _emailCtrl.text = compte.email;
      _telephoneCtrl.text = compte.telephone;
      _regionCtrl.text = compte.region;
      _matricule = compte.matricule;
      _roleDisplay = compte.roleDisplay;
      return compte;
    });
  }

  @override
  void dispose() {
    _nomCtrl.dispose();
    _prenomCtrl.dispose();
    _emailCtrl.dispose();
    _telephoneCtrl.dispose();
    _regionCtrl.dispose();
    super.dispose();
  }

  Future<void> _enregistrer() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _enregistrement = true);
    try {
      await ApiService.instance.majMonCompte(
        nom: _nomCtrl.text.trim(),
        prenom: _prenomCtrl.text.trim(),
        email: _emailCtrl.text.trim(),
        telephone: _telephoneCtrl.text.trim(),
        region: _regionCtrl.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Profil mis à jour.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _enregistrement = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mon profil')),
      body: FutureBuilder<MonCompte>(
        future: _futureCompte,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('Erreur : ${snapshot.error}'));
          }
          return Form(
            key: _formKey,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  'Matricule $_matricule${_roleDisplay.isNotEmpty ? ' · $_roleDisplay' : ''}',
                  style: TextStyle(color: Colors.grey.shade600, fontSize: 13),
                ),
                const SizedBox(height: 18),
                TextFormField(
                  controller: _prenomCtrl,
                  decoration: const InputDecoration(labelText: 'Prénom'),
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Champ obligatoire' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _nomCtrl,
                  decoration: const InputDecoration(labelText: 'Nom'),
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Champ obligatoire' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _emailCtrl,
                  decoration: const InputDecoration(labelText: 'Email'),
                  keyboardType: TextInputType.emailAddress,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _telephoneCtrl,
                  decoration: const InputDecoration(labelText: 'Téléphone'),
                  keyboardType: TextInputType.phone,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _regionCtrl,
                  decoration: const InputDecoration(labelText: 'Région'),
                ),
                const SizedBox(height: 22),
                FilledButton(
                  onPressed: _enregistrement ? null : _enregistrer,
                  child: _enregistrement
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Enregistrer'),
                ),
                const SizedBox(height: 24),
                OutlinedButton.icon(
                  onPressed: () => showDialog(context: context, builder: (_) => const _DialogueMotDePasse()),
                  icon: const Icon(Icons.lock_outline),
                  label: const Text('Changer mon mot de passe'),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _DialogueMotDePasse extends StatefulWidget {
  const _DialogueMotDePasse();

  @override
  State<_DialogueMotDePasse> createState() => _DialogueMotDePasseState();
}

class _DialogueMotDePasseState extends State<_DialogueMotDePasse> {
  final _formKey = GlobalKey<FormState>();
  final _actuelCtrl = TextEditingController();
  final _nouveauCtrl = TextEditingController();
  final _confirmationCtrl = TextEditingController();
  bool _enCours = false;
  String? _erreur;

  @override
  void dispose() {
    _actuelCtrl.dispose();
    _nouveauCtrl.dispose();
    _confirmationCtrl.dispose();
    super.dispose();
  }

  Future<void> _valider() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _enCours = true;
      _erreur = null;
    });
    try {
      await ApiService.instance.changerMonMotDePasse(
        motDePasseActuel: _actuelCtrl.text,
        motDePasse: _nouveauCtrl.text,
        confirmation: _confirmationCtrl.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Mot de passe mis à jour.')));
    } catch (e) {
      setState(() => _erreur = '$e');
    } finally {
      if (mounted) setState(() => _enCours = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Changer mon mot de passe'),
      content: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextFormField(
              controller: _actuelCtrl,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Mot de passe actuel'),
              validator: (v) => (v == null || v.isEmpty) ? 'Champ obligatoire' : null,
            ),
            const SizedBox(height: 10),
            TextFormField(
              controller: _nouveauCtrl,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Nouveau mot de passe'),
              validator: (v) => (v == null || v.isEmpty) ? 'Champ obligatoire' : null,
            ),
            const SizedBox(height: 10),
            TextFormField(
              controller: _confirmationCtrl,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Confirmer le nouveau mot de passe'),
              validator: (v) => (v == null || v.isEmpty) ? 'Champ obligatoire' : null,
            ),
            if (_erreur != null) ...[
              const SizedBox(height: 10),
              Text(_erreur!, style: const TextStyle(color: Colors.red, fontSize: 13)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _enCours ? null : () => Navigator.of(context).pop(), child: const Text('Annuler')),
        FilledButton(
          onPressed: _enCours ? null : _valider,
          child: _enCours
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Valider'),
        ),
      ],
    );
  }
}
