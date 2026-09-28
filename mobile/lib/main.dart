import 'package:flutter/material.dart';

import 'screens/login_screen.dart';
import 'screens/home_screen.dart';
import 'screens/lock_screen.dart';
import 'services/api_service.dart';
import 'services/lock_service.dart';

void main() {
  runApp(const MutuelleYatruApp());
}

class MutuelleYatruApp extends StatefulWidget {
  const MutuelleYatruApp({super.key});

  @override
  State<MutuelleYatruApp> createState() => _MutuelleYatruAppState();
}

class _MutuelleYatruAppState extends State<MutuelleYatruApp> with WidgetsBindingObserver {
  final _navigatorKey = GlobalKey<NavigatorState>();
  bool _futEnArrierePlan = false;
  bool _verrouAffiche = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Le verrouillage au lancement à froid est géré par _StartupGate. Ici,
    // on ne s'occupe que du retour au premier plan après une mise en
    // arrière-plan effective — sinon le premier `resumed` du démarrage
    // pousserait un deuxième écran de verrouillage par-dessus le premier.
    if (state == AppLifecycleState.paused) {
      _futEnArrierePlan = true;
    } else if (state == AppLifecycleState.resumed && _futEnArrierePlan) {
      _futEnArrierePlan = false;
      _verrouillerSiNecessaire();
    }
  }

  Future<void> _verrouillerSiNecessaire() async {
    if (_verrouAffiche) return;
    final connecte = await ApiService.instance.isLoggedIn;
    if (!connecte) return;
    final aUnPin = await LockService.instance.hasPin;
    if (!aUnPin) return;

    final navigator = _navigatorKey.currentState;
    if (navigator == null) return;

    _verrouAffiche = true;
    await navigator.push(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (context) => LockScreen(onUnlocked: () => Navigator.of(context).pop()),
      ),
    );
    _verrouAffiche = false;
  }

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFF2563EB);
    return MaterialApp(
      navigatorKey: _navigatorKey,
      title: 'Mutuelle Yatru',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: accent, primary: accent),
        scaffoldBackgroundColor: const Color(0xFFF4F6F8),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF111827),
          foregroundColor: Colors.white,
          elevation: 0,
        ),
        cardTheme: CardThemeData(
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: Colors.grey.shade300),
          ),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: accent,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(vertical: 14),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide(color: Colors.grey.shade300),
          ),
        ),
      ),
      home: const _StartupGate(),
    );
  }
}

class _StartupGate extends StatefulWidget {
  const _StartupGate();

  @override
  State<_StartupGate> createState() => _StartupGateState();
}

class _StartupGateState extends State<_StartupGate> {
  bool _loading = true;
  bool _loggedIn = false;
  bool _pinConfigure = false;
  bool _deverrouille = false;

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    final loggedIn = await ApiService.instance.isLoggedIn;
    final pinConfigure = loggedIn && await LockService.instance.hasPin;
    if (!mounted) return;
    setState(() {
      _loggedIn = loggedIn;
      _pinConfigure = pinConfigure;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!_loggedIn) {
      return const LoginScreen();
    }
    if (_pinConfigure && !_deverrouille) {
      return LockScreen(onUnlocked: () => setState(() => _deverrouille = true));
    }
    return const HomeScreen();
  }
}
