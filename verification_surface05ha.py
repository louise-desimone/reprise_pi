# -*- coding: utf-8 -*-
"""Détecte les polygones de surface inférieure à 0,5 ha.

La correction propose de fusionner via l'outil Fusionner : elle présélectionne
le petit polygone et laisse l'utilisateur choisir le voisin.
"""

from .commun_edition import recuperer_entite, valeur_champ_texte
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_parametres import SURFACE_MINIMALE_M2, TOLERANCE_ADJACENCE_M
from .commun_topologie import limite_polygone, meilleur_voisin_par_contact, partage_une_limite


def detecter(feature, mesure_surface):
    """Retourne ``(fid, surface_m2)`` si l'entité fait moins de 0,5 ha."""
    if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
        return None
    surface = abs(float(mesure_surface.measureArea(feature.geometry())))
    if surface < SURFACE_MINIMALE_M2:
        return int(feature.id()), surface
    return None


def est_isole(controleur, fid, geometrie):
    """Vrai si aucun autre polygone BD Forêt ne partage une vraie limite.

    S'appuie sur l'index spatial déjà tenu à jour par le contrôleur : aucun
    nouveau calcul sur toute la couche n'est nécessaire, seuls les polygones
    proches de celui-ci sont examinés.
    """
    index = controleur._spatial_index
    feature_by_id = controleur._cached_feature_by_id
    if index is None or not feature_by_id:
        return False
    limite = limite_polygone(geometrie)
    if limite is None:
        return False
    for autre_fid in index.intersects(geometrie.boundingBox()):
        autre_fid = int(autre_fid)
        if autre_fid == fid:
            continue
        autre_feature = feature_by_id.get(autre_fid)
        if autre_feature is None or not autre_feature.hasGeometry():
            continue
        autre_limite = limite_polygone(autre_feature.geometry())
        # Précision du projet (1 cm) pour l'alignement des sommets ; longueur
        # minimale de contact identique à celle utilisée pour toute adjacence
        # dans le plugin (cf. verification_tache_relations.py).
        if partage_une_limite(limite, autre_limite, 0.01, TOLERANCE_ADJACENCE_M) is not None:
            return False
    return True


@vue_stable_pendant_modification
def fusionner_avec(controleur, fid):
    """Délègue la correction au véritable outil Fusionner du plugin.

    Présélectionne le petit polygone (via activer_avec_fids) puis laisse
    l'outil Fusionner attendre le clic de l'utilisateur sur le voisin : aucune
    logique de fusion n'est dupliquée ici.
    """
    fusionner = getattr(controleur.manager, "fusionner", None) if controleur.manager else None
    if fusionner is None or not hasattr(fusionner, "activer_avec_fids"):
        controleur.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "L'outil Fusionner n'est pas disponible."
        )
        return
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        return
    couche = controleur._trouver_couche()
    if couche is None:
        controleur.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "La couche BD Forêt est introuvable."
        )
        return
    try:
        controleur.iface.setActiveLayer(couche)
    except RuntimeError:
        pass
    if not fusionner.activer_avec_fids(
        [fid],
        ouvrir_formulaire_apres=False,
        finaliser_au_deuxieme_clic=True,
        callback_fin=lambda fids, ref: apres_fusion(controleur, fids, ref),
    ):
        return
    controleur.iface.messageBar().pushInfo(
        "Fusionner BD Forêt",
        "Le petit polygone est présélectionné. Cliquez sur le polygone voisin à fusionner.",
    )


def actualiser_visibles(controleur):
    """Recalcule et met en cache les petits polygones à afficher.

    Retire les polygones isolés (aucun voisin avec qui fusionner) : "Fusionner
    avec…" ne pourrait rien leur proposer, ils ne doivent apparaître ni dans
    le décompte du panneau ni dans la liste détaillée. Seul ce module connaît
    l'existence du cache ``_cached_small_visibles`` sur le contrôleur ;
    ``verification.py`` appelle cette fonction puis relit le résultat avec
    :func:`visibles`.
    """
    resultat = []
    for fid, surface in sorted(controleur._cached_small.items()):
        feature = controleur._cached_feature_by_id.get(fid)
        if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        if est_isole(controleur, fid, feature.geometry()):
            continue
        resultat.append((fid, surface))
    controleur._cached_small_visibles = resultat
    return resultat


def visibles(controleur):
    """Retourne le dernier résultat mis en cache par :func:`actualiser_visibles`."""
    return getattr(controleur, "_cached_small_visibles", [])


