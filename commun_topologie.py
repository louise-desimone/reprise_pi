# -*- coding: utf-8 -*-
"""Fonctions géométriques communes aux outils de Reprise PI.

Ce module centralise le nettoyage, les découpes protégées et la fusion des
polygones. Il ne modifie jamais directement une couche QGIS.
"""

import math

from qgis.analysis import QgsGeometrySnapper
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsPointXY,
    QgsRectangle,
    QgsWkbTypes,
)

from .commun_couches import trouver_couche_emprise
from .commun_parametres import (
    TOLERANCE_MIN_AIRE,
    TOLERANCE_NETTOYAGE_FUSION_M,
    TOLERANCE_NETTOYAGE_DECOUPE_M,
    TOLERANCE_RELATIVE_AIRE,
    SURFACE_MAXIMALE_BOUCLE_PARASITE_M2,
    TOLERANCE_RETOUR_POINTE_PARASITE_M,
    PROFONDEUR_MINIMALE_POINTE_PARASITE_M,
)


def nettoyer_geometrie_base(geometrie):
    """Retourne une géométrie polygonale valide ou ``None``.

    ``makeValid`` peut produire une collection de géométries. Dans ce cas,
    seules les parties polygonales sont conservées puis réunies.
    """
    if geometrie is None or geometrie.isEmpty():
        return None

    try:
        resultat = QgsGeometry(geometrie)
        if not resultat.isGeosValid():
            resultat = resultat.makeValid()
        if resultat is None or resultat.isEmpty():
            return None

        if QgsWkbTypes.geometryType(resultat.wkbType()) == QgsWkbTypes.PolygonGeometry:
            return resultat

        parties = []
        for partie in resultat.asGeometryCollection():
            if (
                partie is not None
                and not partie.isEmpty()
                and QgsWkbTypes.geometryType(partie.wkbType())
                == QgsWkbTypes.PolygonGeometry
            ):
                parties.append(QgsGeometry(partie))

        if not parties:
            return None
        resultat = QgsGeometry.unaryUnion(parties)
        return resultat if resultat is not None and not resultat.isEmpty() else None
    except (AttributeError, TypeError, RuntimeError):
        return None


def calculer_tolerance_aire(geometrie):
    """Retourne une petite tolérance d'aire adaptée à la géométrie."""
    if geometrie is None or geometrie.isEmpty():
        return TOLERANCE_MIN_AIRE
    try:
        return max(
            TOLERANCE_MIN_AIRE,
            abs(float(geometrie.area())) * TOLERANCE_RELATIVE_AIRE,
        )
    except (TypeError, ValueError, RuntimeError):
        return TOLERANCE_MIN_AIRE


def compter_parties_polygonales(geometrie):
    """Compte uniquement les composantes polygonales ayant une aire réelle.

    Certains MultiPolygon contiennent une composante dégénérée d'aire nulle ou
    quasi nulle (résidu numérique après une opération géométrique). Elle ne doit
    pas faire classer l'entité comme multipartie.
    """
    if geometrie is None or geometrie.isEmpty():
        return 0
    try:
        if not geometrie.isMultipart():
            return 1

        tolerance = calculer_tolerance_aire(geometrie)
        compteur = 0
        for partie in geometrie.asGeometryCollection():
            if (
                partie is not None
                and not partie.isEmpty()
                and QgsWkbTypes.geometryType(partie.wkbType())
                == QgsWkbTypes.PolygonGeometry
                and abs(float(partie.area())) > tolerance
            ):
                compteur += 1
        return compteur
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return 0


def limite_polygone(geometrie):
    """Reconstruit la bordure d'un polygone comme géométrie de lignes.

    ``QgsGeometry.boundary()`` (GEOS ``Boundary``) ferait la même chose en
    une ligne, mais c'est une vraie opération topologique GEOS : elle peut
    échouer (ou renvoyer une géométrie vide) sur une géométrie invalide,
    auto-intersectée ou avec des sommets quasi dupliqués — exactement le
    genre de défaut que « Géométries parasites » sert à détecter sur de la
    BD Forêt en cours d'édition. On reconstruit donc la bordure en lisant
    directement les sommets, sans opération topologique, pour que le
    diagnostic reste possible même sur une géométrie topologiquement
    invalide.
    """
    if geometrie is None:
        return None
    try:
        if geometrie.isNull() or geometrie.isEmpty():
            return None

        copie = QgsGeometry(geometrie)
        try:
            copie.convertToStraightSegment()
        except (AttributeError, RuntimeError, TypeError):
            pass

        anneaux = []
        if copie.isMultipart():
            polygones = copie.asMultiPolygon()
            for polygone in polygones:
                for anneau in polygone:
                    if anneau and len(anneau) >= 2:
                        anneaux.append([QgsPointXY(p) for p in anneau])
        else:
            polygone = copie.asPolygon()
            for anneau in polygone:
                if anneau and len(anneau) >= 2:
                    anneaux.append([QgsPointXY(p) for p in anneau])

        if not anneaux:
            return None
        if len(anneaux) == 1:
            limite = QgsGeometry.fromPolylineXY(anneaux[0])
        else:
            limite = QgsGeometry.fromMultiPolylineXY(anneaux)
        if limite is None or limite.isNull() or limite.isEmpty():
            return None
        return limite
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def morceaux_lineaires(geometrie):
    """Décompose une géométrie en une liste de morceaux linéaires simples.

    Une intersection GEOS peut renvoyer une GeometryCollection contenant des
    lignes et des points : seules les composantes linéaires sont conservées.
    Les segments d'une même ligne qui se touchent sont fusionnés.
    """
    if geometrie is None or geometrie.isEmpty():
        return []
    try:
        type_geom = QgsWkbTypes.geometryType(geometrie.wkbType())
    except (AttributeError, RuntimeError, TypeError):
        return []
    if type_geom == QgsWkbTypes.LineGeometry:
        try:
            fusionnee = geometrie.mergeLines()
            if fusionnee is not None and not fusionnee.isEmpty():
                geometrie = fusionnee
        except (AttributeError, RuntimeError, TypeError):
            pass
        try:
            if geometrie.isMultipart():
                # asGeometryCollection() renvoie déjà des QgsGeometry.
                return [
                    partie
                    for partie in geometrie.asGeometryCollection()
                    if partie is not None and not partie.isEmpty()
                ]
        except (AttributeError, RuntimeError, TypeError):
            pass
        return [geometrie]

    morceaux = []
    try:
        for partie in geometrie.asGeometryCollection():
            morceaux.extend(morceaux_lineaires(partie))
    except (AttributeError, RuntimeError, TypeError):
        pass
    return morceaux


