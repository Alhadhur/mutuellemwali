import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/models.dart';
import '../services/api_service.dart';
import '../widgets/status_badge.dart';
import 'prescription_form_screen.dart';

class PrescriptionsTab extends StatefulWidget {
  const PrescriptionsTab({super.key});

  @override
  State<PrescriptionsTab> createState() => _PrescriptionsTabState();
}

class _PrescriptionsTabState extends State<PrescriptionsTab> {
  late Future<List<Prescription>> _futurePrescriptions;
  final _montant = NumberFormat.decimalPatternDigits(locale: 'fr_FR', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    _charger();
  }

  void _charger() {
    _futurePrescriptions = ApiService.instance.getPrescriptions();
  }

  Future<void> _rafraichir() async {
    setState(_charger);
    await _futurePrescriptions;
  }

  Future<void> _ouvrirFormulaire() async {
    final cree = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const PrescriptionFormScreen()),
    );
    if (cree == true) _rafraichir();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _ouvrirFormulaire,
        icon: const Icon(Icons.add_a_photo_outlined),
        label: const Text('Soumettre'),
      ),
      body: RefreshIndicator(
        onRefresh: _rafraichir,
        child: FutureBuilder<List<Prescription>>(
          future: _futurePrescriptions,
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
            final prescriptions = snapshot.data!;
            if (prescriptions.isEmpty) {
              return ListView(children: const [
                SizedBox(height: 100),
                Center(
                  child: Padding(
                    padding: EdgeInsets.symmetric(horizontal: 32),
                    child: Text(
                      'Aucune prescription soumise.\nUtilisez le bouton "Soumettre" pour envoyer une ordonnance ou une facture.',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              ]);
            }
            return ListView.builder(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 90),
              itemCount: prescriptions.length,
              itemBuilder: (context, index) {
                final p = prescriptions[index];
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
                            Expanded(
                              child: Text('N° ${p.numeroOrdonnance}',
                                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                            ),
                            StatusBadge(label: p.statutDisplay, color: couleurStatutPrescription(p.statut)),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                            // Les prescriptions reprises de l'historique n'ont pas de nature.
                            [p.prestataireNom, p.beneficiaireNom, if (p.natureLibelle.isNotEmpty) p.natureLibelle]
                                .join(' · '),
                            style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
                        const SizedBox(height: 10),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text('Montant : ${_montant.format(p.montantTotal)}', style: const TextStyle(fontSize: 13)),
                            Text('Remboursé : ${_montant.format(p.montantRembourse)}',
                                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                          ],
                        ),
                        Text('Émise le ${p.dateEmission}', style: TextStyle(fontSize: 12, color: Colors.grey.shade500)),
                        if (p.motifSignalement.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: const Color(0xFFFFF4E5),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(p.motifSignalement, style: const TextStyle(fontSize: 12, color: Color(0xFF8A5A00))),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
