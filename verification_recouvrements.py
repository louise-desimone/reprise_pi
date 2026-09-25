# -*- coding: utf-8 -*-
"""Détection et correction des recouvrements surfaciques."""

from qgis.analysis import QgsGeometrySnapper
from qgis.PyQt.QtWidgets import QComboBox, QInputDialog
from qgis.core import QgsFeature, QgsFeatureRequest, QgsGeometry, QgsRectangle

from .commun_couches import couche_est_disponible
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_edition import (
    annuler_derniere_commande, prochain_id_foret, recuperer_entite, recuperer_entites,
    exiger_fid_valide,
)
from .commun_parametres import (
    CHAMP_ID_FORET,
    SURFACE_BRUIT_NUMERIQUE_GEOS_M2,
    SURFACE_MAXIMALE_MICRO_ECART_M2,
)
from .commun_synchronisation_alertes import synchroniser_zone
from .commun_topologie import (
    construire_geometrie_emprise_locale,
    extraire_intersection_surfacique_significative,
    extraire_parties_polygonales,
    meilleur_voisin_par_contact,
    nettoyer_geometrie_avance,
    nettoyer_geometrie_decoupee_protegee,
    nettoyer_geometrie_base,
    reunir_parties_polygonales,
)

# Précision du projet (1 cm) pour aligner un micro-trou/micro-recouvrement sur
# son voisin avant fusion, même valeur que verification_nettoyage_automatique.py.
_TOLERANCE_FUSION_VOISIN_LOCAL_M = 0.01


def recouvrement_depuis_intersection(intersection):
    """Retourne la partie surfacique d'une intersection, aussi petite soit-elle.

    Un polygone BD Forêt ne doit jamais recouvrir son voisin : il n'y a donc
    pas de seuil métier en dessous duquel un recouvrement serait ignoré (seul
    le bruit numérique GEOS pur est filtré). Cette fonction permet au
    vérificateur de calculer une seule fois ``geom_a.intersection(geom_b)``
    puis d'utiliser le même résultat pour distinguer recouvrement, adjacence
    par bord et simple contact ponctuel.
    """
    return extraire_intersection_surfacique_significative(
        intersection, SURFACE_BRUIT_NUMERIQUE_GEOS_M2
    )


def intersection_recouvrement(geom_a, geom_b):
    """Calcule l'intersection puis retourne le recouvrement, aussi petit soit-il."""
    if geom_a is None or geom_b is None or geom_a.isEmpty() or geom_b.isEmpty():
        return QgsGeometry()
    try:
        intersection = geom_a.intersection(geom_b)
    except (AttributeError, TypeError, RuntimeError):
        return QgsGeometry()
    return recouvrement_depuis_intersection(intersection)


def corriger_micro_recouvrement(geom_a, geom_b):
    """Absorbe un recouvrement trop petit pour représenter un vrai conflit.

    Un polygone BD Forêt ne doit jamais recouvrir son voisin : sous 100 m²,
    il n'y a aucun arbitrage à faire, c'est toujours un artefact de
    numérisation. La zone commune est retirée du plus petit des deux
    polygones, qui la perd au profit du plus grand — même règle que
    :func:`redecouper_polygones_inclus` dans commun_topologie.py. Utilisée
    par le nettoyage automatique (verification_nettoyage_automatique.py) ;
    le panneau Vérifier affiche lui tous les recouvrements, sans seuil.

    Retourne ``("a", geometrie_corrigee)`` ou ``("b", geometrie_corrigee)``
    selon le polygone à corriger, ou ``None`` si ce n'est pas un micro-
    recouvrement (rien à corriger, ou trop grand pour être auto-résolu).
    """
    recouvrement = intersection_recouvrement(geom_a, geom_b)
    if recouvrement is None or recouvrement.isEmpty():
        return None
    aire = abs(float(recouvrement.area()))
    if aire <= 0.0 or aire >= SURFACE_MAXIMALE_MICRO_ECART_M2:
        return None

    aire_a = abs(float(geom_a.area()))
    aire_b = abs(float(geom_b.area()))
    cote_perdant = "b" if aire_a >= aire_b else "a"
    geom_perdant = geom_b if cote_perdant == "b" else geom_a

    reste = nettoyer_geometrie_base(geom_perdant.difference(recouvrement))
    if reste is None or reste.isEmpty():
        return None
    return cote_perdant, reste


