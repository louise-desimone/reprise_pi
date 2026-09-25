# -*- coding: utf-8 -*-
"""Petites fonctions communes aux opérations d'édition QGIS."""

from functools import wraps

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import NULL, QgsFeatureRequest, QgsProject, QgsVectorLayerUtils
from qgis.gui import QgsMapToolIdentify

from .commun_affichage import (
    creer_surbrillance_polygone,
    definir_action_cochee,
    supprimer_surbrillance_polygone,
    supprimer_surbrillances_polygones,
)
from .commun_couches import couche_est_disponible, trouver_couche_travail, valider_couche_modifiable
from .commun_parametres import CHAMP_ID_FORET, DECIMALES_SURFACE_HA


# Champs recalculés par commun_compteur_alertes.py à partir des points
# "Alertes Centroides" liés : jamais hérités par une nouvelle entité (voir
# creer_entite_nouvelle), toujours remis à zéro/recalculés après coup.
CHAMPS_DERIVES_ALERTES = {
    "nb_alertes",
    "nb_alertes_vues",
    "priorite_max",
    "essence_v2_priorite_max",
    "toutes_alertes_vues",
}


# -----------------------------------------------------------------------------
# Entités, attributs et géométrie : petites fonctions communes à toute écriture
# en couche (id_foret, surface, sécurisation des clés primaires, FID valides...).
# -----------------------------------------------------------------------------


def surface_ha(geometrie):
    """Convertit l'aire d'une géométrie (m²) en hectares.

    Le nombre de décimales est centralisé dans ``parametres.DECIMALES_SURFACE_HA``.
    """
    if geometrie is None or geometrie.isEmpty():
        return None
    try:
        return round(abs(float(geometrie.area())) / 10000.0, int(DECIMALES_SURFACE_HA))
    except (TypeError, ValueError, AttributeError):
        return None


def valeur_champ_texte(couche, feature, nom_champ, defaut="Non renseigné"):
    """Valeur texte d'un champ d'une entité, ou un texte de repli si absente/vide."""
    index = couche.fields().indexOf(nom_champ)
    if index < 0:
        return defaut
    try:
        valeur = feature[index]
    except (IndexError, KeyError):
        return defaut
    if valeur is None or str(valeur).strip() == "":
        return defaut
    return str(valeur)


def prochain_id_foret(couche):
    """Retourne un nouvel ``id_foret`` numérique disponible.

    ``id_foret`` est un identifiant métier du plugin. Contrairement au ``fid``
    du GeoPackage, il peut être attribué avant l'enregistrement. Les entités
    déjà présentes dans le tampon d'édition sont prises en compte.
    """
    index_id = couche.fields().indexOf(CHAMP_ID_FORET)
    if index_id < 0:
        raise RuntimeError(f"le champ « {CHAMP_ID_FORET} » est introuvable")

    maximum = 0

    # Le GeoPackage peut calculer son maximum côté fournisseur, sans transférer
    # toutes les entités vers Python. On complète uniquement avec le petit tampon
    # d'édition local (nouvelles entités / changements non enregistrés).
    try:
        provider = couche.dataProvider()
        valeur = provider.maximumValue(index_id) if provider is not None else None
        if valeur is not None and valeur != NULL and str(valeur).strip() != "":
            maximum = max(maximum, int(valeur))
    except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
        provider = None

    try:
        tampon = couche.editBuffer()
        if tampon is not None:
            for entite in tampon.addedFeatures().values():
                try:
                    valeur = entite[index_id]
                    if valeur is not None and valeur != NULL and str(valeur).strip() != "":
                        maximum = max(maximum, int(valeur))
                except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                    pass
            for changements in tampon.changedAttributeValues().values():
                if index_id not in changements:
                    continue
                try:
                    valeur = changements[index_id]
                    if valeur is not None and valeur != NULL and str(valeur).strip() != "":
                        maximum = max(maximum, int(valeur))
                except (TypeError, ValueError, OverflowError):
                    pass
    except (AttributeError, RuntimeError, TypeError):
        pass

    if maximum > 0:
        return maximum + 1

    # Secours générique pour un fournisseur qui n'exposerait pas maximumValue.
    for entite in couche.getFeatures(
        QgsFeatureRequest().setSubsetOfAttributes([index_id]).setFlags(
            QgsFeatureRequest.NoGeometry
        )
    ):
        try:
            valeur = entite[index_id]
            if valeur is None or valeur == NULL or str(valeur).strip() == "":
                continue
            maximum = max(maximum, int(valeur))
        except (IndexError, KeyError, TypeError, ValueError, OverflowError):
            continue

    return maximum + 1


