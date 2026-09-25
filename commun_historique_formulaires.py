# -*- coding: utf-8 -*-
"""Navigation Précédent/Suivant dans les vues formulaire QGIS."""

import os
import weakref

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer, QSignalBlocker
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QStackedWidget,
    QToolBar,
    QWidget,
)
from qgis.gui import QgsDualView, QgsFeatureListView

from .commun_couches import normaliser_nom
from .commun_protection_vue import ProtectionVueCarte


class HistoriqueFormulaires:
    """Conserve les dix dernières fiches consultées dans chaque vue formulaire."""

    LIMITE_HISTORIQUE = 10
    NOM_ACTION_PRECEDENT = "historique_formulaire_precedent"
    NOM_ACTION_SUIVANT = "historique_formulaire_suivant"
    NOM_ACTION_RECALCULER_ALERTES = "historique_formulaire_recalculer_alertes"

    def __init__(self, iface):
        self.iface = iface
        # Les trois callbacks ci-dessous sont câblés depuis l'extérieur (voir
        # commun_outils.py, definir_recalcul_alertes/etat_formulaire/
        # fid_persistant) plutôt qu'importés directement : ce fichier n'a
        # ainsi besoin de connaître ni CompteurAlertes ni EtatSessionProjet.
        self._callback_recalculer_alertes = None
        self._callback_etat_formulaire = None
        self._callback_fid_persistant = None
        self.plugin_dir = os.path.dirname(__file__)
        self.fenetres = {}

        # Dernière fiche réellement consultée pour chaque couche.
        # Cette mémoire est volontairement limitée au FID : si l'entité a
        # disparu, QGIS garde simplement sa fiche par défaut à la réouverture.
        self._derniere_fiche_par_couche = {}

        self._application = QApplication.instance()
        self._focus_connecte = False
        # Fenêtres déjà identifiées comme non attributaires (gestionnaire
        # d'extensions, options, etc.). Un WeakSet n'empêche pas Qt de les
        # détruire et rend les changements de focus suivants quasi gratuits.
        self._fenetres_ignorees = weakref.WeakSet()
        self._fenetres_en_attente = weakref.WeakSet()

    def initGui(self):
        """Détecte les vues formulaire sans balayage périodique.

        On conserve la détection légère par changement de focus, mais on effectue
        aussi deux contrôles ponctuels au chargement. C'est important lorsque le
        plugin est rechargé alors qu'une table attributaire est déjà ouverte :
        aucun changement de focus n'est alors forcément émis par Qt.
        """
        application = self._application or QApplication.instance()
        self._application = application
        if application is not None and not self._focus_connecte:
            try:
                application.focusChanged.connect(self._focus_change)
                self._focus_connecte = True
            except (TypeError, RuntimeError, AttributeError):
                self._focus_connecte = False

        # Même principe que l'ancienne version qui affichait correctement les
        # boutons, mais sans remettre son timer de balayage toutes les 700 ms.
        QTimer.singleShot(250, self.detecter_tables)
        QTimer.singleShot(1000, self.detecter_tables)

    def unload(self):
        application = self._application
        if application is not None and self._focus_connecte:
            try:
                application.focusChanged.disconnect(self._focus_change)
            except (TypeError, RuntimeError, AttributeError):
                pass
        self._focus_connecte = False
        self._fenetres_ignorees.clear()
        self._fenetres_en_attente.clear()
        self._derniere_fiche_par_couche.clear()
        for fenetre in list(self.fenetres):
            self.deconnecter_fenetre(fenetre)
        self.fenetres.clear()

    # ------------------------------------------------------------------
    # Détection des vues formulaire
    # ------------------------------------------------------------------

    def _focus_change(self, _ancien, nouveau):
        """Inspecte une nouvelle fenêtre seulement lorsqu'elle reçoit le focus.

        On utilise volontairement le même marqueur que la version historique qui
        fonctionnait dans QGIS : la présence du widget ``mMainView``. Le filtre
        ajouté ensuite sur le nom de classe Qt était trop strict et pouvait écarter
        une vraie table attributaire selon la version/configuration de QGIS.
        """
        if nouveau is None:
            return
        try:
            fenetre = nouveau.window()
            if not isinstance(fenetre, QDialog) or not fenetre.isVisible():
                return
            if fenetre in self.fenetres or fenetre in self._fenetres_ignorees:
                return
            if fenetre.findChild(QStackedWidget, "mMainView") is not None:
                self.connecter_fenetre(fenetre)
            elif fenetre not in self._fenetres_en_attente:
                # Au tout premier focus, QGIS peut encore être en train de finir
                # de construire les enfants de la table. On réessaie une seule
                # fois un peu plus tard avant de classer le dialogue comme ignoré.
                try:
                    self._fenetres_en_attente.add(fenetre)
                    reference = weakref.ref(fenetre)
                    QTimer.singleShot(200, lambda ref=reference: self._verifier_fenetre_differee(ref))
                except (TypeError, RuntimeError):
                    pass
        except (AttributeError, RuntimeError):
            return

    def _verifier_fenetre_differee(self, reference_fenetre):
        """Deuxième et dernier essai pour une fenêtre nouvellement ouverte."""
        try:
            fenetre = reference_fenetre()
        except RuntimeError:
            return
        if fenetre is None:
            return
        try:
            self._fenetres_en_attente.discard(fenetre)
            if fenetre in self.fenetres or not fenetre.isVisible():
                return
            if fenetre.findChild(QStackedWidget, "mMainView") is not None:
                self.connecter_fenetre(fenetre)
            else:
                self._fenetres_ignorees.add(fenetre)
        except (AttributeError, TypeError, RuntimeError):
            return

    def detecter_tables(self):
        """Balayage ponctuel des tables déjà ouvertes.

        Contrairement à l'ancienne implémentation, cette fonction n'est jamais
        exécutée en boucle. Elle reprend toutefois son test fiable sur ``mMainView``
        afin de rester compatible avec les différentes fenêtres de table QGIS.
        """
        visibles = []
        for widget in QApplication.topLevelWidgets():
            try:
                if not isinstance(widget, QDialog) or not widget.isVisible():
                    continue
                if widget in self.fenetres:
                    continue
                if widget.findChild(QStackedWidget, "mMainView") is not None:
                    visibles.append(widget)
                else:
                    try:
                        self._fenetres_ignorees.add(widget)
                    except (TypeError, RuntimeError):
                        pass
            except RuntimeError:
                continue

        for fenetre in visibles:
            if fenetre not in self.fenetres:
                self.connecter_fenetre(fenetre)

        # Ne pas déconnecter une vue simplement parce qu'elle devient invisible.
        # Lors de la fermeture d'un formulaire QGIS, les widgets enfants peuvent être
        # en cours de destruction au moment où ce timer s'exécute. Appeler
        # ``signal.disconnect()`` sur un wrapper SIP dont l'objet C++ est déjà en
        # destruction peut provoquer un crash natif (access violation), impossible à
        # intercepter avec un try/except Python. Les connexions Qt sont donc laissées
        # en place jusqu'au signal ``destroyed`` de la fenêtre, qui retire simplement
        # l'entrée de notre registre.

    def connecter_fenetre(self, fenetre):
        """Prépare le suivi complet d'une fenêtre de table attributaire fraîchement détectée."""
        composants = self._trouver_composants_fenetre(fenetre)
        if composants is None:
            return
        dual_view, feature_list, toolbar = composants

        actions = self._creer_actions(fenetre, toolbar)
        if actions is None:
            return
        action_precedent, action_suivant, action_recalculer, separateur = actions

        # Un dictionnaire d'état par fenêtre (pas d'attribut de classe) : QGIS
        # peut avoir plusieurs tables attributaires ouvertes en même temps,
        # chacune avec son propre historique de navigation.
        self.fenetres[fenetre] = {
            "dual_view": dual_view,
            "feature_list": feature_list,
            "toolbar": toolbar,
            "action_precedent": action_precedent,
            "action_suivant": action_suivant,
            "action_recalculer": action_recalculer,
            "separateur": separateur,
            "historique": [],
            "position": -1,
            "navigation_programmatique": False,
            "slot_changement": None,
            "modele_liste": None,
            "slot_modele_avant_reset": None,
            "slot_modele_apres_reset": None,
            "scroll_avant_reset": None,
            "blocage_fiche_suppression": None,
        }

        def slot_changement(feature, f=fenetre):
            self.fiche_changee(f, feature)

        try:
            feature_list.currentEditSelectionChanged.connect(slot_changement)
            self.fenetres[fenetre]["slot_changement"] = slot_changement
        except (AttributeError, TypeError, RuntimeError):
            self.deconnecter_fenetre(fenetre)
            return

        # QGIS peut réinitialiser le modèle de la liste lors d'un Undo/Redo,
        # d'une fusion ou d'un autre rafraîchissement structurel. Ce reset remet
        # parfois la barre verticale à zéro alors que l'utilisateur n'a demandé
        # aucune navigation. On conserve uniquement cette valeur autour du reset :
        # aucune sélection, aucun FID courant et aucun tri ne sont modifiés.
        try:
            modele_liste = feature_list.model()
        except (AttributeError, RuntimeError):
            modele_liste = None
        if modele_liste is not None:
            reference = weakref.ref(fenetre)

            def slot_avant_reset(ref=reference):
                self._memoriser_scroll_avant_reset(ref)

            def slot_apres_reset(ref=reference):
                self._restaurer_scroll_apres_reset(ref)

            try:
                modele_liste.modelAboutToBeReset.connect(slot_avant_reset)
                modele_liste.modelReset.connect(slot_apres_reset)
                self.fenetres[fenetre]["modele_liste"] = modele_liste
                self.fenetres[fenetre]["slot_modele_avant_reset"] = slot_avant_reset
                self.fenetres[fenetre]["slot_modele_apres_reset"] = slot_apres_reset
            except (AttributeError, TypeError, RuntimeError):
                pass

        action_precedent.triggered.connect(
            lambda _checked=False, f=fenetre: self.revenir_precedent(f)
        )
        action_suivant.triggered.connect(
            lambda _checked=False, f=fenetre: self.aller_suivant(f)
        )
        action_recalculer.triggered.connect(
            lambda _checked=False: self.recalculer_alertes()
        )

        try:
            reference = weakref.ref(fenetre)
            fenetre.destroyed.connect(
                lambda _objet=None, ref=reference: self.fenetre_detruite(ref)
            )
        except (TypeError, RuntimeError):
            pass

        # Une table attributaire fermée puis rouverte est un nouvel objet Qt.
        # QGIS la place généralement sur sa première fiche. Si nous avons déjà
        # vu cette couche pendant la session, restaurer uniquement son dernier
        # FID, via l'API officielle du QgsDualView. Aucun tri, sélection de couche,
        # zoom ou position de défilement n'est modifié.
        self._restaurer_derniere_fiche(fenetre)
        self.enregistrer_fiche_initiale(fenetre)
        self.mettre_a_jour_actions(fenetre)

    def _memoriser_scroll_avant_reset(self, reference_fenetre):
        """Mémorise uniquement le scroll juste avant un reset du modèle QGIS."""
        try:
            fenetre = reference_fenetre()
        except RuntimeError:
            return
        if fenetre is None:
            return
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return
        feature_list = donnees.get("feature_list")
        if not self._objet_qt_valide(feature_list):
            return
        try:
            barre = feature_list.verticalScrollBar()
            donnees["scroll_avant_reset"] = int(barre.value())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            donnees["scroll_avant_reset"] = None

    def _restaurer_scroll_apres_reset(self, reference_fenetre):
        """Restaure le scroll après le reset sans toucher à la fiche courante."""
        try:
            fenetre = reference_fenetre()
        except RuntimeError:
            return
        if fenetre is None:
            return
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return
        valeur = donnees.get("scroll_avant_reset")
        if valeur is None:
            return
        donnees["scroll_avant_reset"] = None
        reference = weakref.ref(fenetre)
        QTimer.singleShot(0, lambda ref=reference, v=int(valeur): self._appliquer_scroll_si_valide(ref, v))

    def _appliquer_scroll_si_valide(self, reference_fenetre, valeur):
        """Applique une restauration différée seulement si la vue existe encore."""
        try:
            fenetre = reference_fenetre()
        except RuntimeError:
            return
        if fenetre is None:
            return
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return
        feature_list = donnees.get("feature_list")
        if not self._objet_qt_valide(feature_list):
            return
        try:
            barre = feature_list.verticalScrollBar()
            cible = max(barre.minimum(), min(int(valeur), barre.maximum()))
            barre.setValue(cible)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _trouver_composants_fenetre(self, fenetre):
        main_view = fenetre.findChild(QStackedWidget, "mMainView")
        if main_view is None:
            return None
        try:
            dual_view = sip.cast(main_view, QgsDualView)
        except Exception:
            return None

        liste_widget = self._trouver_liste_principale(main_view)
        if liste_widget is None:
            return None
        try:
            feature_list = sip.cast(liste_widget, QgsFeatureListView)
        except Exception:
            return None

        toolbar = self._trouver_barre_outils(fenetre)
        return (dual_view, feature_list, toolbar) if toolbar is not None else None

    @staticmethod
    def _trouver_liste_principale(main_view_widget):
        """Écarte les listes appartenant aux sous-relations du formulaire.

        Une table attributaire QGIS peut contenir plusieurs widgets nommés
        "mFeatureListView" : la vraie liste principale, mais aussi une par
        relation enfant affichée dans le formulaire (ex. la liste des alertes
        liées, si le formulaire l'affiche). On ne retient donc que celles
        dont un ancêtre direct est bien ``main_view_widget`` sans passer par
        un widget nommé "QgsDualViewBase" en chemin (signe d'un sous-panneau
        de relation) ; à égalité, la plus grande (probablement la principale).
        """
        try:
            listes = main_view_widget.findChildren(QWidget, "mFeatureListView")
        except RuntimeError:
            return None

        candidates = []
        for liste in listes:
            try:
                if not liste.isVisible():
                    continue
                parent = liste.parentWidget()
                sous_relation = False
                appartient_vue = False
                while parent is not None:
                    if parent.objectName() == "QgsDualViewBase":
                        sous_relation = True
                        break
                    if parent is main_view_widget:
                        appartient_vue = True
                        break
                    parent = parent.parentWidget()
                if appartient_vue and not sous_relation:
                    candidates.append(liste)
            except RuntimeError:
                continue
        return max(candidates, key=lambda vue: (vue.height(), vue.width())) if candidates else None

    @staticmethod
    def _trouver_barre_outils(fenetre):
        """Repère la barre d'outils de la table (celle avec le plus de boutons).

        QGIS ne donne pas de nom d'objet stable à cette barre selon les
        versions : l'heuristique "la plus garnie parmi les barres visibles"
        évite de dépendre d'un nom interne fragile.
        """
        try:
            barres = [
                barre
                for barre in fenetre.findChildren(QToolBar)
                if barre.isVisible() and barre.actions()
            ]
        except RuntimeError:
            return None
        return max(barres, key=lambda barre: len(barre.actions())) if barres else None

    def _creer_actions(self, fenetre, toolbar):
        """Ajoute les boutons sans reconstruire la barre d'outils QGIS.

        La logique Précédent/Suivant reste volontairement celle de la version 4
        stable. Le bouton de recalcul est simplement ajouté à leur suite.
        """
        precedent = self._trouver_action(toolbar, self.NOM_ACTION_PRECEDENT)
        suivant = self._trouver_action(toolbar, self.NOM_ACTION_SUIVANT)
        recalculer = self._trouver_action(toolbar, self.NOM_ACTION_RECALCULER_ALERTES)

        separateur = None
        if precedent is None or suivant is None:
            # Comportement identique à la v4 stable : on crée ensemble les deux
            # boutons d'historique et leur séparateur.
            precedent = self._creer_action(
                fenetre,
                "icon_precedent.svg",
                "Fiche précédente",
                self.NOM_ACTION_PRECEDENT,
                "Revenir à la fiche précédemment ouverte",
            )
            suivant = self._creer_action(
                fenetre,
                "icon_suivant.svg",
                "Fiche suivante",
                self.NOM_ACTION_SUIVANT,
                "Revenir à la fiche suivante de l'historique",
            )
            separateur = toolbar.addSeparator()
            toolbar.addAction(precedent)
            toolbar.addAction(suivant)

        if recalculer is None:
            recalculer = self._creer_action(
                fenetre,
                "icon_recalculer_alertes.svg",
                "Vérifier les alertes et recalculer",
                self.NOM_ACTION_RECALCULER_ALERTES,
                "Recalculer les alertes et le classement",
            )
            toolbar.addAction(recalculer)

        # QGIS peut conserver une QAction lors d'un rechargement du plugin.
        # Dans ce cas son objet existe encore mais son icône peut être devenue
        # vide. On réapplique donc les SVG sans reconstruire la barre d'outils.
        precedent.setIcon(QIcon(os.path.join(self.plugin_dir, "icon_precedent.svg")))
        suivant.setIcon(QIcon(os.path.join(self.plugin_dir, "icon_suivant.svg")))
        recalculer.setIcon(QIcon(os.path.join(self.plugin_dir, "icon_recalculer_alertes.svg")))
        # Réappliquer aussi le texte : QGIS peut conserver une ancienne QAction
        # après rechargement du plugin.
        recalculer.setText("Vérifier les alertes et recalculer")
        recalculer.setToolTip("Recalculer les alertes et le classement")
        recalculer.setEnabled(self._callback_recalculer_alertes is not None)
        return precedent, suivant, recalculer, separateur

    def _creer_action(self, fenetre, icone, texte, nom_objet, info_bulle):
        action = QAction(QIcon(os.path.join(self.plugin_dir, icone)), texte, fenetre)
        action.setObjectName(nom_objet)
        action.setToolTip(info_bulle)
        action.setEnabled(False)
        return action

    @staticmethod
    def _trouver_action(toolbar, nom):
        for action in toolbar.actions():
            try:
                if action.objectName() == nom:
                    return action
            except RuntimeError:
                continue
        return None

    def definir_etat_formulaire(self, callback):
        """Reçoit un callback léger ``(couche, fid, vue_formulaire)``."""
        self._callback_etat_formulaire = callback if callable(callback) else None

    def definir_fid_persistant(self, callback):
        """Branche la lecture du dernier FID conservé entre deux sessions QGIS."""
        self._callback_fid_persistant = callback if callable(callback) else None

    def _notifier_etat_formulaire(self, fenetre, fid):
        callback = self._callback_etat_formulaire
        donnees = self.fenetres.get(fenetre)
        if callback is None or donnees is None:
            return
        try:
            dual_view = donnees["dual_view"]
            modele = dual_view.masterModel()
            couche = modele.layer() if modele is not None else None
            if couche is None:
                return
            vue_formulaire = dual_view.view() == QgsDualView.AttributeEditor
            callback(couche, int(fid), bool(vue_formulaire))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def definir_recalcul_alertes(self, callback):
        """Branche le bouton de recalcul sur le service des compteurs."""
        self._callback_recalculer_alertes = callback
        for donnees in list(self.fenetres.values()):
            action = donnees.get("action_recalculer")
            if action is None:
                continue
            try:
                action.setEnabled(callback is not None)
            except RuntimeError:
                pass

    def recalculer_alertes(self):
        """Lance le recalcul global sans changer de fiche ni de sélection."""
        callback = self._callback_recalculer_alertes
        if callback is None:
            return
        try:
            callback()
        except Exception as erreur:
            self.iface.messageBar().pushWarning(
                "Compteurs d'alertes",
                f"Le recalcul n'a pas pu être lancé : {erreur}",
            )

    def _couche_fenetre(self, fenetre):
        """Retourne la couche principale associée à une vue attributaire."""
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return None
        dual_view = donnees.get("dual_view")
        if not self._objet_qt_valide(dual_view):
            return None
        try:
            modele = dual_view.masterModel()
            return modele.layer() if modele is not None else None
        except (AttributeError, RuntimeError):
            return None

    @staticmethod
    def _cle_couche(couche):
        """Clé stable pendant la session QGIS, sans dépendre d'un attribut métier."""
        try:
            return str(couche.id()) if couche is not None else ""
        except (AttributeError, RuntimeError):
            return ""

    def _memoriser_derniere_fiche(self, fenetre, fid):
        """Mémorise seulement le FID courant, sans relire la couche."""
        couche = self._couche_fenetre(fenetre)
        cle = self._cle_couche(couche)
        if not cle:
            return
        try:
            self._derniere_fiche_par_couche[cle] = int(fid)
        except (TypeError, ValueError):
            return

    def _restaurer_derniere_fiche(self, fenetre):
        """Rouvre le dernier FID connu ; sinon laisse QGIS sur sa première fiche."""
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return False
        couche = self._couche_fenetre(fenetre)
        cle = self._cle_couche(couche)
        if not cle:
            return False

        # 1) mémoire de la session courante ;
        # 2) sinon mémoire persistante du projet.
        fid = self._derniere_fiche_par_couche.get(cle)
        if fid is None and self._callback_fid_persistant is not None:
            try:
                fid = self._callback_fid_persistant(couche)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                fid = None
        if fid is None:
            return False
        try:
            entite = couche.getFeature(int(fid))
            if entite is None or not entite.isValid():
                self._derniere_fiche_par_couche.pop(cle, None)
                return False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._derniere_fiche_par_couche.pop(cle, None)
            return False

        # Une valeur relue depuis le projet devient désormais la mémoire RAM de
        # cette couche pour les fermetures/réouvertures suivantes.
        self._derniere_fiche_par_couche[cle] = int(fid)

        dual_view = donnees.get("dual_view")
        if not self._objet_qt_valide(dual_view):
            return False

        donnees["navigation_programmatique"] = True
        try:
            dual_view.setCurrentEditSelection([int(fid)])
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        finally:
            donnees["navigation_programmatique"] = False

    # ------------------------------------------------------------------
    # Historique
    # ------------------------------------------------------------------

    def fiche_changee(self, fenetre, feature):
        donnees = self.fenetres.get(fenetre)
        if donnees is None or donnees["navigation_programmatique"]:
            return
        try:
            if feature is None or not feature.isValid():
                return
            fid = int(feature.id())
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return
        self._memoriser_derniere_fiche(fenetre, fid)
        self.ajouter_fid_historique(fenetre, fid)

    def enregistrer_fiche_initiale(self, fenetre):
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return
        try:
            fids = list(donnees["feature_list"].currentEditSelection())
        except (AttributeError, TypeError, RuntimeError):
            return
        if fids:
            fid = int(fids[0])
            self._memoriser_derniere_fiche(fenetre, fid)
            self.ajouter_fid_historique(fenetre, fid)

    def ajouter_fid_historique(self, fenetre, fid):
        """Ajoute un FID à l'historique de navigation (même logique qu'un
        historique de navigateur web : visiter une nouvelle page après être
        revenu en arrière efface le "futur" précédent)."""
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return

        historique = donnees["historique"]
        position = donnees["position"]
        # Déjà sur ce FID (ex. re-sélection du même enregistrement) : ne pas
        # dupliquer l'entrée, juste rafraîchir l'état des boutons.
        if 0 <= position < len(historique) and historique[position] == fid:
            self.mettre_a_jour_actions(fenetre)
            self._notifier_etat_formulaire(fenetre, fid)
            return

        # Si l'utilisateur était revenu en arrière (position pas à la fin) et
        # consulte maintenant une fiche différente, tout ce qui suivait dans
        # l'historique ("Suivant") devient obsolète et est tronqué.
        if position < len(historique) - 1:
            historique = historique[: position + 1]
        historique.append(fid)
        # Garde seulement les LIMITE_HISTORIQUE (10) dernières entrées.
        donnees["historique"] = historique[-self.LIMITE_HISTORIQUE :]
        donnees["position"] = len(donnees["historique"]) - 1
        self.mettre_a_jour_actions(fenetre)
        self._notifier_etat_formulaire(fenetre, fid)

    def revenir_precedent(self, fenetre):
        donnees = self.fenetres.get(fenetre)
        if donnees is not None and donnees["position"] > 0:
            self.ouvrir_position(fenetre, donnees["position"] - 1)

    def aller_suivant(self, fenetre):
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return
        if donnees["position"] < len(donnees["historique"]) - 1:
            self.ouvrir_position(fenetre, donnees["position"] + 1)

    def ouvrir_position(self, fenetre, nouvelle_position):
        """Change de fiche uniquement à la demande Précédent/Suivant."""
        donnees = self.fenetres.get(fenetre)
        if donnees is None or not 0 <= nouvelle_position < len(donnees["historique"]):
            return

        dual_view = donnees.get("dual_view")
        if not self._objet_qt_valide(dual_view):
            return

        fid = donnees["historique"][nouvelle_position]
        donnees["navigation_programmatique"] = True
        try:
            # Le signal émis pendant cet appel est synchrone : le drapeau suffit.
            # Aucun QTimer ne vient réutiliser un widget Qt plus tard.
            dual_view.setCurrentEditSelection([fid])
            donnees["position"] = nouvelle_position
            self._memoriser_derniere_fiche(fenetre, fid)
            self._notifier_etat_formulaire(fenetre, fid)
        except Exception as erreur:
            self.iface.messageBar().pushWarning(
                "Historique des formulaires",
                f"Impossible d'ouvrir le FID {fid} : {erreur}",
            )
        finally:
            donnees["navigation_programmatique"] = False
            self.mettre_a_jour_actions(fenetre)

    def mettre_a_jour_actions(self, fenetre):
        donnees = self.fenetres.get(fenetre)
        if donnees is None:
            return
        historique = donnees["historique"]
        position = donnees["position"]
        try:
            donnees["action_precedent"].setEnabled(len(historique) >= 2 and position > 0)
            donnees["action_suivant"].setEnabled(
                len(historique) >= 2 and position < len(historique) - 1
            )
            donnees["action_recalculer"].setEnabled(
                self._callback_recalculer_alertes is not None
            )
        except RuntimeError:
            pass

    def geler_fiche_si_fid_supprime(self, couche, fids_supprimes):
        """Empêche QGIS de basculer la fiche principale sur la première ligne.

        Le gel n'est armé que si le FID actuellement affiché fait partie des FID
        qui vont réellement disparaître. Le modèle de la liste peut se mettre à
        jour, mais son signal de changement de fiche est temporairement bloqué.
        Le blocage est relâché après les événements Qt générés par la suppression ;
        la prochaine navigation volontaire de l'utilisateur fonctionne normalement.
        """
        if couche is None:
            return []
        try:
            supprimes = set(int(fid) for fid in (fids_supprimes or []))
        except (TypeError, ValueError):
            return []
        if not supprimes:
            return []
        try:
            nom_couche = normaliser_nom(couche.name())
        except (AttributeError, RuntimeError):
            nom_couche = ""

        gels = []
        for fenetre, donnees in list(self.fenetres.items()):
            try:
                if not fenetre.isVisible():
                    continue
                if nom_couche and nom_couche not in normaliser_nom(fenetre.windowTitle()):
                    continue
                feature_list = donnees.get("feature_list")
                if not self._objet_qt_valide(feature_list):
                    continue
                selection = list(feature_list.currentEditSelection())
                if not selection or int(selection[0]) not in supprimes:
                    continue
                barre = feature_list.verticalScrollBar()
                scroll = int(barre.value())
                bloqueur = QSignalBlocker(feature_list)
                gels.append((weakref.ref(fenetre), bloqueur, scroll))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        return gels

    def liberer_gel_fiche(self, gels):
        """Relâche un gel de fiche après les signaux différés de QGIS."""
        if not gels:
            return

        def _liberer():
            for ref, bloqueur, scroll in gels:
                try:
                    fenetre = ref()
                except RuntimeError:
                    fenetre = None
                if fenetre is not None:
                    try:
                        self._appliquer_scroll_si_valide(weakref.ref(fenetre), int(scroll))
                    except (RuntimeError, TypeError, ValueError):
                        pass
                try:
                    bloqueur.unblock()
                except (AttributeError, RuntimeError):
                    pass
            gels.clear()

        # Les changements de sélection internes du QgsDualView consécutifs à une
        # suppression sont différés. On laisse passer deux tours d'événements
        # avant de rendre la main, sans modifier la sélection nous-mêmes.
        QTimer.singleShot(0, lambda: QTimer.singleShot(250, _liberer))

    def capturer_contexte_visuel_couche(self, couche, fids_supprimes_prevus=None):
        """Mémorise la fiche courante et ses voisines dans l'ordre affiché.

        La règle de restauration est volontairement simple : si le FID courant
        existe toujours après l'opération, on reste dessus. S'il a disparu, on
        ouvre la première fiche suivante qui existait déjà dans la liste avant
        la modification. À défaut, on revient sur la fiche précédente.

        Aucun tri, filtre, sélection de couche, zoom ou emprise de carte n'est
        modifié. ``fids_supprimes_prevus`` permet d'ignorer dès la capture les
        entités dont l'opération sait qu'elles vont disparaître.
        """
        if couche is None:
            return []
        try:
            supprimes = set(int(fid) for fid in (fids_supprimes_prevus or []))
        except (TypeError, ValueError):
            supprimes = set()
        try:
            nom_couche = normaliser_nom(couche.name())
        except (AttributeError, RuntimeError):
            nom_couche = ""

        contexte = []
        for fenetre, donnees in list(self.fenetres.items()):
            try:
                if not fenetre.isVisible():
                    continue
                if nom_couche and nom_couche not in normaliser_nom(fenetre.windowTitle()):
                    continue
                feature_list = donnees.get("feature_list")
                if not self._objet_qt_valide(feature_list):
                    continue

                selection = list(feature_list.currentEditSelection())
                fid = int(selection[0]) if selection else None
                barre = feature_list.verticalScrollBar()
                scroll = int(barre.value())

                ligne = -1
                fid_suivant = None
                fid_precedent = None
                modele = None
                try:
                    modele = feature_list.featureListModel()
                except (AttributeError, RuntimeError):
                    modele = None

                if fid is not None and modele is not None:
                    try:
                        index_courant = modele.fidToIdx(int(fid))
                        if index_courant is not None and index_courant.isValid():
                            ligne = int(index_courant.row())
                            nb_lignes = int(modele.rowCount())

                            for numero in range(ligne + 1, nb_lignes):
                                index = modele.index(numero, 0)
                                candidat = int(modele.idxToFid(index))
                                if candidat not in supprimes:
                                    fid_suivant = candidat
                                    break

                            for numero in range(ligne - 1, -1, -1):
                                index = modele.index(numero, 0)
                                candidat = int(modele.idxToFid(index))
                                if candidat not in supprimes:
                                    fid_precedent = candidat
                                    break
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        ligne = -1
                        fid_suivant = None
                        fid_precedent = None

                contexte.append({
                    "fenetre": weakref.ref(fenetre),
                    "fid": fid,
                    "ligne": ligne,
                    "fid_suivant": fid_suivant,
                    "fid_precedent": fid_precedent,
                    "fid_supprime_prevu": bool(fid is not None and fid in supprimes),
                    "scroll": scroll,
                })
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        return contexte

    def deplacer_fiche_avant_suppression(self, couche, contexte):
        """Quitte une fiche dont le FID va disparaître, avant la suppression.

        C'est une protection essentielle contre les FID fantômes : une table
        attributaire laissée sur une entité supprimée peut encore émettre plus
        tard ``attributeValueChanged`` pour cet ancien FID. On déplace donc la
        fiche vers la suivante (ou la précédente) tant que l'ancien FID existe
        encore. La carte est gelée et son emprise restaurée : cette navigation
        de formulaire ne doit produire aucun zoom ni panoramique.
        """
        if couche is None or not contexte:
            return

        protecteur = ProtectionVueCarte(self.iface.mapCanvas())
        with protecteur.modification():
            for etat in list(contexte):
                if not isinstance(etat, dict) or not etat.get("fid_supprime_prevu"):
                    continue
                ref = etat.get("fenetre")
                try:
                    fenetre = ref() if ref is not None else None
                except RuntimeError:
                    fenetre = None
                if fenetre is None:
                    continue
                donnees = self.fenetres.get(fenetre)
                if donnees is None:
                    continue
                feature_list = donnees.get("feature_list")
                dual_view = donnees.get("dual_view")
                if not self._objet_qt_valide(feature_list) or not self._objet_qt_valide(dual_view):
                    continue

                try:
                    modele = feature_list.featureListModel()
                except (AttributeError, RuntimeError):
                    modele = None

                def _present(fid):
                    if fid is None or modele is None:
                        return False
                    try:
                        idx = modele.fidToIdx(int(fid))
                        return idx is not None and idx.isValid()
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        return False

                cible = None
                if _present(etat.get("fid_suivant")):
                    cible = int(etat["fid_suivant"])
                elif _present(etat.get("fid_precedent")):
                    cible = int(etat["fid_precedent"])

                try:
                    donnees["navigation_programmatique"] = True
                    if cible is None:
                        dual_view.setCurrentEditSelection([])
                    else:
                        dual_view.setCurrentEditSelection([cible])
                        self._memoriser_derniere_fiche(fenetre, cible)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
                finally:
                    donnees["navigation_programmatique"] = False

    def assainir_fiche_apres_suppression(self, couche, fid_supprime):
        """Filet de sécurité après toute suppression signalée par QGIS.

        Les outils du plugin déplacent normalement la fiche *avant* de supprimer
        une entité. Cette méthode couvre les suppressions provenant d'un autre
        chemin (outil natif, futur contrôle, signal différé). Si une vue formulaire
        pointe encore vers le FID disparu, elle est replacée sur la ligne qui a
        pris sa place, ou sur la dernière ligne disponible. L'emprise cartographique
        reste strictement protégée.
        """
        if couche is None:
            return
        try:
            fid_supprime = int(fid_supprime)
        except (TypeError, ValueError):
            return

        cle_couche = self._cle_couche(couche)
        for fenetre, donnees in list(self.fenetres.items()):
            try:
                if not fenetre.isVisible():
                    continue
                if self._cle_couche(self._couche_fenetre(fenetre)) != cle_couche:
                    continue
                feature_list = donnees.get("feature_list")
                dual_view = donnees.get("dual_view")
                if not self._objet_qt_valide(feature_list) or not self._objet_qt_valide(dual_view):
                    continue

                selection = list(feature_list.currentEditSelection())
                if selection:
                    courant = int(selection[0])
                    if courant != fid_supprime:
                        # QGIS a déjà choisi une fiche valide : ne rien imposer.
                        self._derniere_fiche_par_couche[cle_couche] = courant
                        continue
                elif self._derniere_fiche_par_couche.get(cle_couche) != fid_supprime:
                    continue

                modele = feature_list.featureListModel()
                nb_lignes = int(modele.rowCount()) if modele is not None else 0
                if nb_lignes <= 0:
                    protecteur = ProtectionVueCarte(self.iface.mapCanvas())
                    with protecteur.modification():
                        donnees["navigation_programmatique"] = True
                        dual_view.setCurrentEditSelection([])
                    donnees["navigation_programmatique"] = False
                    self._derniere_fiche_par_couche.pop(cle_couche, None)
                    continue

                try:
                    index_courant = feature_list.currentIndex()
                    ligne = int(index_courant.row()) if index_courant is not None and index_courant.isValid() else 0
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    ligne = 0
                ligne = max(0, min(ligne, nb_lignes - 1))
                index = modele.index(ligne, 0)
                cible = int(modele.idxToFid(index))

                protecteur = ProtectionVueCarte(self.iface.mapCanvas())
                with protecteur.modification():
                    donnees["navigation_programmatique"] = True
                    dual_view.setCurrentEditSelection([cible])
                    self._memoriser_derniere_fiche(fenetre, cible)
                donnees["navigation_programmatique"] = False
            except (AttributeError, RuntimeError, TypeError, ValueError):
                try:
                    donnees["navigation_programmatique"] = False
                except Exception:
                    pass
                continue

    def _restaurer_contexte_visuel_une_fois(self, couche, contexte, fid_remplacement=None):
        """Applique une tentative de restauration après mise à jour du modèle QGIS."""
        if not contexte or couche is None:
            return
        for etat in list(contexte):
            if not isinstance(etat, dict):
                continue
            ref = etat.get("fenetre")
            try:
                fenetre = ref() if ref is not None else None
            except RuntimeError:
                continue
            if fenetre is None:
                continue
            donnees = self.fenetres.get(fenetre)
            if donnees is None:
                continue
            feature_list = donnees.get("feature_list")
            dual_view = donnees.get("dual_view")
            if not self._objet_qt_valide(feature_list) or not self._objet_qt_valide(dual_view):
                continue

            fid_avant = etat.get("fid")
            fid_suivant = etat.get("fid_suivant")
            fid_precedent = etat.get("fid_precedent")
            ligne = etat.get("ligne", -1)
            cible = None

            try:
                modele = feature_list.featureListModel()
            except (AttributeError, RuntimeError):
                modele = None

            def _fid_present(fid):
                if fid is None or modele is None:
                    return False
                try:
                    index = modele.fidToIdx(int(fid))
                    return index is not None and index.isValid()
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    return False

            # 1. Le FID affiché a survécu : on reste exactement sur sa fiche.
            # S'il était explicitement annoncé comme supprimé par l'opération,
            # ne jamais le resélectionner, même si le modèle QGIS le conserve
            # encore brièvement pendant son reset asynchrone.
            if not etat.get("fid_supprime_prevu") and _fid_present(fid_avant):
                cible = int(fid_avant)
            # 2. Le FID a disparu : on avance dans l'ordre qui était affiché.
            elif _fid_present(fid_suivant):
                cible = int(fid_suivant)
            # 3. Si l'ancienne fiche était en fin de liste, on prend la précédente.
            elif _fid_present(fid_precedent):
                cible = int(fid_precedent)
            else:
                # Filet de sécurité : si le modèle a été profondément reconstruit,
                # on reprend la même position de ligne plutôt que la première fiche.
                try:
                    nb_lignes = int(modele.rowCount()) if modele is not None else 0
                    if nb_lignes > 0 and int(ligne) >= 0:
                        numero = min(int(ligne), nb_lignes - 1)
                        index = modele.index(numero, 0)
                        candidat = int(modele.idxToFid(index))
                        if _fid_present(candidat):
                            cible = candidat
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    cible = None

            if cible is None and _fid_present(fid_remplacement):
                cible = int(fid_remplacement)

            if cible is not None:
                try:
                    # Une table peut être configurée pour zoomer automatiquement
                    # sur la fiche courante. La restauration de fiche est donc
                    # elle-même protégée, y compris lorsqu'elle est exécutée par
                    # un QTimer après la fin de l'opération géométrique.
                    protecteur = ProtectionVueCarte(self.iface.mapCanvas())
                    with protecteur.modification():
                        donnees["navigation_programmatique"] = True
                        dual_view.setCurrentEditSelection([int(cible)])
                        self._memoriser_derniere_fiche(fenetre, int(cible))
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass
                finally:
                    donnees["navigation_programmatique"] = False

            try:
                scroll = int(etat.get("scroll", 0))
                reference = weakref.ref(fenetre)
                self._appliquer_scroll_si_valide(reference, scroll)
            except (TypeError, RuntimeError, ValueError):
                pass

    def restaurer_contexte_visuel_couche(
        self,
        couche,
        contexte,
        fid_remplacement=None,
        restaurer_fid=True,
    ):
        """Restaure la fiche sans retour en haut après création/fusion/suppression.

        ``restaurer_fid`` est conservé pour compatibilité avec les anciens appels ;
        la règle appliquée est désormais toujours : même FID s'il existe, sinon
        fiche suivante, sinon précédente. Plusieurs tentatives différées couvrent
        les resets asynchrones du ``QgsDualView`` sans toucher au tri ni à la carte.
        """
        if not contexte:
            return

        def _restaurer():
            self._restaurer_contexte_visuel_une_fois(
                couche, contexte, fid_remplacement=fid_remplacement
            )

        # QGIS 3.34/3.44 peut réinitialiser la liste sur plusieurs tours
        # d'événements après une suppression. La dernière tentative intervient
        # après le déblocage utilisé par ``liberer_gel_fiche`` (250 ms).
        try:
            QTimer.singleShot(0, _restaurer)
            QTimer.singleShot(80, _restaurer)
            QTimer.singleShot(320, _restaurer)
        except (RuntimeError, TypeError):
            _restaurer()

    # ------------------------------------------------------------------
    # Nettoyage
    # ------------------------------------------------------------------

    def fenetre_detruite(self, reference_fenetre):
        try:
            fenetre = reference_fenetre()
        except RuntimeError:
            fenetre = None
        if fenetre is not None:
            self.fenetres.pop(fenetre, None)

    @staticmethod
    def _objet_qt_valide(objet):
        """Indique si le wrapper Python pointe encore vers un objet Qt vivant.

        ``sip.isdeleted`` est vérifié avant tout accès à un widget conservé dans le
        registre. C'est particulièrement important pour les vues formulaire QGIS,
        dont les enfants peuvent être détruits avant que Python ne perde leur wrapper.
        """
        if objet is None:
            return False
        try:
            return not sip.isdeleted(objet)
        except (AttributeError, RuntimeError):
            return False

    def deconnecter_fenetre(self, fenetre):
        """Retire proprement une vue encore vivante (notamment lors de ``unload``).

        Cette méthode n'est plus appelée par le timer lors de la fermeture normale
        d'une fenêtre. Dans ce cas Qt détruit automatiquement les connexions et
        ``fenetre_detruite`` se contente de retirer l'entrée du registre.
        """
        # Retirer d'abord l'état interne évite toute réentrance d'un signal pendant
        # le nettoyage.
        donnees = self.fenetres.pop(fenetre, None)
        if donnees is None:
            return

        feature_list = donnees.get("feature_list")
        slot = donnees.get("slot_changement")
        if self._objet_qt_valide(feature_list) and slot is not None:
            try:
                feature_list.currentEditSelectionChanged.disconnect(slot)
            except (AttributeError, TypeError, RuntimeError):
                pass

        modele_liste = donnees.get("modele_liste")
        if self._objet_qt_valide(modele_liste):
            slot_avant = donnees.get("slot_modele_avant_reset")
            slot_apres = donnees.get("slot_modele_apres_reset")
            if slot_avant is not None:
                try:
                    modele_liste.modelAboutToBeReset.disconnect(slot_avant)
                except (AttributeError, TypeError, RuntimeError):
                    pass
            if slot_apres is not None:
                try:
                    modele_liste.modelReset.disconnect(slot_apres)
                except (AttributeError, TypeError, RuntimeError):
                    pass

        toolbar = donnees.get("toolbar")
        if self._objet_qt_valide(toolbar):
            for action in (
                donnees.get("action_precedent"),
                donnees.get("action_suivant"),
                donnees.get("action_recalculer"),
                donnees.get("separateur"),
            ):
                if not self._objet_qt_valide(action):
                    continue
                try:
                    toolbar.removeAction(action)
                except (AttributeError, RuntimeError):
                    pass
