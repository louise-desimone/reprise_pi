# -*- coding: utf-8 -*-
"""Initialisation standard du plugin QGIS."""


# QGIS appelle cette fonction par son nom (convention imposée par l'API
# plugin) au chargement, avec sa propre instance d'iface (point d'entrée vers
# la fenêtre principale, le canevas, les couches...). Rien ne l'appelle
# ailleurs dans le code : ce n'est pas du code mort.
def classFactory(iface):
    """Fonction appelée par QGIS lors du chargement du plugin."""
    # Import différé : évite de charger tout le plugin (et ses dépendances
    # PyQt/QGIS) tant que QGIS n'a pas réellement demandé à l'activer.
    from .commun_outils import OutilsBdForet
    return OutilsBdForet(iface)