def indices_fid(couche):
    """Retourne les champs techniques servant de clé primaire au fournisseur."""
    indices = set()

    try:
        indices.update(int(i) for i in couche.dataProvider().pkAttributeIndexes())
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass

    # Sur un GeoPackage, la clé primaire est généralement nommée ``fid``.
    # On l'ajoute explicitement par sécurité si elle apparaît dans les champs.
    index_fid = couche.fields().indexOf("fid")
    if index_fid >= 0:
        indices.add(index_fid)

    return sorted(indices)


def creer_entite_nouvelle(couche, geometrie, attributs_reference):
    """Crée une entité en copiant les attributs utiles de l'entité source.

    Les clés primaires techniques (dont ``fid``), ``surface`` et les compteurs
    dérivés des alertes ne sont jamais hérités du polygone source. Ils sont
    recalculés à partir de la nouvelle géométrie. Le champ ``classement`` fait
    volontairement exception : il est hérité du polygone de référence afin
    qu'une entité créée ou issue d'une division reste proche de son parent
    dans la liste. Seul le recalcul global renumérote ensuite les classements.
    Un nouvel ``id_foret`` est ensuite attribué.
    """
    attributs_reference = list(attributs_reference)
    champs = couche.fields()

    index_id_foret = champs.indexOf(CHAMP_ID_FORET)
    if index_id_foret < 0:
        raise RuntimeError(f"le champ « {CHAMP_ID_FORET} » est introuvable")

    index_surface = champs.indexOf("surface")
    indices_exclus = set(indices_fid(couche))
    indices_exclus.add(index_id_foret)
    if index_surface >= 0:
        indices_exclus.add(index_surface)
    for nom_champ in CHAMPS_DERIVES_ALERTES:
        index = champs.indexOf(nom_champ)
        if index >= 0:
            indices_exclus.add(index)

    # On transmet uniquement les attributs réellement hérités. Les champs
    # exclus restent libres afin que QGIS applique leurs valeurs par défaut.
    attributs_a_copier = {
        index: valeur
        for index, valeur in enumerate(attributs_reference)
        if index < len(champs) and index not in indices_exclus
    }

    entite = QgsVectorLayerUtils.createFeature(
        couche,
        geometrie,
        attributs_a_copier,
    )
    entite[index_id_foret] = prochain_id_foret(couche)

    return entite


def recuperer_entite(couche, fid):
    """Retourne une entité par FID, y compris depuis le tampon d'édition."""
    if couche is None:
        return None
    # getFeatures() côté couche (pas dataProvider()) fusionne automatiquement
    # le tampon d'édition avec les entités déjà enregistrées : une entité
    # créée ou modifiée mais pas encore commitée est donc bien vue ici.
    requete = QgsFeatureRequest().setFilterFid(int(fid))
    entite = next(couche.getFeatures(requete), None)
    if entite is None or not entite.isValid():
        return None
    return entite


def recuperer_entites(couche, fids):
    """Retourne un dictionnaire ``FID: entité`` pour les FID demandés."""
    fids = [int(fid) for fid in fids]
    if couche is None or not fids:
        return {}
    requete = QgsFeatureRequest().setFilterFids(fids)
    return {int(entite.id()): entite for entite in couche.getFeatures(requete)}


def fid_est_valide(couche, fid):
    """Indique si un FID peut encore recevoir une écriture dans la couche.

    Une entité marquée supprimée dans le tampon d'édition est considérée comme
    invalide immédiatement, même si le fournisseur la connaît encore jusqu'au
    prochain commit. Inversement, une entité nouvellement créée dans le tampon
    est considérée comme valide dès qu'elle est visible via ``getFeatures``.

    Cette fonction est la barrière centrale contre les « FID fantômes » : aucun
    recalcul métier ne doit appeler ``changeAttributeValue(s)`` ou
    ``changeGeometry`` sur un identifiant qui a déjà disparu.
    """
    if couche is None:
        return False
    try:
        fid = int(fid)
    except (TypeError, ValueError, OverflowError):
        return False

    try:
        tampon = couche.editBuffer()
        if tampon is not None and fid in set(int(v) for v in tampon.deletedFeatureIds()):
            return False
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass

    return recuperer_entite(couche, fid) is not None


def exiger_fid_valide(couche, fid, action="modifier l'entité"):
    """Lève une erreur claire avant toute écriture sur un FID disparu."""
    if not fid_est_valide(couche, fid):
        raise RuntimeError(
            f"le FID {fid} n'existe plus : impossible de {action}. "
            "Aucune écriture n'a été envoyée au tampon QGIS."
        )
    return int(fid)



