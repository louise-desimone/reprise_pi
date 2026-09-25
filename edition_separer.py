# -*- coding: utf-8 -*-
"""Séparer et renseigner un ou plusieurs polygones BD Forêt.

L'utilisateur choisit des polygones (surbrillance jaune), puis dessine une
ligne de coupe. La séparation géométrique et l'écriture en couche passent par
le moteur natif QGIS (QgsVectorLayer.splitFeatures).
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.core import NULL, Qgis, QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsVectorLayerUtils
from qgis.gui import QgsMapToolCapture, QgsMapToolIdentify

from .commun_affichage import definir_action_cochee, remplacer_surbrillance_polygone
from .commun_couches import valider_couche_modifiable
from .commun_parametres import CHAMP_ID_FORET
from .commun_edition import (
    CHAMPS_DERIVES_ALERTES,
    AttenteDebutEdition,
    SurveillanceCoucheActive,
    avertir_message_bar,
    basculer_cible_surbrillance,
    basculer_outil_geometrique,
    creer_action_outil,
    detruire_action_outil,
    effacer_cibles_surbrillance,
    exiger_fid_valide,
    fid_est_valide,
    obtenir_couche_editable,
    ouvrir_formulaire_ou_annuler,
    recuperer_entite,
    recuperer_entites,
    retirer_cible_surbrillance,
    sans_reentrance,
    surface_ha,
)
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_synchronisation_alertes import synchroniser_zone_outil
from .commun_topologie import nettoyer_geometrie_base


class EchecSeparationNative(RuntimeError):
    """Échec attendu du moteur de séparation QGIS, avec un message déjà prêt pour l'utilisateur."""


class OutilSelectionSeparation(QgsMapToolIdentify):
    """Choisit les entités à découper, uniquement via les surbrillances du plugin."""

    def __init__(self, canvas, plugin):
        super().__init__(canvas)
        self.plugin = plugin
        self.setCursor(Qt.ArrowCursor)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.plugin.demarrer_trace()
        elif event.button() == Qt.LeftButton:
            self.plugin.basculer_entite_cliquee(
                event.x(),
                event.y(),
                bool(event.modifiers() & Qt.ControlModifier),
            )


class OutilLigneSeparation(QgsMapToolCapture):
    """Capture la ligne comme l'outil natif ``QgsMapToolSplitFeatures``.

    Le point important est de ne pas déléguer la fin du tracé au comportement
    générique de ``QgsMapToolCapture`` : l'outil natif QGIS ajoute lui-même
    chaque clic avec le couple ``mapPoint() / mapPointMatch()`` puis transmet
    directement ``captureCurve()`` à ``splitFeatures``. On reproduit cette
    séquence afin de conserver exactement les sommets accrochés.
    """

    def __init__(self, plugin):
        super().__init__(
            plugin.iface.mapCanvas(),
            plugin.iface.cadDockWidget(),
            QgsMapToolCapture.CaptureLine,
        )
        self.plugin = plugin
        # QgsMapToolSplitFeatures fait explicitement la même chose : la grille
        # de couche ne doit pas déplacer silencieusement les sommets capturés.
        try:
            self.setSnapToLayerGridEnabled(False)
        except (AttributeError, RuntimeError):
            pass

    def supportsTechnique(self, technique):
        """Seule la numérisation clic par clic a du sens pour une ligne de coupe."""
        try:
            return technique == Qgis.CaptureTechnique.StraightSegments
        except (AttributeError, TypeError):
            return True

    def cadCanvasReleaseEvent(self, event):
        """Reproduit la capture de ``QgsMapToolSplitFeatures`` de QGIS."""
        if event.button() == Qt.LeftButton:
            try:
                # C'est volontairement le même appel que dans l'outil natif :
                # le Match permet à QgsMapToolCapture de récupérer le vrai
                # sommet/segment accroché dans le SCR de la couche cible.
                self.addVertex(event.mapPoint(), event.mapPointMatch())
            except (AttributeError, RuntimeError, TypeError) as exc:
                self.plugin._avertir(f"Le point du tracé n'a pas pu être ajouté : {exc}")
                return
            try:
                self.startCapturing()
            except (AttributeError, RuntimeError):
                pass
            return

        if event.button() == Qt.RightButton:
            try:
                if self.size() < 2:
                    self.stopCapturing()
                    self.plugin.retour_selection_apres_annulation()
                    return
            except (AttributeError, RuntimeError, TypeError):
                pass

            try:
                self.deleteTempRubberBand()
            except (AttributeError, RuntimeError):
                pass

            try:
                capture = self.captureCurve()
                if capture is None:
                    raise RuntimeError("courbe de capture vide")
                geometrie = QgsGeometry(capture.clone())
            except (AttributeError, RuntimeError, TypeError) as exc:
                self.plugin._avertir(f"La ligne dessinée n'a pas pu être lue : {exc}")
                self.stopCapturing()
                return

            try:
                self.plugin.traiter_ligne_dessinee(geometrie)
            finally:
                try:
                    self.stopCapturing()
                except (AttributeError, RuntimeError):
                    pass
            return

    def lineCaptured(self, line):
        """Filet de compatibilité : la capture normale passe par cadCanvasReleaseEvent."""
        # Ne rien déclencher ici : sinon certaines versions pourraient lancer
        # deux séparations pour le même tracé.
        return

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            try:
                self.stopCapturing()
            except (RuntimeError, AttributeError):
                pass
            self.plugin.retour_selection_apres_annulation()
            event.accept()
            return
        super().keyPressEvent(event)


