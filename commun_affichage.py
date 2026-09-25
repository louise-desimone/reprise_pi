# -*- coding: utf-8 -*-
"""Affichage cartographique commun du plugin Reprise PI.

Ce module centralise :
- les surbrillances temporaires des polygones (hachures jaunes de sélection,
  utilisées par tous les outils d'édition et par le panneau Vérification) ;
- la mise à jour silencieuse de l'état des QAction.

Le clignotement des anomalies au clic, la couche mémoire « Anomalies BD Forêt »
et le zoom sur une emprise ont été déplacés dans verification.py (audit de
placement avant transmission du code) : ils n'étaient utilisés que par ce
panneau, contrairement à tout ce qui reste ici.

Les couleurs, largeurs, distances et temporisations sont définies dans
``commun_parametres.py``.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand

from .commun_parametres import (
    COULEUR_REMPLISSAGE_SURBRILLANCE,
    COULEUR_SURBRILLANCE,
    FINESSE_ARRONDI_SURBRILLANCE,
    LARGEUR_SURBRILLANCE_EXTERIEURE,
    LARGEUR_SURBRILLANCE_INTERIEURE,
    RETRAIT_SURBRILLANCE_PIXELS,
)


# -----------------------------------------------------------------------------
# Interface QGIS
# -----------------------------------------------------------------------------


def definir_action_cochee(action, coche):
    """Coche ou décoche une QAction sans déclencher son signal ``toggled``."""
    if action is None:
        return

    try:
        coche = bool(coche)
        # Rien à faire si l'état est déjà le bon : évite un blocage/déblocage
        # de signal inutile.
        if action.isChecked() == coche:
            return

        # blockSignals(True) empêche setChecked() de redéclencher toggled(),
        # ce qui provoquerait une boucle infinie si cette fonction est
        # elle-même appelée depuis un gestionnaire de toggled.
        etat_signaux = action.blockSignals(True)
        try:
            action.setChecked(coche)
        finally:
            action.blockSignals(etat_signaux)
    except RuntimeError:
        pass


# -----------------------------------------------------------------------------
# Fonctions graphiques internes
# -----------------------------------------------------------------------------


def _creer_contour_polygone(canvas, geometrie, couche, largeur, couleur=None, couleur_remplissage=None):
    """Crée un contour temporaire autour d'une géométrie polygonale."""
    band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
    band.setToGeometry(geometrie, couche)
    band.setStrokeColor(QColor(*(couleur or COULEUR_SURBRILLANCE)))
    band.setFillColor(QColor(*(couleur_remplissage or COULEUR_REMPLISSAGE_SURBRILLANCE)))
    band.setWidth(int(largeur))
    try:
        # Pas de remplissage QBrush par défaut : seul le contour doit être
        # visible, la couleur de remplissage RGBA ci-dessus gère elle-même sa
        # transparence.
        band.setBrushStyle(Qt.NoBrush)
    except (AttributeError, TypeError):
        pass
    band.show()
    return band


def _distance_retrait_surbrillance(canvas, geometrie, couche):
    """Convertit le retrait en pixels en unités de la couche.

    Le contour intérieur garde ainsi un retrait visuel stable au changement de
    zoom, y compris lorsque le SCR du canevas diffère de celui de la couche.
    """
    try:
        # mapUnitsPerPixel() dépend du zoom courant : recalculé à chaque
        # appel (voir SurbrillancePolygone._mettre_a_jour_interieur, appelée
        # sur scaleChanged), jamais mis en cache.
        distance_carte = (
            float(canvas.mapUnitsPerPixel())
            * float(RETRAIT_SURBRILLANCE_PIXELS)
        )
        if distance_carte <= 0:
            return 0.0

        if couche is None:
            return distance_carte

        crs_couche = couche.crs()
        crs_carte = canvas.mapSettings().destinationCrs()
        # Cas courant (couche et carte dans le même SCR) : la distance carte
        # est directement utilisable, pas besoin de conversion.
        if (
            not crs_couche.isValid()
            or not crs_carte.isValid()
            or crs_couche == crs_carte
        ):
            return distance_carte

        # SCR différents : convertit la distance en la mesurant réellement au
        # niveau du centroïde (une distance en mètres ne se convertit pas par
        # un simple facteur d'échelle entre deux SCR quelconques, surtout des
        # projections différentes) — décale un point d'exactement
        # distance_carte dans le SCR carte, puis mesure l'écart obtenu une
        # fois reconverti dans le SCR couche.
        centre = geometrie.centroid()
        if centre is None or centre.isEmpty():
            return distance_carte

        p_couche = QgsPointXY(centre.asPoint())
        vers_carte = QgsCoordinateTransform(
            crs_couche,
            crs_carte,
            QgsProject.instance(),
        )
        vers_couche = QgsCoordinateTransform(
            crs_carte,
            crs_couche,
            QgsProject.instance(),
        )
        p_carte = vers_carte.transform(p_couche)
        p_decale = QgsPointXY(
            p_carte.x() + distance_carte,
            p_carte.y(),
        )
        p_retour = vers_couche.transform(p_decale)

        return p_retour.distance(p_couche)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0.0