def annuler_derniere_commande(couche, canvas=None):
    """Annule la dernière commande d'édition et rafraîchit éventuellement la carte."""
    try:
        pile = couche.undoStack()
        if pile is None or not pile.canUndo():
            return False
        pile.undo()
        # triggerRepaint(True) force le redessin même si QGIS pense que rien
        # de visible n'a changé (ex. un attribut seul, sans la carte au premier
        # plan) : sans ça, l'annulation peut être invisible à l'écran jusqu'au
        # prochain pan/zoom.
        couche.triggerRepaint(True)
        if canvas is not None:
            canvas.refresh()
        return True
    except (AttributeError, RuntimeError):
        return False


# -----------------------------------------------------------------------------
# Messages dans la barre QGIS : utilitaires génériques, utilisés partout (pas
# seulement pendant l'activation/désactivation d'un outil).
# -----------------------------------------------------------------------------


def avertir_message_bar(iface, nom_outil, message):
    """Affiche un avertissement dans la barre de messages QGIS."""
    try:
        iface.messageBar().pushWarning(nom_outil, str(message))
    except (AttributeError, RuntimeError):
        pass


# -----------------------------------------------------------------------------
# Cycle de vie commun des 4 outils géométriques (Créer, Séparer, Fusionner,
# Remodeler) : chacun a sa propre logique d'activation/désactivation, mais la
# création de la QAction, le bouton coché/décoché, la garde anti-réentrance et
# la surveillance de la couche sont identiques partout.
# -----------------------------------------------------------------------------


def creer_action_outil(iface, canvas, nom_outil, chemin_icone, info_bulle, callback_toggled):
    """Crée la QAction standard d'un outil géométrique et la relie au canevas.

    Factorise ce que ``initGui`` répétait à l'identique dans les 4 outils :
    icône, case à cocher, info-bulle, ajout à la barre d'outils et au menu
    Vecteur, connexion du signal ``toggled``.
    """
    action = QAction(QIcon(chemin_icone), nom_outil, iface.mainWindow())
    action.setCheckable(True)
    action.setToolTip(info_bulle)
    action.toggled.connect(callback_toggled)
    iface.addToolBarIcon(action)
    iface.addPluginToVectorMenu(nom_outil, action)
    return action


def detruire_action_outil(iface, action, nom_outil, callback_toggled):
    """Détache et détruit la QAction créée par ``creer_action_outil``.

    Retourne toujours ``None`` pour permettre ``self.action = detruire_action_outil(...)``.
    """
    if action is None:
        return None
    try:
        action.toggled.disconnect(callback_toggled)
    except (TypeError, RuntimeError):
        pass
    try:
        iface.removeToolBarIcon(action)
        iface.removePluginVectorMenu(nom_outil, action)
    except (AttributeError, RuntimeError):
        pass
    action.deleteLater()
    return None


def basculer_outil_geometrique(outil, coche):
    """Active ou désactive ``outil`` suite au basculement de sa QAction.

    ``outil`` doit exposer ``_activer()`` (retourne un booléen de succès),
    ``_desactiver()`` et ``action``. Identique dans les 4 outils géométriques.
    """
    if coche:
        if not outil._activer():
            definir_action_cochee(outil.action, False)
    else:
        outil._desactiver()


# Déplacé depuis commun_couches.py (audit de placement avant transmission du
# code) : n'était utilisée que par obtenir_couche_editable() ci-dessous.
def activer_couche_travail(iface):
    """Trouve la couche de travail et la rend immédiatement active dans QGIS.

    Le clic sur un outil Reprise PI doit suffire : même si l'utilisateur est
    actuellement positionné sur la couche d'alertes ou sur une autre couche, la
    couche BD Forêt est sélectionnée dans le panneau des couches avant les
    contrôles propres à l'outil et avant l'installation du curseur cartographique.
    """
    couche = trouver_couche_travail(iface)
    if couche is None or iface is None:
        return couche

    try:
        if iface.activeLayer() is not couche:
            iface.setActiveLayer(couche)
    except (RuntimeError, AttributeError, TypeError):
        pass
    return couche