def apres_fusion(controleur, fids_operation, fid_reference):
    """Programme le rafraîchissement local après une fusion déléguée."""
    try:
        controleur._pending_fids.update(int(fid) for fid in (fids_operation or []))
        controleur._pending_fids.add(int(fid_reference))
    except (TypeError, ValueError):
        pass
    if controleur.dock is not None and controleur.dock.isVisible():
        controleur._refresh_timer.start(50)


def _meilleur_voisin(controleur, fid):
    """Retourne le voisin partageant la plus grande frontière avec ce polygone."""
    couche = controleur._trouver_couche()
    if couche is None:
        return None
    entite = recuperer_entite(couche, fid)
    if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
        return None
    return meilleur_voisin_par_contact(couche, entite.geometry(), fid_exclu=fid)


def fusionner_tous_avec_meilleur_voisin(controleur):
    """Fusionne chaque petit polygone visible avec son voisin le plus adéquat.

    Un polygone isolé n'apparaît jamais dans la liste (cf. :func:`filtrer_isoles`
    dans :func:`actualiser_visibles`) : chaque entité traitée ici a donc déjà
    un vrai voisin avec qui fusionner.
    """
    couche = controleur._trouver_couche()
    if couche is None:
        controleur.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "La couche BD Forêt est introuvable."
        )
        return
    if not couche.isEditable():
        controleur.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La couche BD Forêt doit être en mode édition.",
        )
        return

    fusionner = getattr(controleur.manager, "fusionner", None) if controleur.manager else None
    if fusionner is None or not hasattr(fusionner, "fusionner_fids_direct"):
        controleur.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "Le moteur commun Fusionner n'est pas disponible."
        )
        return

    # Snapshot des FID : la liste visible peut évoluer au fur et à mesure des
    # corrections locales.
    fids = [int(fid) for fid, _surface in visibles(controleur)]
    if not fids:
        return

    corriges = 0
    ignores = 0
    for fid in fids:
        voisin = _meilleur_voisin(controleur, fid)
        if voisin is None:
            ignores += 1
            continue
        succes, fid_reference = fusionner.fusionner_fids_direct(
            [int(voisin), fid],
            fid_reference=int(voisin),
            ouvrir_formulaire=False,
            nom_commande="Fusionner un petit polygone avec son meilleur voisin",
        )
        controleur._pending_fids.update([fid, int(voisin)])
        if fid_reference is not None:
            controleur._pending_fids.add(int(fid_reference))
        if succes:
            corriges += 1
        else:
            ignores += 1

    controleur._refresh_timer.start(50)
    if corriges:
        texte = f"{corriges} polygone(s) fusionné(s) avec leur meilleur voisin."
        if ignores:
            texte += f" {ignores} cas ignoré(s) car ils avaient changé."
        controleur.iface.messageBar().pushSuccess("Vérification BD Forêt", texte)
    elif ignores:
        controleur.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Aucun polygone n'a pu être fusionné automatiquement.",
        )


def ajouter_au_panneau(controleur, arbre, anomalies, groupe=None):
    """Ajoute la branche « Surfaces < 0,5 ha » au panneau Vérifier.

    ``anomalies`` doit déjà avoir été calculée par :func:`actualiser_visibles`.
    """
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QTreeWidgetItem

    couche = controleur._trouver_couche()
    lignes = []
    for fid, surface in anomalies:
        feature = controleur._cached_feature_by_id.get(fid)
        if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        essence = (
            valeur_champ_texte(couche, feature, "nouvelle_essence")
            if couche is not None else "Non renseigné"
        )
        lignes.append((essence, surface, fid, feature))
    lignes.sort(key=lambda ligne: (ligne[0].lower(), ligne[1]))

    if groupe is None:
        groupe = QTreeWidgetItem([f"Surfaces < 0,5 ha ({len(lignes)})", ""])
        arbre.addTopLevelItem(groupe)

    for essence, surface, fid, feature in lignes:
        libelle = f"{essence} ({fid})"
        item = QTreeWidgetItem([libelle, f"{surface / 10000:.3f} ha"])
        # "small_fid" est la clé que _actions_pour_payload() (verification_panneau.py)
        # reconnaît pour proposer "Fusionner avec…" sur cette anomalie.
        payload = {
            "fids": [int(fid)],
            "small_fid": int(fid),
            "extent": controleur._emprise_vers_tuple(feature.geometry().boundingBox()),
        }
        item.setData(0, Qt.UserRole, payload)
        groupe.addChild(item)