def _fusionner_petite_geometrie_dans_voisin(couche, petite_geometrie, fid_voisin):
    """Fusionne ``petite_geometrie`` (trou ou micro-recouvrement) dans un voisin.

    Même schéma que ``_fusionner_dans_voisin`` du nettoyage automatique
    (verification_nettoyage_automatique.py) : le voisin est aligné SUR la
    petite géométrie avant union, pour éviter qu'un écart de sommets laisse
    une pointe résiduelle. Dupliqué ici plutôt qu'importé pour éviter un
    import circulaire (ce fichier-ci est déjà importé par le nettoyage
    automatique).
    """
    feature_voisin = couche.getFeature(fid_voisin)
    if feature_voisin is None or not feature_voisin.hasGeometry():
        return None
    geometrie_voisin = feature_voisin.geometry()
    try:
        voisin_aligne = QgsGeometrySnapper.snapGeometry(
            geometrie_voisin, _TOLERANCE_FUSION_VOISIN_LOCAL_M, [petite_geometrie]
        )
    except (AttributeError, TypeError, RuntimeError):
        voisin_aligne = geometrie_voisin
    try:
        fusion = QgsGeometry.unaryUnion([petite_geometrie, voisin_aligne])
    except (TypeError, RuntimeError):
        return None
    return nettoyer_geometrie_base(fusion)


