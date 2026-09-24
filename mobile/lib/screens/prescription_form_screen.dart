import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/models.dart';
import '../services/api_service.dart';
import '../widgets/repartition_prise_en_charge.dart';

class PrescriptionFormScreen extends StatefulWidget {
  const PrescriptionFormScreen({super.key});

  @override
  State<PrescriptionFormScreen> createState() => _PrescriptionFormScreenState();
}

class _PrescriptionFormScreenState extends State<PrescriptionFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _numeroCtrl = TextEditingController();
  final _montantCtrl = TextEditingController();

  late Future<List<Prestataire>> _futurePrestataires;
  Prestataire? _prestataireChoisi;
  NatureSoin? _natureChoisie;
  List<NatureSoin> _natures = [];
  AyantDroit? _ayantDroitChoisi;
  List<AyantDroit> _ayantsDroit = [];
  DateTime _dateEmission = DateTime.now();
  File? _photo;

  bool _envoiEnCours = false;
  String? _erreur;

  @override
  void initState() {
    super.initState();
    _futurePrestataires = ApiService.instance.getPrestataires();
    ApiService.instance.getProfilAgent().then((profil) {
      if (mounted) setState(() => _ayantsDroit = profil.ayantsDroit);
    });
    ApiService.instance.getNaturesDeSoin().then((natures) {
      if (mounted) setState(() => _natures = natures);
    });
  }

  Future<void> _choisirPhoto(ImageSource source) async {
    final picker = ImagePicker();
    final fichier = await picker.pickImage(source: source, imageQuality: 85);
    if (fichier != null) {
      setState(() => _photo = File(fichier.path));
    }
  }

  Future<void> _choisirDate() async {
    final choisie = await showDatePicker(
      context: context,
      initialDate: _dateEmission,
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (choisie != null) setState(() => _dateEmission = choisie);
  }

  Future<void> _soumettre() async {
    setState(() => _erreur = null);
    if (!_formKey.currentState!.validate()) return;
    if (_prestataireChoisi == null) {
      setState(() => _erreur = 'Veuillez choisir un prestataire conventionné.');
      return;
    }
    if (_natureChoisie == null) {
      setState(() => _erreur = 'Veuillez indiquer la nature du soin.');
      return;
    }
    if (_photo == null) {
      setState(() => _erreur = 'Veuillez joindre une photo de l\'ordonnance ou de la facture.');
      return;
    }

    setState(() => _envoiEnCours = true);
    try {
      await ApiService.instance.soumettrePrescription(
        prestataireId: _prestataireChoisi!.id,
        ayantDroitId: _ayantDroitChoisi?.id,
        natureId: _natureChoisie!.id,
        numeroOrdonnance: _numeroCtrl.text.trim(),
        montantTotal: int.parse(_montantCtrl.text.trim()),
        dateEmission: _dateEmission,
        justificatif: _photo!,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Prescription soumise avec succès.')),
      );
      Navigator.of(context).pop(true);
    } catch (e) {
      setState(() => _erreur = e.toString().replaceFirst('ApiException: ', ''));
    } finally {
      if (mounted) setState(() => _envoiEnCours = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Soumettre une prescription')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            GestureDetector(
              onTap: () => _afficherOptionsPhoto(context),
              child: Container(
                height: 180,
                decoration: BoxDecoration(
                  color: Colors.grey.shade100,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.grey.shade300),
                ),
                child: _photo == null
                    ? Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.add_a_photo_outlined, size: 36, color: Colors.grey.shade500),
                          const SizedBox(height: 8),
                          Text('Ajouter une photo de l\'ordonnance / facture',
                              style: TextStyle(color: Colors.grey.shade600)),
                        ],
                      )
                    : ClipRRect(
                        borderRadius: BorderRadius.circular(12),
                        child: Image.file(_photo!, fit: BoxFit.cover, width: double.infinity),
                      ),
              ),
            ),
            const SizedBox(height: 20),
            FutureBuilder<List<Prestataire>>(
              future: _futurePrestataires,
              builder: (context, snapshot) {
                if (!snapshot.hasData) {
                  return const LinearProgressIndicator();
                }
                return DropdownButtonFormField<Prestataire>(
                  initialValue: _prestataireChoisi,
                  decoration: const InputDecoration(labelText: 'Prestataire conventionné'),
                  isExpanded: true,
                  items: snapshot.data!
                      .map((p) => DropdownMenuItem(
                            value: p,
                            child: Text('${p.nom} (${p.typePrestataireDisplay})', overflow: TextOverflow.ellipsis),
                          ))
                      .toList(),
                  onChanged: (v) => setState(() => _prestataireChoisi = v),
                );
              },
            ),
            const SizedBox(height: 14),
            DropdownButtonFormField<NatureSoin>(
              initialValue: _natureChoisie,
              decoration: const InputDecoration(labelText: 'Nature du soin'),
              isExpanded: true,
              items: _natures
                  .map((n) => DropdownMenuItem(
                        value: n,
                        child: Text(n.libelle, overflow: TextOverflow.ellipsis),
                      ))
                  .toList(),
              onChanged: (v) => setState(() => _natureChoisie = v),
            ),
            const SizedBox(height: 14),
            if (_ayantsDroit.isNotEmpty)
              DropdownButtonFormField<AyantDroit?>(
                initialValue: _ayantDroitChoisi,
                decoration: const InputDecoration(labelText: 'Bénéficiaire (vide = vous-même)'),
                isExpanded: true,
                items: [
                  const DropdownMenuItem<AyantDroit?>(value: null, child: Text('Moi-même')),
                  ..._ayantsDroit.map((a) => DropdownMenuItem(value: a, child: Text('${a.prenom} ${a.nom}'))),
                ],
                onChanged: (v) => setState(() => _ayantDroitChoisi = v),
              ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _numeroCtrl,
              decoration: const InputDecoration(labelText: 'Numéro d\'ordonnance / acte'),
              validator: (v) => (v == null || v.trim().isEmpty) ? 'Champ obligatoire' : null,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _montantCtrl,
              decoration: const InputDecoration(
                labelText: 'Coût total du soin (KMF)',
                helperText: 'Le montant porté sur l\'ordonnance, avant prise en charge.',
                helperMaxLines: 2,
              ),
              keyboardType: TextInputType.number,
              onChanged: (_) => setState(() {}),
              validator: (v) {
                if (v == null || v.trim().isEmpty) return 'Champ obligatoire';
                final montant = int.tryParse(v.trim());
                if (montant == null) return 'Montant invalide (entier en KMF)';
                if (montant <= 0) return 'Le montant doit être supérieur à 0';
                return null;
              },
            ),
            const SizedBox(height: 10),
            RepartitionPriseEnCharge(prestataire: _prestataireChoisi, montantSaisi: _montantCtrl.text),
            const SizedBox(height: 14),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Date d\'émission'),
              subtitle: Text('${_dateEmission.day.toString().padLeft(2, '0')}/${_dateEmission.month.toString().padLeft(2, '0')}/${_dateEmission.year}'),
              trailing: const Icon(Icons.calendar_today_outlined),
              onTap: _choisirDate,
            ),
            if (_erreur != null) ...[
              const SizedBox(height: 8),
              Text(_erreur!, style: const TextStyle(color: Colors.red, fontSize: 13)),
            ],
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: _envoiEnCours ? null : _soumettre,
              child: _envoiEnCours
                  ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Text('Envoyer'),
            ),
          ],
        ),
      ),
    );
  }

  void _afficherOptionsPhoto(BuildContext context) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.camera_alt_outlined),
              title: const Text('Prendre une photo'),
              onTap: () {
                Navigator.pop(context);
                _choisirPhoto(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choisir depuis la galerie'),
              onTap: () {
                Navigator.pop(context);
                _choisirPhoto(ImageSource.gallery);
              },
            ),
          ],
        ),
      ),
    );
  }
}
