# -*- coding: utf-8 -*-
"""Point d'entrée du plugin Reprise PI.

Chaque outil reste dans son propre module. Ce gestionnaire ne fait que les
charger et garantir qu'un seul outil géométrique prend la main sur la carte.
"""

from .commun_compteur_alertes import CompteurAlertes
from .edition_creer import CreerPolygonePlugin
from .edition_separer import SeparerPolygonePlugin
from .commun_etat_session import EtatSessionProjet
from .edition_fusionner import FusionnerBdForetPlugin
from .edition_reporter_bdfv2 import ReporterBdFv2Plugin
from .commun_historique_formulaires import HistoriqueFormulaires
from .commun_protection_vue import ProtectionVueCarte
from .edition_remodeler import RemodelerBdForetPlugin
from .verification import VerificationBdForetPlugin


class OutilsBdForet:
    """Charge, coordonne et décharge les outils de Reprise PI."""

    def __init__(self, iface):
        self.iface = iface
        # Un seul gardien de vue partagé par toutes les modifications de géométrie.
        self.protection_vue = ProtectionVueCarte(iface.mapCanvas())

        # Chaque outil/service reçoit `manager=self` : c'est ce qui lui permet
        # d'appeler desactiver_autres_outils_geometriques() ci-dessous (via
        # obtenir_couche_editable dans commun_edition.py) sans que ce fichier
        # ait besoin de connaître la logique interne de chaque outil.
        self.remodeler = RemodelerBdForetPlugin(iface, manager=self)
        self.creer_polygone = CreerPolygonePlugin(iface, manager=self)
        self.separer = SeparerPolygonePlugin(iface, manager=self)
        self.fusionner = FusionnerBdForetPlugin(iface, manager=self)
        self.reporter_bdfv2 = ReporterBdFv2Plugin(iface, manager=self)
        self.verification = VerificationBdForetPlugin(iface, manager=self)
        self.historique = HistoriqueFormulaires(iface)
        # CompteurAlertes a besoin de l'historique pour savoir quel formulaire
        # est actuellement ouvert (voir commun_compteur_alertes.py).
        self.compteur_alertes = CompteurAlertes(iface, historique=self.historique)
        self.etat_session = EtatSessionProjet(iface)
        # Câblage par callback plutôt que par import direct : HistoriqueFormulaires
        # ne connaît ni CompteurAlertes ni EtatSessionProjet, seulement les trois
        # fonctions qu'on lui passe ici. Ça évite une dépendance circulaire entre
        # ces trois fichiers (chacun pourrait sinon avoir besoin des deux autres).
        self.historique.definir_recalcul_alertes(
            self.compteur_alertes.recalculer_tous_les_compteurs
        )
        self.historique.definir_etat_formulaire(
            self.etat_session.memoriser_formulaire
        )
        self.historique.definir_fid_persistant(
            self.etat_session.fid_memorise_pour_couche
        )

        # Sous-ensemble de `services` : seuls ces 5 outils posent un curseur
        # sur la carte et doivent donc être mutuellement exclusifs (voir
        # desactiver_autres_outils_geometriques ci-dessous). Vérification,
        # l'historique, le compteur d'alertes et l'état de session tournent en
        # arrière-plan sans jamais prendre la main sur le canevas.
        self.outils_geometriques = (
            self.remodeler,
            self.creer_polygone,
            self.separer,
            self.fusionner,
            self.reporter_bdfv2,
        )
        # Tout ce qui a un cycle de vie QGIS (initGui/unload), dans l'ordre où
        # initGui() doit s'exécuter.
        self.services = (
            self.remodeler,
            self.creer_polygone,
            self.separer,
            self.fusionner,
            self.reporter_bdfv2,
            self.verification,
            self.historique,
            self.compteur_alertes,
            self.etat_session,
        )

    def initGui(self):
        for service in self.services:
            service.initGui()

    def unload(self):
        # Ordre inverse d'initGui() (dernier chargé, premier déchargé) et un
        # échec d'un service ne doit jamais empêcher les autres de se
        # décharger correctement : QGIS peut fermer ou recharger le plugin
        # dans des conditions imprévisibles (fermeture brutale, rechargement
        # à chaud pendant le développement...).
        for service in reversed(self.services):
            try:
                service.unload()
            except Exception:
                pass

    def desactiver_autres_outils_geometriques(self, outil_actif):
        """Désactive tous les outils géométriques sauf celui qui prend la main."""
        for outil in self.outils_geometriques:
            if outil is outil_actif:
                continue
            try:
                outil.desactiver_pour_autre_outil()
            except (AttributeError, RuntimeError, TypeError):
                pass