def longueur_lineaire(geometrie):
    """Longueur totale des morceaux linéaires d'une géométrie."""
    total = 0.0
    for morceau in morceaux_lineaires(geometrie):
        try:
            total += abs(float(morceau.length()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    return total


def epsilon_longueur(tolerance):
    """Petite tolérance de longueur, proportionnelle à ``tolerance``.

    Sert à distinguer une longueur réellement nulle d'un bruit numérique,
    sans dépendre d'une valeur fixe qui serait trop grande ou trop petite
    selon l'échelle de la tolérance appelante.
    """
    try:
        return max(abs(float(tolerance)) * 1e-5, 1e-9)
    except (TypeError, ValueError):
        return 1e-9


def partage_une_limite(limite_a, limite_b, tolerance_alignement_m=0.01, longueur_minimale_m=None):
    """Retourne le contact (ligne) entre deux limites de polygones, si réel.

    Aligne d'abord ``limite_b`` sur ``limite_a`` avec ``QgsGeometrySnapper`` :
    deux polygones numérisés séparément ont rarement des sommets exactement
    identiques le long de leur frontière commune, et une intersection brute
    peut manquer ce contact ou le sous-évaluer. ``limite_a``/``limite_b``
    s'obtiennent avec :func:`limite_polygone`.

    ``tolerance_alignement_m`` est la distance de rapprochement des sommets
    avant intersection, pas la longueur de contact exigée. ``longueur_minimale_m``
    fixe cette dernière ; par défaut, seul le bruit numérique est filtré
    (:func:`epsilon_longueur`), sans exiger de longueur de contact minimale.
    """
    if limite_a is None or limite_b is None or limite_a.isEmpty() or limite_b.isEmpty():
        return None
    try:
        limite_b_alignee = QgsGeometrySnapper.snapGeometry(
            limite_b, tolerance_alignement_m, [limite_a]
        )
        contact = limite_a.intersection(limite_b_alignee)
    except (AttributeError, TypeError, RuntimeError):
        return None
    if contact is None or contact.isEmpty():
        return None
    if longueur_minimale_m is None:
        longueur_minimale_m = epsilon_longueur(tolerance_alignement_m)
    if longueur_lineaire(contact) <= longueur_minimale_m:
        return None
    return contact


def meilleur_voisin_par_contact(couche, geometrie, fid_exclu=None):
    """Retourne le fid du polygone de la couche partageant la plus longue frontière.

    Généralise la règle déjà utilisée pour absorber un petit polygone ou un
    résidu parasite dans son voisin : la plus longue frontière commune
    l'emporte, le plus grand voisin départage une égalité. ``geometrie`` peut
    provenir d'une entité existante de la couche (auquel cas ``fid_exclu``
    l'exclut d'elle-même) ou d'une géométrie sans entité, comme un trou.
    """
    if couche is None or geometrie is None or geometrie.isEmpty():
        return None
    limite = limite_polygone(geometrie)

    meilleur = None
    meilleure_longueur = -1.0
    meilleure_surface = -1.0
    requete = QgsFeatureRequest().setFilterRect(geometrie.boundingBox())
    for autre in couche.getFeatures(requete):
        autre_fid = int(autre.id())
        if fid_exclu is not None and autre_fid == int(fid_exclu):
            continue
        if not autre.hasGeometry() or autre.geometry().isEmpty():
            continue
        autre_geom = autre.geometry()
        try:
            if not (geometrie.intersects(autre_geom) or geometrie.touches(autre_geom)):
                continue
            longueur = 0.0
            if limite is not None and not limite.isEmpty():
                autre_limite = limite_polygone(autre_geom)
                # Précision du projet (1 cm) pour l'alignement des sommets :
                # deux polygones voisins n'ont pas forcément des sommets
                # exactement coïncidents (cf. partage_une_limite).
                contact = partage_une_limite(limite, autre_limite, 0.01)
                if contact is not None:
                    longueur = longueur_lineaire(contact)
            surface = abs(float(autre_geom.area()))
        except (AttributeError, TypeError, ValueError, RuntimeError):
            continue
        # Priorité à la plus longue frontière commune ; à égalité stricte
        # (deux voisins touchant sur exactement la même longueur, rare mais
        # possible avec des formes régulières), le plus grand des deux
        # départage.
        if longueur > meilleure_longueur or (
            abs(longueur - meilleure_longueur) <= 1e-9 and surface > meilleure_surface
        ):
            meilleur = autre_fid
            meilleure_longueur = longueur
            meilleure_surface = surface

    return meilleur


def intersection_surfacique(geometrie_a, geometrie_b, tolerance=None):
    """Retourne l'intersection si elle possède une aire significative."""
    if (
        geometrie_a is None
        or geometrie_b is None
        or geometrie_a.isEmpty()
        or geometrie_b.isEmpty()
    ):
        return None

    if tolerance is None:
        tolerance = calculer_tolerance_aire(geometrie_a)

    try:
        intersection = geometrie_a.intersection(geometrie_b)
        if (
            intersection is not None
            and not intersection.isEmpty()
            and intersection.area() > tolerance
        ):
            return intersection
    except (TypeError, RuntimeError):
        pass
    return None


def extraire_intersection_surfacique_significative(
    intersection, surface_minimale, surface_partie_minimale=1e-8
):
    """Retourne la partie polygonale d'une intersection si elle est significative.

    La fonction ne connaît ni couche, ni interface, ni règle d'anomalie. Elle
    peut donc être appelée dans le thread principal ou dans un ``QgsTask`` qui
    travaille uniquement sur ses propres géométries.
    """
    if intersection is None or intersection.isEmpty():
        return QgsGeometry()

    # Chemin rapide pour l'immense majorité des voisins qui ne partagent qu'un
    # bord ou un point. ``area()`` vaut alors zéro et on évite l'extraction des
    # composantes polygonales + makeValid/unaryUnion, nettement plus coûteux.
    try:
        if abs(float(intersection.area())) < float(surface_minimale):
            return QgsGeometry()
    except (AttributeError, TypeError, ValueError, RuntimeError):
        pass

    resultat = reunir_parties_polygonales(
        intersection, surface_minimale=surface_partie_minimale
    )
    if (
        resultat is None
        or resultat.isEmpty()
        or abs(float(resultat.area())) < float(surface_minimale)
    ):
        return QgsGeometry()
    return resultat


def trouver_entites_intersectees(couche, geometrie, fids_exclus=None):
    """Retourne les entités ayant une intersection surfacique avec ``geometrie``."""
    if couche is None or geometrie is None or geometrie.isEmpty():
        return []

    exclus = {int(fid) for fid in (fids_exclus or [])}
    requete = QgsFeatureRequest().setFilterRect(geometrie.boundingBox())
    entites = []

    for entite in couche.getFeatures(requete):
        if int(entite.id()) in exclus:
            continue
        autre = entite.geometry()
        if autre is None or autre.isEmpty():
            continue
        if intersection_surfacique(geometrie, autre) is not None:
            entites.append(entite)

    return entites




def construire_geometrie_emprise_locale(couche_emprise, rectangle_cible, crs_cible=None):
    """Construit uniquement le morceau d'emprise nécessaire à une zone.

    Cette fonction ne parcourt jamais toute la couche pour une édition locale.
    Le rectangle reçu
    est exprimé dans ``crs_cible`` ; il est transformé vers le SCR de l'emprise
    uniquement pour filtrer les entités utiles côté fournisseur.
    """
    if couche_emprise is None or rectangle_cible is None:
        return None
    try:
        rectangle = QgsRectangle(rectangle_cible)
        if rectangle.isEmpty():
            return None

        transformation = None
        rectangle_source = QgsRectangle(rectangle)
        # setFilterRect() ci-dessous filtre côté fournisseur dans le SCR de
        # la couche d'emprise : le rectangle doit donc être converti vers ce
        # SCR avant la requête, et chaque géométrie récupérée reconvertie
        # vers crs_cible (transformation inverse) avant d'être combinée.
        if crs_cible is not None and couche_emprise.crs() != crs_cible:
            vers_source = QgsCoordinateTransform(
                crs_cible, couche_emprise.crs(), QgsProject.instance()
            )
            rectangle_source = vers_source.transformBoundingBox(rectangle_source)
            transformation = QgsCoordinateTransform(
                couche_emprise.crs(), crs_cible, QgsProject.instance()
            )

        request = QgsFeatureRequest().setFilterRect(rectangle_source).setNoAttributes()
        geometries = []
        for entite in couche_emprise.getFeatures(request):
            if not entite.hasGeometry():
                continue
            geometrie = QgsGeometry(entite.geometry())
            if geometrie.isEmpty():
                continue
            if transformation is not None:
                geometrie.transform(transformation)
            # Le filtre fournisseur est rectangulaire. Un vrai test évite
            # d'envoyer à unaryUnion des objets qui ne touchent pas la zone.
            if not geometrie.boundingBox().intersects(rectangle):
                continue
            geometries.append(geometrie)

        if not geometries:
            return None
        resultat = geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)
        if resultat is None or resultat.isEmpty():
            return None
        # Validation seulement sur le petit résultat local, pas sur chaque
        # polygone de toute la couche d'emprise.
        return nettoyer_geometrie_base(resultat)
    except (AttributeError, RuntimeError, TypeError):
        return None



def _supprimer_anneaux_interieurs(geometrie):
    """Reconstruit une géométrie uniquement avec ses contours extérieurs.

    Cette étape reprend le comportement historique de Fusionner : tous les
    trous et anneaux internes disparaissent. Les vraies enclaves sont recréées
    ensuite à partir des autres entités réellement présentes dans la couche.
    """
    # Répare d'abord la géométrie source : un anneau intérieur invalide
    # pourrait sinon fausser l'extraction ci-dessous.
    geometrie = nettoyer_geometrie_base(geometrie)
    if geometrie is None:
        return None

    try:
        # asPolygon()/asMultiPolygon() renvoient une liste d'anneaux par
        # polygone : l'index 0 est toujours l'anneau extérieur, les suivants
        # (s'il y en a) sont les trous.
        polygones = (
            geometrie.asMultiPolygon()
            if geometrie.isMultipart()
            else [geometrie.asPolygon()]
        )
        # Ne garde que l'anneau [0] de chaque polygone : les trous disparaissent.
        contours = [[polygone[0]] for polygone in polygones if polygone]
        if not contours:
            return None
        if len(contours) == 1:
            resultat = QgsGeometry.fromPolygonXY(contours[0])
        else:
            resultat = QgsGeometry.fromMultiPolygonXY(contours)
        # Reconstruire un contour à la main peut produire une géométrie
        # auto-intersectée (ex. un contour en forme de huit) : revalider.
        return nettoyer_geometrie_base(resultat)
    except (AttributeError, TypeError, RuntimeError, ValueError):
        return None


def nettoyer_contacts_ponctuels(geometrie):
    """Supprime les contacts ponctuels parasites produits par une fusion.

    Un buffer positif puis négatif d'un micromètre raccorde les parties qui ne
    se rejoignent qu'en un ou plusieurs sommets, sans simplifier volontairement
    le contour. Les nœuds strictement dupliqués sont ensuite supprimés.
    """
    resultat = nettoyer_geometrie_base(geometrie)
    if resultat is None:
        return None

    try:
        resultat = resultat.buffer(TOLERANCE_NETTOYAGE_FUSION_M, 1)
        if resultat is None or resultat.isEmpty():
            return None

        resultat = resultat.buffer(-TOLERANCE_NETTOYAGE_FUSION_M, 1)
        if resultat is None or resultat.isEmpty():
            return None

        resultat.removeDuplicateNodes()
        return nettoyer_geometrie_base(resultat)
    except (AttributeError, TypeError, RuntimeError):
        return None



def nettoyer_geometrie_decoupee_protegee(
    couche, geometrie, fids_exclus=None, tolerance_m=None
):
    """Nettoie une géométrie issue d'une découpe sans jamais l'agrandir.

    Le but est de supprimer les micro-pointes et nœuds parasites produits par
    ``difference``/``intersection`` tout en garantissant qu'aucune surface ne
    soit ajoutée au-delà de la géométrie reçue. Après le nettoyage, toutes les
    surfaces des autres polygones de la couche sont soustraites : une création
    de trou ou une attribution de recouvrement ne peut donc pas recouvrir une
    entité voisine ou une enclave existante.

    ``fids_exclus`` contient uniquement les entités que l'on ne doit pas
    soustraire (typiquement l'entité que l'on est en train de modifier).
    """
    original = nettoyer_geometrie_base(geometrie)
    if original is None or original.isEmpty():
        return None

    if tolerance_m is None:
        tolerance_m = TOLERANCE_NETTOYAGE_DECOUPE_M
    try:
        tolerance_m = max(0.0, float(tolerance_m))
    except (TypeError, ValueError):
        tolerance_m = TOLERANCE_NETTOYAGE_DECOUPE_M

    resultat = QgsGeometry(original)
    try:
        # Retire d'abord les nœuds strictement dupliqués.
        resultat.removeDuplicateNodes()

        # Une ouverture morphologique très faible retire les pointes/slivers
        # plus fins que la tolérance. On recoupe ensuite avec ``original`` :
        # même si le buffer arrondit légèrement un angle, aucune surface
        # nouvelle ne peut être créée. Si l'érosion vide la géométrie (objet
        # très fin), on conserve simplement le nettoyage des doublons.
        if tolerance_m > 0:
            erodee = resultat.buffer(-tolerance_m, 1)
            if erodee is not None and not erodee.isEmpty():
                rouverte = erodee.buffer(tolerance_m, 1)
                rouverte = nettoyer_geometrie_base(rouverte)
                if rouverte is not None and not rouverte.isEmpty():
                    rouverte = nettoyer_geometrie_base(rouverte.intersection(original))
                    if rouverte is not None and not rouverte.isEmpty():
                        resultat = rouverte
    except (AttributeError, TypeError, RuntimeError):
        resultat = QgsGeometry(original)

    resultat = nettoyer_geometrie_base(resultat)
    if resultat is None:
        return None

    if couche is not None:
        exclus = {int(fid) for fid in (fids_exclus or [])}
        try:
            requete = QgsFeatureRequest().setFilterRect(resultat.boundingBox())
            for entite in couche.getFeatures(requete):
                if int(entite.id()) in exclus:
                    continue
                autre = nettoyer_geometrie_base(entite.geometry())
                if autre is None or autre.isEmpty():
                    continue
                try:
                    # Recouper avec chaque voisin l'un après l'autre (plutôt
                    # qu'une seule différence avec leur union) : chaque étape
                    # reste une opération GEOS simple, moins fragile sur une
                    # couche avec beaucoup de petits voisins.
                    intersection = resultat.intersection(autre)
                    if (
                        intersection is None
                        or intersection.isEmpty()
                        or abs(float(intersection.area())) <= 0.0
                    ):
                        continue
                    resultat = nettoyer_geometrie_base(resultat.difference(autre))
                    if resultat is None or resultat.isEmpty():
                        return None
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    continue
        except (AttributeError, RuntimeError):
            pass

    # Dernier passage anti-doublons : les difference() successives peuvent
    # laisser des sommets quasi identiques le long des limites recoupées.
    try:
        resultat.removeDuplicateNodes()
    except (AttributeError, RuntimeError):
        pass
    return nettoyer_geometrie_base(resultat)


def fusionner_geometries(geometries):
    """Réunit et nettoie les polygones choisis pour une fusion.

    Chaque géométrie est d'abord alignée sur les précédentes avec
    ``QgsGeometrySnapper`` : deux polygones numérisés séparément ont rarement
    des sommets exactement identiques le long de leur frontière commune, et
    ``unaryUnion`` ne dissout pas une limite qui ne coïncide pas au sommet
    près (elle laisse alors un pique interne visible dans le résultat). Les
    anneaux intérieurs sont ensuite supprimés, comme dans le comportement
    historique de l'outil. Un buffer aller-retour extrêmement faible nettoie
    les contacts ponctuels parasites, puis un nettoyage anti-parasites répare
    pointes/fentes/papillons résiduels. Les vraies enclaves sont redécoupées
    après cette fonction à partir des autres entités de la couche.
    """
    # Passe 1 : valide chaque géométrie individuellement avant tout calcul
    # groupé (un seul polygone invalide dans le lot ferait sinon échouer
    # l'union entière).
    geometries = [
        nettoyer_geometrie_base(geometrie)
        for geometrie in geometries
        if geometrie is not None and not geometrie.isEmpty()
    ]
    geometries = [geometrie for geometrie in geometries if geometrie is not None]
    if not geometries:
        return None

    # Précision du projet (1 cm) pour l'alignement des sommets.
    distance_alignement_m = 0.01
    # Passe 2 : aligne chaque géométrie suivante sur TOUTES celles déjà
    # traitées (liste cumulative), pas seulement sur la première : avec 3
    # polygones ou plus, la 3e doit pouvoir s'accrocher aussi bien à la 1re
    # qu'à la 2e.
    geometries_alignees = [geometries[0]]
    for geometrie in geometries[1:]:
        try:
            alignee = QgsGeometrySnapper.snapGeometry(
                geometrie, distance_alignement_m, geometries_alignees
            )
        except (AttributeError, TypeError, RuntimeError):
            alignee = geometrie
        geometries_alignees.append(alignee)

    # Passe 3 : la vraie fusion géométrique, maintenant que les sommets
    # coïncident le long des frontières communes.
    try:
        resultat = QgsGeometry.unaryUnion(geometries_alignees)
    except (TypeError, RuntimeError):
        return None

    # Passe 4 : retire les trous/enclaves internes (comportement historique
    # de l'outil, voir docstring) — les vraies enclaves sont redécoupées
    # séparément par redecouper_polygones_inclus() à partir de la couche.
    resultat = _supprimer_anneaux_interieurs(resultat)
    if resultat is None:
        return None

    # Passe 5 : nettoie les points de contact parasites (buffer aller-retour
    # d'un micromètre, voir nettoyer_contacts_ponctuels).
    resultat = nettoyer_contacts_ponctuels(resultat)
    if resultat is None or resultat.isEmpty():
        return None

    # Passe 6 : répare les pointes/fentes/papillons résiduels ; si ce
    # nettoyage échoue ou vide la géométrie, on garde quand même le résultat
    # de la passe 5 plutôt que de tout perdre.
    nettoyee = nettoyer_geometrie_avance(resultat)
    if nettoyee is not None and not nettoyee.isEmpty():
        resultat = nettoyee
    return resultat


def redecouper_polygones_inclus(couche, geometrie_fusionnee, fids_fusionnes):
    """Retire du résultat toute zone qui recouvre un autre polygone de la couche.

    Le nettoyage de Fusionner supprime volontairement tous les anneaux
    intérieurs. En cas de recouvrement avec un autre polygone de la couche —
    vraie enclave ou simple défaut —, c'est toujours l'autre polygone qui
    garde la zone commune ; elle est retirée du résultat de la fusion.

    Un simple contact par le bord, même avec un infime recouvrement
    numérique, n'est jamais utilisé pour découper la fusion.
    """
    resultat = nettoyer_geometrie_base(geometrie_fusionnee)
    if couche is None or resultat is None:
        return resultat

    # Les entités qu'on vient de fusionner ne doivent jamais se recouper
    # elles-mêmes.
    exclus = {int(fid) for fid in (fids_fusionnes or [])}
    requete = QgsFeatureRequest().setFilterRect(resultat.boundingBox())

    for entite in couche.getFeatures(requete):
        if int(entite.id()) in exclus:
            continue

        voisin = nettoyer_geometrie_base(entite.geometry())
        if voisin is None:
            continue

        try:
            surface_voisin = abs(float(voisin.area()))
            if surface_voisin <= 0:
                continue

            intersection = resultat.intersection(voisin)
            if intersection is None or intersection.isEmpty():
                continue

            surface_intersection = abs(float(intersection.area()))
            tolerance = max(
                TOLERANCE_MIN_AIRE,
                surface_voisin * TOLERANCE_RELATIVE_AIRE,
            )

            # Pas d'intersection surfacique : simple contact par le bord.
            if surface_intersection <= tolerance:
                continue

            resultat = resultat.difference(voisin)
            resultat = nettoyer_geometrie_base(resultat)
            if resultat is None:
                return None

        except (AttributeError, TypeError, ValueError, RuntimeError):
            continue

    return resultat


def preparer_fusion_protegee(couche, geometries, fids_fusionnes):
    """Prépare une fusion avec exactement les règles de l'outil Fusionner.

    Cette fonction constitue l'unique chaîne géométrique de fusion du plugin :
    1. nettoyage des géométries polygonales ;
    2. alignement des sommets, union et suppression des limites/anneaux
       intérieurs parasites ;
    3. nettoyage des contacts ponctuels et des pointes/fentes résiduelles ;
    4. retrait de toute zone qui recouvre un autre polygone de la couche ;
    5. retrait de toute zone hors de l'emprise.

    L'utiliser partout évite que Vérifier et l'outil Fusionner produisent des
    géométries différentes pour une même situation. L'étape 5 est nécessaire
    même quand chaque partie fusionnée est déjà dans l'emprise : l'emprise
    n'est pas une surface homogène, elle peut contenir des trous (zones hors
    production), qu'une fusion peut se mettre à chevaucher une fois réunie.
    """
    # Étape 1 : nettoyage individuel. Un seul polygone invalide fait échouer
    # toute la fusion (return None), plutôt que d'ignorer silencieusement une
    # entité que l'utilisateur avait explicitement sélectionnée.
    propres = []
    for geometrie in geometries or []:
        propre = nettoyer_geometrie_base(geometrie)
        if propre is None or propre.isEmpty():
            return None
        propres.append(propre)

    if not propres:
        return None

    # Étapes 2-3 : alignement, union, nettoyage des contacts/pointes.
    resultat = fusionner_geometries(propres)
    if resultat is None or resultat.isEmpty():
        return None

    # Étape 4 : retire toute zone qui recouvre un autre polygone de la couche.
    resultat = redecouper_polygones_inclus(
        couche,
        resultat,
        fids_fusionnes,
    )
    if resultat is None or resultat.isEmpty():
        return None

    # Étape 5 : retire toute zone hors de l'emprise, si une couche d'emprise
    # existe dans le projet (sinon cette étape est simplement sautée).
    couche_emprise = trouver_couche_emprise()
    if couche_emprise is not None:
        crs_cible = couche.crs() if couche is not None else None
        masque_local = construire_geometrie_emprise_locale(
            couche_emprise, resultat.boundingBox(), crs_cible
        )
        if masque_local is None or masque_local.isEmpty():
            return None
        resultat = nettoyer_geometrie_base(resultat.intersection(masque_local))
        if resultat is None or resultat.isEmpty():
            return None

    # Aucune étape ci-dessus n'a été atteinte sans succès : le résultat est
    # une géométrie propre, sans recouvrement ni dépassement d'emprise.
    return resultat





# -----------------------------------------------------------------------------
# Primitives communes utilisées par le vérificateur
# -----------------------------------------------------------------------------


def extraire_parties_polygonales(geometrie, surface_minimale=0.0, rendre_valide=True):
    """Retourne les composantes polygonales significatives d'une géométrie.

    ``surface_minimale`` est exprimée dans les unités carrées du SCR. Cette
    fonction est la référence commune pour les trous, recouvrements,
    multiparties et la couche d'anomalies.
    """
    if geometrie is None or geometrie.isEmpty():
        return []
    try:
        geom = QgsGeometry(geometrie)
        if rendre_valide and not geom.isGeosValid():
            geom = geom.makeValid()
        if geom is None or geom.isEmpty():
            return []

        # makeValid() peut transformer un polygone en GeometryCollection
        # mixte (polygones + lignes + points résiduels) : les deux branches
        # ci-dessous couvrent respectivement "toujours resté polygonal" et
        # "collection à trier".
        candidates = []
        if QgsWkbTypes.geometryType(geom.wkbType()) == QgsWkbTypes.PolygonGeometry:
            if geom.isMultipart():
                candidates = [QgsGeometry(partie) for partie in geom.asGeometryCollection()]
            else:
                candidates = [geom]
        else:
            candidates = [QgsGeometry(partie) for partie in geom.asGeometryCollection()]

        # Ne garde que les composantes réellement polygonales et assez grandes :
        # une collection peut contenir des lignes/points résiduels et des
        # miettes numériques sans intérêt métier.
        resultat = []
        for partie in candidates:
            if partie is None or partie.isEmpty():
                continue
            if QgsWkbTypes.geometryType(partie.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue
            if abs(float(partie.area())) <= float(surface_minimale):
                continue
            resultat.append(partie)
        return resultat
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return []


def extraire_parties_multipartie_brutes(geometrie):
    """Extrait les vraies parties d'un MultiPolygon sans lancer ``makeValid``.

    Cette absence volontaire de ``makeValid`` évite que QGIS fusionne deux
    parties qui se touchent avant que l'utilisateur choisisse entre les
    actions « Séparer les parties » et « Fusionner les parties ».
    """
    if geometrie is None or geometrie.isEmpty():
        return []
    try:
        geom = QgsGeometry(geometrie)
        if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
            return []
        # Un simple Polygon (pas Multi) n'a qu'une seule partie par définition.
        if not geom.isMultipart():
            return [geom]
        tolerance = calculer_tolerance_aire(geom)
        resultat = []
        for partie in geom.asGeometryCollection():
            if (
                partie is not None
                and not partie.isEmpty()
                and QgsWkbTypes.geometryType(partie.wkbType()) == QgsWkbTypes.PolygonGeometry
                and abs(float(partie.area())) > tolerance
            ):
                resultat.append(QgsGeometry(partie))
        return resultat
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return []


def reunir_parties_polygonales(geometrie, surface_minimale=0.0, rendre_valide=True):
    """Réunit les composantes polygonales significatives en une géométrie.

    Retourne une géométrie vide si aucune composante ne subsiste. Cette fonction
    évite de réécrire dans chaque outil la séquence extraction + ``unaryUnion``.
    """
    parties = extraire_parties_polygonales(
        geometrie,
        surface_minimale=surface_minimale,
        rendre_valide=rendre_valide,
    )
    if not parties:
        return QgsGeometry()
    if len(parties) == 1:
        return QgsGeometry(parties[0])
    try:
        resultat = QgsGeometry.unaryUnion(parties)
        return resultat if resultat is not None else QgsGeometry()
    except (TypeError, RuntimeError):
        return QgsGeometry()


def _aire_anneau(anneau):
    try:
        if anneau is None or len(anneau) < 4:
            return 0.0
        return abs(float(QgsGeometry.fromPolygonXY([anneau]).area()))
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return 0.0


def nettoyer_pointes_interieures(anneau):
    """Retire les pointes/fentes intérieures de surface quasi nulle.

    Une "pointe" ici est un sommet ``courant`` dont le contour part vers lui
    puis repart quasiment sur la même droite (aller-retour) : les trois
    conditions testées dans la boucle ci-dessous sont, dans l'ordre,
    (1) ``courant`` est presque exactement sur le segment [precedent,suivant]
    (distance point-droite <= tol), (2) l'aller-retour parcourt une vraie
    distance (pas du bruit numérique : detour >= 2x la profondeur minimale),
    et (3) les deux segments qui se rejoignent en ``courant`` repartent
    presque en sens opposé (cosinus proche de -1 = quasi 180°, un vrai
    demi-tour). Un sommet qui ne vérifie que 1 des 3 n'est pas une pointe.
    """
    try:
        points = [QgsPointXY(point) for point in anneau]
    except (TypeError, RuntimeError):
        return anneau, 0
    if len(points) < 4:
        return points, 0

    tol = float(TOLERANCE_RETOUR_POINTE_PARASITE_M)
    profondeur_min = float(PROFONDEUR_MINIMALE_POINTE_PARASITE_M)
    if tol <= 0 or profondeur_min <= 0:
        return points, 0
    # Un anneau QGIS répète son premier point à la fin pour se refermer : on
    # le retire ici et le tour ci-dessous boucle par l'indexation modulo n.
    if points[0].distance(points[-1]) <= tol:
        points = points[:-1]

    def supprimer_retours_collineaires(liste_points):
        points_travail = list(liste_points)
        supprimes = 0
        # Répété jusqu'à plus aucune pointe trouvée : en retirer une peut en
        # révéler une autre juste à côté (pointes imbriquées).
        while len(points_travail) >= 3:
            index_a_supprimer = None
            n = len(points_travail)
            for i in range(n):
                precedent = points_travail[(i - 1) % n]
                courant = points_travail[i]
                suivant = points_travail[(i + 1) % n]
                longueur_avant = precedent.distance(courant)
                longueur_apres = courant.distance(suivant)
                longueur_directe = precedent.distance(suivant)
                # Segments trop courts (bruit) ou distance directe non finie
                # (points confondus) : rien de significatif à analyser ici.
                if (
                    longueur_avant < profondeur_min
                    or longueur_apres < profondeur_min
                    or not math.isfinite(longueur_directe)
                ):
                    continue
                try:
                    # Vecteur direct precedent→suivant (la "corde" que la
                    # pointe s'écarte à peine de) et vecteur precedent→courant,
                    # pour calculer ensuite la distance de courant à cette corde.
                    vx = float(suivant.x()) - float(precedent.x())
                    vy = float(suivant.y()) - float(precedent.y())
                    wx = float(courant.x()) - float(precedent.x())
                    wy = float(courant.y()) - float(precedent.y())
                    norme = (vx * vx + vy * vy) ** 0.5
                except (AttributeError, TypeError, ValueError, OverflowError):
                    continue
                if norme <= tol:
                    continue
                # Distance point-droite via le produit vectoriel 2D (aire du
                # parallélogramme / base = hauteur) : condition (1) ci-dessus.
                distance_droite = abs(vx * wy - vy * wx) / norme
                if distance_droite > tol:
                    continue
                # Détour = combien de distance en plus le contour parcourt en
                # passant par "courant" plutôt que directement : condition (2).
                detour = longueur_avant + longueur_apres - longueur_directe
                if detour < 2.0 * profondeur_min:
                    continue
                try:
                    # Angle entre les segments entrant et sortant de "courant"
                    # via le cosinus (produit scalaire normalisé) : condition (3).
                    in_x = float(courant.x()) - float(precedent.x())
                    in_y = float(courant.y()) - float(precedent.y())
                    out_x = float(suivant.x()) - float(courant.x())
                    out_y = float(suivant.y()) - float(courant.y())
                    produit = in_x * out_x + in_y * out_y
                    cosinus = produit / (longueur_avant * longueur_apres)
                except (AttributeError, TypeError, ValueError, ZeroDivisionError):
                    continue
                # cosinus proche de -1 = les deux segments repartent presque
                # exactement en sens inverse (demi-tour), pas un simple virage.
                if cosinus > -0.999999:
                    continue
                index_a_supprimer = i
                break
            if index_a_supprimer is None:
                break
            points_travail.pop(index_a_supprimer)
            supprimes += 1
        return points_travail, supprimes

    # Première passe : pointes "aller-retour" simples (3 points consécutifs).
    points, nombre_retours = supprimer_retours_collineaires(points)

    def trouver_meilleure_pointe(liste_points):
        """Cherche une boucle parasite : le contour part de ``i``, s'éloigne
        en dessinant une petite aire fermée, puis revient à moins de ``tol``
        de son point de départ en ``j`` (i et j ne sont pas forcément
        consécutifs, contrairement à supprimer_retours_collineaires
        ci-dessus). Un index spatial en grille (``buckets``) évite de
        comparer chaque point à tous les autres (coût quadratique) : seuls
        les points tombant dans la même case ou une case adjacente (grille de
        taille ``tol``) sont candidats à un "retour au même endroit".
        """
        n = len(liste_points)
        if n < 3:
            return None
        inv_tol = 1.0 / tol
        buckets = {}
        candidats = []
        for j, point in enumerate(liste_points):
            try:
                # Coordonnées de la case de grille contenant ce point.
                bx = math.floor(float(point.x()) * inv_tol)
                by = math.floor(float(point.y()) * inv_tol)
            except (TypeError, ValueError, OverflowError):
                continue
            # Les 9 cases (3x3) centrées sur la case du point : un point à
            # moins de tol peut se trouver dans une case voisine, pas
            # seulement dans la case exacte.
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for i in buckets.get((bx + dx, by + dy), ()):
                        # Exclut les points trop proches dans le contour
                        # (déjà couverts par la 1re passe) et le cas où i/j
                        # sont les deux extrémités de l'anneau (pas une boucle).
                        if j - i < 2 or (i == 0 and j == n - 1):
                            continue
                        if liste_points[i].distance(point) > tol:
                            continue
                        # Profondeur = à quel point le détour s'éloigne du
                        # point de départ ; une boucle trop plate (bruit
                        # numérique) est ignorée via profondeur_min.
                        profondeur = 0.0
                        for point_intermediaire in liste_points[i:j + 1]:
                            profondeur = max(
                                profondeur,
                                liste_points[i].distance(point_intermediaire),
                            )
                        if profondeur < profondeur_min:
                            continue
                        # L'aire de la boucle elle-même doit rester petite :
                        # une vraie excroissance volontaire ne doit jamais
                        # être confondue avec une boucle parasite.
                        sous_anneau = [QgsPointXY(p) for p in liste_points[i:j + 1]]
                        sous_anneau.append(QgsPointXY(liste_points[i]))
                        aire = _aire_anneau(sous_anneau)
                        if aire <= SURFACE_MAXIMALE_BOUCLE_PARASITE_M2:
                            candidats.append((profondeur, j - i, i, j))
            buckets.setdefault((bx, by), []).append(j)
        if not candidats:
            return None
        # La boucle la plus "profonde" (puis la plus longue à égalité) est
        # traitée en premier : c'est la plus probable d'être un vrai défaut
        # plutôt qu'un repli mineur du contour.
        candidats.sort(reverse=True)
        return candidats[0]

    # Répété jusqu'à ce qu'aucune boucle parasite ne subsiste ; en retirer une
    # peut modifier la géométrie assez pour en révéler une autre.
    nombre = nombre_retours
    while len(points) >= 3:
        meilleur = trouver_meilleure_pointe(points)
        if meilleur is None:
            break
        _, _, i, j = meilleur
        # Retire tout le détour entre i et j, ne garde que le point de
        # départ de la boucle (le contour "saute" directement de i à j+1).
        points = points[:i + 1] + points[j + 1:]
        nombre += 1
    if len(points) >= 3:
        points.append(QgsPointXY(points[0]))
    return points, nombre


def _decomposer_polygones_xy(geometrie):
    """Retourne les polygones XY d'une géométrie polygonale."""
    if geometrie is None or geometrie.isEmpty():
        return []
    try:
        if QgsWkbTypes.geometryType(geometrie.wkbType()) != QgsWkbTypes.PolygonGeometry:
            return []
        return geometrie.asMultiPolygon() if geometrie.isMultipart() else [geometrie.asPolygon()]
    except (AttributeError, TypeError, RuntimeError):
        return []


def supprimer_micro_residus_polygonaux(geometrie, seuil_m2=None):
    """Supprime les micro-composantes et micro-anneaux créés par une réparation.

    La fonction ne supprime jamais l'unique composante d'une entité : si toutes
    les composantes sont sous le seuil, la géométrie d'origine est conservée.
    """
    if geometrie is None or geometrie.isEmpty():
        return None
    seuil = float(
        SURFACE_MAXIMALE_BOUCLE_PARASITE_M2 if seuil_m2 is None else seuil_m2
    )
    propre = nettoyer_geometrie_base(geometrie)
    if propre is None or propre.isEmpty() or seuil < 0:
        return propre

    polygones = _decomposer_polygones_xy(propre)
    if not polygones:
        return propre

    # Calcule l'aire de chaque composante (polygone du Multi) avant de
    # décider quoi garder.
    infos = []
    for polygone in polygones:
        if not polygone or not polygone[0]:
            continue
        try:
            partie = QgsGeometry.fromPolygonXY(polygone)
            aire = abs(float(partie.area())) if partie is not None else 0.0
        except (AttributeError, TypeError, ValueError, RuntimeError):
            aire = 0.0
        infos.append((polygone, aire))

    if not infos:
        return propre

    # Règle du docstring : ne jamais tout supprimer. Si au moins une
    # composante dépasse le seuil (une "vraie" partie), les micro-composantes
    # sont éliminées ; sinon (toutes minuscules), elles sont toutes gardées.
    existe_partie_reelle = any(aire > seuil for _, aire in infos)
    reconstruits = []
    for polygone, aire in infos:
        if existe_partie_reelle and aire <= seuil:
            continue

        # Même logique pour les anneaux intérieurs (trous) de la composante
        # gardée : un trou minuscule (résidu numérique) est comblé en ne le
        # recopiant pas dans la reconstruction.
        contour = [QgsPointXY(point) for point in polygone[0]]
        anneaux = [contour]
        for anneau in polygone[1:]:
            points_anneau = [QgsPointXY(point) for point in anneau]
            try:
                aire_anneau = _aire_anneau(points_anneau)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                aire_anneau = seuil + 1.0
            if aire_anneau > seuil:
                anneaux.append(points_anneau)
        reconstruits.append(anneaux)

    if not reconstruits:
        return propre

    try:
        resultat = (
            QgsGeometry.fromMultiPolygonXY(reconstruits)
            if len(reconstruits) > 1
            else QgsGeometry.fromPolygonXY(reconstruits[0])
        )
        resultat = nettoyer_geometrie_base(resultat)
        return resultat if resultat is not None and not resultat.isEmpty() else propre
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return propre




# Petites excroissances du contour : le contour s'éloigne puis revient presque
# exactement à son point de départ. Ces valeurs reprennent le test validé sur
# le cas opérateur (~1,455 m de profondeur, ~2,91 m aller-retour).
LONGUEUR_MIN_EXCROISSANCE_PARASITE_M = 0.50
LONGUEUR_MAX_EXCROISSANCE_PARASITE_M = 6.0
DISTANCE_RETOUR_EXCROISSANCE_PARASITE_M = 0.05
NB_SEGMENTS_MAX_EXCROISSANCE_PARASITE = 15


def _trouver_excroissance_parasite(anneau):
    """Trouve une petite branche du contour qui sort puis revient au même endroit.

    On ne juge pas un segment parce qu'il est court : on recherche un trajet de
    contour de 0,5 à 6 m dont les deux extrémités sont à moins de 5 cm.
    """
    points = [QgsPointXY(p) for p in anneau]
    if len(points) < 4:
        return None
    ferme = points[0].distance(points[-1]) < 1e-9
    pts = points[:-1] if ferme else points
    n = len(pts)
    meilleur = None
    # Pour chaque point de départ possible, avance segment par segment
    # (jusqu'à NB_SEGMENTS_MAX) en cumulant la longueur parcourue, et teste à
    # chaque pas si le contour est revenu près de son point de départ.
    for debut in range(n):
        longueur = 0.0
        for nb_segments in range(1, NB_SEGMENTS_MAX_EXCROISSANCE_PARASITE + 1):
            fin = debut + nb_segments
            # Ne pas traverser artificiellement le point de fermeture de l'anneau.
            if fin >= n:
                break
            longueur += pts[fin - 1].distance(pts[fin])
            # Trop long pour être une excroissance parasite : abandonne ce
            # point de départ plutôt que de continuer à accumuler.
            if longueur > LONGUEUR_MAX_EXCROISSANCE_PARASITE_M:
                break
            if nb_segments < 2 or longueur < LONGUEUR_MIN_EXCROISSANCE_PARASITE_M:
                continue
            retour = pts[debut].distance(pts[fin])
            if retour <= DISTANCE_RETOUR_EXCROISSANCE_PARASITE_M:
                # Parmi tous les candidats valides trouvés, garde le plus
                # long (l'excroissance la plus significative).
                candidat = (debut, fin, longueur, retour)
                if meilleur is None or longueur > meilleur[2]:
                    meilleur = candidat
    return meilleur


def nettoyer_excroissances_parasites_anneau(anneau):
    """Retire uniquement les branches aller-retour détectées ci-dessus."""
    points = [QgsPointXY(p) for p in anneau]
    if len(points) < 4:
        return points, 0
    ferme = points[0].distance(points[-1]) < 1e-9
    if ferme:
        points = points[:-1]
    nombre = 0
    # Répété jusqu'à ce qu'aucune excroissance ne subsiste (comme pour les
    # boucles parasites plus haut, en retirer une peut en révéler une autre).
    while len(points) >= 3:
        candidat = _trouver_excroissance_parasite(points)
        if candidat is None:
            break
        debut, fin, _, _ = candidat
        # Retire la branche entière (debut..fin), ne garde que son point de départ.
        points = points[:debut + 1] + points[fin:]
        nombre += 1
    if ferme and points:
        points.append(QgsPointXY(points[0]))
    return points, nombre


def nettoyer_geometrie_avance(geometrie):
    """Nettoie les pointes/fentes et répare les papillons, sans simplifier le contour."""
    if geometrie is None or geometrie.isEmpty():
        return None
    try:
        source = QgsGeometry(geometrie)
        source_polygones = source.asMultiPolygon() if source.isMultipart() else [source.asPolygon()]
        polygones_nettoyes = []
        for polygone in source_polygones:
            if not polygone or not polygone[0]:
                continue
            # Excroissances puis pointes internes, sur l'anneau extérieur [0]
            # uniquement : ce nettoyage sert à la chaîne de fusion
            # (fusionner_geometries), qui n'a jamais eu besoin de traiter les
            # trous des polygones qu'elle réunit.
            contour, _ = nettoyer_excroissances_parasites_anneau(polygone[0])
            contour, _ = nettoyer_pointes_interieures(contour)
            # Les anneaux intérieurs (trous), eux, sont recopiés tels quels.
            anneaux = [contour]
            anneaux.extend([[QgsPointXY(point) for point in ring] for ring in polygone[1:]])
            partie = QgsGeometry.fromPolygonXY(anneaux)
            if partie is not None and not partie.isEmpty() and partie.asPolygon():
                polygones_nettoyes.append(partie.asPolygon())
        if not polygones_nettoyes:
            return None
        resultat = (
            QgsGeometry.fromMultiPolygonXY(polygones_nettoyes)
            if len(polygones_nettoyes) > 1
            else QgsGeometry.fromPolygonXY(polygones_nettoyes[0])
        )
        # La reconstruction main peut produire un "papillon" (auto-intersection) :
        # makeValid() le sépare proprement en parties polygonales distinctes.
        if resultat is not None and not resultat.isEmpty() and not resultat.isGeosValid():
            valide = nettoyer_geometrie_base(resultat)
            if valide is not None and not valide.isEmpty():
                resultat = valide
        # Dernier passage : élimine les miettes polygonales issues de la
        # réparation ci-dessus (voir supprimer_micro_residus_polygonaux).
        sans_micro_residus = supprimer_micro_residus_polygonaux(resultat)
        if sans_micro_residus is not None and not sans_micro_residus.isEmpty():
            resultat = sans_micro_residus
        return resultat
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return QgsGeometry(geometrie)


