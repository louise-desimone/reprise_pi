# -*- coding: utf-8 -*-
"""Synchronisation spatiale entre les alertes et les polygones BD Forêt.

Après une modification géométrique, ``id_foret`` ne doit pas seulement être
présent : il doit désigner le polygone qui contient réellement chaque point
d'alerte. Ce module centralise cette règle et recalcule les indicateurs dérivés
sur les polygones concernés.
"""

from qgis.PyQt.QtWidgets import QApplication
from qgis.gui import QgsRelationEditorWidget

from qgis.core import (
    NULL,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsSpatialIndex,
)

from .commun_couches import trouver_couche_alertes
from .commun_edition import recuperer_entite, fid_est_valide
from .commun_parametres import CHAMP_ID_FORET, PREFIXE_COUCHE_ALERTES


# Champs de la couche parente (BD Forêt) recalculés à partir des alertes liées.
CHAMP_PRIORITE_MAX = "priorite_max"
CHAMP_NB_ALERTES = "nb_alertes"
CHAMP_NB_ALERTES_VUES = "nb_alertes_vues"
CHAMP_TOUTES_ALERTES_VUES = "toutes_alertes_vues"
CHAMP_ESSENCE_V2_PRIORITE_MAX = "essence_v2_priorite_max"
# Champs lus sur chaque point "Alertes Centroides" pour calculer les champs ci-dessus.
CHAMP_PRIORITE_ALERTE = "priorite"
CHAMP_VU = "vu"
CHAMP_ESSENCE_V2_ALERTE = "ESSENCE_V2"



# Couches parentes dont les indicateurs sont en cours de recalcul interne.
# Le signal attributeValueChanged est synchrone : ce marqueur permet au
# CompteurAlertes de distinguer sans temporisation une écriture automatique
# d'un vrai clic utilisateur sur ``toutes_alertes_vues``.
_COUCHES_PARENT_EN_ECRITURE_INTERNE = set()

# Couches d'alertes dont la session d'édition a été ouverte automatiquement
# par le plugin. QGIS maintient une session d'édition indépendante par couche :
# si l'utilisateur enregistre la BD Forêt sans enregistrer Alertes Centroides,
# les nouveaux id_foret des points resteraient uniquement dans le tampon enfant.
# Le CompteurAlertes utilise ce marqueur pour valider la couche enfant après un
# commit réussi de la couche de travail. Une couche déjà en édition avant
# l'intervention du plugin n'est jamais marquée : ses modifications restent
# entièrement sous le contrôle de l'utilisateur.
_COUCHES_ALERTES_EDITION_OUVERTE_PAR_PLUGIN = set()


def marquer_edition_alertes_ouverte_par_plugin(couche):
    """Mémorise que le plugin a lui-même démarré l'édition de ``couche``."""
    if couche is None:
        return
    _COUCHES_ALERTES_EDITION_OUVERTE_PAR_PLUGIN.add(_cle_couche(couche))


def edition_alertes_ouverte_par_plugin(couche):
    """Indique si la session d'édition enfant appartient au plugin."""
    if couche is None:
        return False
    return _cle_couche(couche) in _COUCHES_ALERTES_EDITION_OUVERTE_PAR_PLUGIN


def oublier_edition_alertes_ouverte_par_plugin(couche):
    """Oublie le marqueur d'édition automatique d'une couche d'alertes."""
    if couche is None:
        return
    _COUCHES_ALERTES_EDITION_OUVERTE_PAR_PLUGIN.discard(_cle_couche(couche))


def ecriture_parent_interne_en_cours(couche):
    """Indique si ``synchroniser_zone`` écrit actuellement sur la couche."""
    if couche is None:
        return False
    try:
        cle = couche.id()
    except (AttributeError, RuntimeError):
        cle = str(id(couche))
    return cle in _COUCHES_PARENT_EN_ECRITURE_INTERNE


def _cle_couche(couche):
    """Identifiant stable pour indexer une couche dans les deux ensembles ci-dessus.

    couche.id() est l'identifiant QGIS normal ; le repli sur id(couche)
    (identité Python de l'objet) ne sert qu'en cas d'accès à un wrapper déjà
    partiellement détruit, pour ne jamais lever d'exception ici.
    """
    try:
        return couche.id()
    except (AttributeError, RuntimeError):
        return str(id(couche))


