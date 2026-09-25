# -*- coding: utf-8 -*-
"""Remodeler une frontière commune entre deux polygones de la BD Forêt.

L'utilisateur clique sur une limite existante, puis dessine son nouveau tracé.
QGIS applique ensuite ce tracé aux polygones concernés avec sa propre fonction
de remodelage (reshapeGeometry), comme le ferait l'outil natif "Remodeler les
entités".
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLineString,
    QgsPointXY,
    QgsRectangle,
    QgsWkbTypes,
)
from qgis.gui import QgsMapToolCapture, QgsRubberBand

from .commun_affichage import definir_action_cochee
from .commun_edition import (
    AttenteDebutEdition,
    SurveillanceCoucheActive,
    avertir_message_bar,
    basculer_outil_geometrique,
    creer_action_outil,
    detruire_action_outil,
    exiger_fid_valide,
    obtenir_couche_editable,
    recuperer_entite,
    sans_reentrance,
    surface_ha,
)
from .commun_parametres import COULEUR_SURBRILLANCE, LARGEUR_FRONTIERE_REMODELER
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_synchronisation_alertes import synchroniser_zone_outil
from .commun_topologie import (
    limite_polygone,
    nettoyer_geometrie_base,
    partage_une_limite,
)


# Déplacée depuis commun_topologie.py (audit de placement avant transmission
# du code) : n'était utilisée que par cet outil.
def _distance_point_geometrie(point, geometrie):
    """Distance d'un point (avec ``.x()``/``.y()``) à une géométrie quelconque."""
    try:
        geom_point = QgsGeometry.fromPointXY(QgsPointXY(point.x(), point.y()))
        return abs(float(geom_point.distance(geometrie)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return float("inf")


# Déplacées depuis commun_affichage.py (audit de placement avant transmission
# du code) : n'étaient utilisées que par cet outil (verrouillage visuel de la
# frontière avant le tracé de remplacement).
def _creer_ligne_surbrillance(canvas, geometrie, couche, couleur, largeur):
    """Affiche une géométrie linéaire en surbrillance temporaire."""
    if geometrie is None or geometrie.isEmpty():
        return None
    try:
        bande = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        bande.setToGeometry(geometrie, couche)
        bande.setColor(QColor(*couleur))
        try:
            bande.setStrokeColor(QColor(*couleur))
        except (AttributeError, RuntimeError):
            pass
        bande.setWidth(largeur)
        bande.show()
        return bande
    except (AttributeError, RuntimeError, TypeError):
        return None


def _supprimer_ligne_surbrillance(canvas, bande):
    """Retire une surbrillance créée par ``_creer_ligne_surbrillance``."""
    if bande is None:
        return
    try:
        bande.reset(QgsWkbTypes.LineGeometry)
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        canvas.scene().removeItem(bande)
    except (AttributeError, RuntimeError, TypeError):
        pass


class OutilLigneRemodelage(QgsMapToolCapture):
    """Capture le nouveau tracé dessiné par l'utilisateur."""

    def __init__(self, plugin):
        super().__init__(
            plugin.iface.mapCanvas(),
            plugin.iface.cadDockWidget(),
            QgsMapToolCapture.CaptureLine,
        )
        self.plugin = plugin

    def cadCanvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self.plugin.frontiere_active:
            event.snapPoint()
            match = event.mapPointMatch()
            if not self.plugin.preparer_frontiere(
                match, event.mapPoint(), event.originalMapPoint()
            ):
                return
        super().cadCanvasReleaseEvent(event)

    def lineCaptured(self, line):
        if line is None:
            return
        try:
            # Le WKT évite les soucis de typage/ownership propres aux bindings
            # PyQGIS lors du passage direct de l'objet interne à QgsGeometry.
            geometrie = QgsGeometry.fromWkt(line.asWkt())
        except (TypeError, RuntimeError, AttributeError):
            self.plugin._avertir("Le tracé de remodelage n'a pas pu être lu.")
            self.plugin.reinitialiser_trace()
            return
        self.plugin.traiter_ligne_dessinee(geometrie)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            try:
                self.stopCapturing()
            except (RuntimeError, AttributeError):
                pass
            self.plugin.reinitialiser_trace()
            event.accept()
            return
        super().keyPressEvent(event)

class RemodelerBdForetPlugin:
    """Remodèle une frontière partagée entre deux polygones BD Forêt.

    Une bordure extérieure seule (sans second polygone voisin, ex. contre
    l'emprise) est explicitement refusée par _limites_pres_du_point() : voir
    le message d'avertissement "le remodelage de la bordure extérieure n'est
    pas possible".
    """

    NOM_OUTIL = "Remodeler la limite entre 2 polygones BD Forêt"

    def __init__(self, iface, manager=None):
        self.iface = iface
        self.manager = manager
        self.canvas = iface.mapCanvas()
        self.action = None
        self.actif = False
        self.couche = None
        self.outil_carte = None
        self.traitement_en_cours = False
        self._changement_outil = False  # pour ne pas réagir à nos propres changements d'outil
        self.frontiere_active = False
        self._candidats_frontiere = []
        self._surbrillances_frontiere = []
        self._attente_edition = AttenteDebutEdition(self._edition_demarree)
        self._surveillance = SurveillanceCoucheActive(self._desactiver)

    # ------------------------------------------------------------------
    # Chargement / activation
    # ------------------------------------------------------------------

    def initGui(self):
        chemin_icone = os.path.join(os.path.dirname(__file__), "icon_remodeler.svg")
        self.action = creer_action_outil(
            self.iface, self.canvas, self.NOM_OUTIL, chemin_icone,
            self.NOM_OUTIL, self._basculer_outil,
        )
        self.canvas.mapToolSet.connect(self._outil_carte_change)
        self._surveillance.demarrer()

    def unload(self):
        self._attente_edition.annuler()
        self._surveillance.arreter()
        try:
            self.canvas.mapToolSet.disconnect(self._outil_carte_change)
        except (TypeError, RuntimeError):
            pass
        self.action = detruire_action_outil(
            self.iface, self.action, self.NOM_OUTIL, self._basculer_outil
        )

    def _basculer_outil(self, coche):
        basculer_outil_geometrique(self, coche)

    def _activer(self):
        couche, editable = obtenir_couche_editable(
            self.iface, self.NOM_OUTIL, manager=self.manager, outil=self
        )
        if couche is None:
            return False
        self.couche = couche
        if not editable:
            # Couche trouvée mais pas encore en édition : le bouton reste
            # coché, et on s'accroche directement au signal de début
            # d'édition pour terminer l'activation sans que l'utilisateur
            # ait besoin de recliquer sur le bouton.
            self.actif = False
            self._attente_edition.attendre(couche)
            return True

        self._attente_edition.annuler()
        self.actif = True
        self._surveillance.surveiller_couche(couche)
        self.outil_carte = OutilLigneRemodelage(self)
        self._changement_outil = True
        try:
            self.canvas.setMapTool(self.outil_carte)
        finally:
            self._changement_outil = False
        return True

    def _edition_demarree(self, couche):
        """Termine l'activation si le bouton est toujours coché."""
        if self.action is None or not self.action.isChecked():
            return
        if self.couche is not couche:
            return
        if not self._activer():
            definir_action_cochee(self.action, False)

    def _desactiver(self):
        self._attente_edition.annuler()
        self._surveillance.oublier_couche()
        self.actif = False
        self.couche = None
        self.reinitialiser_trace()
        if self.outil_carte is not None:
            try:
                self.outil_carte.stopCapturing()
            except (RuntimeError, AttributeError):
                pass
        self.outil_carte = None
        definir_action_cochee(self.action, False)

    def desactiver_pour_autre_outil(self):
        self._desactiver()

    def _outil_carte_change(self, nouvel_outil, ancien_outil=None):
        """QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive."""
        if self._changement_outil or not self.actif:
            return
        if nouvel_outil is not self.outil_carte:
            self._desactiver()

    # ------------------------------------------------------------------
    # Détection de la frontière
    # ------------------------------------------------------------------

    def preparer_frontiere(self, match, point_carte, point_original_carte):
        if not self.actif:
            return False
        if not match.isValid() or not (match.hasVertex() or match.hasEdge()):
            self._avertir(
                "Accrochez le premier point à un sommet ou à un segment."
            )
            return False

        point = self._point_vers_couche(point_carte)
        if point is None:
            self._avertir("Le point accroché n'a pas pu être reprojeté.")
            return False

        # On ne se fie pas à match.layer() : à la bordure de l'Emprise, une
        # limite de polygone BD Forêt et une limite d'Emprise coïncident
        # exactement, et le snapping global de QGIS peut accrocher l'une ou
        # l'autre. On cherche directement une limite BD Forêt près du point,
        # quelle que soit la couche sur laquelle QGIS a affiché l'accrochage.
        candidats, bordure_seule = self._limites_pres_du_point(point)
        if not candidats:
            if bordure_seule:
                self._avertir(
                    "Vous êtes en limite du masque : le remodelage de la bordure "
                    "extérieure n'est pas possible."
                )
            else:
                self._avertir("Aucune limite de la couche BD Forêt n'a été trouvée à cet endroit.")
            return False

        self._candidats_frontiere = candidats
        self.frontiere_active = True
        self._afficher_limites([c["geometrie"] for c in candidats])

        if len(candidats) > 1:
            self.iface.messageBar().pushInfo(
                self.NOM_OUTIL,
                "Attention, vous êtes à un carrefour de plusieurs polygones : veillez à ne modifier "
                "la limite qu'entre 2 polygones.",
            )
        return True

    def _afficher_limites(self, geometries):
        self._supprimer_surbrillance_frontiere()
        self._surbrillances_frontiere = [
            _creer_ligne_surbrillance(
                self.canvas, g, self.couche, COULEUR_SURBRILLANCE, LARGEUR_FRONTIERE_REMODELER
            )
            for g in geometries
            if g is not None
        ]

    def _supprimer_surbrillance_frontiere(self):
        bandes = self._surbrillances_frontiere
        self._surbrillances_frontiere = []
        for bande in bandes:
            _supprimer_ligne_surbrillance(self.canvas, bande)

    def _point_vers_couche(self, point_carte):
        try:
            return self.canvas.mapSettings().mapToLayerCoordinates(
                self.couche, QgsPointXY(point_carte.x(), point_carte.y())
            )
        except (AttributeError, RuntimeError, TypeError):
            return None

    def _limites_pres_du_point(self, point):
        """Limites entre paires de polygones proches de `point`, triées du plus proche au plus loin.

        On ne part d'aucun polygone particulier : le clic peut avoir été
        accroché par QGIS sur une autre couche que la BD Forêt (ex. l'Emprise,
        dont la limite coïncide exactement avec une bordure extérieure). On
        cherche donc directement, parmi les polygones BD Forêt proches du
        point, toutes les paires qui partagent une limite à cet endroit.
        """
        # Distance (mètres, dans l'unité de la couche) à laquelle on cherche des
        # polygones autour du point cliqué. C'est la précision du
        # projet (1 cm), pas une notion générale de "tolérance topologique".
        distance_voisin_m = 0.01
        rayon = distance_voisin_m * 4.0
        rectangle = QgsRectangle(
            point.x() - rayon, point.y() - rayon, point.x() + rayon, point.y() + rayon
        )
        requete = QgsFeatureRequest().setFilterRect(rectangle).setNoAttributes()

        limites = {}
        for entite in self.couche.getFeatures(requete):
            if not entite.hasGeometry():
                continue
            limite = limite_polygone(entite.geometry())
            if limite is not None and not limite.isEmpty():
                limites[int(entite.id())] = limite

        candidats = []
        fids = sorted(limites)
        for i, fid_a in enumerate(fids):
            for fid_b in fids[i + 1:]:
                contact = partage_une_limite(limites[fid_a], limites[fid_b], distance_voisin_m)
                if contact is None:
                    continue

                distance = _distance_point_geometrie(point, contact)
                if distance > distance_voisin_m * 2.0:
                    continue

                candidats.append(
                    {"fids": (fid_a, fid_b), "geometrie": contact, "distance": distance}
                )

        candidats.sort(key=lambda c: c["distance"])

        # Si aucune paire n'a été trouvée, on distingue le cas où le point est
        # quand même sur la bordure d'un polygone BD Forêt (bordure extérieure,
        # sans voisin de ce côté) d'un simple clic à côté de tout polygone.
        bordure_seule = False
        if not candidats:
            for limite in limites.values():
                if _distance_point_geometrie(point, limite) <= distance_voisin_m * 2.0:
                    bordure_seule = True
                    break

        return candidats, bordure_seule

    # ------------------------------------------------------------------
    # Remodelage
    # ------------------------------------------------------------------

    @sans_reentrance
    def traiter_ligne_dessinee(self, geometrie_tracee):
        if not self.frontiere_active or not self._candidats_frontiere:
            self._avertir("Commencez le tracé sur une limite jaune surlignée.")
            self.reinitialiser_trace()
            return

        ligne = QgsLineString(list(geometrie_tracee.vertices()))

        resultat = self._trouver_paire_remodelable(ligne)
        if resultat is None:
            self._avertir("Le tracé ne correspond à aucune des limites indiquées en jaune.")
            self.reinitialiser_trace()
            return
        fid_a, anciennes, nouvelles = resultat

        try:
            zone_sync = nettoyer_geometrie_base(
                QgsGeometry.unaryUnion(list(anciennes.values()) + list(nouvelles.values()))
            )
        except (AttributeError, RuntimeError, TypeError):
            zone_sync = None
        if zone_sync is None or zone_sync.isEmpty():
            zone_sync = anciennes[fid_a]

        try:
            self._appliquer_remodelage(nouvelles, zone_sync)
        except Exception as erreur:
            self.iface.messageBar().pushCritical(
                self.NOM_OUTIL, f"Le remodelage a échoué : {erreur}"
            )
        self.reinitialiser_trace()

    def _trouver_paire_remodelable(self, ligne):
        """Essaie chaque paire candidate (la plus proche du clic d'abord) et retient
        la première dont les deux polygones sont effectivement remodelables par ce tracé.

        Plusieurs limites peuvent être affichées en jaune à un carrefour, mais une
        seule correspond réellement au tracé dessiné : on laisse reshapeGeometry()
        lui-même trancher plutôt que de se fier à la proximité du premier clic.
        """
        for candidat in self._candidats_frontiere:
            fid_a, fid_b = (int(candidat["fids"][0]), int(candidat["fids"][1]))

            anciennes = {}
            for fid in (fid_a, fid_b):
                entite = recuperer_entite(self.couche, fid)
                if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
                    anciennes = None
                    break
                anciennes[fid] = QgsGeometry(entite.geometry())
            if anciennes is None:
                continue

            nouvelles = {}
            for fid in (fid_a, fid_b):
                nouvelle = self._remodeler_polygone(anciennes[fid], ligne, fid, silencieux=True)
                if nouvelle is None:
                    nouvelles = None
                    break
                nouvelles[fid] = nouvelle
            if nouvelles is None:
                continue

            return fid_a, anciennes, nouvelles
        return None

    def _remodeler_polygone(self, ancienne, ligne, fid, silencieux=False):
        """Applique reshapeGeometry() (le moteur natif QGIS) à un seul polygone."""
        nouvelle = QgsGeometry.fromWkt(ancienne.asWkt())
        try:
            resultat = nouvelle.reshapeGeometry(ligne)
        except (AttributeError, RuntimeError, TypeError) as erreur:
            if not silencieux:
                self._avertir(f"QGIS n'a pas pu remodeler le polygone {fid} : {erreur}")
            return None

        if resultat != Qgis.GeometryOperationResult.Success:
            # reshapeGeometry() refuse à tort sur certains polygones complexes
            # (confirmé avec l'outil natif QGIS "Remodeler les entités", qui
            # échoue de la même façon) même quand le résultat serait valide.
            # On tente notre propre reconstruction avant d'abandonner.
            secours = self._reshape_secours(ancienne, ligne)
            if secours is not None:
                return secours
            if not silencieux:
                self._avertir(f"Le tracé n'est pas valide pour remodeler le polygone {fid}.")
            return None

        nouvelle = nettoyer_geometrie_base(nouvelle)
        if nouvelle is None or nouvelle.isEmpty():
            if not silencieux:
                self._avertir(f"Le remodelage du polygone {fid} produirait une géométrie invalide.")
            return None
        return nouvelle

    def _reshape_secours(self, ancienne, ligne):
        """Reconstruit le contour nous-mêmes quand reshapeGeometry() refuse à tort.

        Cherche, sur l'anneau (extérieur ou un trou) où le tracé touche le
        polygone à ses deux extrémités, la portion la plus courte entre ces
        deux points, et la remplace par le tracé. Le résultat n'est retourné
        que s'il est géométriquement valide : ce repli ne relâche jamais la
        vérification, il essaie juste une reconstruction que reshapeGeometry()
        n'a pas tentée.
        """
        try:
            points_trace = [QgsPointXY(p) for p in ligne.vertices()]
        except (AttributeError, RuntimeError, TypeError):
            return None
        if len(points_trace) < 2:
            return None
        p_debut, p_fin = points_trace[0], points_trace[-1]

        try:
            if ancienne.isMultipart():
                # Un GeoPackage type souvent la colonne géométrie en
                # MultiPolygon même quand chaque entité n'a qu'une seule
                # partie réelle (cas de fid 14 dans nos tests) : on gère ce
                # cas courant, mais pas les vraies entités multiparties.
                parties = ancienne.asMultiPolygon()
                if len(parties) != 1:
                    return None
                anneaux = parties[0]
            else:
                anneaux = ancienne.asPolygon()
        except (AttributeError, RuntimeError, TypeError):
            return None
        if not anneaux:
            return None

        # Distance (mètres) tolérée entre l'extrémité du tracé et le sommet du
        # contour le plus proche. Écrite en dur : le tracé est dessiné à la
        # souris, donc moins précis qu'un accrochage automatique.
        tolerance = 0.05

        for index_anneau, anneau_brut in enumerate(anneaux):
            contour = [QgsPointXY(p) for p in anneau_brut]
            if len(contour) > 1 and contour[0] == contour[-1]:
                contour = contour[:-1]
            n = len(contour)
            if n < 3:
                continue

            ia = min(range(n), key=lambda i: contour[i].distance(p_debut))
            ib = min(range(n), key=lambda i: contour[i].distance(p_fin))
            if contour[ia].distance(p_debut) > tolerance or contour[ib].distance(p_fin) > tolerance:
                continue
            if ia == ib:
                continue

            def arc_avant(depart, arrivee):
                if depart <= arrivee:
                    return contour[depart:arrivee + 1]
                return contour[depart:] + contour[:arrivee + 1]

            arc_ia_vers_ib = arc_avant(ia, ib)
            arc_ib_vers_ia = arc_avant(ib, ia)

            # On remplace toujours la portion la plus courte (en nombre de
            # sommets) par le tracé : c'est celle-là que l'utilisateur édite
            # localement, l'autre représente le reste du polygone.
            if len(arc_ia_vers_ib) <= len(arc_ib_vers_ia):
                nouveau_contour = points_trace + arc_ib_vers_ia[1:-1]
            else:
                nouveau_contour = list(reversed(points_trace)) + arc_ia_vers_ib[1:-1]

            autres_anneaux = [anneau for j, anneau in enumerate(anneaux) if j != index_anneau]
            candidat = QgsGeometry.fromPolygonXY([nouveau_contour] + autres_anneaux)
            candidat = nettoyer_geometrie_base(candidat)
            if candidat is not None and not candidat.isEmpty() and candidat.isGeosValid():
                return candidat

        return None

    @vue_stable_pendant_modification
    def _appliquer_remodelage(self, nouvelles, zone_sync):
        """Applique géométries + surfaces + alertes dans une commande annulable."""
        commande_ouverte = False
        index_surface = self.couche.fields().indexOf("surface")

        try:
            self.couche.beginEditCommand(self.NOM_OUTIL)
            commande_ouverte = True

            for fid, geometrie in nouvelles.items():
                exiger_fid_valide(self.couche, fid, "remodeler la géométrie")
                if not self.couche.changeGeometry(fid, geometrie):
                    raise RuntimeError(f"la géométrie de l'entité {fid} n'a pas pu être modifiée")
                if index_surface >= 0:
                    surface = surface_ha(geometrie)
                    if not self.couche.changeAttributeValue(fid, index_surface, surface):
                        raise RuntimeError(f"la surface de l'entité {fid} n'a pas pu être recalculée")

            synchroniser_zone_outil(
                self.manager, self.iface, self.couche, zone_sync, self.NOM_OUTIL
            )

            self.couche.endEditCommand()
            commande_ouverte = False

            self.couche.triggerRepaint(True)
            try:
                self.canvas.refresh()
            except RuntimeError:
                pass
        except Exception:
            if commande_ouverte:
                try:
                    self.couche.destroyEditCommand()
                except (AttributeError, RuntimeError):
                    pass
            raise

    def reinitialiser_trace(self):
        self.frontiere_active = False
        self._candidats_frontiere = []
        self._supprimer_surbrillance_frontiere()

    def _avertir(self, message):
        avertir_message_bar(self.iface, self.NOM_OUTIL, message)