# -----------------------------------------------------------------------------
# Surbrillance temporaire des polygones
# -----------------------------------------------------------------------------


class SurbrillancePolygone:
    """Double contour polygonal dont l'aspect reste stable à l'écran."""

    def __init__(self, canvas, geometrie, couche=None, couleur=None, couleur_remplissage=None):
        self.canvas = canvas
        self.couche = couche
        self.geometrie = geometrie
        self.visible = True
        self._couleur = couleur or COULEUR_SURBRILLANCE
        self._couleur_remplissage = couleur_remplissage or COULEUR_REMPLISSAGE_SURBRILLANCE

        # Contour extérieur : largeur fixe en pixels, ne bouge jamais.
        self.contour_exterieur = _creer_contour_polygone(
            canvas,
            geometrie,
            couche,
            LARGEUR_SURBRILLANCE_EXTERIEURE,
            self._couleur,
            self._couleur_remplissage,
        )
        # Contour intérieur : construit ici vide, sa géométrie (un buffer
        # négatif retiré du contour exact) est calculée juste en dessous par
        # _mettre_a_jour_interieur() puis recalculée à chaque zoom.
        self.contour_interieur = QgsRubberBand(
            canvas,
            QgsWkbTypes.PolygonGeometry,
        )
        self.contour_interieur.setStrokeColor(
            QColor(*self._couleur)
        )
        self.contour_interieur.setFillColor(
            QColor(*self._couleur_remplissage)
        )
        self.contour_interieur.setWidth(
            int(LARGEUR_SURBRILLANCE_INTERIEURE)
        )
        try:
            self.contour_interieur.setBrushStyle(Qt.NoBrush)
        except (AttributeError, TypeError):
            pass

        self._connecte = False
        self._mettre_a_jour_interieur()
        try:
            # Le retrait du contour intérieur est en pixels : il doit être
            # recalculé à chaque changement de zoom pour rester visuellement
            # stable (voir _distance_retrait_surbrillance).
            self.canvas.scaleChanged.connect(self._mettre_a_jour_interieur)
            self._connecte = True
        except (AttributeError, RuntimeError, TypeError):
            pass

    def contours(self):
        """Retourne les QgsRubberBand composant la surbrillance."""
        return tuple(
            contour
            for contour in (
                self.contour_exterieur,
                self.contour_interieur,
            )
            if contour is not None
        )

    def definir_visible(self, visible):
        """Affiche ou masque les deux contours sans perdre leur géométrie."""
        self.visible = bool(visible)
        for contour in self.contours():
            try:
                contour.show() if self.visible else contour.hide()
            except RuntimeError:
                pass

    def _mettre_a_jour_interieur(self, *args):
        """Recalcule le contour intérieur pour le zoom courant.

        Appelée une fois à la construction, puis à chaque signal
        ``scaleChanged`` du canevas (voir ``__init__``).
        """
        if self.canvas is None or self.geometrie is None:
            return

        try:
            distance = _distance_retrait_surbrillance(
                self.canvas,
                self.geometrie,
                self.couche,
            )
            if distance <= 0:
                self.contour_interieur.hide()
                return

            # Buffer négatif = contour rétréci d'exactement "distance" par
            # rapport au contour extérieur, quel que soit le zoom.
            interieur = self.geometrie.buffer(
                -distance,
                FINESSE_ARRONDI_SURBRILLANCE,
            )
            if interieur is None or interieur.isEmpty():
                # Polygone trop petit à ce niveau de zoom pour qu'un retrait
                # ait un sens géométrique : masque simplement le contour
                # intérieur plutôt que d'afficher une forme dégénérée.
                self.contour_interieur.hide()
                return

            self.contour_interieur.setToGeometry(
                interieur,
                self.couche,
            )
            if self.visible:
                self.contour_interieur.show()
            else:
                self.contour_interieur.hide()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            try:
                self.contour_interieur.hide()
            except RuntimeError:
                pass

    def supprimer(self):
        """Déconnecte et retire définitivement la surbrillance du canevas."""
        if self._connecte:
            try:
                self.canvas.scaleChanged.disconnect(
                    self._mettre_a_jour_interieur
                )
            except (AttributeError, RuntimeError, TypeError):
                pass
            self._connecte = False

        for contour in self.contours():
            try:
                contour.reset(QgsWkbTypes.PolygonGeometry)
                contour.hide()
                # removeItem() retire réellement le QgsRubberBand de la scène
                # graphique Qt : reset()/hide() seuls le laisseraient présent
                # (invisible mais alloué) jusqu'à la destruction du canevas.
                scene = self.canvas.scene()
                if scene is not None:
                    scene.removeItem(contour)
            except RuntimeError:
                pass

        # Libère les références : une SurbrillancePolygone supprimée ne doit
        # jamais être réutilisée par erreur (ex. un double appel à supprimer()
        # échoue silencieusement au lieu de manipuler un canevas déjà oublié).
        self.contour_exterieur = None
        self.contour_interieur = None
        self.geometrie = None
        self.couche = None
        self.canvas = None


