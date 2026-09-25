"""Panneau de recherche des anomalies et création de couches temporaires.

Ordre des catégories : petits polygones, multiparties, recouvrements, trous, adjacents, incohérence essence / TFF.

"Rechercher des anomalies" commence toujours par un nettoyage automatique et
silencieux de la couche (verification_nettoyage_automatique.py) : hors
emprise et géométries parasites (pics, non-conformité OGC, micro-écarts
entre voisins) ne sont plus des contrôles du panneau, ce sont des artefacts
toujours corrigés sans arbitrage humain avant même la recherche.
"""

from pathlib import Path
import builtins
import hashlib

from qgis.PyQt.QtCore import Qt, QTimer, QDateTime, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QTreeWidgetItem,
)
from qgis.core import (
    QgsApplication, QgsDistanceArea, QgsFeature, QgsFeatureRequest, QgsField, QgsFillSymbol,
    QgsGeometry, QgsLinePatternFillSymbolLayer, QgsLineSymbol, QgsProject,
    QgsRectangle, QgsSpatialIndex, QgsVectorLayer, QgsWkbTypes,
)

from .commun_affichage import (
    SurbrillancePolygone, creer_surbrillance_polygone, supprimer_surbrillances_polygones,
)
from .commun_couches import couche_est_disponible, trouver_couche_emprise, trouver_couche_travail
from .commun_parametres import (
    ANGLES_HACHURE_ANOMALIE,
    CLIGNOTEMENT_ANOMALIE_ETAPES_MS,
    CLIGNOTEMENT_ANOMALIE_FIN_MS,
    COULEUR_CONTOUR_ANOMALIE,
    COULEUR_HACHURE_ANOMALIE,
    COULEUR_REMPLISSAGE_ANOMALIE,
    CRS_ANOMALIES_DEFAUT,
    DELAI_RAFRAICHISSEMENT_VERIFICATION_MS,
    DISTANCE_HACHURE_ANOMALIE,
    LARGEUR_CONTOUR_ANOMALIE,
    LARGEUR_HACHURE_ANOMALIE,
    NOM_COUCHE_ANOMALIES,
    SEUIL_TACHE_RELATIONS,
    TAILLE_LOT_PREPARATION_VERIFICATION,
    TAILLE_LOT_TROUS_VERIFICATION,
    TAILLE_LOT_VOISINAGE_VERIFICATION,
    TOLERANCE_ADJACENCE_M,
    resoudre_champs,
    signature_attributs,
)
from .commun_topologie import (
    extraire_parties_multipartie_brutes,
    extraire_parties_polygonales,
)
from . import verification_surface05ha as verif_surface
from . import verification_entites_multiparties as verif_multiparties
from . import verification_recouvrements as verif_recouvrements
from . import verification_trous as verif_trous
from . import verification_polygones_adjacents_attributs_identiques as verif_adjacents
from . import verification_coherence_essence_tff as verif_coherence
from . import verification_nettoyage_automatique as verif_nettoyage
from .verification_tache_relations import TacheRelationsVoisines
from .verification_panneau import PanneauVerification, ORDRE_REGLES_METIER, LIBELLES_REGLES_METIER


# Déplacée depuis commun_affichage.py (audit de placement avant transmission
# du code) : n'était utilisée que par ce panneau.
def zoomer_sur_emprise(canvas, emprise, facteur=1.25):
    """Zoome sur une emprise QGIS en conservant une marge autour."""
    if emprise is None:
        return False

    try:
        rectangle = QgsRectangle(emprise)
        rectangle.scale(float(facteur))
        canvas.setExtent(rectangle)
        canvas.refresh()
        return True
    except (RuntimeError, TypeError, ValueError):
        return False


# Déplacées depuis commun_affichage.py (audit de placement avant transmission
# du code) : symbologie de la couche mémoire "Anomalies BD Forêt", n'était
# utilisée que par ce panneau.
def _couleur_vers_texte(couleur):
    """Convertit une couleur RGBA en chaîne comprise par les symboles QGIS."""
    return ",".join(str(valeur) for valeur in couleur)


def _creer_symbole_anomalies():
    """Construit la symbologie de la couche temporaire des anomalies."""
    symbole = QgsFillSymbol.createSimple(
        {
            "color": _couleur_vers_texte(COULEUR_REMPLISSAGE_ANOMALIE),
            "outline_color": _couleur_vers_texte(COULEUR_CONTOUR_ANOMALIE),
            "outline_width": str(LARGEUR_CONTOUR_ANOMALIE),
            "outline_style": "solid",
        }
    )

    for angle in ANGLES_HACHURE_ANOMALIE:
        hachure = QgsLinePatternFillSymbolLayer()
        hachure.setLineAngle(angle)
        hachure.setDistance(DISTANCE_HACHURE_ANOMALIE)
        hachure.setSubSymbol(
            QgsLineSymbol.createSimple(
                {
                    "color": _couleur_vers_texte(COULEUR_HACHURE_ANOMALIE),
                    "width": str(LARGEUR_HACHURE_ANOMALIE),
                }
            )
        )
        symbole.appendSymbolLayer(hachure)

    return symbole


class CoucheSurbrillanceVerification:
    """Crée, retrouve et met à jour la couche mémoire des anomalies."""

    def __init__(self):
        self.layer_id = None

    def detacher(self):
        """Oublie la couche courante sans la supprimer du projet."""
        self.layer_id = None

    def courante(self):
        """Retourne la couche d'anomalies courante si elle existe encore."""
        if not self.layer_id:
            return None

        couche = QgsProject.instance().mapLayer(self.layer_id)
        if couche is None:
            self.layer_id = None
        return couche

    @staticmethod
    def prochain_nom():
        """Retourne un nom disponible pour la couche d'anomalies."""
        noms_existants = {
            couche.name()
            for couche in QgsProject.instance().mapLayers().values()
        }

        if NOM_COUCHE_ANOMALIES not in noms_existants:
            return NOM_COUCHE_ANOMALIES

        numero = 2
        while f"{NOM_COUCHE_ANOMALIES} {numero}" in noms_existants:
            numero += 1
        return f"{NOM_COUCHE_ANOMALIES} {numero}"

    def assurer(self, couche_travail):
        """Retourne la couche d'anomalies, en la créant si nécessaire."""
        couche = self.courante()
        if couche is not None:
            return couche

        crs = CRS_ANOMALIES_DEFAUT
        if couche_travail is not None:
            try:
                authid = couche_travail.crs().authid()
                if authid:
                    crs = authid
            except (AttributeError, RuntimeError):
                pass

        couche = QgsVectorLayer(
            f"MultiPolygon?crs={crs}",
            self.prochain_nom(),
            "memory",
        )

        provider = couche.dataProvider()
        provider.addAttributes(
            [
                QgsField("cle", QVariant.String),
                QgsField("categorie", QVariant.String),
                QgsField("date_heure", QVariant.DateTime),
            ]
        )
        couche.updateFields()
        couche.renderer().setSymbol(_creer_symbole_anomalies())
        couche.setReadOnly(True)
        couche.setCustomProperty("identify/disabled", True)

        self._ajouter_au_projet(couche, couche_travail)
        self.layer_id = couche.id()
        return couche

    @staticmethod
    def _ajouter_au_projet(couche, couche_travail):
        """Ajoute la couche d'anomalies juste après la couche de travail."""
        projet = QgsProject.instance()
        projet.addMapLayer(couche, False)

        racine = projet.layerTreeRoot()
        cible = (
            racine.findLayer(couche_travail.id())
            if couche_travail is not None
            else None
        )

        if cible is None or cible.parent() is None:
            racine.addLayer(couche)
            return

        parent = cible.parent()
        position = parent.children().index(cible) + 1
        parent.insertLayer(position, couche)

    def remplacer_entites(self, couche_travail, entites):
        """Remplace les anciennes anomalies par les nouvelles."""
        couche = self.assurer(couche_travail)
        provider = couche.dataProvider()
        provider.truncate()

        if entites:
            provider.addFeatures(entites)

        couche.updateExtents()
        noeud = (
            QgsProject.instance()
            .layerTreeRoot()
            .findLayer(couche.id())
        )
        if noeud is not None:
            noeud.setItemVisibilityChecked(True)

        couche.triggerRepaint()
        return couche


# Déplacées depuis commun_affichage.py (audit de placement avant transmission
# du code) : clignotement des anomalies au clic, n'était utilisé que par ce
# panneau.
def _contours_surbrillance(surbrillance):
    """Retourne les contours d'une surbrillance sous forme de tuple."""
    if surbrillance is None:
        return ()
    if isinstance(surbrillance, SurbrillancePolygone):
        return surbrillance.contours()
    if isinstance(surbrillance, (tuple, list, set)):
        return tuple(surbrillance)
    return (surbrillance,)


def _definir_surbrillance_visible(surbrillance, visible):
    """Affiche ou masque une surbrillance quel que soit son ancien format."""
    if isinstance(surbrillance, SurbrillancePolygone):
        surbrillance.definir_visible(visible)
        return

    for contour in _contours_surbrillance(surbrillance):
        try:
            contour.show() if visible else contour.hide()
        except RuntimeError:
            pass


class ClignotementVerification:
    """Fait clignoter temporairement les anomalies au simple clic."""

    def __init__(self, iface):
        self.iface = iface
        self.surbrillances = []
        self.generation = 0

    def afficher(self, geometries, couche_reference=None):
        """Affiche puis fait clignoter les géométries fournies."""
        self.effacer()

        generation = self.generation
        canvas = self.iface.mapCanvas()

        for geometrie in geometries or []:
            if geometrie is None or geometrie.isEmpty():
                continue

            surbrillance = creer_surbrillance_polygone(
                canvas,
                geometrie,
                couche_reference,
            )
            if surbrillance is not None:
                self.surbrillances.append(surbrillance)

        if not self.surbrillances:
            return

        def definir_visible(visible):
            if generation != self.generation:
                return

            for surbrillance in self.surbrillances:
                _definir_surbrillance_visible(surbrillance, visible)

            try:
                canvas.refresh()
            except RuntimeError:
                pass

        for delai, visible in CLIGNOTEMENT_ANOMALIE_ETAPES_MS:
            QTimer.singleShot(
                delai,
                lambda visible=visible: definir_visible(visible),
            )

        def effacer_si_generation_courante():
            if generation == self.generation:
                self.effacer()

        QTimer.singleShot(
            CLIGNOTEMENT_ANOMALIE_FIN_MS,
            effacer_si_generation_courante,
        )

    def effacer(self):
        """Supprime le clignotement courant et invalide les anciens timers."""
        self.generation += 1

        try:
            canvas = self.iface.mapCanvas()
        except (AttributeError, RuntimeError):
            self.surbrillances.clear()
            return

        supprimer_surbrillances_polygones(canvas, self.surbrillances)
        self.surbrillances.clear()

        try:
            canvas.refresh()
        except RuntimeError:
            pass


