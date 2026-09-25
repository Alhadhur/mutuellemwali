"""Tests du fuseau horaire de la mutuelle.

L'application est hébergée hors des Comores, sur un serveur réglé en UTC.
« Aujourd'hui » doit donc être la date **comorienne**, pas celle du serveur :
entre 21h et minuit UTC, les deux diffèrent d'un jour, et un soin enregistré
ce soir-là tomberait dans la mauvaise période de quota ou le mauvais jour de
rapport.
"""
from datetime import datetime, timezone as tz_python
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from parametrage.models import Parametrage


class FuseauTest(TestCase):
    def test_le_fuseau_est_celui_des_comores(self):
        self.assertEqual(settings.TIME_ZONE, "Indian/Comoro")

    def test_les_dates_sont_stockees_en_utc(self):
        """USE_TZ garantit que changer de fuseau ne réinterprète pas les
        données déjà enregistrées."""
        self.assertTrue(settings.USE_TZ)

    def test_en_soiree_la_date_locale_devance_celle_du_serveur(self):
        """Le cas qui motive la correction : 22h30 UTC, soit 1h30 le lendemain
        aux Comores."""
        instant = datetime(2026, 9, 24, 22, 30, tzinfo=tz_python.utc)

        self.assertEqual(instant.date().isoformat(), "2026-09-24")
        self.assertEqual(timezone.localtime(instant).date().isoformat(), "2026-09-25")

    def test_la_periode_de_quota_suit_la_date_locale(self):
        """Un soin enregistré en soirée le dernier jour d'un cycle doit tomber
        dans le cycle suivant, comme le vit l'agent."""
        parametres = Parametrage.charger()
        parametres.duree_cycle_mois = 1
        parametres.save()

        instant = datetime(2026, 9, 30, 22, 30, tzinfo=tz_python.utc)  # 1er octobre aux Comores
        with patch("django.utils.timezone.localdate", return_value=timezone.localtime(instant).date()):
            debut, fin = parametres.periode()

        self.assertEqual(debut.month, 10)
        self.assertEqual(fin.month, 10)
