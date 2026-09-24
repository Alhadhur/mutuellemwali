import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/models.dart';
import '../services/api_service.dart';
import '../widgets/status_badge.dart';

class AyantsDroitTab extends StatefulWidget {
  const AyantsDroitTab({super.key});

  @override
  State<AyantsDroitTab> createState() => _AyantsDroitTabState();
}

class _AyantsDroitTabState extends State<AyantsDroitTab> {
  late Future<AgentProfil> _futureProfil;
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
          final ayantsDroit = snapshot.data!.ayantsDroit;
          if (ayantsDroit.isEmpty) {
            return ListView(children: const [
              SizedBox(height: 100),
              Center(child: Text('Aucun ayant droit enregistré.\nContactez le service mutuelle / RH pour en ajouter.',
                  textAlign: TextAlign.center)),
            ]);
          }
          return ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: ayantsDroit.length,
            itemBuilder: (context, index) {
              final a = ayantsDroit[index];
              return Card(
                margin: const EdgeInsets.only(bottom: 12),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('${a.prenom} ${a.nom}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15.5)),
                          StatusBadge(
                            label: a.statutVerificationDisplay,
                            color: couleurStatutVerification(a.statutVerification),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(a.lienParenteDisplay, style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
                      const SizedBox(height: 10),
                      Text('Consommé sur la période : ${_montant.format(a.consommationPeriode)} KMF',
                          style: const TextStyle(fontSize: 13)),
                      if (a.age != null) ...[
                        const SizedBox(height: 4),
                        Text('${a.age} ans', style: TextStyle(color: Colors.grey.shade600, fontSize: 12.5)),
                      ],
                      if (a.limiteAgeDepassee) ...[
                        const SizedBox(height: 8),
                        Row(children: [
                          const Icon(Icons.block, color: Colors.red, size: 16),
                          const SizedBox(width: 4),
                          Text('Limite d\'âge atteinte (${a.ageLimite} ans) — couverture à revoir',
                              style: const TextStyle(color: Colors.red, fontSize: 12.5)),
                        ]),
                      ],
                      if (a.estExpire) ...[
                        const SizedBox(height: 8),
                        Row(children: const [
                          Icon(Icons.warning_amber_rounded, color: Colors.red, size: 16),
                          SizedBox(width: 4),
                          Text('Justificatif expiré — à renouveler', style: TextStyle(color: Colors.red, fontSize: 12.5)),
                        ]),
                      ],
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