def nettoyer_micro_anomalies_locales(controleur, couche, geometrie_zone, fids_proteges=None):
    """Résout tout de suite les micro-trous/micro-recouvrements (< 100 m²)
    laissés par une correction, dans la même commande d'édition qu'elle.

    Une correction du panneau ("Attribuer à…", "Découper le recouvrement"...)
    ne touche délibérément que les entités concernées : elle ne redécoupe
    jamais avec leurs autres voisins (voir le commentaire dans
    :func:`attribuer_recouvrement`, un redécoupage complet a déjà fait
    disparaître des entités entières par le passé). Un polygone tiers présent
    dans la zone peut donc se retrouver, après coup, avec un minuscule écart
    contre la nouvelle limite. Même seuil et même principe que le nettoyage
    automatique (étapes 3 et 4), appliqué ici localement et immédiatement
    plutôt que d'attendre un passage complet sur toute la couche.

    ``fids_proteges`` ne peuvent jamais perdre de surface ici (ex. le
    polygone choisi par « Attribuer à… », qui doit rester totalement
    inchangé) : un micro-recouvrement qui les impliquerait est laissé tel
    quel plutôt que d'être corrigé à leurs dépens.

    Retourne le nombre de micro-anomalies résolues.
    """
    if geometrie_zone is None or geometrie_zone.isEmpty():
        return 0
    fids_proteges = {int(fid) for fid in (fids_proteges or [])}
    try:
        rect = QgsRectangle(geometrie_zone.boundingBox())
    except (AttributeError, RuntimeError):
        return 0
    marge = max(rect.width(), rect.height()) * 0.05 + 1.0
    rect.grow(marge)

    corriges = 0

    # --- Micro-recouvrements entre les polygones présents dans la zone ---
    try:
        geometries = {
            int(entite.id()): QgsGeometry(entite.geometry())
            for entite in couche.getFeatures(QgsFeatureRequest().setFilterRect(rect))
            if entite.hasGeometry() and not entite.geometry().isEmpty()
        }
    except (AttributeError, RuntimeError):
        geometries = {}

    fids = sorted(geometries)
    for indice, fid in enumerate(fids):
        geometrie = geometries.get(fid)
        if geometrie is None or geometrie.isEmpty():
            continue
        for autre_fid in fids[indice + 1:]:
            autre_geometrie = geometries.get(autre_fid)
            if autre_geometrie is None or autre_geometrie.isEmpty():
                continue
            if not geometrie.boundingBox().intersects(autre_geometrie.boundingBox()):
                continue
            try:
                resultat = corriger_micro_recouvrement(geometrie, autre_geometrie)
            except (AttributeError, TypeError, RuntimeError):
                resultat = None
            if resultat is None:
                continue
            cote_perdant, geometrie_corrigee = resultat
            fid_perdant = fid if cote_perdant == "a" else autre_fid
            if fid_perdant in fids_proteges:
                continue
            if not couche.changeGeometry(fid_perdant, geometrie_corrigee):
                continue
            geometries[fid_perdant] = geometrie_corrigee
            if fid_perdant == fid:
                geometrie = geometrie_corrigee
            corriges += 1

    # --- Micro-trous (emprise moins couverture) dans la même zone ---
    couche_emprise = None
    trouver = getattr(controleur, "_trouver_couche_emprise", None)
    if callable(trouver):
        try:
            couche_emprise = trouver()
        except (AttributeError, RuntimeError, TypeError):
            couche_emprise = None
    if couche_emprise is not None and couche_est_disponible(couche_emprise):
        emprise_locale = construire_geometrie_emprise_locale(couche_emprise, rect, couche.crs())
        if emprise_locale is not None and not emprise_locale.isEmpty():
            try:
                couverture = [
                    QgsGeometry(entite.geometry())
                    for entite in couche.getFeatures(QgsFeatureRequest().setFilterRect(rect))
                    if entite.hasGeometry() and not entite.geometry().isEmpty()
                ]
                couverture_union = QgsGeometry.unaryUnion(couverture) if couverture else QgsGeometry()
                trou_zone = (
                    emprise_locale if couverture_union.isEmpty()
                    else emprise_locale.difference(couverture_union)
                )
            except (AttributeError, TypeError, RuntimeError):
                trou_zone = None
            if trou_zone is not None and not trou_zone.isEmpty():
                for trou in extraire_parties_polygonales(trou_zone):
                    if trou.area() >= SURFACE_MAXIMALE_MICRO_ECART_M2:
                        continue
                    fid_voisin = meilleur_voisin_par_contact(couche, trou)
                    if fid_voisin is None or fid_voisin in fids_proteges:
                        continue
                    fusion = _fusionner_petite_geometrie_dans_voisin(couche, trou, fid_voisin)
                    if fusion is None or fusion.isEmpty():
                        continue
                    if couche.changeGeometry(fid_voisin, fusion):
                        corriges += 1

    return corriges


def libelle_entite_essence_surface(couche, entite):
    """Libellé compact utilisé pour choisir un polygone dans une liste."""
    champs = couche.fields()
    index_essence = champs.indexOf("nouvelle_essence")
    if index_essence >= 0:
        try:
            valeur = entite[index_essence]
            essence = str(valeur).strip() if valeur is not None else ""
        except (KeyError, RuntimeError, TypeError):
            essence = ""
    else:
        essence = ""
    if not essence:
        essence = "Non renseigné"
    try:
        surface_ha = abs(entite.geometry().area()) / 10000.0
        surface = f"{surface_ha:.2f} ha"
    except (AttributeError, RuntimeError, TypeError):
        surface = "Surface inconnue"
    return f"Nouvelle essence : {essence}, surface : {surface}"


