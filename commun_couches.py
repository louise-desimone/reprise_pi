# -*- coding: utf-8 -*-
"""Recherche et validation des couches utilisées par Reprise PI."""

import unicodedata

from qgis.PyQt import sip
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes

from .commun_parametres import (
    MOT_CLE_COUCHE_EMPRISE,
    MOTS_CLES_COUCHE_TRAVAIL,
    PREFIXE_COUCHE_ALERTES,
    PREFIXE_COUCHE_PARENT,
)


def couche_est_disponible(couche):
    """Indique si le wrapper Python pointe encore vers une couche QGIS vivante.

    QGIS peut détruire l'objet C++ d'une couche lors d'un changement de projet
    ou d'un remplacement de couche alors qu'une ancienne référence Python existe
    encore. Accéder à un signal de ce wrapper lève alors ``RuntimeError``.
    """
    if couche is None:
        return False
    try:
        return isinstance(couche, QgsVectorLayer) and not sip.isdeleted(couche)
    except (RuntimeError, TypeError, ReferenceError):
        return False


def normaliser_nom(nom):
    """Met un nom en minuscules et supprime les accents."""
    # Décomposition NFD : sépare chaque lettre accentuée en (lettre de base +
    # signe diacritique séparé), ce qui permet de retirer uniquement les
    # diacritiques (catégorie Unicode "Mn" = Mark, nonspacing) sans dépendre
    # d'une table de correspondance accent → lettre écrite à la main.
    texte = unicodedata.normalize("NFD", str(nom).strip().lower())
    return "".join(
        caractere
        for caractere in texte
        if unicodedata.category(caractere) != "Mn"
    )


def est_couche_polygonale(couche):
    """Indique si ``couche`` est une couche vectorielle polygonale."""
    if not couche_est_disponible(couche):
        return False
    try:
        return QgsWkbTypes.geometryType(couche.wkbType()) == QgsWkbTypes.PolygonGeometry
    except (AttributeError, RuntimeError, TypeError):
        return False


def trouver_couche_travail(iface=None):
    """Retourne la couche BD Forêt destinée aux reprises.

    Même règle, et même moteur de recherche, que celle utilisée pour la
    relation avec `Alertes Centroides` (voir :func:`trouver_couche_alertes`) :
    la couche doit être polygonale et son nom normalisé doit commencer par
    ``Bdfv3 Priorites``. C'est une seule et même couche qui joue les deux
    rôles (couche de travail éditée par les 5 outils, couche parente de la
    relation), une règle unique évite qu'elles divergent. La couche active
    est prioritaire ; à défaut, une couche déjà en mode édition est
    préférée (utile si plusieurs chantiers sont ouverts dans le même projet).
    """
    return _trouver_couche_par_prefixe(
        PREFIXE_COUCHE_PARENT,
        iface,
        couche_valide=est_couche_polygonale,
        prioriser_edition=True,
    )


def trouver_couche_emprise():
    """Retourne la couche polygonale servant d'emprise de production.

    Lorsqu'il existe plusieurs couches contenant ``emprise``, une couche dont
    le nom contient aussi ``bdfv`` ou ``foret`` est prioritaire.
    """
    candidates = []
    for couche in QgsProject.instance().mapLayers().values():
        if not est_couche_polygonale(couche):
            continue
        nom = normaliser_nom(couche.name())
        if MOT_CLE_COUCHE_EMPRISE not in nom:
            continue
        # 0 = nom contenant aussi "bdfv"/"foret" (ex. "Bdfv3 Emprise"), trié
        # avant les couches d'emprise génériques (priorité 1) ; à égalité,
        # ordre alphabétique pour un résultat reproductible.
        priorite = 0 if any(mot in nom for mot in MOTS_CLES_COUCHE_TRAVAIL) else 1
        candidates.append((priorite, couche.name().lower(), couche))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def message_couche_travail_absente():
    """Message commun affiché lorsque la couche de travail est introuvable."""
    return (
        "Aucune couche polygonale dont le nom commence par « Bdfv3 Priorites » "
        "n'a été trouvée."
    )


def valider_couche_modifiable(couche):
    """Retourne ``None`` si la couche est modifiable, sinon un message d'erreur."""
    if not est_couche_polygonale(couche):
        return message_couche_travail_absente()
    if not couche.isEditable():
        return "Activez d'abord le mode édition de la couche de travail."
    return None


def _trouver_couche_par_prefixe(prefixe, iface=None, couche_valide=None, prioriser_edition=False):
    """Moteur commun : retourne la couche dont le nom commence par ``prefixe``.

    Fonction interne partagée par :func:`trouver_couche_travail` et
    :func:`trouver_couche_alertes`, chacune l'appelant avec son propre
    préfixe ; elle n'est pas destinée à être appelée directement ailleurs.
    ``couche_valide`` est un filtre optionnel (ex. :func:`est_couche_polygonale`)
    appliqué avant toute comparaison de nom. Si ``prioriser_edition`` est vrai et
    qu'aucune couche active ne correspond, la couche déjà en mode édition est
    préférée aux autres candidates (utile lorsque plusieurs couches partagent
    le même préfixe, par exemple plusieurs chantiers ouverts dans le même
    projet).
    """
    prefixe = normaliser_nom(prefixe)
    candidates = []
    for couche in QgsProject.instance().mapLayers().values():
        if couche_valide is not None and not couche_valide(couche):
            continue
        try:
            if normaliser_nom(couche.name()).startswith(prefixe):
                candidates.append(couche)
        except (AttributeError, RuntimeError):
            continue

    if iface is not None:
        try:
            couche_active = iface.activeLayer()
            if couche_active in candidates:
                return couche_active
        except RuntimeError:
            pass

    if prioriser_edition:
        for candidate in candidates:
            try:
                if candidate.isEditable():
                    return candidate
            except RuntimeError:
                continue

    return candidates[0] if candidates else None


def trouver_couche_alertes(iface=None):
    """Retourne la couche dont le nom normalisé commence par
    ``Alertes Centroides``. La couche active est prioritaire.
    """
    return _trouver_couche_par_prefixe(PREFIXE_COUCHE_ALERTES, iface)