def obtenir_couche_editable(iface, nom_outil, couche_attendue=None, manager=None, outil=None):
    """Retourne ``(couche, est_editable)``, ou ``(None, False)`` si aucune
    couche de travail valide n'est trouvée.

    Répète ce que les 4 outils géométriques vérifient à l'identique avant de
    s'activer : désactiver les autres outils géométriques (si ``manager`` et
    ``outil`` sont fournis), trouver la couche BD Forêt du projet, puis
    vérifier qu'elle est en mode édition. Affiche directement l'avertissement
    adapté dans la barre de messages QGIS dans les deux cas d'échec.
    """
    if manager is not None and outil is not None:
        manager.desactiver_autres_outils_geometriques(outil)

    couche = couche_attendue or activer_couche_travail(iface)
    if couche is None:
        avertir_message_bar(iface, nom_outil, valider_couche_modifiable(couche))
        return None, False
    if not couche.isEditable():
        avertir_message_bar(iface, nom_outil, "Activez le mode édition de la couche de travail.")
        return couche, False
    return couche, True


def sans_reentrance(fonction):
    """Empêche une méthode de s'exécuter si un appel précédent est encore en cours.

    L'objet doit exposer un attribut ``traitement_en_cours`` (initialisé à
    ``False``). Sert de garde-fou sur les points d'entrée déclenchés par un
    signal QGIS (capture terminée, tracé dessiné), qui ne doivent jamais se
    chevaucher sur une même couche.
    """
    @wraps(fonction)
    def enveloppe(objet, *args, **kwargs):
        if getattr(objet, "traitement_en_cours", False):
            return None
        objet.traitement_en_cours = True
        try:
            return fonction(objet, *args, **kwargs)
        finally:
            objet.traitement_en_cours = False

    return enveloppe


class SurveillanceCoucheActive:
    """Désactive un outil si sa couche sort d'édition, est supprimée, ou si le
    projet est vidé pendant que l'outil est actif.

    Reprend une logique jusqu'ici dupliquée dans chaque outil géométrique
    (``editingStopped`` de la couche, ``layersRemoved``/``cleared`` du projet).
    """

    def __init__(self, callback_perte):
        self._callback = callback_perte
        self._couche = None

    def demarrer(self):
        """À appeler une fois dans ``initGui()`` : écoute le projet en permanence."""
        projet = QgsProject.instance()
        projet.layersRemoved.connect(self._couches_supprimees)
        projet.cleared.connect(self._projet_vide)

    def arreter(self):
        """À appeler une fois dans ``unload()``."""
        self.oublier_couche()
        projet = QgsProject.instance()
        for signal, fonction in (
            (projet.layersRemoved, self._couches_supprimees),
            (projet.cleared, self._projet_vide),
        ):
            try:
                signal.disconnect(fonction)
            except (TypeError, RuntimeError):
                pass

    def surveiller_couche(self, couche):
        """À appeler dans ``_activer()``, une fois la couche en édition."""
        self.oublier_couche()
        if not couche_est_disponible(couche):
            return
        self._couche = couche
        try:
            couche.editingStopped.connect(self._edition_arretee)
        except (AttributeError, RuntimeError, TypeError):
            pass

    def oublier_couche(self):
        """À appeler dans ``_desactiver()``."""
        couche = self._couche
        self._couche = None
        if couche_est_disponible(couche):
            try:
                couche.editingStopped.disconnect(self._edition_arretee)
            except (AttributeError, RuntimeError, TypeError):
                pass

    def _couches_supprimees(self, ids_couches):
        """Signal layersRemoved : vérifie que la couche surveillée n'y est pas."""
        couche = self._couche
        if couche is None:
            return
        if not couche_est_disponible(couche) or couche.id() in set(ids_couches):
            self._declencher()

    def _projet_vide(self, *args):
        """Signal cleared : le projet entier vient d'être vidé (fermeture/nouveau projet)."""
        if self._couche is not None:
            self._declencher()

    def _edition_arretee(self, *args):
        """Signal editingStopped de la couche surveillée elle-même."""
        self._declencher()

    def _declencher(self):
        """Point commun aux trois cas de perte : oublie la couche puis prévient l'outil."""
        self.oublier_couche()
        self._callback()


class AttenteDebutEdition:
    """Mémorise une activation d'outil jusqu'au début de l'édition QGIS.

    Un outil Reprise PI peut être choisi avant que la couche de travail soit
    en édition. Le bouton reste alors coché et cette classe attend le signal
    ``editingStarted`` de la couche. Dès que QGIS ouvre la session d'édition,
    l'outil demande à son propriétaire de terminer son activation.
    """

    def __init__(self, callback):
        self._callback = callback
        self._couche = None

    @property
    def en_attente(self):
        return couche_est_disponible(self._couche)

    def attendre(self, couche):
        """Attend ``editingStarted`` sur ``couche`` sans multiplier les signaux."""
        if not couche_est_disponible(couche):
            self.annuler()
            return False

        if self._couche is couche:
            return True

        self.annuler()
        self._couche = couche
        try:
            couche.editingStarted.connect(self._edition_demarree)
            return True
        except (AttributeError, RuntimeError, TypeError):
            self._couche = None
            return False

    def annuler(self):
        """Supprime l'attente courante, si elle existe."""
        couche = self._couche
        self._couche = None
        if not couche_est_disponible(couche):
            return
        try:
            couche.editingStarted.disconnect(self._edition_demarree)
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _edition_demarree(self, *args):
        """Déclenche une seule fois l'activation demandée."""
        couche = self._couche
        self.annuler()
        if not couche_est_disponible(couche):
            return
        try:
            self._callback(couche)
        except (AttributeError, RuntimeError, TypeError):
            # L'outil a pu être déchargé ou la couche détruite pendant le signal.
            pass