def choisir_fid_attribution_recouvrement(controleur, couche, fids, entites):
    """Demande à quel polygone doit appartenir toute la zone commune."""
    items = []
    fids_items = []
    for fid in fids:
        entite = entites.get(int(fid))
        if entite is None:
            continue
        items.append(libelle_entite_essence_surface(couche, entite))
        fids_items.append(int(fid))
    if len(items) != 2:
        return None

    dialogue = QInputDialog(controleur.iface.mainWindow())
    dialogue.setWindowTitle("Attribuer le recouvrement")
    dialogue.setLabelText("Attribuer la zone de recouvrement à quel polygone ?")
    dialogue.setComboBoxItems(items)
    dialogue.setComboBoxEditable(False)
    combo = dialogue.findChild(QComboBox)
    if combo is not None:
        combo.setCurrentIndex(0)
        combo.setMinimumWidth(700)
    dialogue.resize(760, 170)
    if not dialogue.exec():
        return None
    combo = dialogue.findChild(QComboBox)
    index = combo.currentIndex() if combo is not None else 0
    if index < 0 or index >= len(fids_items):
        return None
    return fids_items[index]


@vue_stable_pendant_modification
def attribuer_recouvrement(self, fids_recouvrement):
    """Attribue toute la zone commune à l'un des deux polygones.

    Le polygone choisi reste inchangé. La surface commune est retirée de
    l'autre polygone (ou celui-ci est supprimé s'il était entièrement
    contenu). Aucune nouvelle entité n'est créée.
    """
    couche = self._trouver_couche()
    if couche is None:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "La couche BD Forêt est introuvable."
        )
        return
    if not couche.isEditable():
        try:
            demarre = couche.startEditing()
        except RuntimeError:
            demarre = False
        if not demarre and not couche.isEditable():
            self.iface.messageBar().pushWarning(
                "Vérification BD Forêt",
                "La couche BD Forêt n'a pas pu être passée en mode édition.",
            )
            return

    try:
        fids = list(dict.fromkeys(int(fid) for fid in fids_recouvrement))
    except (TypeError, ValueError):
        return
    if len(fids) != 2:
        return

    entites = recuperer_entites(couche, fids)
    if len(entites) != 2:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Une des deux entités n'est plus disponible. Relancez la recherche des anomalies.",
        )
        self._pending_fids.update(fids)
        self._refresh_timer.start(50)
        return

    fid_cible = choisir_fid_attribution_recouvrement(self, couche, fids, entites)
    if fid_cible is None:
        return
    fid_autre = fids[1] if fids[0] == fid_cible else fids[0]

    geom_cible = QgsGeometry(entites[fid_cible].geometry())
    geom_autre = QgsGeometry(entites[fid_autre].geometry())
    recouvrement = intersection_recouvrement(geom_cible, geom_autre)
    if recouvrement is None or recouvrement.isEmpty():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Ces deux entités ne se recouvrent plus. Relancez la recherche des anomalies.",
        )
        self._pending_fids.update(fids)
        self._refresh_timer.start(50)
        return

    try:
        # « Attribuer à » doit être strict : le polygone choisi reste
        # totalement inchangé et l'autre perd UNIQUEMENT leur surface
        # commune. Une différence ne peut pas créer de nouveau
        # recouvrement, il ne faut donc surtout pas redécouper le résultat
        # avec tous les voisins (cela pouvait faire disparaître une grande
        # partie, voire toute l'entité).
        aire_autre_avant = abs(float(geom_autre.area()))
        aire_recouvrement = abs(float(recouvrement.area()))
        reste_brut = nettoyer_geometrie_base(
            geom_autre.difference(recouvrement)
        )

        # Si l'autre polygone est entièrement contenu dans le polygone
        # choisi, la différence est vide. C'est désormais un cas autorisé :
        # l'entité absorbée sera supprimée dans la commande d'édition ci-dessous.
        # Le polygone choisi reste inchangé et conserve tous ses attributs.
        if reste_brut is None or reste_brut.isEmpty():
            reste_autre = None
        else:
            # Nettoyage léger SANS couche : suppression des petits artefacts
            # issus de difference(), mais aucune soustraction avec des
            # polygones tiers. Cette fonction recoupe toujours le résultat
            # avec sa géométrie d'origine et ne peut donc pas l'agrandir.
            reste_nettoye = nettoyer_geometrie_decoupee_protegee(
                None, reste_brut, fids_exclus=None
            )
            if reste_nettoye is None or reste_nettoye.isEmpty():
                reste_autre = reste_brut
            else:
                reste_autre = reste_nettoye

            # Répare les pointes/fentes résiduelles laissées par difference()
            # (même nettoyage auto-contenu que la chaîne de fusion, voir
            # fusionner_geometries) : si un troisième polygone empiétait sur
            # la zone de recouvrement, la différence peut laisser une pointe
            # qui ne touche aucun autre polygone de la couche — invisible
            # pour nettoyer_geometrie_decoupee_protegee ci-dessus (qui ne
            # recoupe qu'avec la géométrie d'origine), mais bien réelle.
            # Purement géométrique, sans dépendre des autres polygones : ne
            # peut donc pas réintroduire le risque décrit plus haut.
            reste_avance = nettoyer_geometrie_avance(reste_autre)
            if reste_avance is not None and not reste_avance.isEmpty():
                reste_autre = reste_avance

            # Garde-fou : le nettoyage ne doit jamais enlever sensiblement
            # plus que le recouvrement demandé. Si cela arrive, on revient à
            # la différence brute, qui est la géométrie de référence.
            aire_attendue = max(0.0, aire_autre_avant - aire_recouvrement)
            aire_finale = abs(float(reste_autre.area()))
            tolerance_aire = max(1e-6, aire_autre_avant * 1e-9)
            if aire_finale < aire_attendue - tolerance_aire:
                reste_autre = reste_brut
    except (AttributeError, TypeError, ValueError, RuntimeError) as erreur:
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"L'attribution du recouvrement a échoué : {erreur}",
        )
        return

    commande_ouverte = False
    autre_supprime = reste_autre is None or reste_autre.isEmpty()
    historique = getattr(getattr(self, "manager", None), "historique", None)
    contexte_formulaire = []
    gels_fiche = []
    if historique is not None:
        # Si la fiche ouverte affiche justement le polygone absorbé, on
        # mémorise sa position dans la liste avant de le supprimer, pour
        # rouvrir ensuite le bon voisin plutôt que de perdre la navigation.
        try:
            contexte_formulaire = historique.capturer_contexte_visuel_couche(
                couche, [fid_autre] if autre_supprime else []
            )
        except (AttributeError, RuntimeError, TypeError):
            contexte_formulaire = []
        if autre_supprime:
            try:
                historique.deplacer_fiche_avant_suppression(couche, contexte_formulaire)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            # Gèle temporairement la fiche pour qu'elle ne se ferme pas toute
            # seule pendant la suppression, le temps de la rediriger nous-mêmes.
            try:
                gels_fiche = historique.geler_fiche_si_fid_supprime(couche, [fid_autre])
            except (AttributeError, RuntimeError, TypeError, ValueError):
                gels_fiche = []
    try:
        couche.beginEditCommand("Attribuer un recouvrement")
        commande_ouverte = True

        if autre_supprime:
            exiger_fid_valide(couche, fid_autre, "supprimer l'entité recouverte")
            if not couche.deleteFeatures([fid_autre]):
                raise RuntimeError(f"l'entité {fid_autre} n'a pas pu être supprimée")
        else:
            exiger_fid_valide(couche, fid_autre, "modifier le recouvrement")
            if not couche.changeGeometry(fid_autre, reste_autre):
                raise RuntimeError(f"l'entité {fid_autre} n'a pas pu être découpée")

        try:
            # Emprise couvrant les deux polygones d'origine : les alertes
            # peuvent chevaucher l'un ou l'autre, il faut donc les réévaluer
            # sur toute la zone plutôt que sur le seul recouvrement.
            geometrie_zone = QgsGeometry.unaryUnion([geom_cible, geom_autre])
        except (TypeError, RuntimeError):
            geometrie_zone = QgsGeometry(recouvrement)

        synchroniser_zone(
            self.iface,
            couche,
            geometrie_zone,
            "Attribuer un recouvrement",
        )

        # Corrige tout de suite les micro-trous/micro-recouvrements que ce
        # découpage a pu laisser contre un troisième polygone de la zone
        # (voir nettoyer_micro_anomalies_locales), dans la même commande.
        # fid_cible est protégé : il doit rester totalement inchangé, comme
        # le garantit cette fonction depuis le début (voir plus haut).
        nettoyer_micro_anomalies_locales(
            self, couche, geometrie_zone, fids_proteges={fid_cible}
        )

        couche.endEditCommand()
        commande_ouverte = False

        couche.triggerRepaint(True)
        self.iface.mapCanvas().refresh()
        if autre_supprime and historique is not None and gels_fiche:
            try:
                historique.liberer_gel_fiche(gels_fiche)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if historique is not None and contexte_formulaire:
            try:
                historique.restaurer_contexte_visuel_couche(
                    couche, contexte_formulaire, fid_remplacement=fid_cible
                )
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        self._pending_fids.update(fids)
        self._refresh_timer.start(50)
        if autre_supprime:
            message_succes = (
                "La zone de recouvrement a été attribuée au polygone choisi ; "
                "l'autre entité, entièrement absorbée, a été supprimée."
            )
        else:
            message_succes = "La zone de recouvrement a été attribuée au polygone choisi."
        self.iface.messageBar().pushSuccess(
            "Vérification BD Forêt",
            message_succes,
        )
    except Exception as erreur:
        if historique is not None and gels_fiche:
            try:
                historique.liberer_gel_fiche(gels_fiche)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if commande_ouverte:
            try:
                couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"L'attribution du recouvrement a échoué : {erreur}",
        )


