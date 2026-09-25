# -*- coding: utf-8 -*-
"""Fusionner plusieurs polygones BD Forêt en une seule entité.

Les polygones sont choisis directement sur la carte (surbrillance jaune). La
fusion géométrique et l'écriture en couche passent par le moteur natif QGIS
(unaryUnion puis QgsVectorLayerEditUtils.mergeFeatures).
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QVBoxLayout,
)
from qgis.core import QgsGeometry, QgsVectorLayerEditUtils
from qgis.gui import QgsMapToolIdentify

from .commun_affichage import (
    creer_surbrillance_polygone,
    definir_action_cochee,
    remplacer_surbrillance_polygone,
)
from .commun_couches import (
    couche_est_disponible,
    trouver_couche_travail,
    valider_couche_modifiable,
)
from .commun_edition import (
    AttenteDebutEdition,
    SurveillanceCoucheActive,
    avertir_message_bar,
    basculer_cible_surbrillance,
    basculer_outil_geometrique,
    creer_action_outil,
    detruire_action_outil,
    effacer_cibles_surbrillance,
    exiger_fid_valide,
    indices_fid,
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
from .commun_topologie import (
    nettoyer_geometrie_base,
    preparer_fusion_protegee,
)


# Déplacées depuis commun_edition.py (audit de placement avant transmission
# du code) : spécifiques à la fusion, n'étaient utilisées que par cet outil.
def _securiser_attributs_pour_fid(couche, fid_cible, attributs):
    """Retourne une copie des attributs sans jamais changer une clé primaire.

    Les API de fusion QGIS attendent une liste alignée sur tous les champs.
    On conserve donc les positions des champs PK, mais on y remet toujours la
    valeur actuellement portée par l'entité cible. Ainsi une fusion qui prend
    ses attributs métier sur une autre entité ne peut jamais tenter de copier
    son ``fid``/PK sur l'entité survivante.
    """
    valeurs = list(attributs)
    cible = recuperer_entite(couche, fid_cible)
    if cible is None:
        raise RuntimeError("l'entité cible est introuvable pour sécuriser sa clé primaire")

    for index in indices_fid(couche):
        if 0 <= index < len(valeurs):
            try:
                valeurs[index] = cible[index]
            except (IndexError, KeyError):
                pass
    return valeurs


def _changements_attributaires_sans_pk(couche, attributs):
    """Construit un dictionnaire index/valeur excluant toutes les clés primaires."""
    exclus = set(indices_fid(couche))
    return {
        index: valeur
        for index, valeur in enumerate(list(attributs))
        if index < len(couche.fields()) and index not in exclus
    }


class EchecFusionNative(RuntimeError):
    """Échec attendu du moteur de fusion QGIS, avec un message déjà prêt pour l'utilisateur."""


class _OutilSelectionFusion(QgsMapToolIdentify):
    """Sélectionne les polygones par clic sans utiliser la sélection attributaire."""

    def __init__(self, canvas, plugin):
        super().__init__(canvas)
        self.plugin = plugin
        self.setCursor(Qt.ArrowCursor)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.plugin.fusionner_selection()
        elif event.button() == Qt.LeftButton:
            self.plugin.basculer_entite_cliquee(
                event.x(),
                event.y(),
                bool(event.modifiers() & Qt.ControlModifier),
            )


