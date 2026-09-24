import 'package:flutter/material.dart';

import '../models/models.dart';

/// Une entrée du menu latéral.
///
/// `ongletIndex` renseigné = l'entrée bascule sur un onglet de l'écran
/// d'accueil ; sinon `action` est exécutée. `disponible` à false affiche
/// l'entrée grisée avec la pastille « Bientôt », pour annoncer une
/// fonctionnalité prévue sans la rendre cliquable.
class EntreeMenu {
  final IconData icone;
  final String libelle;
  final int? ongletIndex;
  final VoidCallback? action;
  final bool disponible;

  const EntreeMenu({
    required this.icone,
    required this.libelle,
    this.ongletIndex,
    this.action,
    this.disponible = true,
  });
}

class SectionMenu {
  final String? titre;
  final List<EntreeMenu> entrees;

  const SectionMenu({this.titre, required this.entrees});
}

class AppDrawer extends StatelessWidget {
  final Utilisateur? utilisateur;
  final int ongletCourant;
  final ValueChanged<int> onOngletChoisi;
  final List<SectionMenu> sections;

  const AppDrawer({
    super.key,
    required this.utilisateur,
    required this.ongletCourant,
    required this.onOngletChoisi,
    required this.sections,
  });

  @override
  Widget build(BuildContext context) {
    return Drawer(
      child: Column(
        children: [
          _EnTete(utilisateur: utilisateur),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: 8),
              children: [
                for (final section in sections) ...[
                  if (section.titre != null)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 14, 20, 6),
                      child: Text(
                        section.titre!.toUpperCase(),
                        style: TextStyle(
                          fontSize: 11,
                          letterSpacing: 0.8,
                          fontWeight: FontWeight.w700,
                          color: Colors.grey.shade600,
                        ),
                      ),
                    ),
                  for (final entree in section.entrees)
                    _Entree(
                      entree: entree,
                      selectionnee: entree.ongletIndex != null && entree.ongletIndex == ongletCourant,
                      onTap: () {
                        Navigator.of(context).pop();
                        if (entree.ongletIndex != null) {
                          onOngletChoisi(entree.ongletIndex!);
                        } else {
                          entree.action?.call();
                        }
                      },
                    ),
                  if (section != sections.last) const Divider(height: 18),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _EnTete extends StatelessWidget {
  final Utilisateur? utilisateur;

  const _EnTete({required this.utilisateur});

  @override
  Widget build(BuildContext context) {
    final u = utilisateur;
    final fond = Theme.of(context).colorScheme.primary;

    return Container(
      width: double.infinity,
      color: fond,
      padding: EdgeInsets.fromLTRB(20, MediaQuery.of(context).padding.top + 22, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Avatar(utilisateur: u),
          const SizedBox(height: 12),
          Text(
            u?.nomComplet ?? 'Chargement…',
            style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.bold),
          ),
          if (u != null) ...[
            const SizedBox(height: 2),
            Text(
              'Matricule ${u.matricule}${u.region.isNotEmpty ? ' · ${u.region}' : ''}',
              style: const TextStyle(color: Colors.white70, fontSize: 12.5),
            ),
          ],
        ],
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  final Utilisateur? utilisateur;

  const _Avatar({required this.utilisateur});

  @override
  Widget build(BuildContext context) {
    final u = utilisateur;
    final secours = CircleAvatar(
      radius: 28,
      backgroundColor: Colors.white24,
      child: Text(
        u?.initiales ?? '',
        style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
      ),
    );

    if (u?.photoUrl == null || u!.photoUrl!.isEmpty) return secours;

    return ClipOval(
      child: Image.network(
        u.photoUrl!,
        width: 56,
        height: 56,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stack) => secours,
      ),
    );
  }
}

class _Entree extends StatelessWidget {
  final EntreeMenu entree;
  final bool selectionnee;
  final VoidCallback onTap;

  const _Entree({required this.entree, required this.selectionnee, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;

    if (!entree.disponible) {
      return ListTile(
        enabled: false,
        leading: Icon(entree.icone, color: Colors.grey.shade400),
        title: Text(entree.libelle, style: TextStyle(color: Colors.grey.shade500)),
        trailing: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: Colors.grey.shade200,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Text('Bientôt', style: TextStyle(fontSize: 10.5, color: Colors.grey.shade700)),
        ),
      );
    }

    return ListTile(
      selected: selectionnee,
      selectedColor: accent,
      selectedTileColor: accent.withValues(alpha: 0.08),
      leading: Icon(entree.icone),
      title: Text(entree.libelle),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 20),
      onTap: onTap,
    );
  }
}