@vue_stable_pendant_modification
def decouper_recouvrement(self, fids_recouvrement):
    """Transforme une zone de recouvrement en entité BD Forêt indépendante.

    La zone commune est soustraite des deux polygones sources puis recréée
    comme une nouvelle entité. Seul ``id_foret`` est initialisé ; les autres
    attributs sont renseignés par l'opérateur dans le formulaire ouvert à la
    fin de l'opération. Si le formulaire est annulé, toute la commande est
    annulée, synchronisation des alertes comprise.
    """
    couche = self._trouver_couche()
    if couche is None:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La couche BD Forêt est introuvable.",
        )
        return
    if not couche.isEditable():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La couche BD Forêt doit être en mode édition pour découper un recouvrement.",
        )
        return

    try:
        fids = list(dict.fromkeys(int(fid) for fid in fids_recouvrement))
    except (TypeError, ValueError):
        return
    if len(fids) != 2:
        return

    entites = recuperer_entites(couche, fids)
    if len(entites) != 2:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Une des deux entités n'est plus disponible. Relancez la recherche des anomalies.",
        )
        self._pending_fids.update(fids)
        self._refresh_timer.start(50)
        return

    fid_a, fid_b = fids
    geom_a = QgsGeometry(entites[fid_a].geometry())
    geom_b = QgsGeometry(entites[fid_b].geometry())
    if geom_a.isEmpty() or geom_b.isEmpty():
        return

    # Recalcul au dernier moment : l'anomalie peut avoir changé depuis le
    # dernier rafraîchissement du panneau.
    recouvrement = intersection_recouvrement(geom_a, geom_b)
    if recouvrement is None or recouvrement.isEmpty():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Ces deux entités ne se recouvrent plus. Relancez la recherche des anomalies.",
        )
        self._pending_fids.update(fids)
        self._refresh_timer.start(50)
        return

    try:
        reste_a = reunir_parties_polygonales(
            geom_a.difference(recouvrement), surface_minimale=1e-8
        )
        reste_b = reunir_parties_polygonales(
            geom_b.difference(recouvrement), surface_minimale=1e-8
        )
        # Répare les pointes/fentes résiduelles laissées par difference() sur
        # chaque reste (même nettoyage auto-contenu que fusionner_geometries,
        # voir attribuer_recouvrement ci-dessus) : purement géométrique, sans
        # dépendre des autres polygones de la couche.
        if reste_a is not None and not reste_a.isEmpty():
            reste_a_avance = nettoyer_geometrie_avance(reste_a)
            if reste_a_avance is not None and not reste_a_avance.isEmpty():
                reste_a = reste_a_avance
        if reste_b is not None and not reste_b.isEmpty():
            reste_b_avance = nettoyer_geometrie_avance(reste_b)
            if reste_b_avance is not None and not reste_b_avance.isEmpty():
                reste_b = reste_b_avance
    except (TypeError, RuntimeError) as erreur:
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"Le découpage géométrique du recouvrement a échoué : {erreur}",
        )
        return

    index_id_foret = couche.fields().indexOf(CHAMP_ID_FORET)
    if index_id_foret < 0:
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"Le champ {CHAMP_ID_FORET} est introuvable dans la couche BD Forêt.",
        )
        return

    # id_foret est un identifiant de travail local (cf. README section 0) :
    # prochain_id_foret() prend le plus grand existant + 1, les autres champs
    # restent vides pour que l'opérateur les renseigne dans le formulaire.
    nouvelle_entite = QgsFeature(couche.fields())
    nouvelle_entite.setGeometry(recouvrement)
    nouvelle_entite.setAttribute(index_id_foret, prochain_id_foret(couche))

    commande_ouverte = False
    historique = getattr(getattr(self, "manager", None), "historique", None)
    contexte_formulaire = []
    gels_fiche = []
    if historique is not None:
        # Un polygone entièrement recouvert disparaîtra (reste vide) : sa
        # fiche doit être repositionnée avant suppression, comme dans
        # attribuer_recouvrement ci-dessus.
        fids_supprimes = []
        if reste_a.isEmpty():
            fids_supprimes.append(fid_a)
        if reste_b.isEmpty():
            fids_supprimes.append(fid_b)
        try:
            contexte_formulaire = historique.capturer_contexte_visuel_couche(
                couche, fids_supprimes
            )
        except (AttributeError, RuntimeError, TypeError):
            contexte_formulaire = []
        try:
            historique.deplacer_fiche_avant_suppression(couche, contexte_formulaire)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        try:
            gels_fiche = historique.geler_fiche_si_fid_supprime(couche, fids_supprimes)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            gels_fiche = []
    try:
        couche.beginEditCommand("Découper un recouvrement")
        commande_ouverte = True

        # Si le recouvrement couvrait entièrement l'un des deux polygones,
        # celui-ci est remplacé par la nouvelle entité au lieu de conserver
        # une géométrie vide.
        if reste_a.isEmpty():
            exiger_fid_valide(couche, fid_a, "supprimer l'entité A du recouvrement")
            if not couche.deleteFeatures([fid_a]):
                raise RuntimeError(f"l'entité {fid_a} n'a pas pu être supprimée")
        else:
            exiger_fid_valide(couche, fid_a, "modifier l'entité A du recouvrement")
            if not couche.changeGeometry(fid_a, reste_a):
                raise RuntimeError(f"l'entité {fid_a} n'a pas pu être découpée")

        if reste_b.isEmpty():
            exiger_fid_valide(couche, fid_b, "supprimer l'entité B du recouvrement")
            if not couche.deleteFeatures([fid_b]):
                raise RuntimeError(f"l'entité {fid_b} n'a pas pu être supprimée")
        else:
            exiger_fid_valide(couche, fid_b, "modifier l'entité B du recouvrement")
            if not couche.changeGeometry(fid_b, reste_b):
                raise RuntimeError(f"l'entité {fid_b} n'a pas pu être découpée")

        if not couche.addFeature(nouvelle_entite):
            raise RuntimeError("la nouvelle entité de recouvrement n'a pas pu être créée")

        try:
            geometrie_zone = QgsGeometry.unaryUnion([geom_a, geom_b])
        except (TypeError, RuntimeError):
            geometrie_zone = QgsGeometry(recouvrement)

        synchroniser_zone(
            self.iface,
            couche,
            geometrie_zone,
            "Découper un recouvrement",
        )

        # Corrige tout de suite les micro-trous/micro-recouvrements que ce
        # découpage a pu laisser contre un troisième polygone de la zone
        # (voir nettoyer_micro_anomalies_locales), dans la même commande.
        nettoyer_micro_anomalies_locales(self, couche, geometrie_zone)

        couche.endEditCommand()
        commande_ouverte = False

        couche.triggerRepaint(True)
        self.iface.mapCanvas().refresh()

        entite_creee = recuperer_entite(couche, nouvelle_entite.id())
        if entite_creee is None:
            raise RuntimeError("la nouvelle entité est introuvable après sa création")

        self.iface.setActiveLayer(couche)
        # L'opérateur doit obligatoirement renseigner la nouvelle entité :
        # un formulaire annulé annule tout le découpage (les deux polygones
        # sources retrouvent leur géométrie d'origine), rien n'est laissé
        # à moitié fait.
        accepte = self.iface.openFeatureForm(couche, entite_creee, False, True)
        if not accepte:
            if not annuler_derniere_commande(couche, self.iface.mapCanvas()):
                self.iface.messageBar().pushWarning(
                    "Vérification BD Forêt",
                    "Le formulaire a été annulé, mais le découpage n'a pas pu être annulé automatiquement.",
                )
            return

        # La fiche principale derrière le formulaire modal ne doit jamais être
        # remplacée automatiquement. Si son FID a disparu, elle reste visuellement
        # telle quelle jusqu'à la prochaine navigation volontaire de l'utilisateur.
        if historique is not None and gels_fiche:
            try:
                historique.liberer_gel_fiche(gels_fiche)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if historique is not None and contexte_formulaire:
            try:
                historique.restaurer_contexte_visuel_couche(
                    couche,
                    contexte_formulaire,
                    fid_remplacement=int(entite_creee.id()),
                )
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

        self._pending_fids.update(fids)
        try:
            self._pending_fids.add(int(entite_creee.id()))
        except (TypeError, ValueError):
            pass
        self._refresh_timer.start(50)

        self.iface.messageBar().pushSuccess(
            "Vérification BD Forêt",
            "Le recouvrement a été transformé en polygone indépendant.",
        )

    except Exception as erreur:
        if commande_ouverte:
            try:
                couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"Le découpage du recouvrement a échoué : {erreur}",
        )



