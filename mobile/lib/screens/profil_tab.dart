import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/models.dart';
import '../services/api_service.dart';

class ProfilTab extends StatefulWidget {
  const ProfilTab({super.key});

  @override
  State<ProfilTab> createState() => _ProfilTabState();
}

class _ProfilTabState extends State<ProfilTab> {
  late Future<AgentProfil> _futureProfil;
  // Le KMF n'a pas de sous-unité : aucun montant n'est affiché avec décimale.
  final _montant = NumberFormat.decimalPatternDigits(locale: 'fr_FR', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    _futureProfil = ApiService.instance.getProfilAgent();
  }

  Future<void> _rafraichir() async {
    setState(() => _futureProfil = ApiService.instance.getProfilAgent());
    await _futureProfil;
  }

  /// Le quota couvre une période paramétrable côté mutuelle : on affiche ses
  /// bornes pour que l'agent sache jusqu'à quand son enveloppe court.
  String _libellePeriode(AgentProfil profil) {
    const base = 'Enveloppe partagée avec vos ayants droit';
    if (profil.periodeDebut.isEmpty || profil.periodeFin.isEmpty) return base;
    // Format numérique : un libellé de mois exigerait d'initialiser les
    // données de locale, ce que l'app ne fait pas.
    final format = DateFormat('dd/MM/yyyy');
    final debut = format.format(DateTime.parse(profil.periodeDebut));
    final fin = format.format(DateTime.parse(profil.periodeFin));
    return '$base\nPériode du $debut au $fin';
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _rafraichir,
      child: FutureBuilder<AgentProfil>(
        future: _futureProfil,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return ListView(children: [
              const SizedBox(height: 80),
              Center(child: Text('Erreur : ${snapshot.error}')),
            ]);
          }
          final profil = snapshot.data!;
          final ratio = profil.quota > 0
              ? (profil.consommationPeriode / profil.quota).clamp(0.0, 1.0)
              : 0.0;

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${profil.prenom} ${profil.nom}',
                          style: const TextStyle(fontSize: 19, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 2),
                      Text('Matricule ${profil.matricule} · ${profil.site}',
                          style: TextStyle(color: Colors.grey.shade600, fontSize: 13.5)),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Quota de remboursement', style: TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 2),
                      Text(_libellePeriode(profil),
                          style: TextStyle(color: Colors.grey.shade600, fontSize: 12.5)),
                      const SizedBox(height: 12),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: LinearProgressIndicator(
                          value: ratio,
                          minHeight: 10,
                          backgroundColor: Colors.grey.shade200,
                          color: ratio > 0.9 ? Colors.red : Theme.of(context).colorScheme.primary,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('Consommé : ${_montant.format(profil.consommationPeriode)} KMF',
                              style: const TextStyle(fontSize: 13)),
                          Text('Quota : ${_montant.format(profil.quota)} KMF',
                              style: const TextStyle(fontSize: 13)),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text('Solde restant : ${_montant.format(profil.soldeQuota)} KMF',
                          style: TextStyle(fontSize: 13, color: Colors.grey.shade700)),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