def synchroniser_zone_outil(manager, iface, couche_parent, geometrie_zone, nom_commande):
    """Synchronise une opération géométrique explicite par le service central.

    Les outils du plugin passent tous ici. Si ``CompteurAlertes`` est chargé, il
    marque la commande comme déjà synchronisée afin d'éviter un second balayage
    automatique à ``editCommandEnded``. Le repli direct conserve le plugin
    utilisable indépendamment du gestionnaire principal.
    """
    # getattr() en chaîne plutôt qu'un import de CompteurAlertes : ce module
    # ne doit pas dépendre de commun_compteur_alertes.py (c'est l'inverse,
    # commun_compteur_alertes.py importe déjà ce module-ci — un import
    # circulaire serait sinon créé).
    compteur = getattr(manager, "compteur_alertes", None) if manager is not None else None
    fonction = getattr(compteur, "synchroniser_modification_geometrique", None)
    if callable(fonction):
        return fonction(couche_parent, geometrie_zone, nom_commande)
    return synchroniser_zone(iface, couche_parent, geometrie_zone, nom_commande)


class ResultatSynchronisation:
    """Polygones parents touchés par une synchronisation d'alertes.

    ``fids_parents`` sert à rafraîchir les formulaires relationnels ouverts
    sur ces entités après la synchronisation (voir
    ``rafraichir_vue_relation_alertes``).
    """

    def __init__(self, fids_parents=None, iface=None):
        self.fids_parents = set(int(fid) for fid in (fids_parents or []))
        self.iface = iface


def _est_nulle(valeur):
    """Teste NULL/None/chaîne vide en une seule fois (QVariant NULL n'est ni
    None ni faux au sens Python : il doit être comparé explicitement)."""
    try:
        return valeur is None or valeur == NULL or str(valeur).strip() == ""
    except Exception:
        return valeur is None


def attribuer_nouvel_id_foret(couche, fid):
    """Attribue à ``id_foret`` la valeur du ``fid`` de l'entité.

    Cette fonction est utilisée comme sécurité lorsqu'une entité existante
    concernée par une synchronisation ne possède pas encore d'``id_foret``.

    C'est la SECONDE façon dont un ``id_foret`` peut être produit dans ce
    plugin, distincte de ``commun_edition.prochain_id_foret()`` (le compteur
    max+1 utilisé partout ailleurs pour une entité neuve) : ici, on ne crée
    rien, on répare une entité déjà existante en recopiant sa clé technique.
    Les deux mécanismes coexistent volontairement — voir README_CODE.md
    section 0 pour le contexte complet (id_foret reste un identifiant de
    travail dans tous les cas, jamais un identifiant définitif IGN).
    """
    entite = recuperer_entite(couche, fid)
    if entite is None:
        raise RuntimeError("l'entité BD Forêt est introuvable")

    index_fid = couche.fields().indexOf("fid")
    index_id = couche.fields().indexOf(CHAMP_ID_FORET)
    if index_fid < 0:
        raise RuntimeError("le champ technique « fid » est introuvable")
    if index_id < 0:
        raise RuntimeError(f"le champ « {CHAMP_ID_FORET} » est introuvable")

    valeur = entite[index_fid]
    if _est_nulle(valeur):
        raise RuntimeError("le fid de l'entité est vide")

    if not couche.changeAttributeValue(int(fid), index_id, valeur):
        raise RuntimeError("l'id_foret n'a pas pu recevoir la valeur du fid")
    return valeur


def _transformer_geometrie(geometrie, crs_source, crs_destination):
    """Copie et reprojette une géométrie, sans rien faire si les deux SCR sont identiques."""
    resultat = QgsGeometry(geometrie)
    if crs_source == crs_destination:
        return resultat
    transformation = QgsCoordinateTransform(
        crs_source,
        crs_destination,
        QgsProject.instance(),
    )
    resultat.transform(transformation)
    return resultat


def priorite_numerique(valeur):
    """Convertit une priorité en nombre, en tolérant la virgule décimale."""
    if _est_nulle(valeur):
        return None
    try:
        # Le champ "priorite" peut être saisi avec une virgule (convention
        # française), que float() ne comprend pas nativement.
        nombre = float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None
    # Un entier stocké en float (2.0) redevient un vrai int (2) : évite
    # d'écrire "2.0" dans priorite_max alors que la source est entière.
    if nombre.is_integer():
        return int(nombre)
    return nombre


def _en_booleen(valeur):
    """Normalise une valeur de champ (bool, nombre ou texte) en True/False.

    Nécessaire car un champ booléen QGIS peut, selon le fournisseur de
    données, retourner un vrai bool Python, un 0/1 entier, ou une chaîne
    ("true"/"vrai"/"oui"...).
    """
    if valeur is True:
        return True
    if valeur is False or _est_nulle(valeur):
        return False
    if isinstance(valeur, (int, float)):
        return valeur != 0
    return str(valeur).strip().lower() in {"true", "1", "t", "yes", "oui", "vrai"}