def ajouter_au_panneau(controleur, arbre, anomalies, groupe=None):
    """Ajoute les recouvrements de surface significative au panneau."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QTreeWidgetItem

    from .commun_edition import valeur_champ_texte

    if groupe is None:
        groupe = QTreeWidgetItem([f"Recouvrements ({len(anomalies)})", ""])
        arbre.addTopLevelItem(groupe)
    couche = controleur._trouver_couche()
    for fid_a, fid_b, geom in anomalies:
        surface_ha = abs(float(geom.area())) / 10000.0 if geom is not None else 0.0
        feature_a = controleur._cached_feature_by_id.get(fid_a)
        feature_b = controleur._cached_feature_by_id.get(fid_b)
        essence_a = (
            valeur_champ_texte(couche, feature_a, "nouvelle_essence")
            if couche is not None and feature_a is not None else "Non renseigné"
        )
        essence_b = (
            valeur_champ_texte(couche, feature_b, "nouvelle_essence")
            if couche is not None and feature_b is not None else "Non renseigné"
        )
        item = QTreeWidgetItem([
            f"{essence_a} ({fid_a}) / {essence_b} ({fid_b})",
            f"{surface_ha:.2f} ha",
        ])
        item.setData(0, Qt.UserRole, {
            "overlap_fids": [int(fid_a), int(fid_b)],
            "overlap_pair": [int(fid_a), int(fid_b)],
            "extent": controleur._emprise_vers_tuple(geom.boundingBox()),
        })
        groupe.addChild(item)