# -----------------------------------------------------------------------------
# Sélection de cibles par clic (surbrillance jaune), commune à Fusionner et
# Séparer : ``outil`` doit exposer ``.actif``, ``.couche``, ``.canvas``,
# ``.surbrillances`` (dict FID -> surbrillance) et ``.fids`` (liste de FID).
# -----------------------------------------------------------------------------


def basculer_cible_surbrillance(outil, x, y, ctrl_appuye, outil_identification):
    """Ajoute ou retire, sous le clic, une entité de la sélection en surbrillance.

    Un clic simple sur une cible déjà en surbrillance la retire ; Ctrl+clic
    n'est qu'un geste de retrait (il n'ajoute jamais). Retourne le FID ajouté,
    ou ``None`` si rien n'a été ajouté (retrait, clic dans le vide, ou outil
    inactif).
    """
    if not outil.actif or outil.couche is None or outil_identification is None:
        return None

    resultats = outil_identification.identify(
        x, y, [outil.couche], QgsMapToolIdentify.TopDownStopAtFirst,
    )
    if not resultats:
        return None

    entite = resultats[0].mFeature
    fid = int(entite.id())
    if fid in outil.surbrillances:
        # Ctrl+clic ou reclic simple : dans les deux cas, une cible déjà en
        # surbrillance est retirée.
        retirer_cible_surbrillance(outil, fid)
        return None
    if ctrl_appuye:
        return None

    outil.fids.append(fid)
    outil.surbrillances[fid] = creer_surbrillance_polygone(
        outil.canvas, entite.geometry(), outil.couche
    )
    try:
        outil.canvas.refresh()
    except RuntimeError:
        pass
    return fid


def retirer_cible_surbrillance(outil, fid):
    """Retire une cible de la sélection en surbrillance de ``outil``."""
    supprimer_surbrillance_polygone(outil.canvas, outil.surbrillances.pop(int(fid), None))
    outil.fids = [item for item in outil.fids if int(item) != int(fid)]
    try:
        outil.canvas.refresh()
    except RuntimeError:
        pass


def effacer_cibles_surbrillance(outil, rafraichir=True):
    """Vide entièrement la sélection en surbrillance de ``outil``."""
    supprimer_surbrillances_polygones(outil.canvas, outil.surbrillances.values())
    outil.surbrillances.clear()
    outil.fids = []
    if rafraichir:
        try:
            outil.canvas.refresh()
        except RuntimeError:
            pass


# -----------------------------------------------------------------------------
# Ouverture de fiche après une écriture en couche déjà commitée (Fusionner,
# Séparer) : annule proprement l'opération entière si l'utilisateur annule le
# formulaire, au lieu de laisser le résultat appliqué quand même.
# -----------------------------------------------------------------------------


def ouvrir_formulaire_ou_annuler(iface, couche, canvas, entite, nom_outil):
    """Ouvre la fiche d'une entité déjà écrite en couche, avec annulation propre.

    Suppose que la commande d'édition qui a créé/modifié ``entite`` est déjà
    refermée (``endEditCommand()``) au moment de l'appel : si l'utilisateur
    annule le formulaire, on défait donc la dernière commande via la pile
    d'annulation (``annuler_derniere_commande``) plutôt que de détruire une
    commande déjà close, afin qu'« Annuler » annule vraiment toute
    l'opération et pas seulement la saisie du formulaire.
    """
    try:
        accepte = bool(iface.openFeatureForm(couche, entite, False, True))
    except RuntimeError as erreur:
        avertir_message_bar(iface, nom_outil, f"La fiche n'a pas pu être ouverte : {erreur}")
        return False

    if accepte:
        return True

    if not annuler_derniere_commande(couche, canvas):
        avertir_message_bar(
            iface, nom_outil,
            "Le formulaire a été annulé, mais l'opération n'a pas pu être annulée automatiquement.",
        )
    return False
