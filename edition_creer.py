# -*- coding: utf-8 -*-
"""Créer un nouveau polygone dans la couverture BD Forêt.

L'utilisateur dessine une surface. Cette surface est retirée aux polygones
existants qu'elle recouvre, puis créée comme une nouvelle entité. Une enclave
est donc possible sans créer de vide ni de recouvrement.
"""

import os

from qgis.core import QgsGeometry
from qgis.gui import QgsMapToolCapture

from .commun_affichage import definir_action_cochee, remplacer_surbrillance_polygone
from .commun_couches import trouver_couche_emprise
from .commun_edition import (
    AttenteDebutEdition,
    SurveillanceCoucheActive,
    avertir_message_bar,
    basculer_outil_geometrique,
    creer_action_outil,
    creer_entite_nouvelle,
    detruire_action_outil,
    exiger_fid_valide,
    obtenir_couche_editable,
    recuperer_entite,
    sans_reentrance,
    surface_ha,
)
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_synchronisation_alertes import synchroniser_zone_outil
from .commun_topologie import (
    calculer_tolerance_aire,
    compter_parties_polygonales,
    construire_geometrie_emprise_locale,
    intersection_surfacique,
    nettoyer_geometrie_base,
    trouver_entites_intersectees,
)


# Déplacée depuis commun_topologie.py (audit de placement avant transmission
# du code) : n'était utilisée que par cet outil.
def _verifier_partition(geometrie_avant, geometries_apres, exiger_monopartie=True):
    """Vérifie qu'une modification conserve exactement la même couverture.

    Retourne ``None`` si la partition est correcte, sinon un message expliquant
    le problème détecté.
    """
    geometries_apres = [
        geometrie for geometrie in geometries_apres
        if geometrie is not None and not geometrie.isEmpty()
    ]
    if not geometries_apres:
        return "Le résultat géométrique est vide."

    tolerance = calculer_tolerance_aire(geometrie_avant)

    if exiger_monopartie:
        for geometrie in geometries_apres:
            if compter_parties_polygonales(geometrie) != 1:
                return "Le résultat contiendrait une entité multipartie."

    for index, geometrie_a in enumerate(geometries_apres):
        for geometrie_b in geometries_apres[index + 1:]:
            if intersection_surfacique(geometrie_a, geometrie_b, tolerance) is not None:
                return "Le résultat créerait un recouvrement entre polygones."

    try:
        reunion = nettoyer_geometrie_base(QgsGeometry.unaryUnion(geometries_apres))
        if reunion is None:
            return "Le résultat géométrique est vide."

        manque = geometrie_avant.difference(reunion)
        surplus = reunion.difference(geometrie_avant)

        if manque is not None and not manque.isEmpty() and manque.area() > tolerance:
            return "Le résultat laisserait un trou non couvert."
        if surplus is not None and not surplus.isEmpty() and surplus.area() > tolerance:
            return "Le résultat créerait une surface en dehors de la couverture initiale."
    except (TypeError, RuntimeError):
        return "Le contrôle de continuité de la couverture a échoué."

    return None


class OutilDessinNouveauPolygone(QgsMapToolCapture):
    """Capture le contour du nouveau polygone avec l'accrochage QGIS."""

    def __init__(self, plugin):
        super().__init__(
            plugin.iface.mapCanvas(),
            plugin.iface.cadDockWidget(),
            QgsMapToolCapture.CapturePolygon,
        )
        self.plugin = plugin

    def polygonCaptured(self, polygon):
        if polygon is None:
            return
        try:
            geometrie = QgsGeometry(polygon.clone())
        except (TypeError, RuntimeError, AttributeError):
            self.plugin._avertir("Le polygone dessiné n'a pas pu être lu.")
            return
        self.plugin.traiter_zone_dessinee(geometrie)