def _choisir_polygone(point, candidats, id_actuel, index_id_parent):
    """Choisit le polygone contenant le point, de façon déterministe."""
    contenus = []
    limites = []
    for entite in candidats:
        geometrie = entite.geometry()
        if geometrie is None or geometrie.isEmpty():
            continue
        try:
            # "contains" (point strictement à l'intérieur) est toujours
            # préféré à "intersects" seul (point exactement sur une limite,
            # cas ambigu entre deux polygones voisins) : voir ci-dessous.
            if geometrie.contains(point):
                contenus.append(entite)
            elif geometrie.intersects(point):
                limites.append(entite)
        except (TypeError, RuntimeError):
            continue

    # Les polygones qui contiennent vraiment le point sont préférés à ceux
    # où il tombe juste sur la limite ; ces derniers ne sont utilisés que si
    # aucun "vrai" contenant n'existe.
    choix = contenus or limites
    if not choix:
        return None
    if len(choix) == 1:
        return choix[0]

    # Sur une limite commune, conserver l'association actuelle si elle reste
    # géométriquement possible évite un basculement arbitraire entre voisins.
    if not _est_nulle(id_actuel):
        for entite in choix:
            try:
                if entite[index_id_parent] == id_actuel:
                    return entite
            except (IndexError, KeyError, TypeError):
                pass

    try:
        # Toujours égalité restante : plus petite surface d'abord (un point
        # tombant pile sur la limite entre un grand et un petit polygone est
        # plus probablement destiné au petit), puis id le plus bas pour un
        # résultat reproductible d'un appel à l'autre.
        return min(choix, key=lambda entite: (abs(entite.geometry().area()), int(entite.id())))
    except Exception:
        return min(choix, key=lambda entite: int(entite.id()))


def _polygones_intersectant_zone(couche_parent, zone):
    """Retourne uniquement les polygones proches de ``zone``.

    L'ancienne version reconstruisait un QgsSpatialIndex de *toute* la couche à
    chaque petite modification géométrique. Une requête rectangulaire laisse le
    fournisseur QGIS filtrer directement les candidats, puis on conserve le vrai
    test géométrique pour éviter les faux positifs de bounding box.
    """
    if zone is None or zone.isEmpty():
        return {}
    requete = QgsFeatureRequest().setFilterRect(zone.boundingBox())
    resultat = {}
    for entite in couche_parent.getFeatures(requete):
        geometrie = entite.geometry()
        if geometrie is None or geometrie.isEmpty():
            continue
        try:
            if geometrie.intersects(zone):
                resultat[int(entite.id())] = entite
        except (TypeError, RuntimeError):
            continue
    return resultat


def _expression_ids_foret(nom_champ, valeurs):
    """Construit un filtre QGIS sûr pour un petit ensemble d'id_foret.

    Les id_foret sont normalement numériques, mais on accepte également une
    couche où le champ serait textuel. Cette requête remplace un parcours de
    toutes les alertes uniquement pour retrouver d'anciens rattachements.
    """
    valeurs_qgis = []
    for valeur in valeurs:
        if _est_nulle(valeur):
            continue
        try:
            # Cas numérique normal : pas de guillemets nécessaires.
            valeurs_qgis.append(str(int(valeur)))
        except (TypeError, ValueError, OverflowError):
            # Cas textuel de secours : échappe les apostrophes (syntaxe SQL
            # standard, doublement de l'apostrophe) pour empêcher toute
            # valeur de casser la structure de l'expression QGIS.
            texte = str(valeur).replace("'", "''")
            valeurs_qgis.append("'" + texte + "'")
    if not valeurs_qgis:
        return None
    # Échappe aussi le nom de champ, au cas improbable où il contiendrait
    # lui-même un guillemet double.
    champ = str(nom_champ).replace('"', '""')
    return f'"{champ}" IN ({", ".join(valeurs_qgis)})'


def _suffixe_groupe(nom):
    """Retourne le suffixe normalisé situé après « groupe » dans un nom de couche."""
    texte = str(nom or "").strip().lower()
    position = texte.rfind("groupe")
    if position < 0:
        return None
    suffixe = texte[position + len("groupe"):].strip(" -_")
    return suffixe or None


