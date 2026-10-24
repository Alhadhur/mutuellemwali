"""Filtres de gabarit : voir backoffice.affichage."""
from django import template

from backoffice import affichage

register = template.Library()

register.filter("milliers", affichage.milliers)
register.filter("kmf", affichage.kmf)
register.filter("badge_statut", affichage.badge_statut)
register.filter("montant_rembourse", affichage.montant_rembourse)