class VerificationBdForetPlugin:
    def __init__(self, iface, manager=None):
        self.iface = iface
        self.manager = manager
        self.action = None
        self.dock = None
        self.layer = None
        self._surbrillance = CoucheSurbrillanceVerification()
        self._clignotement = ClignotementVerification(iface)

        # Dictionnaire conservé pendant tout le processus QGIS, y compris si
        # l’extension est désactivée puis réactivée au cours de la même session.
        session_key = "_verificateur_bdforet_first_detection"
        if not hasattr(builtins, session_key):
            setattr(builtins, session_key, {})
        self._first_detection = getattr(builtins, session_key)

        self._cached_feature_by_id = {}
        self._cached_gap_geometries = []
        self._cached_emprise_layer_id = None
        self._cached_small = {}
        self._cached_multipart = {}
        self._cached_overlaps = {}
        self._cached_adjacent = {}
        self._cached_coherence = {}
        self._cached_signatures = {}
        self._lazy_tree_data = {}
        # État d’ouverture choisi par l’utilisateur. Les catégories sont fermées
        # au premier affichage, puis cet état est conservé lors des recalculs.
        self._categories_ouvertes = set()
        self._spatial_index = None
        self._field_map = None
        self._pending_fids = set()
        self._pending_old_geometries = {}
        self._commande_edition_active = False
        self._connected_layer = None
        self._refreshing = False
        self._shutting_down = False

        # Le contrôle complet délègue uniquement les intersections entre copies
        # de géométries à QgsTask. Aucune couche ni aucun widget n'entre dans le
        # thread secondaire. Pour les petites couches, rester synchrone évite le
        # coût de création d'une tâche.
        self._tache_relations = None
        self._contexte_controle_asynchrone = None
        # Nettoyage automatique de la couche : action indépendante (bouton
        # "Nettoyer la couche"), découpée en petits lots comme le reste du
        # contrôle. Un vrai QgsTask a été essayé, mais un calcul GEOS massif
        # ne répond pas à l'annulation avant la fin de l'appel C++ en cours,
        # ce qui a bloqué la fermeture de QGIS en pratique (voir le docstring
        # de verification_nettoyage_automatique).
        self._etat_nettoyage_automatique = None
        # Vrai seulement si lancer_nettoyage_automatique a gelé le canevas
        # (pour éviter de le dégeler à tort dans _terminer_interface_controle,
        # partagée avec d'autres contrôles qui ne gèlent jamais le canevas).
        self._canvas_gele_par_nettoyage = False
        # Idem pour la commande d'édition Ctrl+Z englobant tout le nettoyage
        # (voir lancer_nettoyage_automatique).
        self._commande_nettoyage_ouverte = False
        # Vrai si lancer_nettoyage_automatique a suspendu l'écoute
        # automatique de CompteurAlertes (voir lancer_nettoyage_automatique
        # et l'étape 7, "synchronisation des alertes", du nettoyage).
        self._alertes_suspendues_par_nettoyage = False
        # La préparation du contrôle (lecture des entités + index + contrôles
        # simples) est elle aussi découpée en petits lots dans le thread
        # principal. Cela évite un gel de l'interface avant même le QgsTask.
        self._etat_preparation_controle = None
        self._etat_recherche_trous = None
        self._contexte_recherche_trous = None
        # Règles cochées dans le menu de "Vérifier les règles métier" lors du
        # dernier contrôle complet lancé (voir rafraichir_verifications) ;
        # toutes activées par défaut avant le tout premier lancement, pour ne
        # jamais afficher "non vérifié" à tort dans le tableau des anomalies.
        self._regles_metier_activees = set(ORDRE_REGLES_METIER)
        self._generation_controle = 0
        self._seuil_tache_relations = SEUIL_TACHE_RELATIONS

        self._refresh_timer = QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(DELAI_RAFRAICHISSEMENT_VERIFICATION_MS)
        self._refresh_timer.timeout.connect(self._rafraichir_apres_edition)

    # ------------------------------------------------------------------
    # Cycle de vie du panneau
    # ------------------------------------------------------------------

    def initGui(self):
        icon_path = str(Path(__file__).with_name("icon_verification.svg"))
        self.action = QAction(QIcon(icon_path), "Vérification BD Forêt", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Vérifier les anomalies géométriques")
        self.action.toggled.connect(self._basculer_panneau)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("Vérification BD Forêt", self.action)

    def unload(self):
        """Décharge le plugin sans réutiliser d'objets Qt/QGIS déjà détruits."""
        self._shutting_down = True

        if self._commande_nettoyage_ouverte:
            try:
                if couche_est_disponible(self.layer):
                    self.layer.endEditCommand()
            except Exception:
                pass
            self._commande_nettoyage_ouverte = False
        if self._canvas_gele_par_nettoyage:
            try:
                self.iface.mapCanvas().freeze(False)
            except Exception:
                pass
            self._canvas_gele_par_nettoyage = False
        if self._alertes_suspendues_par_nettoyage:
            try:
                compteur = getattr(self.manager, "compteur_alertes", None)
                if compteur is not None:
                    compteur.reprendre_synchronisation_geometrique()
            except Exception:
                pass
            self._alertes_suspendues_par_nettoyage = False
        try:
            self._annuler_tache_relations()
        except Exception:
            pass
        try:
            self._deconnecter_signaux_couche()
        except Exception:
            pass
        try:
            self._refresh_timer.stop()
        except Exception:
            pass
        try:
            self._clignotement.effacer()
            self._surbrillance.detacher()
        except Exception:
            self._surbrillance.detacher()

        if self.dock is not None:
            try:
                self.iface.removeDockWidget(self.dock)
            except Exception:
                pass
            try:
                self.dock.deleteLater()
            except Exception:
                pass
            self.dock = None

        if self.action is not None:
            try:
                self.action.toggled.disconnect(self._basculer_panneau)
            except Exception:
                pass
            try:
                self.iface.removeToolBarIcon(self.action)
                self.iface.removePluginVectorMenu("Vérification BD Forêt", self.action)
            except Exception:
                pass
            try:
                self.action.deleteLater()
            except Exception:
                pass
            self.action = None

    def _basculer_panneau(self, checked):
        if self._shutting_down:
            return
        if checked:
            if self.dock is None:
                self.dock = PanneauVerification(self)
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

            # Chaque ouverture repart d'un panneau vide. Les couches temporaires
            # déjà créées restent dans le projet comme des instantanés indépendants.
            self._surbrillance.detacher()
            self._reinitialiser_resultats_panneau()
            self.dock.show()
            self.dock.raise_()
            self._connecter_signaux_couche(self._trouver_couche())
        else:
            self._annuler_tache_relations()
            self._deconnecter_signaux_couche()
            self._refresh_timer.stop()
            self._clignotement.effacer()
            self._surbrillance.detacher()
            self._reinitialiser_resultats_panneau()
            if self.dock is not None:
                self.dock.hide()

    # ------------------------------------------------------------------
    # Couche surveillée et signaux d’édition
    # ------------------------------------------------------------------

    def _trouver_couche(self):
        """Retourne la couche BD Forêt commune aux autres outils."""
        return trouver_couche_travail(self.iface)

    @staticmethod
    def _trouver_couche_emprise():
        """Retourne la couche d'emprise commune aux autres outils."""
        return trouver_couche_emprise()

    def _connecter_signaux_couche(self, layer):
        """Écoute les modifications sans réutiliser un wrapper de couche détruit."""
        if layer is self._connected_layer and couche_est_disponible(layer):
            return

        self._deconnecter_signaux_couche()
        if not couche_est_disponible(layer):
            return

        connections = (
            (layer.geometryChanged, self._geometrie_modifiee),
            (layer.featureAdded, self._entite_ajoutee),
            (layer.featureDeleted, self._entite_supprimee),
            (layer.attributeValueChanged, self._attribut_modifie),
            (layer.editCommandStarted, self._commande_edition_demarre),
            (layer.editCommandEnded, self._commande_edition_terminee),
            (layer.editCommandDestroyed, self._commande_edition_annulee),
        )
        connexion_reussie = False
        for signal, slot in connections:
            try:
                signal.connect(slot)
                connexion_reussie = True
            except (TypeError, RuntimeError):
                pass
        if connexion_reussie:
            self._connected_layer = layer

    def _deconnecter_signaux_couche(self):
        """Oublie la couche avant toute déconnexion Qt.

        Si QGIS a déjà détruit l'objet C++, Qt a également supprimé ses
        connexions : il ne faut surtout plus accéder à ``layer.geometryChanged``.
        """
        layer = self._connected_layer
        self._connected_layer = None
        self._pending_fids.clear()
        self._pending_old_geometries.clear()
        self._commande_edition_active = False

        if not couche_est_disponible(layer):
            if self.layer is layer:
                self.layer = None
            return

        connections = (
            (layer.geometryChanged, self._geometrie_modifiee),
            (layer.featureAdded, self._entite_ajoutee),
            (layer.featureDeleted, self._entite_supprimee),
            (layer.attributeValueChanged, self._attribut_modifie),
            (layer.editCommandStarted, self._commande_edition_demarre),
            (layer.editCommandEnded, self._commande_edition_terminee),
            (layer.editCommandDestroyed, self._commande_edition_annulee),
        )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _commande_edition_demarre(self, *_args):
        """Regroupe les nombreux signaux d'une même commande QGIS."""
        self._commande_edition_active = True
        try:
            self._refresh_timer.stop()
        except RuntimeError:
            pass

    def _commande_edition_terminee(self, *_args):
        """La commande QGIS vient de se refermer : relance le contrôle local
        maintenant que tous les signaux de la même opération sont arrivés."""
        self._commande_edition_active = False
        if self._pending_fids and self.dock is not None and self.dock.isVisible():
            self._refresh_timer.start(0)

    def _commande_edition_annulee(self, *_args):
        """Même relance qu'après une commande normale : un Ctrl+Z pendant une
        commande active doit lui aussi remettre le panneau à jour."""
        self._commande_edition_active = False
        if self._pending_fids and self.dock is not None and self.dock.isVisible():
            self._refresh_timer.start(0)

    def _memoriser_ancienne_geometrie(self, fid):
        """Garde la géométrie AVANT modification, une seule fois par fid et
        par commande : nécessaire pour recalculer correctement les anomalies
        locales qui dépendaient de l'ancienne forme (ex. un trou qui existait
        entre ce polygone et son voisin avant l'édition)."""
        if fid in self._pending_old_geometries:
            return
        old_feature = self._cached_feature_by_id.get(fid)
        if old_feature is not None and old_feature.hasGeometry():
            self._pending_old_geometries[fid] = QgsGeometry(old_feature.geometry())

    # Les 4 gestionnaires ci-dessous partagent la même garde en tête : ignorer
    # tout signal pendant que le nettoyage automatique tourne (voir le
    # commentaire détaillé dans lancer_nettoyage_automatique plus bas).

    def _geometrie_modifiee(self, fid, _geometry):
        if self._etat_nettoyage_automatique is not None:
            return
        self._memoriser_ancienne_geometrie(fid)
        self._programmer_rafraichissement_local(fid)

    def _entite_ajoutee(self, fid):
        if self._etat_nettoyage_automatique is not None:
            return
        self._programmer_rafraichissement_local(fid)

    def _entite_supprimee(self, fid):
        if self._etat_nettoyage_automatique is not None:
            return
        self._memoriser_ancienne_geometrie(fid)
        self._programmer_rafraichissement_local(fid)

    def _attribut_modifie(self, fid, _field_index, _value):
        if self._etat_nettoyage_automatique is not None:
            return
        self._programmer_rafraichissement_local(fid)

    def _programmer_rafraichissement_local(self, fid):
        if self.dock is None or not self.dock.isVisible():
            return
        self._pending_fids.add(fid)
        # Si la couche change pendant un contrôle asynchrone, son instantané est
        # périmé. On annule la tâche ; son callback relancera un contrôle propre.
        if self._tache_relations is not None:
            try:
                self._tache_relations.cancel()
            except RuntimeError:
                pass
        # Une commande géométrique peut émettre des dizaines de signaux. Tant
        # qu'elle est ouverte, on ne fait aucun recalcul intermédiaire.
        if not self._commande_edition_active:
            self._refresh_timer.start()

    def _rafraichir_apres_edition(self):
        if self.dock is None or not self.dock.isVisible() or self._refreshing:
            return
        if not couche_est_disponible(self.layer):
            self._refresh_timer.stop()
            self._deconnecter_signaux_couche()
            self.layer = None
            return
        if not self._cached_feature_by_id or self._spatial_index is None or self._field_map is None:
            return
        self._recalculer_entites_modifiees()

    # ------------------------------------------------------------------
    # Contrôle complet : préparation → tâche de fond → trous
    # ------------------------------------------------------------------

    def rafraichir_verifications(self):
        """Lance la recherche des 6 anomalies sans bloquer l'interface QGIS.

        N'écrit jamais sur la couche : aucun mode édition requis. Le nettoyage
        automatique est une action séparée (bouton "Nettoyer la couche").
        """
        if self.dock is None or not self.dock.isVisible():
            return
        if (
            self._tache_relations is not None
            or self._etat_nettoyage_automatique is not None
            or self._etat_preparation_controle is not None
            or self._etat_recherche_trous is not None
        ):
            self._annuler_tache_relations()

        regles_activees = self.dock.regles_metier_activees()
        if not regles_activees:
            self.dock.summary.setText(
                "Vérification impossible : aucune règle cochée dans le menu à "
                "côté du bouton « Vérifier les règles métier »."
            )
            return
        self._regles_metier_activees = regles_activees

        self.layer = self._trouver_couche()

        self.dock.refresh_button.setEnabled(False)
        self.dock.nettoyage_button.setEnabled(False)
        self.dock.create_layer_button.setVisible(False)
        self.dock.search_progress_metier.setVisible(True)
        self._refreshing = True
        self._demarrer_preparation_controle()

    def lancer_nettoyage_automatique(self):
        """Lance le nettoyage automatique de la couche, par petits lots (QTimer).

        Action indépendante de "Vérifier les règles métier". A besoin d'écrire :
        si la couche n'est pas en mode édition, on demande à l'utilisateur de
        l'activer puis de relancer, plutôt que de l'activer à sa place.
        """
        if self.dock is None or not self.dock.isVisible():
            return
        if self._etat_nettoyage_automatique is not None:
            return
        if (
            self._tache_relations is not None
            or self._etat_preparation_controle is not None
            or self._etat_recherche_trous is not None
        ):
            self._annuler_tache_relations()

        couche = self._trouver_couche()
        if couche is None or not couche.isEditable():
            self.dock.summary.setText(
                "Passez la couche BD Forêt en mode édition, puis relancez le "
                "nettoyage automatique (petites corrections : conformité OGC, "
                "petites surfaces, parties isolées)."
            )
            return
        self.layer = couche

        etapes_activees = self.dock.etapes_nettoyage_activees()
        if not etapes_activees:
            self.dock.summary.setText(
                "Nettoyage impossible : aucune étape cochée dans le menu à "
                "côté du bouton « Nettoyer la couche »."
            )
            return

        etat = verif_nettoyage.preparer_nettoyage(self, etapes_activees=etapes_activees)
        if etat is None:
            self.dock.summary.setText(
                "Nettoyage impossible : couche de travail introuvable."
            )
            return

        self.dock.refresh_button.setEnabled(False)
        self.dock.nettoyage_button.setEnabled(False)
        self.dock.create_layer_button.setVisible(False)
        self.dock.search_progress.setVisible(True)
        self.dock.search_status.setVisible(True)
        self.dock.summary.setText("")
        self._indiquer_progression_nettoyage(etat)
        self._refreshing = True
        # Le nettoyage tourne par lots QTimer sur le thread principal : rien
        # d'autre ne devrait éditer la couche entre deux lots. Les signaux de
        # la couche (geometryChanged...) sont donc ignorés tant que le
        # nettoyage tourne (voir _geometrie_modifiee et les autres gestionnaires
        # de signaux, gardés par `_etat_nettoyage_automatique is not None`) :
        # sans ça, chaque écriture du nettoyage lui-même (des milliers) copierait
        # une géométrie et relancerait un timer pour rien. On vide ici les FID
        # en attente d'avant le clic (édition sans rapport pas encore traitée).
        self._pending_fids.clear()

        # Des milliers d'écritures sur une couche affichée peuvent déclencher
        # des rendus de carte intermédiaires (symbologie souvent complexe sur
        # la BD Forêt) : geler le canevas le temps du nettoyage l'évite, sans
        # rien changer pour l'utilisateur (dégelé et rafraîchi une seule fois
        # à la fin, dans _terminer_interface_controle).
        try:
            canvas = self.iface.mapCanvas()
            if not canvas.isFrozen():
                canvas.freeze(True)
                self._canvas_gele_par_nettoyage = True
        except (AttributeError, RuntimeError):
            pass

        # Regroupe toutes les écritures du nettoyage en une seule commande
        # d'édition Ctrl+Z au lieu d'une par entité. Sans ça, CompteurAlertes
        # (commun_compteur_alertes.py, indépendant du panneau Vérification)
        # ne voit jamais de commande d'édition active pendant le nettoyage
        # (isEditCommandActive() toujours faux) et relance sa synchronisation
        # spatiale à chaque fois que le nettoyage rend la main à Qt entre deux
        # lots — au lieu d'une seule fois à la vraie fin, comme prévu par son
        # propre design. Mesuré : ce recalcul répété (~30 fois sur 6551
        # entités) explique la quasi-totalité de l'écart entre un test isolé
        # (13 s) et un lancement réel depuis le plugin (10 minutes). Effet de
        # bord accepté : le nettoyage devient annulable en un seul Ctrl+Z
        # global, alors qu'il ne l'était pas du tout avant.
        try:
            couche.beginEditCommand("Nettoyage automatique de la couche")
            self._commande_nettoyage_ouverte = True
        except (AttributeError, RuntimeError):
            self._commande_nettoyage_ouverte = False

        # La commande d'édition ci-dessus suffit déjà à ne déclencher qu'un
        # seul recalcul automatique de CompteurAlertes, à sa fin — mais ce
        # recalcul restait silencieux (aucun texte de progression) et
        # impossible à sauter. Suspendre explicitement son écoute permet à
        # l'étape 7 du nettoyage ("synchronisation des alertes") de le
        # déclencher elle-même, avec un texte de progression, et de le sauter
        # entièrement si l'utilisateur la décoche dans le menu.
        try:
            compteur = getattr(self.manager, "compteur_alertes", None)
            if compteur is not None:
                compteur.suspendre_synchronisation_geometrique()
                self._alertes_suspendues_par_nettoyage = True
        except (AttributeError, RuntimeError):
            self._alertes_suspendues_par_nettoyage = False

        self._etat_nettoyage_automatique = etat
        QTimer.singleShot(0, self._continuer_nettoyage_automatique)

    def _continuer_nettoyage_automatique(self):
        """Avance le nettoyage automatique par petits lots non bloquants."""
        etat = self._etat_nettoyage_automatique
        if etat is None:
            return
        if self._shutting_down or self.dock is None or not self.dock.isVisible():
            self._etat_nettoyage_automatique = None
            self._terminer_interface_controle()
            return

        # Appelée depuis QTimer.singleShot : une exception ici ne remonterait
        # nulle part de visible pour l'utilisateur (juste la trace dans la
        # console Python), en laissant la barre de progression bloquée
        # indéfiniment. On l'attrape explicitement pour toujours terminer
        # proprement l'interface et afficher un message clair.
        try:
            termine = verif_nettoyage.traiter_lot_nettoyage(self, etat)
            self._indiquer_progression_nettoyage(etat)
        except Exception as erreur:
            self._etat_nettoyage_automatique = None
            self._terminer_interface_controle()
            self.iface.messageBar().pushCritical(
                "Vérification BD Forêt",
                f"Le nettoyage automatique a échoué : {erreur}",
            )
            return

        if not termine:
            QTimer.singleShot(0, self._continuer_nettoyage_automatique)
            return

        self._etat_nettoyage_automatique = None
        corriges, supprimes, fusionnes = verif_nettoyage.finaliser_nettoyage(etat)
        resume = (
            f"{corriges} géométrie(s) corrigée(s), "
            f"{supprimes} entité(s) supprimée(s), "
            f"{fusionnes} micro-écart(s) fusionné(s)."
        )
        # Les étapes gardent leur numéro dans le tableau ; une ligne "Terminé"
        # à part porte le résumé chiffré (pas une étape du pipeline). Ce
        # résumé n'a donc pas besoin d'être répété dans self.dock.summary en
        # dessous (demande explicite) : le tableau suffit.
        self._indiquer_progression_nettoyage(etat, ligne_finale=("Terminé", resume))
        self._terminer_interface_controle()

    def _demarrer_preparation_controle(self):
        """Prépare un itérateur léger puis rend immédiatement la main à Qt.

        Aucune opération géométrique lourde n'est réalisée ici. La lecture de
        la couche, la construction de l'index, les surfaces/multiparties et les
        signatures sont faites ensuite par lots dans ``_continuer_preparation``.
        """
        if self.dock is None or not self.dock.isVisible():
            self._terminer_interface_controle()
            return

        self.dock.tree.clear()
        self.dock.create_layer_button.setVisible(False)
        self.layer = self._trouver_couche()
        self._connecter_signaux_couche(self.layer)

        if self.layer is None:
            self.dock.summary.setText('La couche "bdfv3_priorites" est introuvable.')
            self._terminer_interface_controle()
            return
        if QgsWkbTypes.geometryType(self.layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            self.dock.summary.setText("La couche cible doit être polygonale.")
            self._terminer_interface_controle()
            return

        field_map, missing_fields = resoudre_champs(self)
        if missing_fields:
            self.dock.summary.setText(
                "Champ(s) introuvable(s) : " + ", ".join(missing_fields) + "."
            )
            self._terminer_interface_controle()
            return

        field_names = sorted(set(field_map.values()))
        request = QgsFeatureRequest().setSubsetOfAttributes(
            field_names, self.layer.fields()
        )
        try:
            total = max(0, int(self.layer.featureCount()))
        except (TypeError, ValueError, RuntimeError):
            total = 0

        # Pour les petites couches, créer un QgsTask coûte plus que le calcul.
        utiliser_tache = total >= self._seuil_tache_relations
        self._pending_fids.clear()
        self._pending_old_geometries.clear()
        self._cached_signatures = {}

        self._etat_preparation_controle = {
            "layer_id": self.layer.id(),
            "iterator": self.layer.getFeatures(request),
            "field_map": field_map,
            "features": [],
            "feature_by_id": {},
            "index": QgsSpatialIndex(),
            "signatures": {},
            "donnees_tache": {},
            "small": [],
            "multipart": [],
            "coherence": [],
            "mesure_surface": self._creer_mesure_surface(),
            "utiliser_tache": utiliser_tache,
            "total": total,
            "traites": 0,
        }
        self._indiquer_etape("Préparation du contrôle…")
        QTimer.singleShot(0, self._continuer_preparation_controle)

    def _continuer_preparation_controle(self):
        """Charge un petit lot d'entités puis rend la main à la boucle Qt."""
        etat = self._etat_preparation_controle
        if etat is None:
            return
        if (
            self._shutting_down
            or self.dock is None
            or not self.dock.isVisible()
            or not couche_est_disponible(self.layer)
            or self.layer.id() != etat.get("layer_id")
        ):
            self._etat_preparation_controle = None
            self._terminer_interface_controle()
            return

        # Une édition pendant la constitution de l'instantané rend celui-ci
        # incohérent. On jette le travail partiel au lieu de mélanger deux états.
        if self._pending_fids:
            self._etat_preparation_controle = None
            self._terminer_interface_controle()
            QTimer.singleShot(0, self.rafraichir_verifications)
            return

        iterator = etat["iterator"]
        field_map = etat["field_map"]
        utiliser_tache = etat["utiliser_tache"]
        limite = TAILLE_LOT_PREPARATION_VERIFICATION
        lus = 0
        termine = False

        while lus < limite:
            try:
                feature = next(iterator)
            except StopIteration:
                termine = True
                break
            except RuntimeError:
                # Couche remplacée/supprimée pendant la lecture.
                self._etat_preparation_controle = None
                self._terminer_interface_controle()
                return

            lus += 1
            etat["traites"] += 1
            if not feature.hasGeometry():
                continue
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue

            fid = int(feature.id())
            etat["features"].append(feature)
            etat["feature_by_id"][fid] = feature
            try:
                etat["index"].addFeature(feature)
            except (TypeError, RuntimeError):
                pass

            # Règles décochées dans le menu de "Vérifier les règles métier" :
            # le détecteur n'est même pas appelé, pas seulement son résultat
            # ignoré (économise le calcul, pas juste l'affichage).
            if "small" in self._regles_metier_activees:
                petit = verif_surface.detecter(feature, etat["mesure_surface"])
                if petit is not None:
                    etat["small"].append(petit)
            if "multipart" in self._regles_metier_activees:
                multipartie = verif_multiparties.detecter(feature)
                if multipartie is not None:
                    etat["multipart"].append(multipartie)
            if "coherence" in self._regles_metier_activees:
                coherence = verif_coherence.detecter(feature, field_map)
                if coherence is not None:
                    etat["coherence"].append(coherence)

            signature = signature_attributs(feature, field_map)
            etat["signatures"][fid] = signature
            # Le thread ne reçoit jamais d'objet QgsGeometry créé dans le
            # thread principal. Le WKB est un simple tableau d'octets Python :
            # il n'emporte aucun QObject ni état QGIS partagé entre threads.
            if utiliser_tache:
                try:
                    geometrie_wkb = bytes(geom.asWkb())
                except (AttributeError, RuntimeError, TypeError):
                    geometrie_wkb = b""
                if geometrie_wkb:
                    etat["donnees_tache"][fid] = (
                        geometrie_wkb,
                        signature,
                        verif_adjacents.detail_adjacence(feature, field_map),
                    )

        total = etat.get("total", 0)
        traites = etat.get("traites", 0)
        if total > 0:
            self._indiquer_etape(f"Préparation du contrôle… {min(traites, total)}/{total}")
        else:
            self._indiquer_etape(f"Préparation du contrôle… {traites} entités")

        if not termine:
            QTimer.singleShot(0, self._continuer_preparation_controle)
            return

        self._etat_preparation_controle = None
        if etat["utiliser_tache"]:
            self._demarrer_preparation_paires(etat)
        else:
            self._lancer_controle_apres_preparation(etat)

    def _demarrer_preparation_paires(self, etat):
        """Prépare les couples de voisins par petits lots dans le thread principal.

        Le QgsTask n'a ainsi jamais besoin d'accéder à un QgsSpatialIndex.
        Les requêtes d'emprise sont peu coûteuses et l'interface reprend la main
        entre les lots.
        """
        etat["position_paires"] = 0
        etat["paires_candidates"] = []
        self._etat_preparation_controle = etat
        self._indiquer_etape("Préparation des voisinages…")
        QTimer.singleShot(0, self._continuer_preparation_paires)

    def _continuer_preparation_paires(self):
        etat = self._etat_preparation_controle
        if etat is None:
            return
        if (
            self._shutting_down
            or self.dock is None
            or not self.dock.isVisible()
            or not couche_est_disponible(self.layer)
            or self.layer.id() != etat.get("layer_id")
        ):
            self._etat_preparation_controle = None
            self._terminer_interface_controle()
            return
        if self._pending_fids:
            self._etat_preparation_controle = None
            self._terminer_interface_controle()
            QTimer.singleShot(0, self.rafraichir_verifications)
            return

        features = etat["features"]
        index = etat["index"]
        debut = int(etat.get("position_paires", 0))
        fin = min(len(features), debut + TAILLE_LOT_VOISINAGE_VERIFICATION)
        paires = etat["paires_candidates"]
        for position in range(debut, fin):
            feature = features[position]
            fid = int(feature.id())
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            try:
                candidats = index.intersects(geom.boundingBox())
            except (AttributeError, RuntimeError):
                candidats = []
            for autre_fid in candidats:
                try:
                    autre_fid = int(autre_fid)
                except (TypeError, ValueError):
                    continue
                if autre_fid > fid:
                    paires.append((fid, autre_fid))

        etat["position_paires"] = fin
        self._indiquer_etape(
            f"Préparation des voisinages… {fin}/{len(features)}"
        )
        if fin < len(features):
            QTimer.singleShot(0, self._continuer_preparation_paires)
            return

        self._etat_preparation_controle = None
        self._lancer_controle_apres_preparation(etat)

    def _lancer_controle_apres_preparation(self, etat):
        """Démarre le calcul spatial à partir de l'instantané déjà préparé."""
        features = etat["features"]
        feature_by_id = etat["feature_by_id"]
        field_map = etat["field_map"]
        index = etat["index"]
        small = etat["small"]
        multipart = etat["multipart"]
        coherence = etat["coherence"]
        utiliser_tache = etat["utiliser_tache"]
        self._cached_signatures = dict(etat["signatures"])

        contexte = (feature_by_id, small, multipart, coherence, index, field_map)

        if not utiliser_tache:
            self._indiquer_etape("Recherche des adjacences et recouvrements…")
            adjacent_pairs, overlaps = self._chercher_relations_voisines(
                features, feature_by_id, field_map, index
            )
            self._finaliser_controle_complet(contexte, adjacent_pairs, overlaps)
            return

        self._indiquer_etape("Relations spatiales en arrière-plan…")
        self._generation_controle += 1
        generation = self._generation_controle
        self._contexte_controle_asynchrone = (generation, contexte)
        tache = TacheRelationsVoisines(
            etat["donnees_tache"],
            etat.get("paires_candidates", ()),
            self._regles_metier_activees,
            lambda task, succes, resultats, erreur, g=generation:
                self._tache_relations_terminee(g, task, succes, resultats, erreur),
        )
        # Libère tout de suite les structures de préparation dont le task a
        # déjà pris une copie. ``features`` n'est utile que pour le petit mode.
        # Le task possède désormais ces structures ; on détache simplement les
        # références de l'état de préparation sans modifier les objets transmis.
        etat["donnees_tache"] = {}
        etat["signatures"].clear()
        etat["paires_candidates"] = []
        etat["features"] = []
        self._tache_relations = tache
        QgsApplication.taskManager().addTask(tache)

    def _tache_relations_terminee(self, generation, task, succes, resultats, erreur):
        """Récupère le résultat dans le thread principal ou l'ignore s'il est périmé."""
        if task is not self._tache_relations:
            return
        self._tache_relations = None

        contexte_enregistre = self._contexte_controle_asynchrone
        self._contexte_controle_asynchrone = None
        if self._shutting_down or self.dock is None or not self.dock.isVisible():
            self._terminer_interface_controle()
            return
        if not couche_est_disponible(self.layer):
            # La couche peut avoir été retirée ou le projet remplacé pendant le
            # calcul. Le task n'a utilisé que des copies, donc il est sûr ; on
            # jette simplement son résultat au lieu de toucher au wrapper détruit.
            self.layer = None
            self._terminer_interface_controle()
            return

        # Toute édition reçue pendant le task invalide l'instantané. On ne
        # mélange jamais des résultats anciens avec la couche courante.
        if self._pending_fids or generation != self._generation_controle:
            self._terminer_interface_controle()
            QTimer.singleShot(0, self.rafraichir_verifications)
            return

        if not succes or resultats is None:
            self._terminer_interface_controle()
            if erreur is not None:
                self.dock.summary.setText(
                    "Le calcul en arrière-plan a été interrompu ; le contrôle peut être relancé."
                )
            return

        if not contexte_enregistre or contexte_enregistre[0] != generation:
            self._terminer_interface_controle()
            return

        contexte = contexte_enregistre[1]
        adjacent_pairs, overlaps_wkb = resultats
        overlaps = self._geometries_recouvrements_depuis_wkb(overlaps_wkb)
        self._finaliser_controle_complet(contexte, adjacent_pairs, overlaps)

    @staticmethod
    def _geometrie_depuis_wkb(wkb):
        """Reconstruit une géométrie dans le thread principal.

        Les tâches de fond échangent uniquement des ``bytes``. Cette petite
        frontière explicite évite qu'un objet géométrique QGIS soit partagé
        accidentellement entre deux threads.
        """
        if not wkb:
            return None
        try:
            geometrie = QgsGeometry()
            geometrie.fromWkb(wkb)
        except (AttributeError, RuntimeError, TypeError):
            return None
        if geometrie.isEmpty():
            return None
        return geometrie

    @classmethod
    def _geometries_recouvrements_depuis_wkb(cls, recouvrements):
        resultat = []
        for fid_a, fid_b, wkb in recouvrements or ():
            geometrie = cls._geometrie_depuis_wkb(wkb)
            if geometrie is not None:
                resultat.append((int(fid_a), int(fid_b), geometrie))
        return resultat

    def _finaliser_controle_complet(self, contexte, adjacent_pairs, overlaps):
        """Démarre la recherche incrémentale des trous dans le thread principal."""
        feature_by_id, small, multipart, coherence, index, field_map = contexte

        donnees_finales = (
            feature_by_id, small, multipart, coherence, adjacent_pairs, overlaps,
            index, field_map
        )
        # Résolue même si "gaps" est décoché (léger, sert aussi à découper
        # l'affichage des autres anomalies sur l'emprise locale) : seul le
        # balayage spatial complet qui suit, lui coûteux, est sauté.
        emprise_layer = self._trouver_couche_emprise()
        self._cached_emprise_layer_id = emprise_layer.id() if emprise_layer else None

        if "gaps" not in self._regles_metier_activees:
            self._terminer_controle_avec_trous(donnees_finales, [])
            return

        self._indiquer_etape("Recherche des trous…")
        if emprise_layer is None:
            self._terminer_controle_avec_trous(donnees_finales, [])
            return

        etat = verif_trous.preparer_recherche_trous(
            self, emprise_layer, feature_by_id, index
        )
        if etat is None:
            self._terminer_controle_avec_trous(donnees_finales, [])
            return

        self._generation_controle += 1
        generation = self._generation_controle
        self._etat_recherche_trous = (generation, etat)
        self._contexte_recherche_trous = (generation, donnees_finales)
        QTimer.singleShot(0, self._continuer_recherche_trous)

    def _continuer_recherche_trous(self):
        """Avance la recherche des trous par petits lots non bloquants."""
        en_cours = self._etat_recherche_trous
        contexte = self._contexte_recherche_trous
        if not en_cours or not contexte:
            return
        generation, etat = en_cours
        if contexte[0] != generation or generation != self._generation_controle:
            return

        if (
            self._shutting_down
            or self.dock is None
            or not self.dock.isVisible()
            or not couche_est_disponible(self.layer)
        ):
            self._etat_recherche_trous = None
            self._contexte_recherche_trous = None
            self._terminer_interface_controle()
            return

        # Une édition pendant le calcul invalide l'instantané. On arrête sans
        # utiliser un résultat ancien, puis on relance proprement sur la couche.
        if self._pending_fids:
            self._etat_recherche_trous = None
            self._contexte_recherche_trous = None
            self._terminer_interface_controle()
            QTimer.singleShot(0, self.rafraichir_verifications)
            return

        termine = verif_trous.traiter_lot_recherche_trous(
            self, etat, taille_lot=TAILLE_LOT_TROUS_VERIFICATION
        )
        try:
            self._indiquer_etape(verif_trous.progression_recherche_trous(etat))
        except Exception:
            pass

        if not termine:
            QTimer.singleShot(0, self._continuer_recherche_trous)
            return

        gaps = verif_trous.finaliser_recherche_trous(etat)
        donnees_finales = contexte[1]
        self._etat_recherche_trous = None
        self._contexte_recherche_trous = None
        self._terminer_controle_avec_trous(donnees_finales, gaps)

    def _terminer_controle_avec_trous(self, donnees_finales, gaps):
        feature_by_id, small, multipart, coherence, adjacent_pairs, overlaps, index, field_map = donnees_finales
        self._enregistrer_cache_controle(
            feature_by_id, small, multipart, coherence, adjacent_pairs, overlaps,
            index, field_map, gaps
        )
        self._reconstruire_depuis_cache(valider_trous=False)
        self._terminer_interface_controle()

    def _terminer_interface_controle(self):
        self._refreshing = False
        if self._commande_nettoyage_ouverte:
            self._commande_nettoyage_ouverte = False
            try:
                if couche_est_disponible(self.layer):
                    self.layer.endEditCommand()
            except (AttributeError, RuntimeError):
                pass
        if self._alertes_suspendues_par_nettoyage:
            self._alertes_suspendues_par_nettoyage = False
            try:
                compteur = getattr(self.manager, "compteur_alertes", None)
                if compteur is not None:
                    compteur.reprendre_synchronisation_geometrique()
            except (AttributeError, RuntimeError):
                pass
        if self._canvas_gele_par_nettoyage:
            self._canvas_gele_par_nettoyage = False
            try:
                canvas = self.iface.mapCanvas()
                canvas.freeze(False)
                canvas.refresh()
            except (AttributeError, RuntimeError):
                pass
        if self.dock is None:
            return
        self.dock.search_progress.setVisible(False)
        self.dock.search_progress_metier.setVisible(False)
        # search_status (tableau des étapes de "Nettoyer la couche") n'est
        # JAMAIS touché ici : c'est une zone indépendante, que seul
        # l'utilisateur ferme via sa croix (voir verification_panneau.py) —
        # un "Vérifier les règles métier" lancé après ne doit pas l'effacer
        # (bug signalé : ça vidait puis masquait le tableau du nettoyage).
        # search_status_metier (le message d'une ligne des autres contrôles,
        # géré par _indiquer_etape) redevient invisible à chaque fin de
        # contrôle, lui.
        self.dock.search_status_metier.setVisible(False)
        self.dock.refresh_button.setEnabled(True)
        self.dock.nettoyage_button.setEnabled(True)

    def _annuler_tache_relations(self):
        """Annule une tâche sans toucher à ses données depuis le mauvais thread."""
        self._generation_controle += 1
        tache = self._tache_relations
        self._tache_relations = None
        self._contexte_controle_asynchrone = None
        self._etat_nettoyage_automatique = None
        self._etat_preparation_controle = None
        self._etat_recherche_trous = None
        self._contexte_recherche_trous = None
        if tache is not None:
            try:
                tache.cancel()
            except RuntimeError:
                pass
        self._refreshing = False

    def _indiquer_etape(self, texte):
        """Message d'une ligne pour "Vérifier les règles métier" (préparation,
        recherche des relations spatiales, des trous...).

        Widget dédié (search_status_metier), séparé du tableau de
        "Nettoyer la couche" (search_status_tree, voir
        _indiquer_progression_nettoyage) : les deux zones sont
        indépendantes, un contrôle ne doit jamais écraser l'autre (bug
        signalé : "Vérifier les règles métier" vidait le tableau du
        nettoyage automatique).
        """
        if self.dock is None:
            return
        self.dock.search_status_metier.setText(texte)
        self.dock.search_status_metier.setVisible(True)

    def _indiquer_progression_nettoyage(self, etat, ligne_finale=None):
        """Met à jour le tableau de progression de "Nettoyer la couche".

        ``ligne_finale`` : (étape, détail) ajoutée après les étapes du
        pipeline (le résumé chiffré "Terminé", une fois le nettoyage
        vraiment fini — voir _continuer_nettoyage_automatique), pas une
        étape du pipeline elle-même.
        """
        if self.dock is None:
            return
        lignes = verif_nettoyage.progression_nettoyage(etat)
        if ligne_finale is not None:
            lignes.append(ligne_finale)
        arbre = self.dock.search_status_tree
        arbre.clear()
        for etape, detail in lignes:
            QTreeWidgetItem(arbre, [etape, detail])
        arbre.resizeColumnToContents(0)
        self._ajuster_hauteur_tableau_progression(arbre, verif_nettoyage.nombre_etapes_prevues(etat))

    def _ajuster_hauteur_tableau_progression(self, arbre, nombre_lignes):
        """Redimensionne le tableau pour tenir tout son contenu, sans barre de défilement.

        Le nombre de lignes varie (une par étape de nettoyage cochée) : une
        hauteur fixe faisait apparaître une barre de défilement non voulue
        dès que le contenu dépassait ce seuil.
        """
        hauteur_ligne = arbre.sizeHintForRow(0) if nombre_lignes else arbre.fontMetrics().height() + 6
        hauteur = arbre.header().sizeHint().height() + hauteur_ligne * max(1, nombre_lignes)
        hauteur += 2 * arbre.frameWidth() + 4
        arbre.setFixedHeight(int(hauteur))

    def _creer_mesure_surface(self):
        """Configure QgsDistanceArea avec le SCR et l'ellipsoïde du projet."""
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(
            self.layer.crs(), QgsProject.instance().transformContext()
        )
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid())
        return distance_area

    def _chercher_relations_voisines(self, features, feature_by_id, field_map, index):
        """Recherche adjacences et recouvrements en un seul parcours spatial.

        Chaque paire candidate issue de l'index spatial n'est examinée qu'une
        seule fois. Les signatures attributaires sont également calculées une
        seule fois et conservées pour les mises à jour locales.
        """
        adjacent_pairs = []
        overlaps = []
        signatures = {
            int(feature.id()): signature_attributs(feature, field_map)
            for feature in features
        }
        self._cached_signatures = dict(signatures)

        for feature in features:
            fid = int(feature.id())
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            signature = signatures.get(fid)

            for candidate_id in index.intersects(geom.boundingBox()):
                try:
                    candidate_id = int(candidate_id)
                except (TypeError, ValueError):
                    continue
                if candidate_id <= fid:
                    continue

                other = feature_by_id.get(candidate_id)
                if other is None or not other.hasGeometry():
                    continue
                other_geom = other.geometry()
                if other_geom is None or other_geom.isEmpty():
                    continue

                # Une seule intersection géométrique sert aux deux contrôles.
                # - surface >= 1 m² : recouvrement ;
                # - sinon, longueur > 1 mm : contact par bord donc adjacence
                #   (si les attributs sont identiques).
                try:
                    intersection = geom.intersection(other_geom)
                except (AttributeError, TypeError, RuntimeError):
                    continue
                if intersection is None or intersection.isEmpty():
                    continue

                recouvrement = verif_recouvrements.recouvrement_depuis_intersection(
                    intersection
                )
                if recouvrement is not None and not recouvrement.isEmpty():
                    # L'intersection sert aux deux contrôles (voir commentaire
                    # plus haut) : décocher une règle ne dispense donc pas de
                    # la calculer, seulement de garder son résultat.
                    if "overlaps" in self._regles_metier_activees:
                        overlaps.append((fid, candidate_id, recouvrement))
                    continue

                try:
                    longueur_contact = float(intersection.length())
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    longueur_contact = 0.0

                if (
                    "adjacent" in self._regles_metier_activees
                    and signatures.get(candidate_id) == signature
                    and longueur_contact > TOLERANCE_ADJACENCE_M
                ):
                    adjacent_pairs.append(
                        (
                            fid,
                            candidate_id,
                            verif_adjacents.detail_adjacence(feature, field_map),
                        )
                    )

        return adjacent_pairs, overlaps



    # ------------------------------------------------------------------
    # Cache et recalcul local après une édition
    # ------------------------------------------------------------------

    def _enregistrer_cache_controle(
        self, feature_by_id, small, multipart, coherence, adjacent_pairs, overlaps,
        index, field_map, gaps
    ):
        """Mémorise les résultats nécessaires aux mises à jour locales suivantes."""
        self._cached_feature_by_id = feature_by_id
        self._cached_small = {fid: area for fid, area in small}
        self._cached_multipart = {fid: count for fid, count in multipart}
        self._cached_coherence = {fid: detail for fid, detail in coherence}
        self._cached_adjacent = {
            tuple(sorted((fid_a, fid_b))): detail
            for fid_a, fid_b, detail in adjacent_pairs
        }
        self._cached_overlaps = {
            tuple(sorted((int(fid_a), int(fid_b)))): QgsGeometry(geom)
            for fid_a, fid_b, geom in overlaps
            if geom is not None and not geom.isEmpty()
        }
        self._spatial_index = index
        self._field_map = field_map
        self._cached_gap_geometries = [geom for _, geom in gaps]
        self._pending_fids.clear()
        self._pending_old_geometries.clear()

    def _recalculer_entites_modifiees(self):
        """Recalcule uniquement les entités modifiées et leurs voisines."""
        pending = set(self._pending_fids)
        old_geometries = dict(self._pending_old_geometries)
        self._pending_fids.clear()
        self._pending_old_geometries.clear()
        if not pending:
            return

        self._refreshing = True
        try:
            affected, affected_rect, has_rect = self._preparer_zone_modifiee(
                pending, old_geometries
            )
            current, affected_rect, has_rect = self._recharger_entites_modifiees(
                pending, affected, affected_rect, has_rect
            )
            self._mettre_a_jour_cache_entites(pending, current)
            self._recalculer_anomalies_entites(pending)
            self._recalculer_relations_locales(affected)

            if has_rect and self._cached_emprise_layer_id:
                # Les trous sont déjà recalculés uniquement dans la zone touchée.
                # Ne pas reparcourir ensuite TOUS les trous et la couche entière.
                verif_trous.mettre_a_jour_trous_locaux(self, affected_rect)

            self._reconstruire_depuis_cache(valider_trous=False)
        finally:
            self._refreshing = False

    def _preparer_zone_modifiee(self, pending, old_geometries):
        """Retire les anciennes entités de l'index et récupère leur voisinage."""
        affected = set(pending)
        affected_rect = QgsRectangle()
        has_rect = False

        for fid in pending:
            old_feature = self._cached_feature_by_id.get(fid)
            old_geom = old_geometries.get(fid)
            if old_geom is None and old_feature is not None and old_feature.hasGeometry():
                old_geom = QgsGeometry(old_feature.geometry())

            if old_geom is not None and not old_geom.isEmpty():
                rect = old_geom.boundingBox()
                affected.update(self._spatial_index.intersects(rect))
                affected_rect, has_rect = self._ajouter_emprise(
                    affected_rect, has_rect, rect
                )

            if old_feature is not None:
                try:
                    self._spatial_index.deleteFeature(old_feature)
                except Exception:
                    pass

        return affected, affected_rect, has_rect

    def _recharger_entites_modifiees(
        self, pending, affected, affected_rect, has_rect
    ):
        """Recharge les entités courantes et réinjecte leur géométrie dans l'index."""
        current = {}
        request = QgsFeatureRequest().setFilterFids(list(pending))
        for feature in self.layer.getFeatures(request):
            if not feature.hasGeometry() or feature.geometry().isEmpty():
                continue
            current[feature.id()] = feature
            self._spatial_index.addFeature(feature)
            rect = feature.geometry().boundingBox()
            affected.update(self._spatial_index.intersects(rect))
            affected_rect, has_rect = self._ajouter_emprise(
                affected_rect, has_rect, rect
            )
        return current, affected_rect, has_rect

    @staticmethod
    def _ajouter_emprise(emprise, emprise_initialisee, nouvelle_emprise):
        """Ajoute une emprise à un QgsRectangle cumulatif."""
        if not emprise_initialisee:
            return QgsRectangle(nouvelle_emprise), True
        emprise.combineExtentWith(nouvelle_emprise)
        return emprise, True

    def _mettre_a_jour_cache_entites(self, pending, current):
        """Remplace dans le cache les entités créées, modifiées ou supprimées."""
        for fid in pending:
            if fid in current:
                self._cached_feature_by_id[fid] = current[fid]
            else:
                self._cached_feature_by_id.pop(fid, None)
            self._cached_small.pop(fid, None)
            self._cached_multipart.pop(fid, None)
            self._cached_coherence.pop(fid, None)
            self._cached_signatures.pop(fid, None)

    def _recalculer_anomalies_entites(self, pending):
        """Délègue aux modules d'anomalies les seuls FID modifiés."""
        mesure_surface = self._creer_mesure_surface()

        for fid in pending:
            feature = self._cached_feature_by_id.get(fid)
            if feature is None:
                continue

            petit = verif_surface.detecter(feature, mesure_surface)
            if petit is not None:
                self._cached_small[fid] = petit[1]

            multipartie = verif_multiparties.detecter(feature)
            if multipartie is not None:
                self._cached_multipart[fid] = multipartie[1]

            if self._field_map:
                self._cached_signatures[fid] = signature_attributs(
                    feature, self._field_map
                )
                coherence = verif_coherence.detecter(feature, self._field_map)
                if coherence is not None:
                    self._cached_coherence[fid] = coherence[1]

    def _recalculer_relations_locales(self, affected):
        """Recalcule adjacences et recouvrements touchés en un seul parcours."""
        affected = {int(fid) for fid in affected}
        # Toute paire impliquant une entité touchée est retirée du cache avant
        # d'être recalculée ci-dessous : une paire dont l'un des deux membres
        # a changé peut ne plus être valide (voisin disparu, forme modifiée).
        for cache in (self._cached_adjacent, self._cached_overlaps):
            for pair in list(cache):
                if pair[0] in affected or pair[1] in affected:
                    del cache[pair]

        checked = set()
        for fid in affected:
            feature = self._cached_feature_by_id.get(fid)
            if feature is None or not feature.hasGeometry():
                continue
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue

            signature = self._cached_signatures.get(fid)
            if signature is None and self._field_map:
                signature = signature_attributs(feature, self._field_map)
                self._cached_signatures[fid] = signature

            for other_id in self._spatial_index.intersects(geom.boundingBox()):
                try:
                    other_id = int(other_id)
                except (TypeError, ValueError):
                    continue
                if other_id == fid:
                    continue
                pair = tuple(sorted((fid, other_id)))
                if pair in checked:
                    continue
                checked.add(pair)

                other = self._obtenir_entite_cachee(other_id)
                if other is None or not other.hasGeometry():
                    continue
                other_geom = other.geometry()
                if other_geom is None or other_geom.isEmpty():
                    continue

                other_signature = self._cached_signatures.get(other_id)
                if other_signature is None and self._field_map:
                    other_signature = signature_attributs(
                        other, self._field_map
                    )
                    self._cached_signatures[other_id] = other_signature

                try:
                    intersection = geom.intersection(other_geom)
                except (AttributeError, TypeError, RuntimeError):
                    continue
                if intersection is None or intersection.isEmpty():
                    continue

                recouvrement = verif_recouvrements.recouvrement_depuis_intersection(
                    intersection
                )
                if recouvrement is not None and not recouvrement.isEmpty():
                    self._cached_overlaps[pair] = QgsGeometry(recouvrement)
                    continue

                try:
                    longueur_contact = float(intersection.length())
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    longueur_contact = 0.0

                if (
                    signature == other_signature
                    and longueur_contact > TOLERANCE_ADJACENCE_M
                ):
                    self._cached_adjacent[pair] = verif_adjacents.detail_adjacence(
                        feature, self._field_map
                    )

    def _obtenir_entite_cachee(self, fid):
        """Retourne une entité du cache ou la charge ponctuellement depuis la couche."""
        feature = self._cached_feature_by_id.get(fid)
        if feature is not None:
            return feature

        if not couche_est_disponible(self.layer):
            return None
        request = QgsFeatureRequest().setFilterFid(fid)
        feature = next(self.layer.getFeatures(request), None)
        if feature is not None and feature.hasGeometry():
            geom = feature.geometry()
            if geom is not None and not geom.isEmpty():
                self._cached_feature_by_id[fid] = feature
                return feature
        return None





    # ------------------------------------------------------------------
    # Présentation des résultats dans le panneau
    # ------------------------------------------------------------------

    def _purger_anomalies_entites_absentes(self):
        """Retire du cache les FID d'anomalies qui n'existent plus réellement.

        Certaines opérations d'édition (fusion, suppression, undo) peuvent
        invalider un FID entre deux rafraîchissements du panneau. On ne
        reparcourt pas toute la couche : seuls les FID actuellement présents
        dans les anomalies sont relus en une requête.
        """
        if not couche_est_disponible(self.layer):
            return

        fids = set(self._cached_small)
        fids.update(self._cached_multipart)
        fids.update(self._cached_coherence)
        for a, b in self._cached_adjacent:
            fids.add(int(a))
            fids.add(int(b))
        for a, b in self._cached_overlaps:
            fids.add(int(a))
            fids.add(int(b))

        if not fids:
            return

        valides = set()
        request = QgsFeatureRequest().setFilterFids(list(fids))
        try:
            iterator = self.layer.getFeatures(request)
        except (AttributeError, RuntimeError):
            return

        for feature in iterator:
            try:
                geom = feature.geometry()
                if not feature.hasGeometry() or geom is None or geom.isEmpty():
                    continue
                fid = int(feature.id())
            except (AttributeError, TypeError, ValueError, RuntimeError):
                continue
            valides.add(fid)
            # Profiter de la relecture pour garder le cache d'entités courant.
            self._cached_feature_by_id[fid] = feature

        invalides = fids - valides
        if not invalides:
            return

        for fid in invalides:
            self._cached_feature_by_id.pop(fid, None)
            self._cached_small.pop(fid, None)
            self._cached_multipart.pop(fid, None)
            self._cached_coherence.pop(fid, None)
            self._cached_signatures.pop(fid, None)

        self._cached_adjacent = {
            pair: detail
            for pair, detail in self._cached_adjacent.items()
            if int(pair[0]) in valides and int(pair[1]) in valides
        }
        self._cached_overlaps = {
            pair: geom
            for pair, geom in self._cached_overlaps.items()
            if int(pair[0]) in valides and int(pair[1]) in valides
        }

    def _reconstruire_depuis_cache(self, valider_trous=True):
        # Une fusion/suppression/annulation peut laisser momentanément un FID
        # obsolète dans le cache. Le retirer avant d'afficher évite les lignes
        # d'anomalies impossibles à cliquer.
        self._purger_anomalies_entites_absentes()

        # Après une édition locale, cette sécurité retire d'éventuels trous
        # devenus obsolètes. Lors d'un contrôle complet elle est inutile, car
        # les trous viennent d'être calculés sur l'état courant de la couche.
        if valider_trous:
            verif_trous.valider_trous_contre_couche_actuelle(self)

        small = verif_surface.actualiser_visibles(self)
        multipart = sorted(self._cached_multipart.items())
        adjacent_pairs = [(a, b, detail) for (a, b), detail in self._cached_adjacent.items()]
        adjacent_groups = verif_adjacents.regrouper_adjacences(adjacent_pairs)
        overlaps = [
            (pair[0], pair[1], geom)
            for pair, geom in sorted(self._cached_overlaps.items())
        ]
        gaps = [(i + 1, geom) for i, geom in enumerate(self._cached_gap_geometries)]
        coherence = sorted(self._cached_coherence.items())

        self._remplir_arbre(
            small, multipart, overlaps, adjacent_groups, gaps, coherence,
            self._cached_emprise_layer_id is not None
        )

        issue_count = (
            len(small) + len(multipart) + len(overlaps)
            + len(adjacent_groups) + len(gaps) + len(coherence)
        )
        self.dock.create_layer_button.setVisible(issue_count > 0)
        if self._surbrillance.courante() is not None:
            self._synchroniser_couche_surbrillance()
        if issue_count:
            resume = f"{issue_count} anomalie(s) détectée(s)."
        else:
            resume = "Aucune anomalie détectée."

        self.dock.summary.setText(resume)











    def _remplir_arbre(self, small, multipart, overlaps, adjacent_groups, gaps, coherence, emprise_found):
        """Affiche les catégories et conserve l'état choisi par l'utilisateur.

        Les catégories sont fermées au premier affichage. Si l'utilisateur en
        ouvre une, elle reste ouverte lors des recalculs automatiques du panneau.
        Les lignes détaillées sont matérialisées uniquement à l'ouverture afin
        de limiter le coût CPU et mémoire.
        """
        arbre = self.dock.tree
        categories_ouvertes = set(self._categories_ouvertes)
        arbre.setUpdatesEnabled(False)
        try:
            arbre.clear()
            self._lazy_tree_data = {
                "small": list(small),
                "multipart": list(multipart),
                "overlaps": list(overlaps),
                "gaps": list(gaps),
                "adjacent": list(adjacent_groups),
                "coherence": list(coherence),
            }
            definitions_actives = (
                ("small", f"Surfaces < 0,5 ha ({len(small)})"),
                ("multipart", f"Entités multiparties ({len(multipart)})"),
                ("overlaps", f"Recouvrements ({len(overlaps)})"),
                (
                    "gaps",
                    f"Trous dans la couche ({len(gaps)})"
                    if emprise_found
                    else "Trous dans la couche (bdfv3_emprise absente)",
                ),
                (
                    "adjacent",
                    (
                        "Polygones adjacents aux attributs identiques "
                        f"({len({fid for groupe, _detail in adjacent_groups for fid in groupe})} polygones, "
                        f"{len(adjacent_groups)} groupes)"
                    ),
                ),
                ("coherence", f"Incohérence essence / TFF ({len(coherence)})"),
            )
            # Une règle décochée dans le menu ("Vérifier les règles métier")
            # n'a rien calculé : sa liste est vide comme pour "rien trouvé",
            # donc afficher "(0)" serait trompeur — "(non vérifié)" à la place.
            definitions = tuple(
                (cle, titre) if cle in self._regles_metier_activees
                else (cle, f"{LIBELLES_REGLES_METIER[cle]} (non vérifié)")
                for cle, titre in definitions_actives
            )
            for cle, titre in definitions:
                groupe = QTreeWidgetItem([titre, ""])
                groupe.setData(0, Qt.UserRole, {"lazy_category": cle, "lazy_loaded": False})
                arbre.addTopLevelItem(groupe)
                if self._lazy_tree_data.get(cle):
                    # Un enfant factice suffit à afficher la flèche d'expansion.
                    groupe.addChild(QTreeWidgetItem(["…", ""]))
                # Fermé par défaut, mais ne pas replier une catégorie que
                # l'utilisateur avait laissée ouverte avant le recalcul.
                groupe.setExpanded(cle in categories_ouvertes)
        finally:
            arbre.setUpdatesEnabled(True)
        arbre.resizeColumnToContents(0)

    def _peupler_categorie_si_besoin(self, groupe):
        """Matérialise une catégorie du panneau lors de sa première ouverture."""
        if self.dock is None or groupe is None:
            return
        payload = groupe.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            return
        cle = payload.get("lazy_category")
        if not cle or payload.get("lazy_loaded"):
            return

        donnees = self._lazy_tree_data.get(cle, [])
        self.dock.tree.setUpdatesEnabled(False)
        try:
            groupe.takeChildren()
            if cle == "small":
                verif_surface.ajouter_au_panneau(self, self.dock.tree, donnees, groupe=groupe)
            elif cle == "multipart":
                verif_multiparties.ajouter_au_panneau(self, self.dock.tree, donnees, groupe=groupe)
            elif cle == "overlaps":
                verif_recouvrements.ajouter_au_panneau(self, self.dock.tree, donnees, groupe=groupe)
            elif cle == "gaps":
                verif_trous.ajouter_au_panneau(
                    self,
                    self.dock.tree,
                    donnees,
                    self._cached_emprise_layer_id is not None,
                    groupe=groupe,
                )
            elif cle == "adjacent":
                verif_adjacents.ajouter_au_panneau(self, self.dock.tree, donnees, groupe=groupe)
            elif cle == "coherence":
                verif_coherence.ajouter_au_panneau(self, self.dock.tree, donnees, groupe=groupe)
            payload["lazy_loaded"] = True
            groupe.setData(0, Qt.UserRole, payload)
        finally:
            self.dock.tree.setUpdatesEnabled(True)

    @staticmethod
    def _emprise_vers_tuple(rectangle):
        """Convertit un QgsRectangle en données simples stockables dans l’arbre."""
        return (
            rectangle.xMinimum(),
            rectangle.yMinimum(),
            rectangle.xMaximum(),
            rectangle.yMaximum(),
        )
















    # ------------------------------------------------------------------
    # Couche temporaire d’anomalies
    # ------------------------------------------------------------------

    def creer_couche_temporaire(self):
        """Crée un nouvel instantané temporaire des anomalies courantes."""
        if self.dock is None or not self.dock.isVisible():
            return
        adjacent_groups = verif_adjacents.regrouper_adjacences([
            (a, b, detail) for (a, b), detail in self._cached_adjacent.items()
        ])
        issue_count = (
            len(verif_surface.visibles(self))
            + len(self._cached_multipart)
            + len(self._cached_overlaps)
            + len(adjacent_groups)
            + len(self._cached_gap_geometries)
            + len(self._cached_coherence)
        )
        if issue_count == 0:
            return
        # Une nouvelle couche est créée à chaque clic. La précédente reste dans
        # le projet et n'est plus modifiée par les actualisations suivantes.
        self._surbrillance.detacher()
        self._synchroniser_couche_surbrillance()



    def _synchroniser_couche_surbrillance(self):
        """Construit puis délègue l'affichage de la couche temporaire à commun_affichage.py."""
        if not couche_est_disponible(self.layer) or self.dock is None or not self.dock.isVisible():
            return
        layer = self._surbrillance.assurer(self.layer)
        entites = self._construire_entites_surbrillance(layer)
        self._surbrillance.remplacer_entites(self.layer, entites)

    def _construire_entites_surbrillance(self, layer):
        """Construit les entités représentant chaque anomalie à afficher."""
        entites = []
        cles_traitees = set()

        for fid, _ in verif_surface.visibles(self):
            feature = self._cached_feature_by_id.get(fid)
            if feature is not None and feature.hasGeometry():
                self._ajouter_geometrie_surbrillance(
                    layer, entites, cles_traitees,
                    f"petit:{fid}", "Petits polygones", feature.geometry(),
                )

        for fid in sorted(self._cached_multipart):
            feature = self._cached_feature_by_id.get(fid)
            if feature is not None and feature.hasGeometry():
                self._ajouter_geometrie_surbrillance(
                    layer, entites, cles_traitees,
                    f"multipartie:{fid}", "Multiparties", feature.geometry(),
                )

        for fid in sorted(self._cached_coherence):
            feature = self._cached_feature_by_id.get(fid)
            if feature is not None and feature.hasGeometry():
                self._ajouter_geometrie_surbrillance(
                    layer, entites, cles_traitees,
                    f"coherence:{fid}", "Incohérence essence / TFF", feature.geometry(),
                )

        for (fid_a, fid_b), geometrie in sorted(self._cached_overlaps.items()):
            if not geometrie or geometrie.isEmpty():
                continue
            self._ajouter_geometrie_surbrillance(
                layer, entites, cles_traitees,
                f"recouvrement:{fid_a}:{fid_b}", "Recouvrements", geometrie,
            )

        for geometrie in self._cached_gap_geometries:
            if not geometrie or geometrie.isEmpty():
                continue
            # Un trou n'a pas de fid (ce n'est pas une entité de la couche) :
            # une empreinte de sa géométrie sert de clé stable pour cles_traitees.
            digest = hashlib.sha1(bytes(geometrie.asWkb())).hexdigest()[:16]
            self._ajouter_geometrie_surbrillance(
                layer, entites, cles_traitees,
                f"trou:{digest}", "Trous", geometrie,
            )

        adjacent_groups = verif_adjacents.regrouper_adjacences([
            (a, b, detail) for (a, b), detail in self._cached_adjacent.items()
        ])
        for fids_groupe, _detail in adjacent_groups:
            geometries = []
            for fid in fids_groupe:
                feature = self._cached_feature_by_id.get(fid)
                if feature is None or not feature.hasGeometry():
                    continue
                geometries.append(QgsGeometry(feature.geometry()))
            if len(geometries) < 2:
                continue

            try:
                geometrie = QgsGeometry.unaryUnion(geometries)
            except (TypeError, RuntimeError):
                continue
            cle_fids = ":".join(str(fid) for fid in fids_groupe)
            self._ajouter_geometrie_surbrillance(
                layer, entites, cles_traitees,
                f"adjacent_groupe:{cle_fids}", "Adjacents", geometrie,
            )

        return entites

    def _ajouter_geometrie_surbrillance(
        self, layer, entites, cles_traitees, cle, categorie, geometrie,
        decouper_emprise=True,
    ):
        """Ajoute une anomalie à la couche temporaire.

        Les anomalies ordinaires sont limitées à l'emprise de production. La
        catégorie « hors emprise » désactive volontairement cette découpe afin
        de montrer précisément la surface excédentaire.
        """
        if cle in cles_traitees or not geometrie or geometrie.isEmpty():
            return

        geometrie = QgsGeometry(geometrie)
        if decouper_emprise and self._cached_emprise_layer_id:
            geometrie = verif_trous.decouper_a_emprise_locale(self, geometrie)

        if geometrie.isEmpty():
            return
        if not geometrie.isGeosValid():
            geometrie = geometrie.makeValid()

        date_detection = self._obtenir_date_premiere_detection(cle)
        for partie in extraire_parties_polygonales(geometrie):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([cle, categorie, date_detection])
            feature.setGeometry(partie)
            entites.append(feature)

        cles_traitees.add(cle)

    def _obtenir_date_premiere_detection(self, cle):
        """Conserve la première date de détection d'une anomalie pendant la session."""
        date_detection = self._first_detection.get(cle)
        if date_detection is None:
            date_detection = QDateTime.currentDateTime()
            self._first_detection[cle] = date_detection
        return date_detection


    # ------------------------------------------------------------------
    # Navigation et interaction avec les anomalies
    # ------------------------------------------------------------------

    def faire_clignoter(self, payload):
        """Construit les géométries à signaler puis délègue le rendu à commun_affichage.py.

        ``payload`` peut contenir plusieurs formes de référence selon la
        catégorie d'anomalie cliquée dans l'arbre (voir verification_panneau.py) :
        "fids" (polygones entiers), "multipart_part" (une seule partie d'un
        multipartie), "gap_index" (un trou, sans fid propre) ou "overlap_pair"
        (la zone de recouvrement entre deux polygones). Les géométries
        correspondantes sont réunies avant d'être transmises au clignotement.
        """
        if not isinstance(payload, dict):
            return
        geometries = []
        for fid in payload.get("fids", []):
            feature = self._cached_feature_by_id.get(fid)
            if feature is not None and feature.hasGeometry():
                geometries.append(QgsGeometry(feature.geometry()))

        multipart_part = payload.get("multipart_part")
        if isinstance(multipart_part, (list, tuple)) and len(multipart_part) == 2:
            try:
                multipart_fid = int(multipart_part[0])
                part_index = int(multipart_part[1])
            except (TypeError, ValueError):
                multipart_fid, part_index = None, -1
            feature = self._cached_feature_by_id.get(multipart_fid) if multipart_fid is not None else None
            if feature is not None and feature.hasGeometry() and not feature.geometry().isEmpty():
                parties = sorted(
                    extraire_parties_multipartie_brutes(QgsGeometry(feature.geometry())),
                    key=lambda geom: abs(geom.area()), reverse=True,
                )
                if 0 <= part_index < len(parties):
                    geometries.append(QgsGeometry(parties[part_index]))

        gap_index = payload.get("gap_index")
        if isinstance(gap_index, int) and 0 <= gap_index < len(self._cached_gap_geometries):
            geometries.append(QgsGeometry(self._cached_gap_geometries[gap_index]))

        overlap_pair = payload.get("overlap_pair")
        if isinstance(overlap_pair, (list, tuple)) and len(overlap_pair) == 2:
            try:
                pair = tuple(sorted((int(overlap_pair[0]), int(overlap_pair[1]))))
            except (TypeError, ValueError):
                pair = None
            geom = self._cached_overlaps.get(pair) if pair else None
            if geom is not None and not geom.isEmpty():
                geometries.append(QgsGeometry(geom))

        affichables = []
        for geom in geometries:
            if self._cached_emprise_layer_id:
                geom = verif_trous.decouper_a_emprise_locale(self, geom)
            if geom is not None and not geom.isEmpty():
                affichables.append(geom)
        self._clignotement.afficher(affichables, self.layer)



    def _reinitialiser_resultats_panneau(self):
        """Vide le panneau et les résultats calculés, sans toucher aux couches créées."""
        self._cached_feature_by_id = {}
        self._cached_gap_geometries = []
        self._cached_emprise_layer_id = None
        self._cached_small = {}
        self._cached_multipart = {}
        self._cached_overlaps = {}
        self._cached_adjacent = {}
        self._cached_coherence = {}
        self._cached_signatures = {}
        self._lazy_tree_data = {}
        self._categories_ouvertes.clear()
        self._spatial_index = None
        self._field_map = None
        self._pending_fids.clear()
        self._pending_old_geometries.clear()
        self._etat_nettoyage_automatique = None
        self._etat_recherche_trous = None
        self._contexte_recherche_trous = None
        if self.dock is not None:
            self.dock.tree.clear()
            self.dock.summary.setText("")
            self.dock.create_layer_button.setVisible(False)
            self.dock.search_progress.setVisible(False)
            self.dock.search_progress_metier.setVisible(False)
            self.dock.search_status.setVisible(False)
            self.dock.search_status_metier.setVisible(False)

    def zoomer_sur_element(self, payload):
        if not isinstance(payload, dict):
            return
        extent_data = payload.get("extent")
        if extent_data:
            zoomer_sur_emprise(self.iface.mapCanvas(), QgsRectangle(*extent_data))
            return
        fids = payload.get("fids")
        if fids:
            self.zoomer_sur_entites(fids)

    def zoomer_sur_entites(self, fids):
        """Zoome sur les géométries déjà en cache plutôt que sur les FID provider.

        C'est notamment plus fiable pour les entités temporaires à FID négatif
        présentes dans le tampon d'édition. Un accès par identifiant au provider
        peut alors échouer alors que la géométrie est bien visible dans QGIS.
        """
        if not couche_est_disponible(self.layer):
            return

        extent = QgsRectangle()
        found = False
        manquants = []
        for fid in fids:
            try:
                fid = int(fid)
            except (TypeError, ValueError):
                continue
            feature = self._cached_feature_by_id.get(fid)
            if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
                manquants.append(fid)
                continue
            rect = feature.geometry().boundingBox()
            if not found:
                extent = QgsRectangle(rect)
                found = True
            else:
                extent.combineExtentWith(rect)

        # Repli uniquement pour une entité non présente dans le cache.
        if manquants:
            request = QgsFeatureRequest().setFilterFids(manquants)
            for feature in self.layer.getFeatures(request):
                if feature.hasGeometry() and not feature.geometry().isEmpty():
                    rect = feature.geometry().boundingBox()
                    if not found:
                        extent = QgsRectangle(rect)
                        found = True
                    else:
                        extent.combineExtentWith(rect)

        if not found:
            return

        zoomer_sur_emprise(self.iface.mapCanvas(), extent)