def _trouver_couche_alertes_associee(couche_parent, iface=None):
    """Choisit de préférence Alertes Centroides du même groupe que la BD Forêt.

    Les projets ordinaires ne contiennent qu'une paire de couches. Cette règle
    évite cependant qu'un ancien groupe ou une couche de test chargée dans le
    même projet reçoive par erreur les modifications d'id_foret.
    """
    projet = QgsProject.instance()
    candidates = []
    prefixe = PREFIXE_COUCHE_ALERTES.strip().lower()
    for couche in projet.mapLayers().values():
        try:
            if str(couche.name()).strip().lower().startswith(prefixe):
                candidates.append(couche)
        except (AttributeError, RuntimeError):
            continue

    if not candidates:
        return None
    # Cas courant (un seul projet de travail) : pas d'ambiguïté possible.
    if len(candidates) == 1:
        return candidates[0]

    # Plusieurs couches candidates : tente de les départager par le suffixe
    # de "groupe" dans le nom (ex. "Bdfv3 Priorites - Groupe 2" doit se lier
    # à "Alertes Centroides - Groupe 2", pas à celles d'un autre groupe).
    groupe_parent = _suffixe_groupe(couche_parent.name())
    if groupe_parent is not None:
        memes_groupes = [
            couche for couche in candidates
            if _suffixe_groupe(couche.name()) == groupe_parent
        ]
        if len(memes_groupes) == 1:
            return memes_groupes[0]

    # Repli sur la règle historique si aucun groupe ne peut être identifié.
    return trouver_couche_alertes(iface)


def trouver_couche_alertes_associee(couche_parent, iface=None):
    """Retourne la couche Alertes Centroides associée à ``couche_parent``.

    Cette fonction publique permet aux autres services du plugin d'utiliser
    exactement la même règle d'association que la synchronisation spatiale,
    notamment lorsqu'un projet contient plusieurs groupes ou couches de test.
    """
    return _trouver_couche_alertes_associee(couche_parent, iface)


def _valeur_cle(valeur):
    """Normalise une valeur d'identifiant pour comparer int/str/QVariant."""
    if _est_nulle(valeur):
        return None
    try:
        return str(int(valeur))
    except (TypeError, ValueError, OverflowError):
        return str(valeur).strip()



def _widgets_relation_alertes_ouverts(iface):
    """Retourne les widgets de relation ouverts, y compris dans un formulaire modal.

    ``iface.mainWindow().findChildren`` suffit pour les formulaires ancrés, mais
    le formulaire ouvert par ``openFeatureForm(..., showModal=True)`` peut être
    une fenêtre de premier niveau. On parcourt donc aussi les top-level widgets
    Qt afin de pouvoir rafraîchir la relation juste après l'ouverture du dialogue.
    """
    racines = []
    try:
        racines.append(iface.mainWindow())
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        racines.extend(QApplication.topLevelWidgets())
    except (AttributeError, RuntimeError, TypeError):
        pass

    widgets = []
    vus = set()
    for racine in racines:
        if racine is None:
            continue
        try:
            candidats = racine.findChildren(QgsRelationEditorWidget)
        except (AttributeError, RuntimeError, TypeError):
            continue
        for widget in candidats:
            cle = id(widget)
            if cle in vus:
                continue
            vus.add(cle)
            widgets.append(widget)
    return widgets


def rafraichir_vue_relation_alertes(iface, couche_parent, couche_alertes, fids_parents):
    """Force les widgets relationnels ouverts à relire les alertes du parent.

    Cette fonction ne recalcule aucune association spatiale : elle ne fait que
    recharger l'affichage de la relation à partir de l'état courant des deux
    tampons d'édition. C'est notamment nécessaire lorsqu'un formulaire modal
    est créé juste après une fusion, donc après la synchronisation des ``id_foret``.
    """
    if iface is None or couche_parent is None or couche_alertes is None:
        return
    try:
        fids = {int(fid) for fid in (fids_parents or [])}
    except (TypeError, ValueError):
        fids = set()
    if not fids:
        return

    for widget in _widgets_relation_alertes_ouverts(iface):
        try:
            relation = widget.relation()
            if relation is None or not relation.isValid():
                continue
            if relation.referencedLayerId() != couche_parent.id():
                continue
            if relation.referencingLayerId() != couche_alertes.id():
                continue
            feature = widget.feature()
            if feature is None or not feature.isValid():
                continue
            fid_parent = int(feature.id())
            if fid_parent not in fids:
                continue

            parent_courant = recuperer_entite(couche_parent, fid_parent)
            if parent_courant is None:
                continue
            widget.setFeature(parent_courant, True)
            try:
                widget.update()
            except (AttributeError, RuntimeError):
                pass
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue


