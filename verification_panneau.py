# -*- coding: utf-8 -*-
"""Interface du panneau « Vérification BD Forêt ».

Ce module ne réalise aucun calcul géométrique. Il contient uniquement les
widgets Qt, la navigation dans l'arbre et le menu contextuel. Le contrôleur
``VerificationBdForetPlugin`` reste dans :mod:`verification`.

Cette séparation est volontaire : une personne qui souhaite modifier le texte,
les boutons ou le menu n'a pas besoin de parcourir le moteur de vérification.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .commun_couches import couche_est_disponible
from . import verification_nettoyage_automatique as verif_nettoyage
from . import verification_surface05ha as verif_surface
from . import verification_entites_multiparties as verif_multiparties
from . import verification_recouvrements as verif_recouvrements
from . import verification_trous as verif_trous
from . import verification_polygones_adjacents_attributs_identiques as verif_adjacents
from . import verification_coherence_essence_tff as verif_coherence

# Les 6 règles que "Vérifier les règles métier" recherche, dans l'ordre
# affiché dans le menu à cases à cocher ET dans le tableau des anomalies
# (voir verification.py, _remplir_arbre). Clés reprises telles quelles dans
# tout le pipeline de contrôle (etat["small"], _lazy_tree_data...).
ORDRE_REGLES_METIER = ["small", "multipart", "overlaps", "gaps", "adjacent", "coherence"]
LIBELLES_REGLES_METIER = {
    "small": "Surfaces < 0,5 ha",
    "multipart": "Entités multiparties",
    "overlaps": "Recouvrements",
    "gaps": "Trous dans la couche",
    "adjacent": "Polygones adjacents aux attributs identiques",
    "coherence": "Incohérence essence / TFF",
}


class PanneauVerification(QDockWidget):
    """Panneau latéral. Toute la logique métier est déléguée au contrôleur."""

    def __init__(self, plugin):
        super().__init__("Vérification BD Forêt", plugin.iface.mainWindow())
        self.plugin = plugin
        self.setObjectName("VerificationBdForetDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)

        # Bouton principal + petite flèche à droite ouvrant un menu à cases à
        # cocher (une par étape du nettoyage automatique, dans l'ordre
        # d'exécution) : clic sur le bouton = lancer avec la sélection
        # actuelle, clic sur la flèche = choisir quelles étapes activer.
        # Tout coché par défaut, remis à zéro (pas mémorisé) à chaque
        # ouverture de QGIS, sur demande explicite (éviter d'oublier une
        # étape désactivée la veille).
        self.nettoyage_button = QToolButton()
        self.nettoyage_button.setText("Nettoyer la couche")
        self.nettoyage_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.nettoyage_button.setPopupMode(QToolButton.MenuButtonPopup)
        # Un QToolButton ne s'étire pas comme un QPushButton par défaut
        # (largeur ajustée à son propre contenu + la flèche du menu) : sans
        # ceci, il ne fait pas la même largeur que "Vérifier les règles métier"
        # juste en dessous.
        self.nettoyage_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.nettoyage_button.clicked.connect(self.plugin.lancer_nettoyage_automatique)
        # Gras (sans couleur de fond, retirée partout ailleurs) : distingue
        # les deux boutons de lancement ("Nettoyer la couche", "Vérifier les
        # règles métier") du reste du panneau.
        self.nettoyage_button.setStyleSheet("QToolButton { font-weight: bold; }")

        # Cases à cocher (QCheckBox dans un QWidgetAction), pas de simples
        # QAction cochables : QMenu ferme le menu au clic sur une QAction
        # même cochable, ce qui empêcherait de cocher/décocher plusieurs
        # étapes de suite. Une QCheckBox est un widget normal, cliquer dessus
        # ne ferme pas le menu qui la contient.
        self._menu_etapes_nettoyage = QMenu(self.nettoyage_button)
        self._actions_etapes_nettoyage = {}
        for cle in verif_nettoyage.ORDRE_ETAPES:
            case = QCheckBox(verif_nettoyage.LIBELLES_ETAPES[cle], self._menu_etapes_nettoyage)
            case.setChecked(True)
            action_widget = QWidgetAction(self._menu_etapes_nettoyage)
            action_widget.setDefaultWidget(case)
            self._menu_etapes_nettoyage.addAction(action_widget)
            self._actions_etapes_nettoyage[cle] = case
        self.nettoyage_button.setMenu(self._menu_etapes_nettoyage)
        layout.addWidget(self.nettoyage_button)

        # Barre de progression dédiée à "Nettoyer la couche", juste sous son
        # bouton et avant son tableau d'étapes (demande explicite : l'ordre
        # précédent la plaçait ailleurs, mélangée avec "Vérifier les règles
        # métier" qui partageait la même barre).
        self.search_progress = QProgressBar()
        self.search_progress.setRange(0, 0)
        self.search_progress.setTextVisible(False)
        self.search_progress.setVisible(False)
        layout.addWidget(self.search_progress)

        # Le nettoyage automatique affiche plusieurs lignes (une par étape),
        # sous forme de petit tableau (mêmes colonnes en esprit que celui des
        # anomalies plus bas : une catégorie, un détail). Une croix permet de
        # le masquer si l'utilisateur n'en a plus besoin — lui seul le fait :
        # ce tableau est dédié à "Nettoyer la couche" et ne doit jamais être
        # touché par un autre contrôle (bug signalé : "Vérifier les règles
        # métier" le vidait puis le masquait). Il redevient visible tout seul
        # au prochain lancement du nettoyage (voir verification.py).
        self.search_status = QWidget()
        search_status_layout = QVBoxLayout(self.search_status)
        search_status_layout.setContentsMargins(0, 0, 0, 0)
        search_status_layout.setSpacing(2)

        entete_search_status = QHBoxLayout()
        entete_search_status.addStretch()
        self.search_status_fermer = QToolButton()
        self.search_status_fermer.setText("✕")
        self.search_status_fermer.setToolTip("Masquer cette zone")
        self.search_status_fermer.setAutoRaise(True)
        self.search_status_fermer.clicked.connect(lambda: self.search_status.setVisible(False))
        entete_search_status.addWidget(self.search_status_fermer)
        search_status_layout.addLayout(entete_search_status)

        self.search_status_tree = QTreeWidget()
        self.search_status_tree.setHeaderLabels(["Étape", "Détail"])
        self.search_status_tree.setRootIsDecorated(False)
        self.search_status_tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.search_status_tree.setFocusPolicy(Qt.NoFocus)
        # Fixe (pas Expanding) : ce tableau ne doit prendre que la place que
        # son contenu réclame (ajustée dynamiquement, voir verification.py),
        # pas empiéter sur celle du grand tableau des anomalies en dessous.
        self.search_status_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        search_status_layout.addWidget(self.search_status_tree)

        self.search_status.setVisible(False)
        layout.addWidget(self.search_status)

        # Même aspect que "Nettoyer la couche" (demande explicite) : un
        # QToolButton avec une flèche ouvrant un menu à cases à cocher, une
        # par règle recherchée (voir ORDRE_REGLES_METIER/LIBELLES_REGLES_METIER
        # en tête de module). Tout coché par défaut, comme pour le nettoyage.
        self.refresh_button = QToolButton()
        self.refresh_button.setText("Vérifier les règles métier")
        self.refresh_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.refresh_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.refresh_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_button.clicked.connect(self.plugin.rafraichir_verifications)

        self._menu_regles_metier = QMenu(self.refresh_button)
        self._actions_regles_metier = {}
        for cle in ORDRE_REGLES_METIER:
            case = QCheckBox(LIBELLES_REGLES_METIER[cle], self._menu_regles_metier)
            case.setChecked(True)
            action_widget = QWidgetAction(self._menu_regles_metier)
            action_widget.setDefaultWidget(case)
            self._menu_regles_metier.addAction(action_widget)
            self._actions_regles_metier[cle] = case
        self.refresh_button.setMenu(self._menu_regles_metier)
        self.refresh_button.setStyleSheet("QToolButton { font-weight: bold; }")
        layout.addWidget(self.refresh_button)

        # Barre de progression dédiée à "Vérifier les règles métier", symétrique
        # de celle du nettoyage plus haut (jamais la même barre partagée entre
        # les deux contrôles — même raison que pour les deux tableaux).
        self.search_progress_metier = QProgressBar()
        self.search_progress_metier.setRange(0, 0)
        self.search_progress_metier.setTextVisible(False)
        self.search_progress_metier.setVisible(False)
        layout.addWidget(self.search_progress_metier)

        # Message d'une ligne pour "Vérifier les règles métier" (préparation,
        # recherche des relations spatiales, des trous...) : zone séparée du
        # tableau du nettoyage plus haut, pour ne jamais écraser l'un avec
        # l'autre.
        self.search_status_metier = QLabel("")
        self.search_status_metier.setWordWrap(True)
        self.search_status_metier.setVisible(False)
        layout.addWidget(self.search_status_metier)

        self.create_layer_button = QPushButton("Créer la couche temporaire")
        self.create_layer_button.setVisible(False)
        self.create_layer_button.clicked.connect(self.plugin.creer_couche_temporaire)
        layout.addWidget(self.create_layer_button)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Anomalie", "Détail"])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemClicked.connect(self._faire_clignoter_element)
        self.tree.itemDoubleClicked.connect(self._zoomer_element)
        self.tree.itemExpanded.connect(self._developper_categorie)
        self.tree.itemCollapsed.connect(self._replier_categorie)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ouvrir_menu_contextuel)
        layout.addWidget(self.tree)

        self.setWidget(container)

    def etapes_nettoyage_activees(self):
        """Étapes actuellement cochées dans le menu de "Nettoyer la couche"."""
        return {
            cle for cle, action in self._actions_etapes_nettoyage.items() if action.isChecked()
        }

    def regles_metier_activees(self):
        """Règles actuellement cochées dans le menu de "Vérifier les règles métier"."""
        return {
            cle for cle, action in self._actions_regles_metier.items() if action.isChecked()
        }

    def closeEvent(self, event):
        """Ferme proprement les calculs et déconnecte la couche surveillée."""
        self.plugin._annuler_tache_relations()
        self.plugin._deconnecter_signaux_couche()
        self.plugin._refresh_timer.stop()
        self.plugin._clignotement.effacer()
        self.plugin._surbrillance.detacher()
        self.plugin._reinitialiser_resultats_panneau()
        self.plugin.action.setChecked(False)
        super().closeEvent(event)

    def _faire_clignoter_element(self, item, _column):
        payload = item.data(0, Qt.UserRole)
        if payload:
            self.plugin.faire_clignoter(payload)

    def _zoomer_element(self, item, _column):
        payload = item.data(0, Qt.UserRole)
        if payload:
            self.plugin.zoomer_sur_element(payload)

    def _developper_categorie(self, item):
        """Mémorise l'ouverture et crée les lignes détaillées si nécessaire."""
        payload = item.data(0, Qt.UserRole)
        if isinstance(payload, dict):
            cle = payload.get("lazy_category")
            if cle:
                self.plugin._categories_ouvertes.add(cle)
        self.plugin._peupler_categorie_si_besoin(item)

    def _replier_categorie(self, item):
        """Mémorise uniquement un repli explicitement demandé par l'utilisateur."""
        payload = item.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            return
        cle = payload.get("lazy_category")
        if cle:
            self.plugin._categories_ouvertes.discard(cle)

    def _ouvrir_menu_contextuel(self, position):
        """Construit puis exécute l'action disponible pour l'anomalie choisie."""
        item = self.tree.itemAt(position)
        if item is None:
            return
        payload = item.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            return

        actions = self._actions_pour_payload(payload)
        if not actions:
            return

        menu = QMenu(self.tree)
        callbacks = {}
        for libelle, callback in actions:
            action_qt = menu.addAction(libelle)
            callbacks[action_qt] = callback

        action_choisie = menu.exec_(self.tree.viewport().mapToGlobal(position))
        callback = callbacks.get(action_choisie)
        if callback is None:
            return

        # Le Ctrl+Z reste celui de QGIS : on cible seulement la bonne couche.
        couche = self.plugin._trouver_couche()
        if couche_est_disponible(couche):
            self.plugin.iface.setActiveLayer(couche)

        callback()

        # Les formulaires modaux conservent leur focus. Sinon, rendre le focus à
        # la carte permet au Ctrl+Z natif QGIS de cibler la couche active.
        try:
            self.plugin.iface.mapCanvas().setFocus()
        except (AttributeError, RuntimeError):
            pass

    def _actions_pour_payload(self, payload):
        """Retourne les actions applicables à un élément de l'arbre.

        Chaque élément est un couple ``(libellé, callback)``. Le panneau décide
        seulement quelle action proposer ; la logique métier reste dans le module
        ``verification_*`` correspondant.
        """
        # Chaque bloc ci-dessous teste une clé de payload différente : les
        # modules verification_*.py posent des clés distinctes selon le type
        # d'élément cliqué (un groupe entier "lazy_category", un polygone
        # "small_fid", une paire "overlap_fids"...). Un seul bloc matche par
        # appel, dans l'ordre où ils sont écrits ici.
        lazy_category = payload.get("lazy_category")
        if lazy_category == "small":
            if verif_surface.visibles(self.plugin):
                return [(
                    "Tout fusionner avec le meilleur voisin",
                    lambda: verif_surface.fusionner_tous_avec_meilleur_voisin(self.plugin),
                )]

        if lazy_category == "adjacent":
            donnees = self.plugin._lazy_tree_data.get("adjacent", [])
            if donnees:
                return [(
                    "Tout fusionner",
                    lambda: verif_adjacents.fusionner_tous_groupes_adjacents(self.plugin),
                )]

        if lazy_category == "gaps":
            donnees = self.plugin._lazy_tree_data.get("gaps", [])
            if donnees:
                return [(
                    "Tout reboucher avec le meilleur voisin",
                    lambda: verif_trous.reboucher_tous_les_trous(self.plugin),
                )]

        small_fid = payload.get("small_fid")
        if isinstance(small_fid, int):
            return [("Fusionner avec…", lambda: verif_surface.fusionner_avec(
                self.plugin, small_fid
            ))]

        gap_index = payload.get("gap_index")
        if isinstance(gap_index, int):
            return [
                ("Créer un nouveau polygone", lambda: verif_trous.reboucher_trou(
                    self.plugin, gap_index
                )),
                ("Attribuer à…", lambda: verif_trous.attribuer_trou(
                    self.plugin, gap_index
                )),
            ]

        multipart_fid = payload.get("multipart_fid")
        if isinstance(multipart_fid, int):
            actions = [("Séparer les parties", lambda: verif_multiparties.separer_multipartie(
                self.plugin, multipart_fid
            ))]
            if verif_multiparties.peut_fusionner_multipartie(self.plugin, multipart_fid):
                actions.append(("Fusionner les parties", lambda: verif_multiparties.fusionner_multipartie(
                    self.plugin, multipart_fid
                )))
            return actions

        multipart_part = payload.get("multipart_part")
        if isinstance(multipart_part, (list, tuple)) and len(multipart_part) == 2:
            fid_parent, index_partie = multipart_part
            return [("Fusionner avec…", lambda: verif_multiparties.attribuer_partie_multipartie(
                self.plugin, fid_parent, index_partie
            ))]

        overlap_fids = payload.get("overlap_fids")
        if isinstance(overlap_fids, (list, tuple)) and len(overlap_fids) == 2:
            fids = tuple(overlap_fids)
            return [
                ("Attribuer à…", lambda: verif_recouvrements.attribuer_recouvrement(
                    self.plugin, fids
                )),
                ("Découper le recouvrement", lambda: verif_recouvrements.decouper_recouvrement(
                    self.plugin, fids
                )),
            ]

        adjacent_group_fids = payload.get("adjacent_group_fids")
        if isinstance(adjacent_group_fids, (list, tuple)) and len(adjacent_group_fids) >= 2:
            fids = tuple(adjacent_group_fids)
            return [("Fusionner le groupe", lambda: verif_adjacents.fusionner_groupe_adjacents(
                self.plugin, fids
            ))]

        adjacent_member_fid = payload.get("adjacent_member_fid")
        if isinstance(adjacent_member_fid, int):
            return [("Modifier les attributs", lambda: verif_adjacents.modifier_attributs_entite(
                self.plugin, adjacent_member_fid
            ))]

        coherence_fid = payload.get("coherence_fid")
        if isinstance(coherence_fid, int):
            return [("Modifier les attributs", lambda: verif_coherence.modifier_attributs_entite(
                self.plugin, coherence_fid
            ))]

        return []