class CreerPolygonePlugin:
    """Retire une surface à la couverture existante puis crée une nouvelle entité."""

    NOM_OUTIL = "Créer un nouveau polygone BD Forêt"

    def __init__(self, iface, manager=None):
        self.iface = iface
        self.manager = manager
        self.canvas = iface.mapCanvas()
        self.action = None
        self.actif = False
        self.couche = None
        self.outil_dessin = None
        self.surbrillance = None
        self.traitement_en_cours = False
        self._changement_outil = False
        self._attente_edition = AttenteDebutEdition(self._edition_demarree)
        self._surveillance = SurveillanceCoucheActive(self._desactiver)

    # ------------------------------------------------------------------
    # Chargement / activation
    # ------------------------------------------------------------------

    def initGui(self):
        chemin_icone = os.path.join(os.path.dirname(__file__), "icon_creer_polygone.svg")
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
        # Cycle d'activation standard, identique dans les 5 outils d'édition
        # (Créer, Séparer, Fusionner, Remodeler, Reporter depuis BDFv2) : la
        # logique commune (trouver la couche, vérifier l'édition, attendre si
        # besoin) vit dans commun_edition.py, pas ici.
        couche, editable = obtenir_couche_editable(
            self.iface, self.NOM_OUTIL, manager=self.manager, outil=self
        )
        if couche is None:
            return False
        self.couche = couche
        if not editable:
            # La couche existe mais n'est pas encore en édition : le bouton
            # reste coché, AttenteDebutEdition prendra le relais dès que
            # l'utilisateur active l'édition (voir _edition_demarree).
            self.actif = False
            self._attente_edition.attendre(couche)
            return True

        self._attente_edition.annuler()
        self.actif = True
        self._surveillance.surveiller_couche(couche)
        self._activer_outil_dessin()
        return True

    def _edition_demarree(self, couche):
        """Termine l'activation si le bouton est toujours coché."""
        if self.action is None or not self.action.isChecked():
            return
        if self.couche is not couche:
            return
        if not self._activer():
            definir_action_cochee(self.action, False)

    def _activer_outil_dessin(self):
        if not self.actif or self.couche is None or not self.couche.isEditable():
            return
        if self.outil_dessin is None:
            self.outil_dessin = OutilDessinNouveauPolygone(self)
        self._changement_outil = True
        try:
            self.canvas.setMapTool(self.outil_dessin)
        finally:
            self._changement_outil = False

    def _desactiver(self):
        self._attente_edition.annuler()
        self._surveillance.oublier_couche()
        self.actif = False
        self.couche = None
        if self.outil_dessin is not None:
            try:
                self.outil_dessin.stopCapturing()
            except (RuntimeError, AttributeError):
                pass
        self.outil_dessin = None
        definir_action_cochee(self.action, False)

    def desactiver_pour_autre_outil(self):
        self._desactiver()

    def _outil_carte_change(self, nouvel_outil, ancien_outil=None):
        """QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive."""
        if self._changement_outil or not self.actif:
            return
        if nouvel_outil is not self.outil_dessin:
            self._desactiver()

    # ------------------------------------------------------------------
    # Création
    # ------------------------------------------------------------------

    @sans_reentrance
    def traiter_zone_dessinee(self, geometrie_dessinee):
        """Prépare, applique puis renseigne le nouveau polygone."""
        if not self.actif:
            return

        historique = getattr(self.manager, "historique", None) if self.manager is not None else None
        contexte_formulaire = []
        gels_fiche = []
        fid_nouvelle_entite = None
        try:
            preparation = self._preparer_creation(geometrie_dessinee)
            if preparation is None:
                return

            # Un polygone source peut être entièrement absorbé par la zone
            # dessinée (preparation["suppressions"]) : si sa fiche est ouverte,
            # on mémorise sa position et on s'en écarte avant la suppression,
            # pour rouvrir ensuite sur le bon voisin plutôt que de perdre la
            # navigation (sinon QGIS revient par défaut en haut de la table).
            if historique is not None and preparation["suppressions"]:
                try:
                    contexte_formulaire = historique.capturer_contexte_visuel_couche(
                        self.couche, preparation["suppressions"]
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    contexte_formulaire = []
                try:
                    historique.deplacer_fiche_avant_suppression(
                        self.couche, contexte_formulaire
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
                try:
                    gels_fiche = historique.geler_fiche_si_fid_supprime(
                        self.couche, preparation["suppressions"]
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    gels_fiche = []

            nouvelle_entite = self._appliquer_creation(preparation)
            fid_nouvelle_entite = int(nouvelle_entite.id())
            self._ouvrir_formulaire(fid_nouvelle_entite)
        except Exception as erreur:
            self.iface.messageBar().pushCritical(
                self.NOM_OUTIL,
                f"La création du polygone a échoué : {erreur}",
            )
        finally:
            self.surbrillance = remplacer_surbrillance_polygone(
                self.canvas, self.surbrillance, None, self.couche
            )
            if self.actif and self.couche is not None and self.couche.isEditable():
                self._activer_outil_dessin()
            try:
                if self.couche is not None:
                    self.iface.setActiveLayer(self.couche)
                self.canvas.setFocus()
            except (AttributeError, RuntimeError):
                pass

            if historique is not None and gels_fiche:
                try:
                    historique.liberer_gel_fiche(gels_fiche)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            if historique is not None and contexte_formulaire:
                try:
                    historique.restaurer_contexte_visuel_couche(
                        self.couche, contexte_formulaire, fid_remplacement=fid_nouvelle_entite,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

    def _preparer_creation(self, geometrie_dessinee):
        """Calcule les géométries à appliquer sans modifier la couche."""
        couche_emprise = trouver_couche_emprise()
        if couche_emprise is not None:
            masque_local = construire_geometrie_emprise_locale(
                couche_emprise, geometrie_dessinee.boundingBox(), self.couche.crs()
            )
            if masque_local is None or masque_local.isEmpty():
                self._avertir("La zone dessinée est en dehors de l'emprise du masque forêt.")
                return None
            geometrie_dessinee = nettoyer_geometrie_base(
                geometrie_dessinee.intersection(masque_local)
            )
            if geometrie_dessinee is None or geometrie_dessinee.isEmpty():
                self._avertir("La zone dessinée ne contient aucune surface dans l'emprise.")
                return None

        sources = trouver_entites_intersectees(self.couche, geometrie_dessinee)
        if not sources:
            self._avertir("Le polygone dessiné ne recoupe aucune entité BD Forêt.")
            return None

        geometries_sources = [QgsGeometry(entite.geometry()) for entite in sources]
        couverture_avant = nettoyer_geometrie_base(
            QgsGeometry.unaryUnion(geometries_sources)
        )
        if couverture_avant is None:
            self._avertir("Les polygones d'origine ne forment pas une géométrie valide.")
            return None

        nouvelle_geometrie = nettoyer_geometrie_base(
            geometrie_dessinee.intersection(couverture_avant)
        )
        if nouvelle_geometrie is None:
            self._avertir("La zone dessinée ne produit aucun nouveau polygone.")
            return None

        modifications = []
        suppressions = []
        restes = []

        # Chaque polygone source perd la surface reprise par la nouvelle
        # entité. S'il ne reste rien après la découpe, le polygone source est
        # entièrement absorbé et doit être supprimé plutôt que modifié.
        for entite in sources:
            reste = entite.geometry().difference(nouvelle_geometrie)
            if reste is None or reste.isEmpty():
                suppressions.append(int(entite.id()))
                continue

            reste = nettoyer_geometrie_base(reste)
            if reste is None:
                self._avertir(
                    f"Le polygone {entite.id()} deviendrait invalide après la découpe."
                )
                return None
            modifications.append((int(entite.id()), reste))
            restes.append(reste)

        probleme = _verifier_partition(
            couverture_avant,
            [nouvelle_geometrie] + restes,
            exiger_monopartie=False,
        )
        if probleme:
            self._avertir(probleme)
            return None

        # Ni bloquant ni corrigé : juste un avertissement si le résultat contient
        # une entité multipartie (le nouveau polygone ou un reste de découpe).
        if any(
            compter_parties_polygonales(geometrie) != 1
            for geometrie in [nouvelle_geometrie] + restes
        ):
            self._avertir(
                "Le résultat produit une entité composée de plusieurs parties."
            )

        # Contrairement à Diviser/Fusionner, un nouveau polygone ne doit hériter
        # d'aucun attribut métier du polygone source (essence, type, etc.) : on
        # repart d'une liste vide, à l'exception de classement (conservé pour
        # que la nouvelle entité reste proche de son parent dans la liste) et
        # de millesime (l'année de la prise de vue ne change pas quand on
        # découpe un polygone existant). id_foret
        # et fid restent générés par creer_entite_nouvelle()/le fournisseur,
        # jamais copiés.
        champs = self.couche.fields()
        attributs_reference = [None] * champs.count()
        for nom_champ_herite in ("classement", "millesime"):
            index = champs.indexOf(nom_champ_herite)
            if index >= 0:
                attributs_reference[index] = sources[0].attributes()[index]

        return {
            "nouvelle_geometrie": nouvelle_geometrie,
            "modifications": modifications,
            "suppressions": suppressions,
            "attributs_reference": attributs_reference,
            "geometrie_zone": couverture_avant,
        }

    @vue_stable_pendant_modification
    def _appliquer_creation(self, preparation):
        """Applique géométries et surfaces, sans encore refermer la commande.

        La commande reste volontairement ouverte : elle n'est refermée qu'après
        le formulaire (cf. ``_ouvrir_formulaire``), pour que la géométrie créée
        et l'attribut saisi dans le formulaire ne fassent qu'un seul Ctrl+Z.
        """
        nouvelle_entite = creer_entite_nouvelle(
            self.couche,
            preparation["nouvelle_geometrie"],
            preparation["attributs_reference"],
        )

        commande_ouverte = False
        index_surface = self.couche.fields().indexOf("surface")

        try:
            self.couche.beginEditCommand(self.NOM_OUTIL)
            commande_ouverte = True

            for fid, geometrie in preparation["modifications"]:
                exiger_fid_valide(self.couche, fid, "modifier la géométrie")
                if not self.couche.changeGeometry(fid, geometrie):
                    raise RuntimeError(f"échec de la modification du polygone {fid}")
                if index_surface >= 0:
                    surface = surface_ha(geometrie)
                    if not self.couche.changeAttributeValue(fid, index_surface, surface):
                        raise RuntimeError(
                            f"la surface du polygone {fid} n'a pas pu être recalculée"
                        )

            for fid in preparation["suppressions"]:
                exiger_fid_valide(self.couche, fid, "supprimer l'entité")
                if not self.couche.deleteFeature(fid):
                    raise RuntimeError(f"échec de la suppression du polygone {fid}")

            if index_surface >= 0:
                nouvelle_entite[index_surface] = surface_ha(preparation["nouvelle_geometrie"])
            if not self.couche.addFeature(nouvelle_entite):
                raise RuntimeError("la nouvelle entité n'a pas pu être créée")

            synchroniser_zone_outil(
                self.manager, self.iface, self.couche, preparation["geometrie_zone"], self.NOM_OUTIL
            )

            self.couche.triggerRepaint(True)
            self.canvas.refresh()
            return nouvelle_entite
        except Exception:
            if commande_ouverte:
                try:
                    self.couche.destroyEditCommand()
                except (RuntimeError, AttributeError):
                    pass
            raise

    def _ouvrir_formulaire(self, fid):
        """Ouvre le formulaire dans la commande encore ouverte de _appliquer_creation.

        La commande n'est refermée (ou détruite) qu'ici, une fois le formulaire
        validé ou annulé : géométrie et attribut saisi ne forment ainsi qu'un
        seul Ctrl+Z, comme le ferait QGIS nativement.
        """
        try:
            entite = recuperer_entite(self.couche, fid)
            if entite is None:
                raise RuntimeError("la nouvelle entité est introuvable")

            self.surbrillance = remplacer_surbrillance_polygone(
                self.canvas, self.surbrillance, entite.geometry(), self.couche
            )
            if self.iface.openFeatureForm(self.couche, entite, False, True):
                self.couche.endEditCommand()
            else:
                self.couche.destroyEditCommand()
                self._avertir("La création du polygone a été annulée.")
        except Exception:
            try:
                self.couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
            raise

    def _avertir(self, message):
        avertir_message_bar(self.iface, self.NOM_OUTIL, message)