def synchroniser_zone(
    iface,
    couche_parent,
    geometrie_zone,
    nom_commande="Synchroniser les alertes",
):
    """Réaligne les alertes et recalcule les indicateurs dans une zone.

    Règles appliquées :
    - tout polygone concerné possède un ``id_foret`` non nul ;
    - chaque point reçoit l'``id_foret`` du polygone qui le contient ;
    - ``priorite_max`` reçoit la plus petite valeur de ``priorite`` ;
    - ``nb_alertes`` compte les points contenus ;
    - ``nb_alertes_vues`` est également recalculé s'il existe ;
    - avec des alertes, ``toutes_alertes_vues`` reflète leur état ``vu`` ;
    - sans alerte (0/0), la valeur manuelle du parent est conservée.

    Les modifications du parent sont ajoutées à la commande d'édition déjà
    ouverte par l'outil appelant lorsqu'il y en a une. Les changements de la
    couche d'alertes sont regroupés dans leur propre commande QGIS.
    """
    if couche_parent is None or geometrie_zone is None or geometrie_zone.isEmpty():
        return ResultatSynchronisation()

    couche_alertes = _trouver_couche_alertes_associee(couche_parent, iface)
    if couche_alertes is None:
        return ResultatSynchronisation()

    champs_parent = couche_parent.fields()
    champs_alertes = couche_alertes.fields()
    index_id_parent = champs_parent.indexOf(CHAMP_ID_FORET)
    index_id_alerte = champs_alertes.indexOf(CHAMP_ID_FORET)
    if index_id_parent < 0 or index_id_alerte < 0:
        raise RuntimeError("le champ id_foret est absent de la couche BD Forêt ou des alertes")

    # Chaque champ dérivé est optionnel (index -1 si absent de la couche) :
    # une couche de test allégée sans "essence_v2_priorite_max", par exemple,
    # ne doit pas faire échouer toute la synchronisation, juste sauter ce
    # champ précis plus loin dans la fonction.
    index_priorite_alerte = champs_alertes.indexOf(CHAMP_PRIORITE_ALERTE)
    index_priorite_max = champs_parent.indexOf(CHAMP_PRIORITE_MAX)
    index_nb_alertes = champs_parent.indexOf(CHAMP_NB_ALERTES)
    index_vu = champs_alertes.indexOf(CHAMP_VU)
    index_nb_vues = champs_parent.indexOf(CHAMP_NB_ALERTES_VUES)
    index_toutes_vues = champs_parent.indexOf(CHAMP_TOUTES_ALERTES_VUES)
    index_essence_v2_alerte = champs_alertes.indexOf(CHAMP_ESSENCE_V2_ALERTE)
    index_essence_v2_priorite = champs_parent.indexOf(
        CHAMP_ESSENCE_V2_PRIORITE_MAX
    )

    zone_parent = QgsGeometry(geometrie_zone)
    polygones = _polygones_intersectant_zone(couche_parent, zone_parent)
    if not polygones:
        return ResultatSynchronisation()

    # Répare aussi d'anciens NULL rencontrés dans la zone modifiée : voir
    # attribuer_nouvel_id_foret(), la seconde façon dont un id_foret peut
    # être produit dans ce plugin.
    for fid in list(polygones):
        entite = recuperer_entite(couche_parent, fid)
        if entite is None:
            continue
        if _est_nulle(entite[index_id_parent]):
            attribuer_nouvel_id_foret(couche_parent, fid)

    # On étend la recherche à l'intégralité des polygones touchés. Ainsi, leurs
    # compteurs sont recalculés sur toutes leurs alertes et pas seulement sur la
    # petite partie de géométrie qui vient de changer.
    geometries_touchees = []
    for fid in polygones:
        entite = recuperer_entite(couche_parent, fid)
        if entite is not None and not entite.geometry().isEmpty():
            geometries_touchees.append(QgsGeometry(entite.geometry()))
    if not geometries_touchees:
        return ResultatSynchronisation()
    # L'union de tous les polygones touchés (pas seulement geometrie_zone
    # reçue en paramètre) sert de zone de recherche des alertes ci-dessous.
    zone_complete = QgsGeometry.unaryUnion(geometries_touchees)

    # L'affectation des points n'a besoin que des polygones présents autour de
    # la zone réellement touchée. On construit donc un petit index local au lieu
    # de reconstruire un index de toute la BD Forêt à chaque découpe.
    rectangle_parents = zone_complete.boundingBox()
    try:
        rectangle_parents.combineExtentWith(zone_parent.boundingBox())
    except (AttributeError, RuntimeError):
        pass
    requete_parents_locaux = QgsFeatureRequest().setFilterRect(rectangle_parents)
    parents_locaux = {}
    index_parent = QgsSpatialIndex()
    for parent_local in couche_parent.getFeatures(requete_parents_locaux):
        geometrie_parent = parent_local.geometry()
        if geometrie_parent is None or geometrie_parent.isEmpty():
            continue
        fid_local = int(parent_local.id())
        parents_locaux[fid_local] = parent_local
        index_parent.addFeature(parent_local)

    # Même principe pour les alertes : on demande directement au fournisseur les
    # points dont la bounding box est dans la zone au lieu de créer un index de
    # toutes les alertes pour une modification locale.
    zone_alertes = _transformer_geometrie(
        zone_complete,
        couche_parent.crs(),
        couche_alertes.crs(),
    )
    fids_alertes = set()
    requete_alertes_spatiales = QgsFeatureRequest().setFilterRect(
        zone_alertes.boundingBox()
    )
    for alerte_locale in couche_alertes.getFeatures(requete_alertes_spatiales):
        fids_alertes.add(int(alerte_locale.id()))

    # Sécurité supplémentaire : une alerte qui porte encore l'id_foret d'un
    # polygone touché doit être réévaluée même si une ancienne synchronisation
    # l'avait laissée avec une association devenue incohérente. Cela permet de
    # réparer automatiquement les rattachements périmés lors de l'opération
    # géométrique suivante.
    ids_touches = set()
    ids_touches_natifs = set()
    for fid_parent in polygones:
        parent = recuperer_entite(couche_parent, fid_parent)
        if parent is None:
            continue
        valeur_id = parent[index_id_parent]
        cle = _valeur_cle(valeur_id)
        if cle is not None:
            ids_touches.add(cle)
            try:
                ids_touches_natifs.add(valeur_id)
            except TypeError:
                # Certains QVariant ne sont pas hashables : la valeur normalisée
                # reste suffisante pour construire le filtre.
                ids_touches_natifs.add(cle)

    if ids_touches_natifs:
        expression = _expression_ids_foret(CHAMP_ID_FORET, ids_touches_natifs)
        if expression:
            requete_anciennes = (
                QgsFeatureRequest()
                .setFilterExpression(expression)
                .setSubsetOfAttributes([index_id_alerte])
            )
            for alerte in couche_alertes.getFeatures(requete_anciennes):
                try:
                    if _valeur_cle(alerte[index_id_alerte]) in ids_touches:
                        fids_alertes.add(int(alerte.id()))
                except (IndexError, KeyError, TypeError, ValueError):
                    continue

    requete_alertes = QgsFeatureRequest().setFilterFids(list(fids_alertes))

    # Cache des entités parentes pour éviter de relire plusieurs fois les mêmes
    # polygones lors de l'affectation des points.
    cache_parent = {}
    affectations = {}
    alertes_sans_parent = set()
    alertes_lues = {}

    for alerte in couche_alertes.getFeatures(requete_alertes):
        geometrie_alerte = alerte.geometry()
        if geometrie_alerte is None or geometrie_alerte.isEmpty():
            continue
        try:
            point_parent = _transformer_geometrie(
                geometrie_alerte,
                couche_alertes.crs(),
                couche_parent.crs(),
            )
        except Exception:
            continue

        # Le filtre rectangulaire est volontairement suivi d'un vrai test
        # géométrique dans _choisir_polygone.
        candidats_fids = index_parent.intersects(point_parent.boundingBox())
        candidats = []
        for fid_parent in candidats_fids:
            fid_parent = int(fid_parent)
            if fid_parent not in cache_parent:
                # Dans le cas normal le parent est déjà dans le petit cache
                # spatial local. Le repli ponctuel couvre les rares entités
                # ajoutées au tampon pendant la synchronisation.
                cache_parent[fid_parent] = parents_locaux.get(fid_parent)
                if cache_parent[fid_parent] is None:
                    cache_parent[fid_parent] = recuperer_entite(
                        couche_parent, fid_parent
                    )
            entite_parent = cache_parent[fid_parent]
            if entite_parent is not None:
                candidats.append(entite_parent)

        parent = _choisir_polygone(
            point_parent,
            candidats,
            alerte[index_id_alerte],
            index_id_parent,
        )
        if parent is None:
            # Si l'alerte appartenait auparavant à l'un des polygones touchés
            # mais qu'aucun polygone ne la contient désormais (par exemple
            # après une découpe à l'emprise), son ancien id_foret ne doit pas
            # rester mensonger. Les ``vu`` ne sont évidemment pas modifiés.
            if _valeur_cle(alerte[index_id_alerte]) in ids_touches:
                fid_alerte = int(alerte.id())
                alertes_sans_parent.add(fid_alerte)
                alertes_lues[fid_alerte] = alerte
            continue

        fid_parent = int(parent.id())
        # On ne traite que les points appartenant réellement à la zone complète
        # ou à un polygone qui vient d'être identifié comme destination.
        try:
            if not zone_complete.intersects(point_parent) and fid_parent not in polygones:
                continue
        except (TypeError, RuntimeError):
            continue

        polygones.setdefault(fid_parent, parent)
        affectations[int(alerte.id())] = fid_parent
        alertes_lues[int(alerte.id())] = alerte

    # Modifications id_foret à appliquer aux alertes. On normalise les valeurs
    # pour éviter les faux écarts int/str, mais l'écriture utilise bien la
    # valeur native du champ id_foret du polygone destination.
    changements_alertes = {
        int(fid_alerte): NULL
        for fid_alerte in alertes_sans_parent
        if not _est_nulle(alertes_lues[fid_alerte][index_id_alerte])
    }
    for fid_alerte, fid_parent in affectations.items():
        alerte = alertes_lues[fid_alerte]
        parent = recuperer_entite(couche_parent, fid_parent)
        if parent is None:
            continue
        nouvel_id = parent[index_id_parent]
        if _valeur_cle(alerte[index_id_alerte]) != _valeur_cle(nouvel_id):
            changements_alertes[fid_alerte] = nouvel_id

    # Les rattachements sont des données dérivées de la géométrie. Ils sont
    # écrits dans le tampon d'édition de la couche Alertes, mais volontairement
    # SANS beginEditCommand/endEditCommand : ils ne doivent pas créer leur
    # propre marche Ctrl+Z. Quand la géométrie est annulée/rétablie, le signal
    # geometryChanged relance simplement cette jointure spatiale.
    if changements_alertes:
        if not couche_alertes.isEditable():
            if not couche_alertes.startEditing():
                raise RuntimeError("la couche d'alertes ne peut pas être placée en mode édition")
            marquer_edition_alertes_ouverte_par_plugin(couche_alertes)

        for fid_alerte, nouvel_id in changements_alertes.items():
            if not fid_est_valide(couche_alertes, fid_alerte):
                continue

            alerte_avant = recuperer_entite(couche_alertes, fid_alerte)
            if alerte_avant is None:
                continue
            ancienne_valeur = alerte_avant[index_id_alerte]

            if not couche_alertes.changeAttributeValue(
                fid_alerte,
                index_id_alerte,
                nouvel_id,
                ancienne_valeur,
                True,
            ):
                raise RuntimeError(
                    f"l'id_foret de l'alerte {fid_alerte} n'a pas pu être mis à jour"
                )

            # Vérification immédiate du tampon d'édition.
            alerte_apres = couche_alertes.getFeature(fid_alerte)
            valeur_apres = (
                alerte_apres[index_id_alerte]
                if alerte_apres is not None and alerte_apres.isValid()
                else NULL
            )
            if _valeur_cle(valeur_apres) != _valeur_cle(nouvel_id):
                if not fid_est_valide(couche_alertes, fid_alerte):
                    continue
                tampon = couche_alertes.editBuffer()
                if tampon is None or not tampon.changeAttributeValue(
                    fid_alerte, index_id_alerte, nouvel_id, valeur_apres
                ):
                    raise RuntimeError(
                        f"l'id_foret de l'alerte {fid_alerte} est resté incohérent"
                    )

    # Les statistiques sont calculées sur la position spatiale réelle des
    # points. Les nouvelles valeurs d'id_foret ne sont donc pas une condition
    # préalable au calcul.
    statistiques = {
        int(fid): {
            "nb": 0,
            "priorites": [],
            "vues": 0,
            "essence_v2": NULL,
            "cle_essence_v2": None,
        }
        for fid in polygones
    }
    for fid_alerte, fid_parent in affectations.items():
        if fid_parent not in statistiques:
            continue
        alerte = alertes_lues[fid_alerte]
        statistiques[fid_parent]["nb"] += 1
        priorite = None
        if index_priorite_alerte >= 0:
            priorite = priorite_numerique(alerte[index_priorite_alerte])
            if priorite is not None:
                statistiques[fid_parent]["priorites"].append(priorite)

        # Même règle que lors de la préparation initiale : conserver l'ESSENCE_V2
        # de l'alerte la plus prioritaire. En cas d'égalité, le FID de l'alerte
        # stabilise le choix afin que le résultat ne dépende pas de l'ordre de
        # parcours du fournisseur.
        if (
            index_essence_v2_alerte >= 0
            and index_essence_v2_priorite >= 0
            and priorite is not None
        ):
            cle = (priorite, int(fid_alerte))
            if (
                statistiques[fid_parent]["cle_essence_v2"] is None
                or cle < statistiques[fid_parent]["cle_essence_v2"]
            ):
                statistiques[fid_parent]["cle_essence_v2"] = cle
                statistiques[fid_parent]["essence_v2"] = alerte[
                    index_essence_v2_alerte
                ]

        if index_vu >= 0 and _en_booleen(alerte[index_vu]):
            statistiques[fid_parent]["vues"] += 1

    for fid_parent, stats in statistiques.items():
        valeurs_calculees = {}
        if index_nb_alertes >= 0:
            valeurs_calculees[index_nb_alertes] = stats["nb"]
        if index_priorite_max >= 0:
            valeurs_calculees[index_priorite_max] = (
                min(stats["priorites"]) if stats["priorites"] else NULL
            )
        if index_nb_vues >= 0:
            valeurs_calculees[index_nb_vues] = stats["vues"]
        if index_essence_v2_priorite >= 0:
            valeurs_calculees[index_essence_v2_priorite] = stats["essence_v2"]
        if index_toutes_vues >= 0 and stats["nb"] > 0:
            # Ne jamais écraser la validation manuelle d'un polygone 0/0 lors
            # d'une découpe, d'une fusion ou d'un remodelage.
            valeurs_calculees[index_toutes_vues] = bool(
                stats["vues"] == stats["nb"]
            )

        # Ne pas réécrire des indicateurs déjà corrects. C'est important pour
        # les synchronisations automatiques déclenchées par les signaux de
        # géométrie : elles peuvent être appelées plusieurs fois pendant une
        # même découpe et ne doivent pas ajouter de commandes d'édition inutiles.
        parent_courant = recuperer_entite(couche_parent, fid_parent)
        # IMPORTANT : un polygone peut avoir disparu pendant la modification
        # géométrique (fusion, suppression, nettoyage, clip...). L'ancienne
        # logique réécrivait alors malgré tout ses compteurs dans l'editBuffer,
        # créant un « FID fantôme » impossible à valider dans le GeoPackage.
        # Un parent absent est désormais simplement ignoré.
        if parent_courant is None or not fid_est_valide(couche_parent, fid_parent):
            continue

        valeurs_parent = {}
        for index_champ, nouvelle_valeur in valeurs_calculees.items():
            try:
                ancienne_valeur = parent_courant[index_champ]
            except (IndexError, KeyError):
                ancienne_valeur = NULL
            if nouvelle_valeur == NULL:
                identique = _est_nulle(ancienne_valeur)
            elif isinstance(nouvelle_valeur, bool):
                identique = _en_booleen(ancienne_valeur) == nouvelle_valeur
            else:
                try:
                    identique = ancienne_valeur == nouvelle_valeur
                except Exception:
                    identique = False
            if not identique:
                valeurs_parent[index_champ] = nouvelle_valeur

        if valeurs_parent:
            # Marque la couche pendant l'écriture : c'est ce que lit
            # ecriture_parent_interne_en_cours() (voir plus haut) pour que
            # CompteurAlertes distingue cette écriture automatique d'un vrai
            # clic utilisateur sur toutes_alertes_vues.
            cle_ecriture = _cle_couche(couche_parent)
            _COUCHES_PARENT_EN_ECRITURE_INTERNE.add(cle_ecriture)
            try:
                ok_parent = couche_parent.changeAttributeValues(
                    fid_parent, valeurs_parent
                )
            finally:
                _COUCHES_PARENT_EN_ECRITURE_INTERNE.discard(cle_ecriture)
            if not ok_parent:
                raise RuntimeError(
                    f"les indicateurs du polygone {fid_parent} n'ont pas pu être recalculés"
                )

    # Regrouper les rafraîchissements : QGIS repeindra ces couches lors du
    # prochain rendu de carte au lieu de forcer deux redraws immédiats.
    couche_parent.triggerRepaint(True)
    couche_alertes.triggerRepaint(True)
    if changements_alertes:
        rafraichir_vue_relation_alertes(
            iface, couche_parent, couche_alertes, polygones.keys()
        )
    return ResultatSynchronisation(
        fids_parents=(fid for fid in polygones.keys() if fid_est_valide(couche_parent, fid)),
        iface=iface,
    )