def creer_surbrillance_polygone(canvas, geometrie, couche=None, couleur=None, couleur_remplissage=None):
    """Crée la surbrillance temporaire d'un polygone.

    Le contour extérieur a une largeur fixe en pixels et le contour intérieur
    recalcule son retrait à chaque changement de zoom. ``couleur``/
    ``couleur_remplissage`` (RGBA, ex. ``(0, 140, 255, 245)``) permettent de
    distinguer visuellement une sélection sur une autre couche (ex. « Reporter
    depuis BDFv2 » : bleu pour la sélection en v2, jaune par défaut pour le
    résultat en v3) ; par défaut, reprend le jaune habituel de tous les outils.
    """
    if geometrie is None or geometrie.isEmpty():
        return None
    return SurbrillancePolygone(canvas, geometrie, couche, couleur, couleur_remplissage)


def supprimer_surbrillance_polygone(canvas, surbrillance):
    """Retire une surbrillance temporaire du canevas."""
    if surbrillance is None:
        return

    if isinstance(surbrillance, SurbrillancePolygone):
        surbrillance.supprimer()
        return

    # Certains appelants passent un groupe entier (ex. Fusionner/Séparer avec
    # plusieurs cibles sélectionnées) plutôt qu'une surbrillance unique.
    if isinstance(surbrillance, (tuple, list, set)):
        for contour in list(surbrillance):
            supprimer_surbrillance_polygone(canvas, contour)
        return

    # Repli : un QgsRubberBand brut, pas encapsulé dans SurbrillancePolygone
    # (peut arriver si un appelant construit directement sa propre bande).
    try:
        surbrillance.reset(QgsWkbTypes.PolygonGeometry)
    except (AttributeError, RuntimeError, TypeError):
        pass

    try:
        surbrillance.hide()
        scene = canvas.scene()
        if scene is not None:
            scene.removeItem(surbrillance)
    except (AttributeError, RuntimeError, TypeError):
        pass


def supprimer_surbrillances_polygones(canvas, surbrillances):
    """Retire une collection de surbrillances temporaires."""
    for surbrillance in list(surbrillances or []):
        supprimer_surbrillance_polygone(canvas, surbrillance)


def remplacer_surbrillance_polygone(canvas, surbrillance, geometrie, couche=None):
    """Remplace une surbrillance par celle de la nouvelle géométrie."""
    supprimer_surbrillance_polygone(canvas, surbrillance)
    if geometrie is None or geometrie.isEmpty():
        return None
    return creer_surbrillance_polygone(canvas, geometrie, couche)


