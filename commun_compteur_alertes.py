# -*- coding: utf-8 -*-
"""Mise à jour automatique des compteurs d'alertes liés aux polygones BD Forêt."""

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication, QProgressBar
from qgis.core import (
    NULL,
    Qgis,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsSpatialIndex,
)

from .commun_protection_vue import vue_stable_pendant_modification
from .commun_edition import fid_est_valide, surface_ha
from .commun_couches import (
    couche_est_disponible,
    trouver_couche_alertes,
    trouver_couche_travail,
)
from .commun_parametres import (
    CHAMP_CLASSEMENT,
    CHAMP_ID_FORET,
    CHAMP_SURFACE_A_RECALCULER,
    CRITERES_CLASSEMENT,
    DELAI_RECONNEXION_COUCHES_MS,
)
from .commun_synchronisation_alertes import (
    ResultatSynchronisation,
    edition_alertes_ouverte_par_plugin,
    ecriture_parent_interne_en_cours,
    marquer_edition_alertes_ouverte_par_plugin,
    oublier_edition_alertes_ouverte_par_plugin,
    priorite_numerique,
    synchroniser_zone,
    trouver_couche_alertes_associee,
)


# Déplacé depuis commun_classement.py (audit de placement avant transmission
# du code) : ce tri du classement global n'était utilisé que par ce fichier.
def valeur_nulle(valeur):
    """Retourne True pour les valeurs qui doivent rester à la fin du tri."""
    if valeur is None or valeur == NULL:
        return True
    return isinstance(valeur, str) and not valeur.strip()


def cle_valeur(valeur):
    """Normalise une valeur pour un tri stable numérique ou textuel."""
    if isinstance(valeur, bool):
        # bool est une sous-classe d'int en Python : ce test doit précéder
        # celui du float ci-dessous, sinon True/False seraient traités comme
        # des nombres arbitraires plutôt que comme 0/1 logiques.
        return (0, int(valeur))
    try:
        if not isinstance(valeur, str):
            return (0, float(valeur))
    except (TypeError, ValueError, OverflowError):
        pass
    # Repli texte : le tuple (1, ...) place toujours les valeurs textuelles
    # après les numériques (0, ...), qu'importe le contenu du texte.
    return (1, str(valeur))


def trier_donnees(donnees, criteres=CRITERES_CLASSEMENT):
    """Trie les éléments selon ``commun_parametres.py`` avec les NULL à la fin."""
    elements = list(donnees)

    def cle_stable(element):
        # Pré-tri par l'ancien classement (ou le fid à défaut) : Python trie
        # de façon stable, donc ce pré-tri garantit qu'à critères égaux plus
        # bas, l'ordre de départ reste prévisible plutôt que dépendant de
        # l'ordre d'arrivée du fournisseur de données.
        try:
            ancien = int(element.get("ancien_classement"))
            ancien_nul = 0
        except (TypeError, ValueError, OverflowError):
            ancien = int(element.get("fid", 0))
            ancien_nul = 1
        return (ancien_nul, ancien, int(element.get("fid", 0)))

    elements.sort(key=cle_stable)
    # CRITERES_CLASSEMENT est trié du plus important au moins important, mais
    # chaque tri Python est stable : en appliquant les critères du DERNIER au
    # PREMIER (reversed), le tri final respecte bien la priorité déclarée
    # (le tout dernier tri appliqué, le premier critère, l'emporte).
    for nom_champ, croissant in reversed(tuple(criteres)):
        presentes = []
        nulles = []
        for element in elements:
            valeur = element.get("valeurs", {}).get(nom_champ, NULL)
            if valeur_nulle(valeur):
                nulles.append(element)
            else:
                presentes.append(element)
        presentes.sort(
            key=lambda element, champ=nom_champ: cle_valeur(
                element.get("valeurs", {}).get(champ)
            ),
            reverse=not bool(croissant),
        )
        # Les NULL restent toujours en fin de liste, quel que soit le sens
        # (croissant ou décroissant) du critère.
        elements = presentes + nulles
    return elements