class FusionnerBdForetPlugin:
    """Fusionne plusieurs polygones dans une seule entité de référence."""

    NOM_OUTIL = "Fusionner plusieurs polygones BD Forêt"

    def __init__(self, iface, manager=None):
        self.iface = iface
        self.manager = manager
        self.canvas = iface.mapCanvas()
        self.action = None
        self.actif = False
        self.couche = None
        self.outil_carte = None
        self.fids = []
        self.surbrillances = {}
        self.surbrillance_resultat = None
        self.traitement_en_cours = False
        self._ouvrir_formulaire_apres_fusion = True
        self._finaliser_au_deuxieme_clic = False
        self._callback_fin_fusion = None
        self._changement_outil = False
        self._attente_edition = AttenteDebutEdition(self._edition_demarree)
        self._surveillance = SurveillanceCoucheActive(self._desactiver)

    # ------------------------------------------------------------------
    # Chargement / activation
    # ------------------------------------------------------------------

    def initGui(self):
        chemin_icone = os.path.join(os.path.dirname(__file__), "icon_fusionner.svg")
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
        self.outil_carte = _OutilSelectionFusion(self.canvas, self)
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
        self._ouvrir_formulaire_apres_fusion = True
        self._finaliser_au_deuxieme_clic = False
        self._callback_fin_fusion = None
        self.effacer_selection_visuelle(rafraichir=False)
        self.surbrillance_resultat = remplacer_surbrillance_polygone(
            self.canvas, self.surbrillance_resultat, None, self.couche
        )
        self.couche = None
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
    # Sélection des cibles
    # ------------------------------------------------------------------

    def basculer_entite_cliquee(self, x, y, ctrl_appuye):
        fid = basculer_cible_surbrillance(self, x, y, ctrl_appuye, self.outil_carte)

        # Dans le mode « Fusionner avec… » du vérificateur, le premier
        # polygone est déjà présélectionné. Le clic sur le second suffit donc
        # à lancer la fusion, sans clic droit supplémentaire.
        if fid is not None and self._finaliser_au_deuxieme_clic and len(self.fids) >= 2:
            self.fusionner_selection()

    def _retirer_fid(self, fid):
        retirer_cible_surbrillance(self, fid)

    def effacer_selection_visuelle(self, rafraichir=True):
        effacer_cibles_surbrillance(self, rafraichir)

    # ------------------------------------------------------------------
    # Fusion
    # ------------------------------------------------------------------

    def activer_avec_fids(
        self, fids, ouvrir_formulaire_apres=True, finaliser_au_deuxieme_clic=False,
        callback_fin=None,
    ):
        """Active l'outil Fusionner en présélectionnant des entités existantes.

        Cette entrée publique permet aux autres outils du plugin (notamment le
        vérificateur) de déléguer une fusion à l'outil Fusionner lui-même, sans
        recopier sa logique géométrique ni sa fenêtre de choix des attributs.
        """
        try:
            fids = list(dict.fromkeys(int(fid) for fid in fids))
        except (TypeError, ValueError):
            return False
        if not fids:
            return False

        # On repart d'une sélection propre. Si l'outil n'est pas encore actif,
        # son activation retrouve la couche BD Forêt et la passe en édition.
        if self.actif:
            self.effacer_selection_visuelle(rafraichir=False)
        else:
            if not self._activer():
                return False
            if not self.actif:
                # Couche trouvée mais pas encore en édition : l'activation
                # différée ne peut pas présélectionner ces FID immédiatement.
                self._desactiver()
                return False
            definir_action_cochee(self.action, True)

        if self.couche is None:
            return False
        entites = recuperer_entites(self.couche, fids)
        if len(entites) != len(fids):
            self._avertir("Une ou plusieurs entités à fusionner n'existent plus.")
            self.effacer_selection_visuelle()
            return False

        for fid in fids:
            entite = entites.get(fid)
            if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
                continue
            self.fids.append(fid)
            self.surbrillances[fid] = creer_surbrillance_polygone(
                self.canvas, entite.geometry(), self.couche
            )

        self._ouvrir_formulaire_apres_fusion = bool(ouvrir_formulaire_apres)
        self._finaliser_au_deuxieme_clic = bool(finaliser_au_deuxieme_clic)
        self._callback_fin_fusion = callback_fin if callable(callback_fin) else None

        try:
            self.iface.setActiveLayer(self.couche)
            if self.canvas.mapTool() is not self.outil_carte:
                self.canvas.setMapTool(self.outil_carte)
            self.canvas.refresh()
        except RuntimeError:
            pass
        return bool(self.fids)

    @sans_reentrance
    def fusionner_selection(self):
        """Prépare, applique puis renseigne le polygone fusionné."""
        if self.couche is None or len(self.fids) < 2:
            self._avertir("Sélectionnez au moins deux polygones à fusionner.")
            return False

        fids_operation = list(dict.fromkeys(int(fid) for fid in self.fids))
        callback = self._callback_fin_fusion
        mode_delegue = self._finaliser_au_deuxieme_clic
        historique = getattr(self.manager, "historique", None) if self.manager is not None else None
        contexte_formulaire = []
        gels_fiche = []
        fid_reference = None
        succes = False
        try:
            preparation = self._preparer_fusion()
            if preparation is None:
                return False

            fid_source_attributs = self._choisir_fid_reference(
                preparation["fids"], preparation["entites"]
            )
            if fid_source_attributs is None:
                return False
            fid_reference = self._choisir_fid_technique_stable(
                preparation["fids"], fid_source_attributs
            )
            autres_fids = [fid for fid in preparation["fids"] if fid != fid_reference]

            # La fiche attributaire est indépendante du FID conservé pour la
            # fusion. On mémorise sa position avant de supprimer les autres
            # entités, pour la restaurer sur la bonne fiche ensuite.
            if historique is not None:
                try:
                    contexte_formulaire = historique.capturer_contexte_visuel_couche(
                        self.couche, autres_fids
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
                        self.couche, autres_fids
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    gels_fiche = []

            self._appliquer_fusion(
                fid_reference,
                preparation["geometrie_fusionnee"],
                autres_fids,
                preparation["geometrie_zone"],
                fid_source_attributs=fid_source_attributs,
                fid_classement=self._fid_fiche_active(preparation["fids"], contexte_formulaire),
            )
            self.effacer_selection_visuelle(rafraichir=False)
            if self._ouvrir_formulaire_apres_fusion:
                succes = self._ouvrir_formulaire(fid_reference)
            else:
                succes = True
        except EchecFusionNative as erreur:
            self._avertir(str(erreur))
        except Exception as erreur:
            self.iface.messageBar().pushCritical(
                self.NOM_OUTIL, f"La fusion a échoué : {erreur}"
            )
        finally:
            self.surbrillance_resultat = remplacer_surbrillance_polygone(
                self.canvas, self.surbrillance_resultat, None, self.couche
            )
            self.effacer_selection_visuelle(rafraichir=False)
            try:
                if couche_est_disponible(self.couche):
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
                        self.couche, contexte_formulaire, fid_remplacement=fid_reference,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

            # En mode délégué (panneau Vérification), l'outil se désactive dans
            # tous les cas dès que l'action se termine — y compris en échec —
            # plutôt que de laisser le bouton Fusionner enfoncé et l'outil actif
            # sur la carte sans raison pour l'utilisateur.
            if mode_delegue:
                self._desactiver()
                if succes and callback is not None:
                    try:
                        callback(fids_operation, fid_reference)
                    except (AttributeError, RuntimeError, TypeError):
                        pass

        return succes

    def fusionner_fids_direct(
        self, fids, fid_reference=None, ouvrir_formulaire=False, nom_commande=None,
        nettoyer_parasites=False,
    ):
        """Fusionne des FID via exactement le même moteur que le bouton Fusionner.

        Entrée destinée aux corrections automatiques du panneau Vérification.
        Elle ne crée pas de sélection QGIS ni de boîte de dialogue, et évite
        toute seconde implémentation de la topologie, du clip à l'emprise, des
        surfaces, des alertes et de l'undo.

        ``nettoyer_parasites`` est conservé pour compatibilité avec les appels
        existants, mais n'a plus d'effet : le nettoyage anti-parasites est
        désormais systématique dans ``_preparer_fusion``.
        """
        if self.manager is not None:
            self.manager.desactiver_autres_outils_geometriques(self)

        couche = trouver_couche_travail(self.iface)
        if couche is not None and not couche.isEditable():
            try:
                couche.startEditing()
            except RuntimeError:
                pass
        probleme = valider_couche_modifiable(couche)
        if probleme:
            self._avertir(probleme)
            return False, None

        ancien_couche = self.couche
        self.couche = couche
        historique = getattr(self.manager, "historique", None) if self.manager is not None else None
        contexte_formulaire = []
        gels_fiche = []
        fid_ref = None
        try:
            preparation = self._preparer_fusion(fids=fids)
            if preparation is None:
                return False, None

            fid_ref = int(fid_reference) if fid_reference is not None else preparation["fids"][0]
            if fid_ref not in preparation["fids"]:
                self._avertir("Le polygone de référence est introuvable.")
                return False, None
            autres_fids = [fid for fid in preparation["fids"] if fid != fid_ref]

            if historique is not None:
                try:
                    contexte_formulaire = historique.capturer_contexte_visuel_couche(
                        couche, autres_fids
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    contexte_formulaire = []
                try:
                    historique.deplacer_fiche_avant_suppression(couche, contexte_formulaire)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
                try:
                    gels_fiche = historique.geler_fiche_si_fid_supprime(couche, autres_fids)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    gels_fiche = []

            self._appliquer_fusion(
                fid_ref,
                preparation["geometrie_fusionnee"],
                autres_fids,
                preparation["geometrie_zone"],
                fid_source_attributs=fid_ref,
                nom_commande=nom_commande or self.NOM_OUTIL,
                fid_classement=self._fid_fiche_active(preparation["fids"], contexte_formulaire),
            )
            if ouvrir_formulaire and not self._ouvrir_formulaire(fid_ref):
                return False, fid_ref
            return True, fid_ref
        finally:
            if historique is not None and gels_fiche:
                try:
                    historique.liberer_gel_fiche(gels_fiche)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            if historique is not None and contexte_formulaire:
                try:
                    historique.restaurer_contexte_visuel_couche(
                        couche, contexte_formulaire, fid_remplacement=fid_ref,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
            if not self.actif:
                self.couche = ancien_couche

    def _preparer_fusion(self, fids=None):
        """Calcule la géométrie fusionnée sans modifier la couche."""
        if fids is None:
            fids = self.fids
        fids = list(dict.fromkeys(int(fid) for fid in fids))
        entites = recuperer_entites(self.couche, fids)
        if len(entites) != len(fids):
            self._avertir("Une ou plusieurs entités n'existent plus.")
            return None

        geometries = []
        for fid in fids:
            geometrie = nettoyer_geometrie_base(entites[fid].geometry())
            if geometrie is None:
                self._avertir("Une des entités possède une géométrie invalide.")
                return None
            geometries.append(geometrie)

        try:
            geometrie_zone = QgsGeometry.unaryUnion([QgsGeometry(g) for g in geometries])
        except (AttributeError, TypeError, RuntimeError):
            geometrie_zone = QgsGeometry(geometries[0])

        # Même chaîne géométrique que la fusion de parties multiparties
        # (Vérification) : alignement des sommets, union, anti-parasites,
        # retrait de tout recouvrement avec un autre polygone de la couche,
        # et retrait de toute zone hors de l'emprise.
        geometrie_fusionnee = preparer_fusion_protegee(self.couche, geometries, fids)
        if geometrie_fusionnee is None or geometrie_fusionnee.isEmpty():
            self._avertir(
                "La fusion géométrique a échoué (résultat vide, ou entièrement hors "
                "de l'emprise ou recouvert par un autre polygone)."
            )
            return None

        # intersection() (découpe à l'emprise) laisse souvent des sommets
        # quasi dupliqués (bruit numérique) : on nettoie une dernière fois,
        # sinon ce bruit ressort ensuite dans le correcteur "Géométries
        # parasites".
        geometrie_fusionnee.removeDuplicateNodes()
        geometrie_fusionnee = nettoyer_geometrie_base(geometrie_fusionnee)
        if geometrie_fusionnee is None or geometrie_fusionnee.isEmpty():
            self._avertir("La fusion produirait une géométrie invalide après nettoyage final.")
            return None

        return {
            "fids": fids,
            "entites": entites,
            "geometrie_fusionnee": geometrie_fusionnee,
            "geometrie_zone": geometrie_zone,
        }

    def _choisir_fid_reference(self, fids, entites):
        """Demande explicitement quelle entité fournit les attributs conservés.

        Le choix porte sur les attributs métier (dont ``id_foret``). Le FID
        technique GeoPackage peut être porté par une autre entité stable si le
        donneur choisi est encore temporaire dans le tampon d'édition.
        """
        if not fids:
            return None

        fid_defaut = int(fids[0])
        items = []
        fids_items = []

        for fid in fids:
            entite = entites.get(int(fid))
            if entite is None:
                continue
            items.append(self._libelle_choix_attributs(entite))
            fids_items.append(int(fid))

        if not items:
            return None

        index_defaut = 0
        for index, fid_item in enumerate(fids_items):
            if int(fid_item) == fid_defaut:
                index_defaut = index
                break

        dialogue = QDialog(self.iface.mainWindow())
        dialogue.setWindowTitle("Fusionner les entités")
        mise_en_page = QVBoxLayout(dialogue)
        mise_en_page.addWidget(QLabel("Conserver les attributs de quelle entité ?"))

        liste = QListWidget(dialogue)
        liste.addItems(items)
        liste.setCurrentRow(index_defaut)
        mise_en_page.addWidget(liste)

        boutons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        boutons.accepted.connect(dialogue.accept)
        boutons.rejected.connect(dialogue.reject)
        mise_en_page.addWidget(boutons)

        # La liste doit rester assez large pour comparer correctement les
        # essences et les surfaces, toutes les options visibles d'un coup.
        dialogue.resize(760, 120 + 24 * len(items))

        if not dialogue.exec():
            return None

        index_choisi = liste.currentRow()
        if index_choisi < 0 or index_choisi >= len(fids_items):
            return None
        return fids_items[index_choisi]

    def _libelle_choix_attributs(self, entite):
        """Affiche en priorité la nouvelle essence et la surface en hectares."""
        champs = self.couche.fields()
        noms = {champ.name().lower(): champ.name() for champ in champs}

        def valeur_champ(nom, valeur_defaut="Non renseigné"):
            nom_reel = noms.get(nom.lower())
            if not nom_reel:
                return valeur_defaut
            try:
                valeur = entite[nom_reel]
            except (KeyError, RuntimeError):
                return valeur_defaut
            if valeur is None or str(valeur).strip() == "":
                return valeur_defaut
            return str(valeur)

        nouvelle_essence = valeur_champ("nouvelle_essence")
        valeur_surface = surface_ha(entite.geometry()) if entite.hasGeometry() else None
        surface = f"{valeur_surface:.2f} ha" if valeur_surface is not None else "Surface inconnue"

        return f"{nouvelle_essence} — {surface}"

    @staticmethod
    def _choisir_fid_technique_stable(fids, fid_source_attributs):
        """Choisit le FID technique survivant sans modifier le choix métier.

        Une entité ajoutée au tampon possède généralement un FID négatif.
        Lorsqu'une fusion mélange entités enregistrées et temporaires, garder
        un FID positif comme support technique évite de propager inutilement
        un identifiant temporaire dans les opérations suivantes.
        """
        fids = [int(fid) for fid in fids]
        fid_source_attributs = int(fid_source_attributs)
        if fid_source_attributs >= 0:
            return fid_source_attributs
        for fid in fids:
            if fid >= 0:
                return fid
        return fid_source_attributs

    @staticmethod
    def _fid_fiche_active(fids_fusionnes, contexte_formulaire):
        """Retourne le FID affiché dans une fiche ouverte avant la fusion, s'il
        fait partie des polygones fusionnés, sinon ``None``."""
        fids_fusionnes = {int(fid) for fid in fids_fusionnes}
        for contexte in contexte_formulaire or []:
            fid = contexte.get("fid")
            if fid is not None and int(fid) in fids_fusionnes:
                return int(fid)
        return None

    @vue_stable_pendant_modification
    def _appliquer_fusion(
        self, fid_reference, geometrie, autres_fids, geometrie_zone, fid_source_attributs,
        nom_commande=None, fid_classement=None,
    ):
        """Fusionne via QGIS puis applique les traitements métier BD Forêt."""
        nom_commande = nom_commande or self.NOM_OUTIL
        commande_ouverte = False

        entite_reference = recuperer_entite(self.couche, int(fid_source_attributs))
        if entite_reference is None:
            raise RuntimeError("l'entité de référence est introuvable")
        attributs = list(entite_reference.attributes())
        index_surface = self.couche.fields().indexOf("surface")
        if index_surface >= 0 and index_surface < len(attributs):
            surface = surface_ha(geometrie)
            if surface is not None:
                attributs[index_surface] = surface

        # classement reste indépendant du choix des autres attributs : on veut
        # que l'entité fusionnée reste proche de la fiche que l'utilisateur
        # regardait avant la fusion, même si les autres attributs viennent
        # d'un polygone différent.
        if fid_classement is not None:
            index_classement = self.couche.fields().indexOf("classement")
            if index_classement >= 0 and index_classement < len(attributs):
                entite_classement = recuperer_entite(self.couche, int(fid_classement))
                if entite_classement is not None:
                    try:
                        attributs[index_classement] = entite_classement["classement"]
                    except (KeyError, RuntimeError):
                        pass

        # Sécurité GeoPackage : les attributs métier peuvent venir d'une autre
        # entité que celle dont on conserve techniquement le FID.
        attributs = _securiser_attributs_pour_fid(self.couche, int(fid_reference), attributs)

        try:
            exiger_fid_valide(self.couche, fid_reference, "fusionner l'entité de référence")
            self.couche.beginEditCommand(nom_commande)
            commande_ouverte = True

            succes_natif, message_natif = self._fusionner_avec_moteur_qgis(
                fid_reference, autres_fids, attributs, geometrie
            )

            if succes_natif is None:
                # Compatibilité QGIS 3.28/3.29 : le plugin reste utilisable
                # même si l'API native introduite en 3.30 n'est pas disponible.
                if not self.couche.changeGeometry(fid_reference, geometrie):
                    raise RuntimeError("la géométrie de référence n'a pas pu être modifiée")
                if autres_fids and not self.couche.deleteFeatures(autres_fids):
                    raise RuntimeError("les autres entités n'ont pas pu être supprimées")
                changements = _changements_attributaires_sans_pk(self.couche, attributs)
                if changements and not self.couche.changeAttributeValues(
                    int(fid_reference), changements, {}, True
                ):
                    raise RuntimeError("les attributs de référence n'ont pas pu être restaurés")
            elif not succes_natif:
                raise EchecFusionNative(message_natif or "le moteur natif QGIS a refusé la fusion")

            exiger_fid_valide(self.couche, fid_reference, "mettre à jour la fusion")

            if index_surface >= 0:
                surface = surface_ha(geometrie)
                if surface is not None:
                    exiger_fid_valide(self.couche, fid_reference, "recalculer la surface fusionnée")
                    if not self.couche.changeAttributeValue(
                        int(fid_reference), int(index_surface), surface
                    ):
                        raise RuntimeError("la surface de l'entité fusionnée n'a pas pu être recalculée")

            synchroniser_zone_outil(
                self.manager, self.iface, self.couche, geometrie_zone, nom_commande
            )

            self.couche.endEditCommand()
            commande_ouverte = False
            self.couche.triggerRepaint(True)
        except Exception:
            if commande_ouverte:
                try:
                    self.couche.destroyEditCommand()
                except (RuntimeError, AttributeError):
                    pass
            raise

    def _fusionner_avec_moteur_qgis(self, fid_reference, autres_fids, attributs, geometrie):
        """Appelle le moteur natif QGIS de fusion d'entités.

        ``mergeFeatures`` est disponible à partir de QGIS 3.30. La forme
        exacte du paramètre de sortie ``errorMessage`` varie dans les
        bindings SIP ; ce petit adaptateur accepte les deux signatures usuelles.
        """
        utilitaire = QgsVectorLayerEditUtils(self.couche)
        methode = getattr(utilitaire, "mergeFeatures", None)
        if not callable(methode):
            return None, "Moteur mergeFeatures indisponible dans cette version de QGIS"

        ids_a_supprimer = [int(fid) for fid in autres_fids]
        args = (
            int(fid_reference),
            ids_a_supprimer,
            list(attributs),
            QgsGeometry(geometrie),
        )
        try:
            resultat = methode(*args)
        except TypeError:
            try:
                resultat = methode(*args, "")
            except Exception as erreur:
                return False, str(erreur)
        except Exception as erreur:
            return False, str(erreur)

        if isinstance(resultat, tuple):
            succes = bool(resultat[0]) if resultat else False
            message = str(resultat[1]) if len(resultat) > 1 and resultat[1] else ""
            return succes, message
        return bool(resultat), ""

    def _ouvrir_formulaire(self, fid_reference):
        entite = recuperer_entite(self.couche, fid_reference)
        if entite is None:
            raise RuntimeError("l'entité fusionnée est introuvable")
        self.surbrillance_resultat = remplacer_surbrillance_polygone(
            self.canvas, self.surbrillance_resultat, entite.geometry(), self.couche
        )
        return ouvrir_formulaire_ou_annuler(self.iface, self.couche, self.canvas, entite, self.NOM_OUTIL)

    def _avertir(self, message):
        avertir_message_bar(self.iface, self.NOM_OUTIL, message)