class SeparerPolygonePlugin:
    """Découpe les polygones choisis par l'utilisateur."""

    NOM_OUTIL = "Séparer un ou plusieurs polygones de la BD Forêt"

    def __init__(self, iface, manager=None):
        self.iface = iface
        self.manager = manager
        self.canvas = iface.mapCanvas()
        self.action = None
        self.actif = False
        self.couche = None
        self.outil_selection = None
        self.outil_dessin = None
        self.fids = []
        self.surbrillances = {}
        self.surbrillance_resultat = None
        self.traitement_en_cours = False
        self._changement_outil = False
        self._attente_edition = AttenteDebutEdition(self._edition_demarree)
        self._surveillance = SurveillanceCoucheActive(self._desactiver)

    def initGui(self):
        chemin_icone = os.path.join(os.path.dirname(__file__), "icon_separer.svg")
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
            self.actif = False
            self._attente_edition.attendre(couche)
            return True

        self._attente_edition.annuler()
        self.actif = True
        self._surveillance.surveiller_couche(couche)
        self.effacer_selection_visuelle(rafraichir=False)
        self._activer_outil_selection()
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
        self.effacer_selection_visuelle(rafraichir=False)
        self.surbrillance_resultat = remplacer_surbrillance_polygone(
            self.canvas, self.surbrillance_resultat, None, self.couche
        )
        self.couche = None
        definir_action_cochee(self.action, False)

    def desactiver_pour_autre_outil(self):
        self._desactiver()

    def _outil_carte_change(self, nouvel_outil, ancien_outil=None):
        """QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive."""
        if self._changement_outil or not self.actif:
            return
        if nouvel_outil in (self.outil_selection, self.outil_dessin):
            return
        self._desactiver()

    # ------------------------------------------------------------------
    # Sélection des cibles
    # ------------------------------------------------------------------

    def _activer_outil_selection(self):
        if not self.actif or self.couche is None or not self.couche.isEditable():
            return
        if self.outil_selection is None:
            self.outil_selection = OutilSelectionSeparation(self.canvas, self)
        self._changement_outil = True
        try:
            self.canvas.setMapTool(self.outil_selection)
        finally:
            self._changement_outil = False

    def basculer_entite_cliquee(self, x, y, ctrl_appuye):
        basculer_cible_surbrillance(self, x, y, ctrl_appuye, self.outil_selection)

    def _retirer_fid(self, fid):
        retirer_cible_surbrillance(self, fid)

    def effacer_selection_visuelle(self, rafraichir=True):
        effacer_cibles_surbrillance(self, rafraichir)

    # ------------------------------------------------------------------
    # Tracé de la ligne de coupe
    # ------------------------------------------------------------------

    def demarrer_trace(self):
        if not self.actif or self.couche is None:
            return
        if not self.fids:
            self._avertir(
                "Cliquez d'abord sur au moins un polygone à séparer, puis faites clic droit."
            )
            return
        self._activer_outil_dessin()

    def _activer_outil_dessin(self):
        if not self.actif or self.couche is None or not self.couche.isEditable():
            return
        if self.outil_dessin is None:
            self.outil_dessin = OutilLigneSeparation(self)
        try:
            self.outil_dessin.stopCapturing()
        except (RuntimeError, AttributeError):
            pass
        self._changement_outil = True
        try:
            self.canvas.setMapTool(self.outil_dessin)
        finally:
            self._changement_outil = False

    def retour_selection_apres_annulation(self):
        self.effacer_selection_visuelle(rafraichir=False)
        self.surbrillance_resultat = remplacer_surbrillance_polygone(
            self.canvas, self.surbrillance_resultat, None, self.couche
        )
        if self.actif and self.couche is not None and self.couche.isEditable():
            self._activer_outil_selection()
        try:
            self.canvas.refresh()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Séparation
    # ------------------------------------------------------------------

    @sans_reentrance
    def traiter_ligne_dessinee(self, geometrie_ligne):
        if not self.actif:
            return

        probleme = valider_couche_modifiable(self.couche)
        if probleme:
            self._avertir(probleme)
            return

        try:
            # splitFeatures()/splitGeometry() attendent des QgsPointXY, alors
            # que vertices() renvoie des QgsPoint (avec Z/M éventuels).
            points = [QgsPointXY(p) for p in geometrie_ligne.vertices()]
            if len(points) < 2:
                self._avertir("La ligne doit contenir au moins deux points.")
                return

            preparation = self._preparer_separation_native()
            if preparation is None:
                return

            self.effacer_selection_visuelle(rafraichir=False)
            nouveaux_fids = self._appliquer_separation_native(preparation, points)

            self._ouvrir_nouveaux_morceaux_en_serie(nouveaux_fids)
        except EchecSeparationNative as erreur:
            self._avertir(str(erreur))
        except Exception as erreur:
            self.iface.messageBar().pushCritical(
                self.NOM_OUTIL, f"La séparation a échoué : {erreur}"
            )
        finally:
            self.surbrillance_resultat = remplacer_surbrillance_polygone(
                self.canvas, self.surbrillance_resultat, None, self.couche
            )
            if self.actif and self.couche is not None and self.couche.isEditable():
                self._activer_outil_selection()

    def _preparer_separation_native(self):
        """Mémorise les cibles et leur état avant l'appel au moteur natif QGIS."""
        entites = recuperer_entites(self.couche, self.fids)
        cibles = []
        for fid in self.fids:
            fid = int(fid)
            entite = entites.get(fid)
            if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
                continue
            cibles.append(fid)

        if not cibles:
            self._avertir(
                "Aucune des cibles n'existe plus ou n'a de géométrie exploitable."
            )
            return None

        geometries_sources = {}
        for fid in cibles:
            geometrie = nettoyer_geometrie_base(entites[fid].geometry())
            if geometrie is None:
                self._avertir(f"Le polygone {fid} a une géométrie invalide.")
                return None
            geometries_sources[fid] = geometrie
        attributs_sources = {fid: list(entites[fid].attributes()) for fid in cibles}

        geometries_zone = list(geometries_sources.values())
        try:
            geometrie_zone = (
                QgsGeometry(geometries_zone[0])
                if len(geometries_zone) == 1
                else QgsGeometry.unaryUnion(geometries_zone)
            )
        except (AttributeError, RuntimeError, TypeError):
            geometrie_zone = QgsGeometry(geometries_zone[0])

        return {
            "cibles": cibles,
            "geometries_sources": geometries_sources,
            "attributs_sources": attributs_sources,
            "geometrie_zone": geometrie_zone,
        }

    @staticmethod
    def _decrire_resultat_split(resultat):
        """Traduit un ``Qgis.GeometryOperationResult`` sans dépendre d'une version précise."""
        enum = Qgis.GeometryOperationResult
        descriptions = (
            ("NothingHappened", "la ligne n'a produit aucune coupe sur les polygones ciblés"),
            ("InvalidBaseGeometry", "au moins une géométrie source est invalide pour la séparation"),
            ("GeometryEngineError", "le moteur géométrique de QGIS/GEOS a rencontré une erreur"),
            ("LayerNotEditable", "la couche n'est pas modifiable"),
        )
        for nom, message in descriptions:
            valeur = getattr(enum, nom, None)
            if valeur is not None and resultat == valeur:
                return nom, message
        try:
            texte = str(resultat)
        except Exception:
            texte = "Unknown"
        if "." in texte:
            texte = texte.rsplit(".", 1)[-1]
        return texte or "Unknown", "QGIS a refusé la séparation pour une raison non reconnue par le plugin"

    # ------------------------------------------------------------------
    # Application de la séparation
    # ------------------------------------------------------------------

    @vue_stable_pendant_modification
    def _appliquer_separation_native(self, preparation, points):
        """Applique le split de couche QGIS + règles BD Forêt dans un seul Ctrl+Z."""
        cibles = [int(fid) for fid in preparation["cibles"]]
        geometrie_zone = preparation.get("geometrie_zone")
        commande_ouverte = False
        selection_avant = []
        contexte_formulaire = []
        historique = getattr(self.manager, "historique", None) if self.manager is not None else None

        # Les FID présents avant l'appel permettent d'identifier exactement les
        # entités que le moteur natif vient de créer.
        fids_avant = {int(entite.id()) for entite in self.couche.getFeatures()}

        if historique is not None:
            try:
                contexte_formulaire = historique.capturer_contexte_visuel_couche(self.couche, [])
            except (AttributeError, RuntimeError, TypeError, ValueError):
                contexte_formulaire = []

        try:
            selection_avant = [int(fid) for fid in self.couche.selectedFeatureIds()]
        except (AttributeError, RuntimeError, TypeError, ValueError):
            selection_avant = []

        try:
            self.couche.beginEditCommand(self.NOM_OUTIL)
            commande_ouverte = True

            # splitFeatures suit la sélection QGIS. On la remplace uniquement
            # pendant l'appel natif, puis on remet celle de l'utilisateur.
            self.couche.selectByIds(cibles)
            try:
                resultat = self.couche.splitFeatures(points, False)
            finally:
                try:
                    self.couche.selectByIds(selection_avant)
                except (AttributeError, RuntimeError, TypeError):
                    pass

            if resultat == Qgis.GeometryOperationResult.NothingHappened:
                # Sur un FID temporaire (entité ajoutée mais pas encore
                # enregistrée, p. ex. juste après un Créer), l'étage couche
                # peut renvoyer NothingHappened alors que le même moteur
                # géométrique, appelé directement sur la géométrie, réussit.
                for fid in cibles:
                    if not self._fid_temporaire_du_tampon(fid):
                        continue
                    resultat_temp, _ = self._separer_fid_temporaire(fid, points)
                    if resultat_temp == Qgis.GeometryOperationResult.Success:
                        resultat = Qgis.GeometryOperationResult.Success

            if resultat != Qgis.GeometryOperationResult.Success:
                code, message = self._decrire_resultat_split(resultat)
                raise EchecSeparationNative(f"La séparation a échoué. QGIS : {code} — {message}.")

            fids_apres = {int(entite.id()) for entite in self.couche.getFeatures()}
            nouveaux_fids = sorted(fids_apres - fids_avant)
            if not nouveaux_fids:
                raise RuntimeError(
                    "QGIS a annoncé une séparation réussie mais aucun nouveau morceau n'a été créé"
                )

            # Le moteur natif gère la géométrie et la création. On réapplique
            # ensuite uniquement les règles métier spécifiques à la BD Forêt.
            self._restaurer_attributs_nouveaux_morceaux(nouveaux_fids, preparation)
            self._recalculer_surfaces(cibles + nouveaux_fids)

            synchroniser_zone_outil(
                self.manager, self.iface, self.couche, geometrie_zone, self.NOM_OUTIL,
            )
            self.couche.endEditCommand()
            commande_ouverte = False

            self.couche.triggerRepaint(True)
            try:
                self.canvas.refresh()
            except RuntimeError:
                pass

            return nouveaux_fids

        except Exception:
            if commande_ouverte:
                try:
                    self.couche.destroyEditCommand()
                except (RuntimeError, AttributeError):
                    pass
            raise
        finally:
            try:
                self.couche.selectByIds(selection_avant)
            except (AttributeError, RuntimeError, TypeError):
                pass
            if historique is not None and contexte_formulaire:
                try:
                    historique.restaurer_contexte_visuel_couche(self.couche, contexte_formulaire)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

    def _fid_temporaire_du_tampon(self, fid):
        """Vrai si ``fid`` désigne une entité ajoutée mais pas encore commitée."""
        try:
            fid = int(fid)
            tampon = self.couche.editBuffer()
            return bool(tampon is not None and fid in tampon.addedFeatures())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _separer_fid_temporaire(self, fid, points):
        """Découpe une entité temporaire directement dans le tampon QGIS.

        ``QgsVectorLayer.splitFeatures`` finit lui-même par appeler
        ``QgsGeometry.splitGeometry`` puis ``changeGeometry``/``addFeatures``.
        Sur certains FID temporaires négatifs, l'étage couche peut pourtant
        retourner ``NothingHappened``. Ce secours reprend le même moteur
        géométrique directement, sans commit intermédiaire et dans la même
        commande d'annulation.
        """
        entite = recuperer_entite(self.couche, fid)
        if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
            return Qgis.GeometryOperationResult.NothingHappened, []

        geometrie = QgsGeometry(entite.geometry())
        try:
            resultat, nouvelles_geometries, _ = geometrie.splitGeometry(points, False, True)
        except (AttributeError, RuntimeError, TypeError):
            return Qgis.GeometryOperationResult.NothingHappened, []

        if resultat != Qgis.GeometryOperationResult.Success:
            return resultat, []

        parties = [QgsGeometry(geometrie)] + [
            QgsGeometry(g) for g in nouvelles_geometries if g is not None and not g.isEmpty()
        ]
        if len(parties) < 2:
            return Qgis.GeometryOperationResult.NothingHappened, []

        # Comme QgsVectorLayerEditUtils::splitFeatures : la plus grande partie
        # reste portée par le FID source, les autres deviennent de nouvelles
        # entités dans le tampon.
        parties.sort(key=lambda g: abs(float(g.area())), reverse=True)
        if not self.couche.changeGeometry(int(fid), parties[0]):
            raise RuntimeError(
                f"la géométrie temporaire {fid} n'a pas pu être remplacée après la séparation"
            )

        nouveaux = []
        for geometrie_nouvelle in parties[1:]:
            nouvelle = QgsVectorLayerUtils.createFeature(
                self.couche, QgsGeometry(geometrie_nouvelle), {}
            )
            if not self.couche.addFeature(nouvelle):
                raise RuntimeError(
                    f"un nouveau morceau issu du FID temporaire {fid} n'a pas pu être créé"
                )
            nouveaux.append(int(nouvelle.id()))

        return Qgis.GeometryOperationResult.Success, nouveaux

    def _trouver_parent_nouveau_morceau(self, geometrie, geometries_sources):
        """Associe un morceau créé au polygone hachuré dont il provient."""
        if geometrie is None or geometrie.isEmpty():
            return None
        meilleur_fid = None
        meilleur_score = -1.0
        for fid, source in geometries_sources.items():
            try:
                if not source.boundingBox().intersects(geometrie.boundingBox()):
                    continue
                intersection = source.intersection(geometrie)
                score = abs(float(intersection.area())) if not intersection.isEmpty() else 0.0
            except (AttributeError, RuntimeError, TypeError, ValueError):
                score = 0.0
            if score > meilleur_score:
                meilleur_score = score
                meilleur_fid = int(fid)
        return meilleur_fid

    def _restaurer_attributs_nouveaux_morceaux(self, nouveaux_fids, preparation):
        """Conserve les règles d'héritage historiques du plugin après le split natif."""
        champs = self.couche.fields()
        index_id = champs.indexOf(CHAMP_ID_FORET)
        if index_id < 0:
            raise RuntimeError(f"le champ « {CHAMP_ID_FORET} » est introuvable")
        index_surface = champs.indexOf("surface")

        exclus = set()
        try:
            exclus.update(int(index) for index in self.couche.primaryKeyAttributes())
        except (AttributeError, RuntimeError, TypeError):
            pass
        exclus.add(index_id)
        if index_surface >= 0:
            exclus.add(index_surface)
        for nom in CHAMPS_DERIVES_ALERTES:
            index = champs.indexOf(nom)
            if index >= 0:
                exclus.add(index)

        for fid in nouveaux_fids:
            exiger_fid_valide(self.couche, fid, "renseigner le nouveau morceau")
            entite = recuperer_entite(self.couche, fid)
            if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
                raise RuntimeError(f"le nouveau morceau {fid} est introuvable")

            fid_parent = self._trouver_parent_nouveau_morceau(
                entite.geometry(), preparation["geometries_sources"],
            )
            if fid_parent is None:
                raise RuntimeError(f"le parent du nouveau morceau {fid} n'a pas pu être identifié")

            attributs_parent = preparation["attributs_sources"][fid_parent]
            changements = {}
            for index, valeur in enumerate(attributs_parent):
                if index >= len(champs) or index in exclus:
                    continue
                try:
                    if entite[index] != valeur:
                        changements[index] = valeur
                except (IndexError, KeyError):
                    changements[index] = valeur

            if changements and not self.couche.changeAttributeValues(int(fid), changements):
                raise RuntimeError(f"les attributs hérités du morceau {fid} n'ont pas pu être restaurés")

        # QGIS copie d'abord les attributs du parent sur chaque morceau créé.
        # id_foret étant la clé de relation avec les alertes, tous les nouveaux
        # morceaux reçoivent ici un identifiant neuf avant toute redistribution.
        self._attribuer_ids_foret_uniques(nouveaux_fids)

    @staticmethod
    def _cle_id_foret(valeur):
        """Normalise un ``id_foret`` pour les contrôles d'unicité."""
        if valeur is None or valeur == NULL:
            return None
        texte = str(valeur).strip()
        if not texte:
            return None
        try:
            nombre = float(texte)
            if nombre.is_integer():
                return ("n", int(nombre))
        except (TypeError, ValueError, OverflowError):
            pass
        return ("t", texte)

    def _attribuer_ids_foret_uniques(self, nouveaux_fids):
        """Donne un ``id_foret`` neuf et globalement unique à chaque morceau."""
        nouveaux_fids = sorted({int(fid) for fid in nouveaux_fids})
        if not nouveaux_fids:
            return

        champs = self.couche.fields()
        index_id = champs.indexOf(CHAMP_ID_FORET)
        if index_id < 0:
            raise RuntimeError(f"le champ « {CHAMP_ID_FORET} » est introuvable")

        nouveaux_set = set(nouveaux_fids)
        ids_utilises = set()
        maximum = 0
        requete = (
            QgsFeatureRequest()
            .setSubsetOfAttributes([index_id])
            .setFlags(QgsFeatureRequest.NoGeometry)
        )
        for entite in self.couche.getFeatures(requete):
            fid = int(entite.id())
            if fid in nouveaux_set:
                continue
            cle = self._cle_id_foret(entite[index_id])
            if cle is None:
                continue
            ids_utilises.add(cle)
            if cle[0] == "n":
                maximum = max(maximum, int(cle[1]))

        candidat = max(1, maximum + 1)
        for fid in nouveaux_fids:
            exiger_fid_valide(self.couche, fid, "attribuer un id_foret unique")
            while ("n", candidat) in ids_utilises:
                candidat += 1
            if not self.couche.changeAttributeValue(fid, index_id, candidat):
                raise RuntimeError(f"un id_foret unique n'a pas pu être attribué au morceau {fid}")
            ids_utilises.add(("n", candidat))
            candidat += 1

    def _recalculer_surfaces(self, fids):
        index_surface = self.couche.fields().indexOf("surface")
        if index_surface < 0:
            return
        for fid in fids:
            if not fid_est_valide(self.couche, fid):
                continue
            entite = recuperer_entite(self.couche, fid)
            if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
                continue
            surface = surface_ha(entite.geometry())
            if not self.couche.changeAttributeValue(int(fid), index_surface, surface):
                raise RuntimeError(f"la surface de l'entité {fid} n'a pas pu être recalculée")

    def _ouvrir_nouveaux_morceaux_en_serie(self, fids):
        for fid in fids:
            if not self.actif or self.couche is None or not self.couche.isEditable():
                return False

            entite = recuperer_entite(self.couche, fid)
            if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
                continue

            self.surbrillance_resultat = remplacer_surbrillance_polygone(
                self.canvas, self.surbrillance_resultat, entite.geometry(), self.couche,
            )
            try:
                self.canvas.refresh()
            except RuntimeError:
                pass

            if not self._ouvrir_formulaire(fid):
                return False
        return True

    def _ouvrir_formulaire(self, fid):
        entite = recuperer_entite(self.couche, fid)
        if entite is None:
            self._avertir("La nouvelle entité est introuvable.")
            return False
        return ouvrir_formulaire_ou_annuler(self.iface, self.couche, self.canvas, entite, self.NOM_OUTIL)

    def _avertir(self, message):
        avertir_message_bar(self.iface, self.NOM_OUTIL, message)