class CompteurAlertes:
    """Synchronise les indicateurs de lecture entre alertes et polygones.

    - une modification de ``vu`` recalcule les compteurs du polygone ;
    - avec des alertes, ``toutes_alertes_vues`` reflète leur état ``vu`` ;
    - sans alerte (0/0), ``toutes_alertes_vues`` reste une validation manuelle ;
    - cocher ``toutes_alertes_vues`` marque toutes les alertes liées comme vues.
    """

    NOM_CHAMP_VU = "vu"
    NOM_CHAMP_NB_ALERTES = "nb_alertes"
    NOM_CHAMP_NB_ALERTES_VUES = "nb_alertes_vues"
    NOM_CHAMP_TOUTES_ALERTES_VUES = "toutes_alertes_vues"
    # Même nom de champ des deux côtés, mais des couches différentes (la
    # relation QGIS "Alertes Centroides" -> "Bdfv3 Priorites").
    CHAMP_LIAISON_PARENT = CHAMP_ID_FORET
    CHAMP_LIAISON_ENFANT = CHAMP_ID_FORET
    # Regroupe les signaux rapprochés (plusieurs attributeValueChanged pour
    # une même édition) en un seul recalcul, au lieu d'un par signal.
    DELAI_RECALCUL_MS = 150
    DELAI_COMMANDE_PARENT_MS = 75

    def __init__(self, iface, historique=None):
        self.iface = iface
        self.historique = historique
        self.projet = QgsProject.instance()
        self._timer_connexion = QTimer()
        self._timer_connexion.setSingleShot(True)
        self._timer_connexion.setInterval(DELAI_RECONNEXION_COUCHES_MS)
        self._timer_connexion.timeout.connect(self.connecter_couches)
        self.couche_alertes = None
        self.couche_parent = None
        self.relation = None
        self.index_champ_vu = -1
        self.index_champ_toutes_alertes_vues = -1
        self.recalculs_programmes = set()
        self.recalculs_parents_programmes = set()
        self._mise_a_jour_parent_interne = False
        self._mise_a_jour_alertes_depuis_parent = False

        # Les clics sur ``toutes_alertes_vues`` arrivent depuis le formulaire
        # pendant que QGIS peut encore être en train de terminer sa propre
        # commande d'édition. On les met donc dans une petite file d'attente et
        # on ne touche aux alertes qu'une fois les commandes QGIS terminées.
        # Cela évite surtout d'imbriquer une commande sur la couche enfant dans
        # la commande attributaire encore active du parent.
        self._synchronisation_attributaire_en_cours = False
        self._commandes_parent_en_attente = {}
        self._timer_commandes_parent = QTimer()
        self._timer_commandes_parent.setSingleShot(True)
        self._timer_commandes_parent.setInterval(self.DELAI_COMMANDE_PARENT_MS)
        self._timer_commandes_parent.timeout.connect(
            self._traiter_commandes_parent_en_attente
        )

        # FID touchés pendant la commande géométrique en cours. Le signal
        # attributeValueChanged peut être émis lorsque QGIS recopie des attributs
        # lors d'un split/fusion : tant que le FID est dans cette commande,
        # ``toutes_alertes_vues`` n'est jamais interprété comme un clic utilisateur.
        self._fids_geometrie_commande = set()

        # Suivi permanent des géométries de la couche BD Forêt. Le panneau
        # Vérification peut être fermé : les compteurs et les id_foret doivent
        # tout de même rester cohérents après une coupe, un remodelage, une
        # création ou une suppression faite avec n'importe quel outil QGIS.
        self._emprises_parent = {}
        self._commande_parent_index_avant = None
        self._zone_geometrie_en_attente = None
        # True uniquement pour le filet de sécurité « géométrie modifiée hors
        # beginEditCommand/endEditCommand ». Lors d'un Ctrl+Z/Ctrl+Y, QGIS émet
        # aussi geometryChanged hors commande ; le changement d'index de la pile
        # permet alors d'annuler ce faux recalcul avant que son QTimer ne parte.
        self._recalcul_hors_commande_programme = False
        self._commande_parent_deja_synchronisee = False
        self._commande_recalcul_interne = False
        self._resultat_sync_geometrie = ResultatSynchronisation()
        self._synchronisation_geometrie_en_cours = False

        self._recalcul_global_en_cours = False
        # Un commit remet la QUndoStack du parent à zéro. Ce changement d'index
        # ne doit jamais être interprété comme un Ctrl+Z géométrique.
        self._commit_parent_en_cours = False

        # Certains outils maison (notamment Remodeler) remplacent eux-mêmes
        # une commande géométrique native afin d'y intégrer leur post-traitement.
        # Pendant cette courte phase, le recalcul géométrique automatique doit
        # rester silencieux, sinon il ajoute une commande sur la pile d'undo
        # avant que l'outil ait fini de traiter la commande native.
        self._suspensions_synchronisation_geometrique = 0

    def initGui(self):
        for signal in (
            self.projet.layersAdded,
            self.projet.layersRemoved,
            self.projet.readProject,
        ):
            try:
                signal.connect(self._programmer_connexion)
            except (TypeError, RuntimeError):
                pass
        try:
            self.projet.cleared.connect(self._projet_vide)
        except (TypeError, RuntimeError):
            pass
        self._timer_connexion.start(DELAI_RECONNEXION_COUCHES_MS)

    def unload(self):
        for signal, fonction in (
            (self.projet.layersAdded, self._programmer_connexion),
            (self.projet.layersRemoved, self._programmer_connexion),
            (self.projet.readProject, self._programmer_connexion),
            (self.projet.cleared, self._projet_vide),
        ):
            try:
                signal.disconnect(fonction)
            except (TypeError, RuntimeError):
                pass
        try:
            self._timer_connexion.stop()
        except RuntimeError:
            pass
        try:
            self._timer_commandes_parent.stop()
        except RuntimeError:
            pass
        self._commandes_parent_en_attente.clear()
        self.deconnecter_couches()
        self.recalculs_programmes.clear()
        self.recalculs_parents_programmes.clear()

    def _programmer_connexion(self, *args):
        # Débounce les rafales de layersAdded/layersRemoved lors d'un chargement
        # de projet : une seule recherche de couches est effectuée à la fin.
        self._timer_connexion.start(DELAI_RECONNEXION_COUCHES_MS)

    def _projet_vide(self, *args):
        self.deconnecter_couches()

    # ------------------------------------------------------------------
    # Connexion aux couches et à la relation
    # ------------------------------------------------------------------

    def connecter_couches(self):
        """Connecte le compteur si les couches nécessaires existent.

        Leur absence est normale dans certains projets et ne produit aucun
        message pour l'utilisateur.
        """
        couche_parent = trouver_couche_travail(self.iface)
        couche_alertes = (
            trouver_couche_alertes_associee(couche_parent, self.iface)
            if couche_parent is not None
            else None
        )
        if couche_alertes is None or couche_parent is None:
            self.deconnecter_couches()
            return

        if (
            self.couche_alertes is couche_alertes
            and self.couche_parent is couche_parent
        ):
            # Les signaux géométriques sont utiles même si la relation QGIS
            # n'est pas encore disponible. Lors d'un chargement de projet, la
            # relation peut apparaître quelques instants après les couches : on
            # la rafraîchit sans déconnecter le suivi spatial déjà en place.
            try:
                relation_valide = self.relation is not None and self.relation.isValid()
            except (AttributeError, RuntimeError):
                relation_valide = False
            if not relation_valide:
                self.relation = self._trouver_relation()
            return

        self.deconnecter_couches()
        self.couche_alertes = couche_alertes
        self.couche_parent = couche_parent
        self.index_champ_vu = couche_alertes.fields().indexOf(self.NOM_CHAMP_VU)
        if self.index_champ_vu < 0:
            self._avertir(
                f"Le champ « {self.NOM_CHAMP_VU} » n'existe pas dans « {couche_alertes.name()} »."
            )
            self.deconnecter_couches()
            return

        # La relation sert aux clics utilisateur sur ``vu`` et
        # ``toutes_alertes_vues``. Elle n'est PAS requise pour la
        # synchronisation spatiale après une modification géométrique.
        self.relation = self._trouver_relation()

        self.index_champ_toutes_alertes_vues = couche_parent.fields().indexOf(
            self.NOM_CHAMP_TOUTES_ALERTES_VUES
        )

        try:
            couche_alertes.attributeValueChanged.connect(self._attribut_alerte_modifie)
            couche_parent.attributeValueChanged.connect(self._attribut_parent_modifie)

            # Ces signaux restent actifs même lorsque le panneau Vérification
            # est fermé. Les événements géométriques ne lancent aucun calcul :
            # ils ne font qu'accumuler la zone, traitée une seule fois à la fin
            # de la commande d'édition.
            couche_parent.editCommandStarted.connect(self._commande_parent_demarre)
            couche_parent.editCommandEnded.connect(self._commande_parent_terminee)
            couche_parent.editCommandDestroyed.connect(self._commande_parent_detruite)
            couche_parent.geometryChanged.connect(self._geometrie_parent_modifiee)
            couche_parent.featureAdded.connect(self._entite_parent_ajoutee)
            couche_parent.featureDeleted.connect(self._entite_parent_supprimee)

            # Une opération géométrique peut modifier deux couches : BD Forêt
            # et Alertes Centroides. Lorsque le plugin a ouvert lui-même
            # l'édition des alertes, enregistrer la BD Forêt doit enregistrer
            # aussi ces rattachements enfant ; sinon ils resteraient seulement
            # dans le tampon d'édition et la relation pourrait sembler se
            # "défaire" après l'enregistrement.
            try:
                couche_parent.beforeCommitChanges.connect(
                    self._avant_enregistrement_parent
                )
                couche_parent.afterCommitChanges.connect(
                    self._apres_enregistrement_parent
                )
            except (AttributeError, TypeError, RuntimeError):
                pass

        except (TypeError, RuntimeError, AttributeError):
            self.deconnecter_couches()

    def deconnecter_couches(self):
        # Oublier d'abord les wrappers : une couche peut avoir été détruite par
        # QGIS lors d'un changement de projet avant que le service soit prévenu.
        couche_alertes = self.couche_alertes
        couche_parent = self.couche_parent
        self.couche_alertes = None
        self.couche_parent = None

        if couche_est_disponible(couche_alertes):
            try:
                couche_alertes.attributeValueChanged.disconnect(
                    self._attribut_alerte_modifie
                )
            except (TypeError, RuntimeError):
                pass
        if couche_est_disponible(couche_parent):
            for signal_nom, slot in (
                ("attributeValueChanged", self._attribut_parent_modifie),
                ("editCommandStarted", self._commande_parent_demarre),
                ("editCommandEnded", self._commande_parent_terminee),
                ("editCommandDestroyed", self._commande_parent_detruite),
                ("geometryChanged", self._geometrie_parent_modifiee),
                ("featureAdded", self._entite_parent_ajoutee),
                ("featureDeleted", self._entite_parent_supprimee),
                ("beforeCommitChanges", self._avant_enregistrement_parent),
                ("afterCommitChanges", self._apres_enregistrement_parent),
            ):
                try:
                    getattr(couche_parent, signal_nom).disconnect(slot)
                except (TypeError, RuntimeError, AttributeError):
                    pass

        self.relation = None
        self.index_champ_vu = -1
        self.index_champ_toutes_alertes_vues = -1
        self.recalculs_programmes.clear()
        self.recalculs_parents_programmes.clear()
        self._mise_a_jour_parent_interne = False
        self._mise_a_jour_alertes_depuis_parent = False
        self._synchronisation_attributaire_en_cours = False
        self._commandes_parent_en_attente.clear()
        try:
            self._timer_commandes_parent.stop()
        except RuntimeError:
            pass
        self._fids_geometrie_commande.clear()
        self._emprises_parent.clear()
        self._commande_parent_index_avant = None
        self._zone_geometrie_en_attente = None
        self._recalcul_hors_commande_programme = False
        self._commande_parent_deja_synchronisee = False
        self._commande_recalcul_interne = False
        self._resultat_sync_geometrie = ResultatSynchronisation()
        self._synchronisation_geometrie_en_cours = False
        self._commit_parent_en_cours = False
        self._suspensions_synchronisation_geometrique = 0

    def suspendre_synchronisation_geometrique(self):
        """Suspend temporairement le recalcul spatial automatique.

        Utilisé par les outils qui gèrent eux-mêmes la synchronisation des
        alertes dans leur commande d'édition. La suspension est comptée afin
        de rester sûre si deux appels sont imbriqués.
        """
        self._suspensions_synchronisation_geometrique += 1
        self._zone_geometrie_en_attente = None
        self._commande_parent_index_avant = None
        self._recalcul_hors_commande_programme = False
        self._commande_parent_deja_synchronisee = False
        self._resultat_sync_geometrie = ResultatSynchronisation()

    def reprendre_synchronisation_geometrique(self):
        """Réactive le recalcul spatial automatique après une suspension."""
        if self._suspensions_synchronisation_geometrique > 0:
            self._suspensions_synchronisation_geometrique -= 1
        if self._suspensions_synchronisation_geometrique == 0:
            # Le prochain signal géométrique suffit à reconstruire la zone locale.
            self._emprises_parent.clear()

    def _synchronisation_geometrique_suspendue(self):
        return self._suspensions_synchronisation_geometrique > 0

    def synchroniser_modification_geometrique(
        self, couche_parent, geometrie_zone, nom_commande
    ):
        """Synchronise les alertes après une modification géométrique explicite.

        Les outils maison peuvent appeler cette méthode lorsqu'ils doivent
        suspendre temporairement l'écoute automatique des commandes QGIS
        (Remodeler, par exemple). La règle reste ainsi centralisée : les ``vu``
        des alertes ne sont jamais modifiés par une géométrie, tandis que
        ``id_foret``, les compteurs, la priorité et ``toutes_alertes_vues`` sont
        recalculés depuis la position réelle des points.
        """
        if not couche_est_disponible(couche_parent):
            return ResultatSynchronisation()
        if geometrie_zone is None or geometrie_zone.isEmpty():
            return ResultatSynchronisation()

        ancien_interne = self._mise_a_jour_parent_interne
        self._mise_a_jour_parent_interne = True
        try:
            resultat = synchroniser_zone(
                self.iface,
                couche_parent,
                geometrie_zone,
                nom_commande,
            )
        finally:
            self._mise_a_jour_parent_interne = ancien_interne

        if resultat is None:
            resultat = ResultatSynchronisation()

        # Si l'appel a lieu dans une commande parent que le compteur suit,
        # signaler que les indicateurs ont déjà été recalculés afin d'éviter un
        # deuxième balayage spatial à editCommandEnded.
        if couche_parent is self.couche_parent:
            try:
                if couche_parent.isEditCommandActive():
                    self._commande_parent_deja_synchronisee = True
            except (AttributeError, RuntimeError):
                pass

        return resultat

    def _trouver_relation(self):
        for relation in self.projet.relationManager().relations().values():
            try:
                if not relation.isValid():
                    continue
                if relation.referencingLayer() is not self.couche_alertes:
                    continue
                if relation.referencedLayer() is not self.couche_parent:
                    continue
                if (
                    relation.fieldPairs().get(self.CHAMP_LIAISON_ENFANT)
                    != self.CHAMP_LIAISON_PARENT
                ):
                    continue
                return relation
            except (AttributeError, RuntimeError, TypeError):
                continue
        return None

    def _avant_enregistrement_parent(self, *args):
        """Protège le suivi Undo pendant le reset de pile provoqué par QGIS."""
        self._commit_parent_en_cours = True
        # Un commit en échec peut ne pas produire afterCommitChanges. Dans ce
        # cas, réarmer le suivi au tour de boucle suivant, sans perdre l'historique.
        try:
            QTimer.singleShot(0, self._terminer_garde_commit_parent)
        except (RuntimeError, TypeError):
            pass

    def _terminer_garde_commit_parent(self):
        if not self._commit_parent_en_cours:
            return
        self._commit_parent_en_cours = False

    def _reinitialiser_suivi_apres_commit_parent(self):
        """Oublie uniquement les index Undo devenus invalides après sauvegarde."""
        self._commit_parent_en_cours = False
        self._recalcul_hors_commande_programme = False
        self._zone_geometrie_en_attente = None
        self._commande_parent_index_avant = None
        self._commande_parent_deja_synchronisee = False
        self._resultat_sync_geometrie = ResultatSynchronisation()
        self._emprises_parent.clear()

    def _apres_enregistrement_parent(self, *args):
        """Valide les alertes que le plugin a modifiées avec la BD Forêt.

        QGIS possède un tampon d'édition par couche. Les outils du plugin
        réalignent ``id_foret`` sur Alertes Centroides pendant que la BD Forêt
        reste la couche active. Si cette session enfant a été ouverte par le
        plugin, on la valide juste après un commit réussi du parent. Une couche
        d'alertes qui était déjà en édition avant l'opération n'est jamais
        enregistrée automatiquement.
        """
        # Le commit parent est terminé : sa pile d'annulation a changé de
        # référentiel. Ne jamais parcourir ces anciens index comme un Undo/Redo.
        self._reinitialiser_suivi_apres_commit_parent()

        couche_parent = self.couche_parent
        couche_alertes = (
            trouver_couche_alertes_associee(couche_parent, self.iface)
            if couche_parent is not None
            else None
        )
        if not couche_est_disponible(couche_alertes):
            return
        if not edition_alertes_ouverte_par_plugin(couche_alertes):
            return

        try:
            if not couche_alertes.isEditable():
                oublier_edition_alertes_ouverte_par_plugin(couche_alertes)
                return
            if self._commande_edition_active(couche_alertes):
                # Cas extrêmement rare : laisser la session ouverte plutôt que
                # d'interrompre une commande encore active. Le prochain commit
                # parent retentera l'enregistrement.
                self._avertir(
                    "Les alertes n'ont pas encore pu être enregistrées car une "
                    "commande d'édition est toujours active sur leur couche."
                )
                return

            # Si l'utilisateur a seulement cliqué sur « Enregistrer les
            # modifications » sans quitter le mode édition, conserver aussi la
            # couche enfant en édition. Si le parent vient de sortir du mode
            # édition, fermer également la session enfant ouverte par le plugin.
            conserver_edition = False
            try:
                conserver_edition = bool(
                    couche_parent is not None and couche_parent.isEditable()
                )
            except (AttributeError, RuntimeError, TypeError):
                conserver_edition = False

            if not couche_alertes.commitChanges(not conserver_edition):
                erreurs = []
                try:
                    erreurs = list(couche_alertes.commitErrors())
                except (AttributeError, RuntimeError, TypeError):
                    pass
                detail = " ; ".join(str(v) for v in erreurs if str(v).strip())
                message = "Les modifications de la couche d'alertes n'ont pas pu être enregistrées."
                if detail:
                    message += " " + detail
                self._avertir(message)
                return

            if not conserver_edition:
                oublier_edition_alertes_ouverte_par_plugin(couche_alertes)

            try:
                couche_alertes.triggerRepaint(True)
            except RuntimeError:
                pass
        except (AttributeError, RuntimeError, TypeError) as exc:
            self._avertir(
                f"Impossible d'enregistrer automatiquement les rattachements des alertes : {exc}"
            )

    # ------------------------------------------------------------------
    # Synchronisation spatiale après toute modification géométrique
    # ------------------------------------------------------------------

    def _emprise_originale_parent(self, fid):
        """Lit ponctuellement l'emprise enregistrée avant le premier changement.

        Aucun cache global de la BD Forêt n'est construit au chargement du plugin.
        Pour le premier changement d'un FID, on interroge directement le provider
        (hors tampon d'édition), puis les changements suivants réutilisent le petit
        cache des seuls FID effectivement touchés.
        """
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return None
        cached = self._emprises_parent.get(fid)
        if cached is not None:
            return QgsRectangle(cached)
        if not couche_est_disponible(self.couche_parent) or fid < 0:
            return None
        try:
            provider = self.couche_parent.dataProvider()
            if provider is None:
                return None
            request = QgsFeatureRequest().setFilterFid(fid).setNoAttributes()
            entite = next(provider.getFeatures(request), None)
            if entite is None or not entite.isValid() or not entite.hasGeometry():
                return None
            geometrie = entite.geometry()
            if geometrie is None or geometrie.isEmpty():
                return None
            return QgsRectangle(geometrie.boundingBox())
        except (AttributeError, RuntimeError, TypeError):
            return None

    @staticmethod
    def _fusionner_rectangles(rectangle_a, rectangle_b):
        if rectangle_a is None:
            return QgsRectangle(rectangle_b) if rectangle_b is not None else None
        resultat = QgsRectangle(rectangle_a)
        if rectangle_b is not None:
            resultat.combineExtentWith(rectangle_b)
        return resultat

    def _commande_parent_demarre(self, _texte=None):
        """Prépare une zone locale pour la commande géométrique en cours.

        La synchronisation spatiale n'est plus liée à la pile Ctrl+Z. Les
        signaux de géométrie accumulent simplement l'ancienne et la nouvelle
        emprise, puis un seul recalcul est lancé à la fin de la commande.
        """
        self._fids_geometrie_commande.clear()
        if self._synchronisation_geometrique_suspendue():
            return
        if self._commande_recalcul_interne:
            return
        self._zone_geometrie_en_attente = None
        self._recalcul_hors_commande_programme = False
        self._commande_parent_deja_synchronisee = False
        self._resultat_sync_geometrie = ResultatSynchronisation()

    def _commande_parent_terminee(self):
        """Synchronise une fois la zone après une vraie commande géométrique."""
        if self._synchronisation_geometrique_suspendue():
            return
        if self._commande_recalcul_interne:
            return

        rectangle = self._zone_geometrie_en_attente
        deja_synchronisee = self._commande_parent_deja_synchronisee
        self._zone_geometrie_en_attente = None
        self._commande_parent_index_avant = None
        self._recalcul_hors_commande_programme = False
        self._commande_parent_deja_synchronisee = False
        self._resultat_sync_geometrie = ResultatSynchronisation()
        self._fids_geometrie_commande.clear()

        if rectangle is None or rectangle.isEmpty():
            return
        if deja_synchronisee:
            return
        self._executer_recalcul_geometrique_differe(rectangle)

    def _commande_parent_detruite(self):
        """Resynchronise aussi lorsqu'une commande active est détruite.

        ``destroyEditCommand()`` remet la géométrie dans son état précédent.
        Les alertes étant un état dérivé et non une commande Undo, on rejoue la
        jointure sur la zone qui venait d'être touchée.
        """
        if self._synchronisation_geometrique_suspendue():
            return
        if self._commande_recalcul_interne:
            return
        rectangle = self._zone_geometrie_en_attente
        self._zone_geometrie_en_attente = None
        self._commande_parent_index_avant = None
        self._recalcul_hors_commande_programme = False
        self._commande_parent_deja_synchronisee = False
        self._resultat_sync_geometrie = ResultatSynchronisation()
        self._fids_geometrie_commande.clear()
        if rectangle is not None and not rectangle.isEmpty():
            QTimer.singleShot(0, lambda r=QgsRectangle(rectangle): self._executer_recalcul_geometrique_differe(r))

    def _memoriser_zone_geometrique(self, rectangle):
        """Agrège une zone et déclenche la jointure spatiale après le signal.

        Cette méthode est volontairement indépendante de la QUndoStack. Un
        Ctrl+Z ou Ctrl+Y modifie lui aussi la géométrie et repasse donc par le
        même chemin qu'une modification normale.
        """
        if self._synchronisation_geometrique_suspendue():
            return
        if rectangle is None or rectangle.isEmpty():
            return
        if self._commande_recalcul_interne or self._synchronisation_geometrie_en_cours:
            return

        self._zone_geometrie_en_attente = self._fusionner_rectangles(
            self._zone_geometrie_en_attente, rectangle
        )

        try:
            commande_active = self.couche_parent.isEditCommandActive()
        except (AttributeError, RuntimeError):
            commande_active = False

        # Pour un outil QGIS normal, editCommandEnded fera le recalcul. Pour un
        # undo/redo (ou une modification hors commande), aucun editCommandEnded
        # n'est garanti : le QTimer regroupe tous les signaux du même tour Qt.
        if not commande_active and not self._recalcul_hors_commande_programme:
            self._recalcul_hors_commande_programme = True
            QTimer.singleShot(0, self._terminer_recalcul_hors_commande)

    def _terminer_recalcul_hors_commande(self):
        """Traite les changements hors commande, notamment Ctrl+Z et Ctrl+Y."""
        if self._commande_recalcul_interne:
            return
        if not self._recalcul_hors_commande_programme:
            return
        rectangle = self._zone_geometrie_en_attente
        self._zone_geometrie_en_attente = None
        self._commande_parent_index_avant = None
        self._recalcul_hors_commande_programme = False
        if rectangle is None or rectangle.isEmpty():
            return
        self._executer_recalcul_geometrique_differe(rectangle)

    def _executer_recalcul_geometrique_differe(self, rectangle, *_args):
        """Recalcule les données dérivées sans créer de commande Ctrl+Z.

        La géométrie est la seule source de vérité. Les id_foret des alertes et
        les compteurs du parent sont remis en cohérence avec l'état géométrique
        courant, que cet état provienne d'une modification, d'un Undo ou d'un
        Redo.
        """
        if self._synchronisation_geometrie_en_cours:
            return
        if rectangle is None or rectangle.isEmpty():
            return
        if not couche_est_disponible(self.couche_parent):
            return

        zone = QgsGeometry.fromRect(rectangle)
        resultat = ResultatSynchronisation()
        self._synchronisation_geometrie_en_cours = True
        self._mise_a_jour_parent_interne = True
        self._commande_recalcul_interne = True
        try:
            # IMPORTANT : aucun beginEditCommand/endEditCommand ici. Ce
            # recalcul est un état dérivé, pas une action utilisateur. Il ne
            # doit donc jamais ajouter une marche dans Ctrl+Z.
            resultat = synchroniser_zone(
                self.iface,
                self.couche_parent,
                zone,
                "Mettre à jour les alertes après modification géométrique",
            )

            for fid_parent in getattr(resultat, "fids_parents", set()):
                self._rafraichir_formulaire_parent(int(fid_parent))

        except Exception as exc:
            self._avertir(
                f"La mise à jour spatiale des alertes après modification "
                f"géométrique a échoué : {exc}"
            )
        finally:
            self._commande_recalcul_interne = False
            self._mise_a_jour_parent_interne = False
            self._synchronisation_geometrie_en_cours = False

        try:
            self.couche_parent.triggerRepaint(True)
            if couche_est_disponible(self.couche_alertes):
                self.couche_alertes.triggerRepaint(True)
        except RuntimeError:
            pass

    def _geometrie_parent_modifiee(self, fid, geometrie):
        """Signal geometryChanged : accumule l'ancienne ET la nouvelle emprise.

        Les deux sont nécessaires : la nouvelle pour retrouver les alertes qui
        doivent maintenant appartenir à ce polygone, l'ancienne pour retrouver
        celles qui lui appartenaient et doivent être réévaluées même si elles
        ne sont plus dans la nouvelle emprise (voir _memoriser_zone_geometrique).
        """
        fid = int(fid)
        self._fids_geometrie_commande.add(fid)
        ancienne = self._emprises_parent.get(fid)
        if ancienne is None:
            ancienne = self._emprise_originale_parent(fid)
        nouvelle = None
        try:
            if geometrie is not None and not geometrie.isEmpty():
                nouvelle = QgsRectangle(geometrie.boundingBox())
        except (AttributeError, RuntimeError):
            nouvelle = None

        zone = self._fusionner_rectangles(ancienne, nouvelle)
        if nouvelle is None:
            self._emprises_parent.pop(fid, None)
        else:
            # Mémorise la nouvelle emprise pour le PROCHAIN changement de ce
            # même fid (plusieurs geometryChanged peuvent arriver pour la
            # même entité dans une seule commande).
            self._emprises_parent[fid] = QgsRectangle(nouvelle)
        self._memoriser_zone_geometrique(zone)

    def _entite_parent_ajoutee(self, fid):
        """Signal featureAdded : une entité neuve (Créer, Séparer) a besoin
        d'être synchronisée comme n'importe quelle géométrie modifiée."""
        fid = int(fid)
        self._fids_geometrie_commande.add(fid)
        rectangle = None
        try:
            entite = self.couche_parent.getFeature(fid)
            if entite is not None and entite.isValid() and entite.hasGeometry():
                geometrie = entite.geometry()
                if geometrie is not None and not geometrie.isEmpty():
                    rectangle = QgsRectangle(geometrie.boundingBox())
                    self._emprises_parent[fid] = QgsRectangle(rectangle)
        except (AttributeError, RuntimeError, TypeError):
            rectangle = None
        self._memoriser_zone_geometrique(rectangle)

    def _entite_parent_supprimee(self, fid):
        fid = int(fid)
        # Filet de sécurité global : même si la suppression vient d'un autre
        # outil que ceux de Reprise PI, aucune table attributaire ne doit rester
        # attachée à ce FID après sa disparition. La correction est différée pour
        # laisser le modèle QgsDualView intégrer la suppression, sans toucher à
        # l'emprise de carte.
        if self.historique is not None:
            try:
                QTimer.singleShot(
                    0,
                    lambda couche=self.couche_parent, f=fid:
                        self.historique.assainir_fiche_apres_suppression(couche, f),
                )
                QTimer.singleShot(
                    80,
                    lambda couche=self.couche_parent, f=fid:
                        self.historique.assainir_fiche_apres_suppression(couche, f),
                )
            except (AttributeError, RuntimeError, TypeError):
                pass

        self.recalculs_parents_programmes.discard(fid)
        rectangle = self._emprises_parent.pop(fid, None)
        if rectangle is None:
            rectangle = self._emprise_originale_parent(fid)
        self._memoriser_zone_geometrique(rectangle)

    # ------------------------------------------------------------------
    # Recalcul des compteurs
    # ------------------------------------------------------------------

    def _attribut_alerte_modifie(self, fid, index_champ, nouvelle_valeur):
        """Signal attributeValueChanged de la couche d'alertes : ne réagit
        qu'à un changement du champ "vu" (voir index_champ_vu)."""
        if self._synchronisation_attributaire_en_cours:
            return
        if self._mise_a_jour_alertes_depuis_parent:
            return
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return
        if not fid_est_valide(self.couche_alertes, fid):
            self.recalculs_programmes.discard(fid)
            return
        if index_champ != self.index_champ_vu or fid in self.recalculs_programmes:
            return

        # ``vu`` est l'unique source de vérité. Un seul recalcul du parent met
        # à jour nb_alertes, nb_alertes_vues et toutes_alertes_vues ensemble.
        self.recalculs_programmes.add(fid)
        QTimer.singleShot(
            self.DELAI_RECALCUL_MS,
            lambda fid_alerte=fid: self._recalculer_parent(fid_alerte),
        )

    def _attribut_parent_modifie(self, fid, index_champ, nouvelle_valeur):
        """Traite uniquement un clic utilisateur sur ``toutes_alertes_vues``.

        Règle unique :
        - ``vu`` des alertes est la source de vérité ;
        - cocher ``toutes_alertes_vues`` est une commande utilisateur qui met
          toutes les alertes liées à ``vu = true`` ;
        - décocher le parent ne décoche jamais les alertes : le champ est simplement
          recalculé depuis leur état réel ;
        - les copies d'attributs produites pendant une opération géométrique ne
          sont jamais interprétées comme un clic utilisateur.
        """
        if self._synchronisation_attributaire_en_cours:
            return
        if self._mise_a_jour_parent_interne:
            return
        if ecriture_parent_interne_en_cours(self.couche_parent):
            return
        if index_champ != self.index_champ_toutes_alertes_vues:
            return

        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return
        if not fid_est_valide(self.couche_parent, fid):
            self.recalculs_parents_programmes.discard(fid)
            return

        # Split/fusion/remodelage peuvent recopier le booléen du parent. Tant que
        # le FID appartient à la commande géométrique en cours, ce changement est
        # technique et ne doit jamais pousser ``True`` vers les alertes.
        if (
            fid in self._fids_geometrie_commande
            or self._synchronisation_geometrie_en_cours
            or self._commande_recalcul_interne
        ):
            return

        # Conserver uniquement la dernière intention si l'utilisateur clique
        # plusieurs fois avant que QGIS ait terminé sa commande de formulaire.
        self.recalculs_parents_programmes.add(fid)
        self._commandes_parent_en_attente[fid] = self._convertir_en_booleen(
            nouvelle_valeur
        )
        self._timer_commandes_parent.start(self.DELAI_COMMANDE_PARENT_MS)

    @staticmethod
    def _commande_edition_active(couche):
        """Indique si QGIS est encore dans un beginEditCommand/endEditCommand."""
        if couche is None:
            return False
        try:
            return bool(couche.isEditCommandActive())
        except (AttributeError, RuntimeError, TypeError):
            return False

    def _traiter_commandes_parent_en_attente(self):
        """Traite les clics parent hors de la pile d'appel du formulaire QGIS.

        Le formulaire peut émettre ``attributeValueChanged`` avant d'avoir clos
        sa commande d'édition. Démarrer à cet instant une commande sur la couche
        d'alertes peut imbriquer les modèles d'édition parent/enfant et provoquer
        des réentrances Qt. On attend donc explicitement que les deux couches
        soient sorties de leurs commandes avant d'appliquer la synchronisation.
        """
        if not self._commandes_parent_en_attente:
            return
        if self._synchronisation_attributaire_en_cours:
            self._timer_commandes_parent.start(self.DELAI_COMMANDE_PARENT_MS)
            return
        if self.couche_alertes is None or self.couche_parent is None or self.relation is None:
            for fid in self._commandes_parent_en_attente:
                self.recalculs_parents_programmes.discard(int(fid))
            self._commandes_parent_en_attente.clear()
            return

        # Ne jamais ouvrir une deuxième commande d'édition tant qu'un formulaire
        # ou un autre outil QGIS n'a pas terminé la sienne.
        if (
            self._commande_edition_active(self.couche_parent)
            or self._commande_edition_active(self.couche_alertes)
        ):
            self._timer_commandes_parent.start(self.DELAI_COMMANDE_PARENT_MS)
            return

        commandes = list(self._commandes_parent_en_attente.items())
        self._commandes_parent_en_attente.clear()
        for fid_parent, valeur_demandee in commandes:
            self._traiter_toutes_alertes_vues_parent(fid_parent, valeur_demandee)

    def _traiter_toutes_alertes_vues_parent(self, fid_parent, valeur_demandee):
        """Applique une commande utilisateur sans réentrance de signaux."""
        fid_parent = int(fid_parent)
        self.recalculs_parents_programmes.discard(fid_parent)
        if self.couche_alertes is None or self.couche_parent is None or self.relation is None:
            return
        if not fid_est_valide(self.couche_parent, fid_parent):
            return
        if self._synchronisation_attributaire_en_cours:
            return

        self._synchronisation_attributaire_en_cours = True
        try:
            parent = self.couche_parent.getFeature(fid_parent)
            if parent is None or not parent.isValid():
                return
            try:
                requete_alertes = self.relation.getRelatedFeaturesRequest(parent)
                nombre_alertes = sum(1 for _ in self.couche_alertes.getFeatures(requete_alertes))
            except Exception:
                nombre_alertes = -1

            if nombre_alertes == 0:
                # Sans alerte, le booléen est une validation manuelle de
                # l'opérateur : surtout ne pas l'écraser par un faux calcul
                # automatique ``0 > 0``. Les compteurs restent recalculables.
                self._recalculer_parent_direct(fid_parent)
                return

            if bool(valeur_demandee):
                # Seul ce clic manuel pousse une information du parent vers les
                # alertes : toutes les alertes liées deviennent vues.
                self._marquer_toutes_alertes_vues(fid_parent)
            else:
                # Décocher le parent n'est jamais une commande « tout décocher ».
                # On restitue simplement l'état calculé depuis les ``vu`` réels.
                self._recalculer_parent_direct(fid_parent)
        finally:
            self._synchronisation_attributaire_en_cours = False

    def _marquer_toutes_alertes_vues(self, fid_parent):
        """Met ``vu = true`` sur toutes les alertes liées au polygone."""
        self.recalculs_parents_programmes.discard(int(fid_parent))
        if self.couche_alertes is None or self.couche_parent is None or self.relation is None:
            return

        parent = self.couche_parent.getFeature(int(fid_parent))
        if parent is None or not parent.isValid():
            return

        try:
            requete_alertes = self.relation.getRelatedFeaturesRequest(parent)
            alertes = list(self.couche_alertes.getFeatures(requete_alertes))
        except Exception:
            return

        a_modifier = [
            alerte for alerte in alertes
            if not self._convertir_en_booleen(alerte[self.NOM_CHAMP_VU])
        ]
        if not a_modifier:
            self._recalculer_parent_direct(int(fid_parent))
            return

        if not self.couche_alertes.isEditable():
            if not self.couche_alertes.startEditing():
                self._avertir(
                    f"La couche « {self.couche_alertes.name()} » ne peut pas être placée en mode édition."
                )
                self._recalculer_parent_direct(int(fid_parent))
                return
            marquer_edition_alertes_ouverte_par_plugin(self.couche_alertes)

        commande_ouverte = False
        self._mise_a_jour_alertes_depuis_parent = True
        try:
            self.couche_alertes.beginEditCommand("Marquer toutes les alertes comme vues")
            commande_ouverte = True
            for alerte in a_modifier:
                fid_alerte = int(alerte.id())
                if not fid_est_valide(self.couche_alertes, fid_alerte):
                    continue
                ancienne_valeur = alerte[self.NOM_CHAMP_VU]
                if not self.couche_alertes.changeAttributeValue(
                    fid_alerte,
                    self.index_champ_vu,
                    True,
                    ancienne_valeur,
                    True,
                ):
                    raise RuntimeError(
                        f"l'alerte {alerte.id()} n'a pas pu être marquée comme vue"
                    )
            self.couche_alertes.endEditCommand()
            commande_ouverte = False
        except Exception as exc:
            if commande_ouverte:
                try:
                    self.couche_alertes.destroyEditCommand()
                except (AttributeError, RuntimeError):
                    pass
            self._avertir(f"Impossible de marquer toutes les alertes comme vues : {exc}")
        finally:
            self._mise_a_jour_alertes_depuis_parent = False

        self.couche_alertes.triggerRepaint(True)
        self._recalculer_parent_direct(int(fid_parent))

    @vue_stable_pendant_modification
    def recalculer_tous_les_compteurs(self):
        """Vérifie spatialement tous les rattachements puis recalcule les compteurs.

        Le bouton constitue le filet de sécurité global du projet :
        1. ``id_foret`` est contrôlé sur toute la couche BD Forêt ; les valeurs
           vides et les doublons sont réparés avec de nouveaux identifiants uniques ;
        2. un index spatial unique est construit sur la couche BD Forêt ;
        3. chaque point d'alerte est testé contre les polygones candidats ;
        4. ``id_foret`` des alertes est réaligné sur le polygone qui les contient ;
        5. un point qui ne coupe plus aucun polygone reçoit ``NULL`` ;
        6. ``nb_alertes_vues`` et ``toutes_alertes_vues`` sont recalculés
           uniquement depuis l'état réel des champs ``vu`` des alertes ;
        7. ``classement`` est recalculé selon ``CRITERES_CLASSEMENT`` dans commun_parametres.py.

        Aucun calcul global n'est lancé automatiquement : ce traitement n'a lieu
        que lorsque l'utilisateur clique sur le bouton de resynchronisation.
        Une barre de progression dans la barre de messages indique l'avancement.
        """
        if self._recalcul_global_en_cours:
            self.iface.messageBar().pushInfo(
                "Compteurs d'alertes",
                "Une vérification spatiale globale est déjà en cours.",
            )
            return

        couche_parent = self.couche_parent
        couche_alertes = self.couche_alertes
        if not couche_est_disponible(couche_parent):
            couche_parent = trouver_couche_travail(self.iface)
        if not couche_est_disponible(couche_alertes):
            couche_alertes = trouver_couche_alertes(self.iface)
        if not couche_est_disponible(couche_parent) or not couche_est_disponible(couche_alertes):
            self._avertir(
                "Les couches BD Forêt et Alertes Centroides doivent être présentes dans le projet."
            )
            return

        champs_parent = couche_parent.fields()
        champs_alertes = couche_alertes.fields()
        index_id_parent = champs_parent.indexOf(self.CHAMP_LIAISON_PARENT)
        index_id_alerte = champs_alertes.indexOf(self.CHAMP_LIAISON_ENFANT)
        index_vu = champs_alertes.indexOf(self.NOM_CHAMP_VU)
        index_priorite = champs_alertes.indexOf("priorite")
        index_essence_v2_alerte = champs_alertes.indexOf("ESSENCE_V2")
        index_total = champs_parent.indexOf(self.NOM_CHAMP_NB_ALERTES)
        index_vues = champs_parent.indexOf(self.NOM_CHAMP_NB_ALERTES_VUES)
        index_priorite_max = champs_parent.indexOf("priorite_max")
        index_essence_v2_priorite = champs_parent.indexOf("essence_v2_priorite_max")
        index_toutes = champs_parent.indexOf(self.NOM_CHAMP_TOUTES_ALERTES_VUES)
        index_classement = champs_parent.indexOf(CHAMP_CLASSEMENT)
        indices_criteres_classement = {
            nom_champ: champs_parent.indexOf(nom_champ)
            for nom_champ, _croissant in CRITERES_CLASSEMENT
        }
        index_surface_recalcul = (
            champs_parent.indexOf(CHAMP_SURFACE_A_RECALCULER)
            if CHAMP_SURFACE_A_RECALCULER
            else -1
        )

        champs_obligatoires = {
            "id_foret (BD Forêt)": index_id_parent,
            "id_foret (alertes)": index_id_alerte,
            self.NOM_CHAMP_NB_ALERTES: index_total,
            self.NOM_CHAMP_NB_ALERTES_VUES: index_vues,
            self.NOM_CHAMP_VU + " (alertes)": index_vu,
        }
        absents = [nom for nom, index in champs_obligatoires.items() if index < 0]
        if absents:
            self._avertir("Champs absents : " + ", ".join(absents) + ".")
            return

        self._recalcul_global_en_cours = True
        # Progression visible dans la barre de messages QGIS. On reste sur le
        # thread principal, car QgsVectorLayer n'est pas sûr à manipuler depuis
        # un thread de fond, mais on rend régulièrement la main à Qt afin que la
        # barre avance et que QGIS ne donne pas l'impression d'être figé.
        message_progression = None
        progression = None
        try:
            message_progression = self.iface.messageBar().createMessage(
                "Compteurs d'alertes",
                "Vérification spatiale des alertes…",
            )
            progression = QProgressBar()
            progression.setRange(0, 100)
            progression.setValue(0)
            progression.setTextVisible(True)
            progression.setMinimumWidth(260)
            progression.setAlignment(Qt.AlignCenter)
            progression.setFormat("Préparation — %p%")
            message_progression.layout().addWidget(progression)
            self.iface.messageBar().pushWidget(
                message_progression,
                level=Qgis.Info,
                duration=0,
            )
            QApplication.processEvents()
        except (AttributeError, RuntimeError, TypeError):
            message_progression = None
            progression = None

        def avancer(debut, fin, position, total, libelle):
            if progression is None:
                return
            total = max(1, int(total))
            position = min(max(0, int(position)), total)
            valeur = int(debut + (fin - debut) * (position / total))
            try:
                progression.setFormat(f"{libelle} — %p%")
                progression.setValue(max(0, min(100, valeur)))
                # Mise à jour assez fréquente pour être visible, sans pénaliser
                # le traitement par un processEvents() à chaque entité.
                if position == total or position % 75 == 0:
                    QApplication.processEvents()
            except RuntimeError:
                pass

        commande_alertes_ouverte = False
        commande_parent_ouverte = False
        try:
            nb_alertes = max(0, int(couche_alertes.featureCount()))

            # --------------------------------------------------------------
            # 1. Contrôler l'unicité de id_foret puis construire l'index.
            #
            # Le moteur QGIS recopie les attributs du parent lors d'un split.
            # Si le post-traitement du split a été interrompu (ancienne version,
            # crash, annulation partielle...), plusieurs polygones peuvent donc
            # partager la même clé de relation. Le recalcul global répare ce cas
            # AVANT de redistribuer les alertes :
            # - la première occurrence (FID le plus petit) conserve sa clé ;
            # - chaque occurrence suivante reçoit un nouvel id_foret ;
            # - les id_foret vides reçoivent eux aussi un nouvel identifiant ;
            # - les nouveaux identifiants tiennent compte de toutes les entités,
            #   y compris celles encore présentes dans le tampon d'édition.
            # --------------------------------------------------------------
            index_spatial = QgsSpatialIndex()
            parents = {}
            ids_attendus = {}
            changements_id_parent = {}
            stats_par_parent = {}

            parents_lus = sorted(
                list(couche_parent.getFeatures()),
                key=lambda entite: int(entite.id()),
            )

            # Réserver toutes les clés existantes afin qu'un identifiant généré
            # ne puisse jamais entrer en collision avec une valeur déjà présente.
            cles_reservees = set()
            maximum_numerique = 0
            for parent in parents_lus:
                cle = self._cle_identifiant(parent[index_id_parent])
                if cle is None:
                    continue
                cles_reservees.add(cle)
                try:
                    nombre = int(cle)
                except (TypeError, ValueError, OverflowError):
                    continue
                maximum_numerique = max(maximum_numerique, nombre)

            candidat_id = max(1, maximum_numerique + 1)

            def prochain_id_unique():
                """Compteur local (indépendant de prochain_id_foret) : avance
                jusqu'à trouver une valeur absente de cles_reservees, la
                réserve immédiatement (pour le prochain appel), puis avance
                encore d'un cran pour le tour suivant."""
                nonlocal candidat_id
                while self._cle_identifiant(candidat_id) in cles_reservees:
                    candidat_id += 1
                valeur = int(candidat_id)
                cles_reservees.add(self._cle_identifiant(valeur))
                candidat_id += 1
                return valeur

            cles_deja_conservees = set()
            nb_doublons_id_repares = 0
            nb_ids_vides_repares = 0

            total_parents_lus = len(parents_lus)
            for numero, parent in enumerate(parents_lus, start=1):
                fid_parent = int(parent.id())
                valeur_id = parent[index_id_parent]
                cle_id = self._cle_identifiant(valeur_id)

                # Une clé vide ou une seconde occurrence d'une même clé reçoit
                # immédiatement une nouvelle valeur attendue. On ne modifie pas
                # encore la couche : toute la redistribution spatiale utilise
                # d'abord ce plan cohérent en mémoire.
                if cle_id is None:
                    valeur_attendue = prochain_id_unique()
                    changements_id_parent[fid_parent] = valeur_attendue
                    cle_attendue = self._cle_identifiant(valeur_attendue)
                    cles_deja_conservees.add(cle_attendue)
                    nb_ids_vides_repares += 1
                elif cle_id in cles_deja_conservees:
                    valeur_attendue = prochain_id_unique()
                    changements_id_parent[fid_parent] = valeur_attendue
                    cle_attendue = self._cle_identifiant(valeur_attendue)
                    cles_deja_conservees.add(cle_attendue)
                    nb_doublons_id_repares += 1
                else:
                    valeur_attendue = valeur_id
                    cles_deja_conservees.add(cle_id)

                parents[fid_parent] = parent
                ids_attendus[fid_parent] = valeur_attendue
                stats_par_parent[fid_parent] = {
                    "nb": 0,
                    "vues": 0,
                    "priorite": None,
                    "essence_v2": NULL,
                    "cle_essence_v2": None,
                }

                geometrie = parent.geometry()
                if geometrie is not None and not geometrie.isEmpty():
                    index_spatial.addFeature(parent)

                avancer(0, 20, numero, total_parents_lus, "Contrôle des id_foret")

            # Transformation créée une seule fois et réutilisée pour tous les
            # points lorsque les deux couches n'ont pas le même SCR.
            transformation = None
            if couche_alertes.crs() != couche_parent.crs():
                transformation = QgsCoordinateTransform(
                    couche_alertes.crs(),
                    couche_parent.crs(),
                    QgsProject.instance(),
                )

            # --------------------------------------------------------------
            # 2. Vérification spatiale de chaque point d'alerte.
            # --------------------------------------------------------------
            noms_alertes = [champs_alertes[index_id_alerte].name()]
            if index_vu >= 0:
                noms_alertes.append(champs_alertes[index_vu].name())
            if index_priorite >= 0:
                noms_alertes.append(champs_alertes[index_priorite].name())
            if index_essence_v2_alerte >= 0:
                noms_alertes.append(champs_alertes[index_essence_v2_alerte].name())
            requete_alertes = QgsFeatureRequest()
            requete_alertes.setSubsetOfAttributes(noms_alertes, champs_alertes)

            changements_alertes = {}
            anciennes_valeurs_alertes = {}
            alertes_hors_polygone = 0
            alertes_multi_candidats = 0

            for numero, alerte in enumerate(couche_alertes.getFeatures(requete_alertes), start=1):
                geometrie_alerte = alerte.geometry()
                if geometrie_alerte is None or geometrie_alerte.isEmpty():
                    alertes_hors_polygone += 1
                    nouvel_id = NULL
                    fid_destination = None
                else:
                    point_parent = QgsGeometry(geometrie_alerte)
                    # Reprojette le point dans le SCR du parent si nécessaire
                    # (transformation construite une seule fois plus haut,
                    # avant la boucle, pour ne pas la recréer par alerte).
                    if transformation is not None:
                        point_parent.transform(transformation)

                    candidats_fids = index_spatial.intersects(point_parent.boundingBox())
                    contenus = []
                    limites = []
                    for fid_candidat in candidats_fids:
                        fid_candidat = int(fid_candidat)
                        parent = parents.get(fid_candidat)
                        if parent is None:
                            continue
                        geometrie_parent = parent.geometry()
                        if geometrie_parent is None or geometrie_parent.isEmpty():
                            continue
                        try:
                            if geometrie_parent.contains(point_parent):
                                contenus.append(fid_candidat)
                            elif geometrie_parent.intersects(point_parent):
                                limites.append(fid_candidat)
                        except (TypeError, RuntimeError):
                            continue

                    choix = contenus or limites
                    if not choix:
                        alertes_hors_polygone += 1
                        nouvel_id = NULL
                        fid_destination = None
                    else:
                        if len(choix) > 1:
                            alertes_multi_candidats += 1
                        id_actuel = self._cle_identifiant(alerte[index_id_alerte])
                        fid_destination = None

                        # Si l'association actuelle reste spatialement valide,
                        # on la conserve. C'est important sur une limite commune
                        # ou tant qu'un recouvrement n'a pas encore été corrigé.
                        if id_actuel is not None:
                            for fid_candidat in choix:
                                if self._cle_identifiant(ids_attendus[fid_candidat]) == id_actuel:
                                    fid_destination = fid_candidat
                                    break

                        if fid_destination is None:
                            try:
                                fid_destination = min(
                                    choix,
                                    key=lambda fid: (
                                        abs(parents[fid].geometry().area()),
                                        int(fid),
                                    ),
                                )
                            except Exception:
                                fid_destination = min(int(fid) for fid in choix)

                        nouvel_id = ids_attendus[fid_destination]
                        stats = stats_par_parent[fid_destination]
                        stats["nb"] += 1
                        if index_vu >= 0:
                            # La synchronisation globale ne pousse jamais le
                            # booléen parent vers les alertes. ``vu`` est la seule
                            # source de vérité.
                            if self._convertir_en_booleen(alerte[index_vu]):
                                stats["vues"] += 1
                        if index_priorite >= 0:
                            priorite = priorite_numerique(alerte[index_priorite])
                            if priorite is not None:
                                if (
                                    stats["priorite"] is None
                                    or priorite < stats["priorite"]
                                ):
                                    stats["priorite"] = priorite

                                if (
                                    index_essence_v2_alerte >= 0
                                    and index_essence_v2_priorite >= 0
                                ):
                                    cle_essence = (priorite, int(alerte.id()))
                                    if (
                                        stats["cle_essence_v2"] is None
                                        or cle_essence < stats["cle_essence_v2"]
                                    ):
                                        stats["cle_essence_v2"] = cle_essence
                                        stats["essence_v2"] = alerte[
                                            index_essence_v2_alerte
                                        ]

                ancienne_valeur = alerte[index_id_alerte]
                if self._cle_identifiant(ancienne_valeur) != self._cle_identifiant(nouvel_id):
                    fid_alerte = int(alerte.id())
                    changements_alertes[fid_alerte] = nouvel_id
                    anciennes_valeurs_alertes[fid_alerte] = ancienne_valeur

                avancer(20, 75, numero, nb_alertes, "Vérification spatiale des alertes")

            # --------------------------------------------------------------
            # 3. Calculer toutes les corrections de compteurs en mémoire.
            # --------------------------------------------------------------
            changements_parent = {}
            parents_liste = list(parents.items())
            donnees_classement = []
            champs_classement_disponibles = (
                index_classement >= 0
                and bool(CRITERES_CLASSEMENT)
                and all(index >= 0 for index in indices_criteres_classement.values())
            )

            for numero, (fid_parent, parent) in enumerate(parents_liste, start=1):
                stats = stats_par_parent[fid_parent]
                priorite_attendue = (
                    stats["priorite"] if stats["priorite"] is not None else NULL
                )
                attendues = {
                    index_total: int(stats["nb"]),
                    index_vues: int(stats["vues"]),
                }
                if index_priorite_max >= 0 and index_priorite >= 0:
                    attendues[index_priorite_max] = priorite_attendue
                if index_essence_v2_priorite >= 0:
                    attendues[index_essence_v2_priorite] = stats["essence_v2"]
                if index_toutes >= 0 and stats["nb"] > 0:
                    # Avec des alertes, le booléen est calculé depuis ``vu``.
                    # Sans alerte (0/0), il reste une validation manuelle et
                    # n'est donc jamais écrasé par un recalcul global.
                    attendues[index_toutes] = bool(
                        stats["vues"] == stats["nb"]
                    )
                if fid_parent in changements_id_parent:
                    attendues[index_id_parent] = changements_id_parent[fid_parent]

                # Si paramétré, la surface est recalculée depuis la géométrie
                # avant le classement. Le calcul est centralisé dans edition.surface_ha.
                surface_attendue = None
                if index_surface_recalcul >= 0:
                    try:
                        surface_attendue = surface_ha(parent.geometry())
                        if surface_attendue is not None:
                            attendues[index_surface_recalcul] = surface_attendue
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        surface_attendue = None

                corrections = {}
                for index_champ, valeur_attendue in attendues.items():
                    valeur_actuelle = parent[index_champ]
                    if index_champ == index_id_parent:
                        identique = (
                            self._cle_identifiant(valeur_actuelle)
                            == self._cle_identifiant(valeur_attendue)
                        )
                    else:
                        identique = self._valeurs_compteur_identiques(
                            valeur_actuelle,
                            valeur_attendue,
                            booleen=(index_champ == index_toutes),
                        )
                    if not identique:
                        corrections[index_champ] = valeur_attendue
                if corrections:
                    changements_parent[fid_parent] = corrections

                if champs_classement_disponibles:
                    valeurs_criteres = {}
                    for nom_champ, _croissant in CRITERES_CLASSEMENT:
                        index_critere = indices_criteres_classement[nom_champ]
                        # Pour les champs recalculés pendant cette passe, trier sur
                        # la valeur attendue et non sur l'ancienne valeur en table.
                        valeurs_criteres[nom_champ] = attendues.get(
                            index_critere, parent[index_critere]
                        )
                    donnees_classement.append(
                        {
                            "fid": fid_parent,
                            "ancien_classement": parent[index_classement],
                            "valeurs": valeurs_criteres,
                        }
                    )

                avancer(75, 84, numero, len(parents_liste), "Calcul des compteurs")

            # --------------------------------------------------------------
            # 4. Recalculer le champ de classement selon commun_parametres.py.
            #
            # Par défaut : priorite_max croissante, nouvelle_essence croissante,
            # surface décroissante. Les NULL sont toujours placés à la fin.
            # L'ancien classement puis le FID stabilisent seulement les égalités.
            # Aucun tri visuel de QgsDualView n'est modifié ici.
            # --------------------------------------------------------------
            nb_classements_modifies = 0
            if champs_classement_disponibles:
                donnees_classement = trier_donnees(
                    donnees_classement,
                    CRITERES_CLASSEMENT,
                )
                total_classement = len(donnees_classement)
                for rang, element in enumerate(donnees_classement, start=1):
                    fid_parent = int(element["fid"])
                    parent = parents[fid_parent]
                    valeur_actuelle = parent[index_classement]
                    if not self._valeurs_compteur_identiques(valeur_actuelle, rang):
                        changements_parent.setdefault(fid_parent, {})[
                            index_classement
                        ] = int(rang)
                        nb_classements_modifies += 1
                    avancer(84, 88, rang, total_classement, "Recalcul du classement")

            # --------------------------------------------------------------
            # 5. Appliquer uniquement les valeurs réellement différentes.
            # --------------------------------------------------------------

            if changements_alertes:
                if not couche_alertes.isEditable():
                    if not couche_alertes.startEditing():
                        raise RuntimeError(
                            f"la couche « {couche_alertes.name()} » ne peut pas être placée en mode édition"
                        )
                    marquer_edition_alertes_ouverte_par_plugin(couche_alertes)
                couche_alertes.beginEditCommand(
                    "Vérifier les rattachements des alertes"
                )
                commande_alertes_ouverte = True

            if changements_parent:
                if not couche_parent.isEditable() and not couche_parent.startEditing():
                    raise RuntimeError(
                        f"la couche « {couche_parent.name()} » ne peut pas être placée en mode édition"
                    )
                couche_parent.beginEditCommand(
                    "Recalculer les alertes et le classement"
                )
                commande_parent_ouverte = True

            total_modifs_alertes = len(changements_alertes)
            for numero, (fid_alerte, nouvel_id) in enumerate(
                changements_alertes.items(), start=1
            ):
                if not fid_est_valide(couche_alertes, fid_alerte):
                    continue
                if not couche_alertes.changeAttributeValue(
                    fid_alerte,
                    index_id_alerte,
                    nouvel_id,
                    anciennes_valeurs_alertes.get(fid_alerte, NULL),
                    True,
                ):
                    raise RuntimeError(
                        f"l'id_foret de l'alerte {fid_alerte} n'a pas pu être mis à jour"
                    )
                avancer(88, 91, numero, total_modifs_alertes, "Correction des id_foret")

            self._mise_a_jour_parent_interne = True
            total_modifs_parent = len(changements_parent)
            try:
                for numero, (fid_parent, corrections) in enumerate(
                    changements_parent.items(), start=1
                ):
                    if not fid_est_valide(couche_parent, fid_parent):
                        continue
                    if not couche_parent.changeAttributeValues(fid_parent, corrections):
                        raise RuntimeError(
                            f"les compteurs du polygone {fid_parent} n'ont pas pu être mis à jour"
                        )
                    avancer(94, 100, numero, total_modifs_parent, "Mise à jour des polygones")
            finally:
                self._mise_a_jour_parent_interne = False

            # Vérification forte après écriture dans le tampon d'édition. Si le
            # provider a refusé/coercé une valeur de façon inattendue, on ne
            # valide pas silencieusement un projet qui possède encore deux clés
            # parentes identiques.
            cles_finales = {}
            requete_verification_ids = (
                QgsFeatureRequest()
                .setSubsetOfAttributes([index_id_parent])
                .setFlags(QgsFeatureRequest.NoGeometry)
            )
            for parent_verification in couche_parent.getFeatures(requete_verification_ids):
                fid_verification = int(parent_verification.id())
                cle_verification = self._cle_identifiant(
                    parent_verification[index_id_parent]
                )
                if cle_verification is None:
                    raise RuntimeError(
                        f"le polygone {fid_verification} possède encore un id_foret vide"
                    )
                autre_fid = cles_finales.get(cle_verification)
                if autre_fid is not None:
                    raise RuntimeError(
                        "l'id_foret "
                        f"{parent_verification[index_id_parent]} est encore partagé "
                        f"par les polygones {autre_fid} et {fid_verification}"
                    )
                cles_finales[cle_verification] = fid_verification

            # On ne ferme les deux commandes qu'une fois toutes les écritures
            # réussies. En cas d'erreur avant ce point, les deux peuvent être
            # détruites proprement dans le bloc except.
            if commande_alertes_ouverte:
                couche_alertes.endEditCommand()
                commande_alertes_ouverte = False
            if commande_parent_ouverte:
                couche_parent.endEditCommand()
                commande_parent_ouverte = False

            couche_alertes.triggerRepaint(True)
            couche_parent.triggerRepaint(True)
            avancer(100, 100, 1, 1, "Terminé")

            message = (
                f"Vérification terminée : {nb_alertes} alerte(s) contrôlée(s), "
                f"{len(changements_alertes)} rattachement(s) d'alerte corrigé(s), "
                f"{len(changements_id_parent)} id_foret de polygone réparé(s) "
                f"({nb_doublons_id_repares} doublon(s), {nb_ids_vides_repares} vide(s)), "
                f"{len(changements_parent)} polygone(s) mis à jour, "
                f"{nb_classements_modifies} classement(s) modifié(s)."
            )
            if alertes_hors_polygone:
                message += (
                    f" {alertes_hors_polygone} alerte(s) ne se trouvent dans aucun polygone "
                    "et ont donc un id_foret vide."
                )
            if alertes_multi_candidats:
                message += (
                    f" {alertes_multi_candidats} alerte(s) intersectent plusieurs polygones ; "
                    "leur rattachement actuel a été conservé lorsqu'il restait valide."
                )
            self.iface.messageBar().pushSuccess("Compteurs d'alertes", message)

        except Exception as exc:
            self._mise_a_jour_parent_interne = False
            self._mise_a_jour_alertes_depuis_parent = False
            if commande_alertes_ouverte:
                try:
                    couche_alertes.destroyEditCommand()
                except (AttributeError, RuntimeError):
                    pass
            if commande_parent_ouverte:
                try:
                    couche_parent.destroyEditCommand()
                except (AttributeError, RuntimeError):
                    pass
            self._avertir(f"La vérification spatiale globale a échoué : {exc}")
        finally:
            self._mise_a_jour_parent_interne = False
            self._mise_a_jour_alertes_depuis_parent = False
            self._recalcul_global_en_cours = False
            if message_progression is not None:
                try:
                    self.iface.messageBar().popWidget(message_progression)
                except (AttributeError, RuntimeError, TypeError):
                    pass

    @staticmethod
    def _cle_identifiant(valeur):
        """Normalise ``id_foret`` pour comparer sans faux écart int/texte.

        Même intention que _valeur_cle() dans commun_synchronisation_alertes.py
        (deux implémentations indépendantes du même besoin de normalisation,
        dans deux fichiers différents).
        """
        if valeur is None or valeur == NULL:
            return None
        texte = str(valeur).strip()
        if not texte:
            return None
        try:
            return str(int(texte))
        except (TypeError, ValueError, OverflowError):
            try:
                nombre = float(texte)
                return str(int(nombre)) if nombre.is_integer() else texte
            except (TypeError, ValueError, OverflowError):
                return texte

    def _valeurs_compteur_identiques(self, actuelle, attendue, booleen=False):
        """Compare une valeur de champ actuelle à la valeur recalculée, en
        tolérant les écarts de représentation (int vs float, NULL vs None)."""
        if attendue == NULL:
            return actuelle is None or actuelle == NULL
        if booleen:
            return self._convertir_en_booleen(actuelle) == self._convertir_en_booleen(attendue)
        try:
            return float(actuelle) == float(attendue)
        except (TypeError, ValueError, OverflowError):
            return actuelle == attendue

    def _recalculer_parent(self, fid_alerte):
        """Retrouve le parent d'une alerte via la relation QGIS, puis délègue
        le vrai recalcul à _recalculer_parent_direct()."""
        self.recalculs_programmes.discard(fid_alerte)
        if self.couche_alertes is None or self.relation is None:
            return

        alerte = self.couche_alertes.getFeature(fid_alerte)
        if not alerte.isValid():
            return

        try:
            requete_parent = self.relation.getReferencedFeatureRequest(alerte)
            parent = next(self.couche_parent.getFeatures(requete_parent), None)
        except Exception:
            return
        if parent is None or not parent.isValid():
            return
        self._recalculer_parent_direct(int(parent.id()))

    def _recalculer_parent_direct(self, fid_parent):
        """Recalcule compteurs et ``toutes_alertes_vues`` pour un polygone."""
        self.recalculs_parents_programmes.discard(int(fid_parent))
        if self.couche_alertes is None or self.couche_parent is None or self.relation is None:
            return
        if not self.couche_parent.isEditable():
            return

        parent = self.couche_parent.getFeature(int(fid_parent))
        if parent is None or not parent.isValid():
            return

        champs = self.couche_parent.fields()
        index_total = champs.indexOf(self.NOM_CHAMP_NB_ALERTES)
        index_vues = champs.indexOf(self.NOM_CHAMP_NB_ALERTES_VUES)
        index_toutes = champs.indexOf(self.NOM_CHAMP_TOUTES_ALERTES_VUES)
        if index_total < 0 or index_vues < 0:
            return

        try:
            requete_alertes = self.relation.getRelatedFeaturesRequest(parent)
            alertes = list(self.couche_alertes.getFeatures(requete_alertes))
        except Exception:
            return

        nombre_total = len(alertes)
        nombre_vues = sum(
            self._convertir_en_booleen(alerte[self.NOM_CHAMP_VU]) for alerte in alertes
        )
        attendues = {
            index_total: nombre_total,
            index_vues: nombre_vues,
        }
        if index_toutes >= 0 and nombre_total > 0:
            # Pour un parent avec des alertes, l'état est entièrement dérivé de
            # leurs champs ``vu``. Pour un 0/0, conserver la valeur manuelle de
            # ``toutes_alertes_vues`` au lieu de la forcer à False.
            attendues[index_toutes] = bool(nombre_vues == nombre_total)

        # Ne jamais appeler changeAttributeValues() si rien ne change. QGIS
        # ajouterait sinon une commande sans effet visible dans la pile d'undo,
        # ce qui pouvait masquer la vraie commande géométrique du panneau.
        changements = {}
        for index_champ, valeur_attendue in attendues.items():
            try:
                valeur_actuelle = parent[index_champ]
            except (IndexError, KeyError):
                continue
            if index_champ == index_toutes:
                identique = (
                    self._convertir_en_booleen(valeur_actuelle)
                    == self._convertir_en_booleen(valeur_attendue)
                )
            else:
                try:
                    identique = int(valeur_actuelle) == int(valeur_attendue)
                except (TypeError, ValueError):
                    identique = valeur_actuelle == valeur_attendue
            if not identique:
                changements[index_champ] = valeur_attendue

        if not changements:
            return

        fid_parent = int(parent.id())
        if not fid_est_valide(self.couche_parent, fid_parent):
            return

        self._mise_a_jour_parent_interne = True
        try:
            if not self.couche_parent.changeAttributeValues(fid_parent, changements):
                return
        finally:
            self._mise_a_jour_parent_interne = False

        self.couche_parent.triggerRepaint(True)
        self._rafraichir_formulaire_parent(int(parent.id()))

    @staticmethod
    def _convertir_en_booleen(valeur):
        """Même intention que _en_booleen() dans commun_synchronisation_alertes.py."""
        if valeur is True:
            return True
        if valeur is False or valeur is None:
            return False
        if isinstance(valeur, (int, float)):
            return valeur != 0
        return str(valeur).strip().lower() in {"true", "1", "t", "yes", "oui", "vrai"}

    def _rafraichir_formulaire_parent(self, fid_parent):
        """Ne force jamais la sélection d'une fiche après un recalcul.

        ``changeAttributeValues`` émet déjà les signaux de mise à jour du modèle
        QGIS. Réappeler ``setCurrentEditSelection`` était inutile et pouvait
        repositionner la liste du formulaire. La méthode reste comme point de
        compatibilité pour les appels existants, mais ne touche plus à l'interface.
        """
        return

    def _avertir(self, message):
        self.iface.messageBar().pushWarning("Compteur d'alertes", message)
