# -*- coding: utf-8 -*-
"""Nettoie automatiquement la couche de travail, par petits lots (QTimer).

C'est une action indépendante du panneau (bouton « Nettoyer la couche »),
distincte de « Vérifier les règles métier ».

Reconstruction en cours, une étape à la fois, chacune testée en réel avant
d'ajouter la suivante (l'ancienne version, construite d'un coup, a produit
plusieurs bugs qui n'apparaissaient que sur de vraies données BD Forêt — voir
l'historique du changelog). Arrondi des coordonnées, découpe à l'emprise et
alignement entre voisins ont été construits, testés, puis retirés sur
décision explicite (voir l'historique du changelog 2026-09-22 : les
interactions entre ces trois étapes et la vraie couche d'emprise, découpée en
plusieurs milliers de morceaux, ont produit plusieurs bugs sérieux d'affilée
— entités déplacées hors de l'emprise, explosion du nombre de trous détectés
— sans qu'un correctif fiable soit trouvé à temps). Étapes actuellement en
place :

1. Mise en conformité OGC : toute géométrie non valide de la couche est
   réparée. isGeosValid() ignore sans calcul les entités déjà valides (le cas
   courant), nettoyer_geometrie_base() (makeValid() puis ne garde que les
   composantes polygonales, en écartant tout résidu non polygonal) répare le
   reste. Purement local à chaque entité, une seule passe suffit.

2. Élimination des petites surfaces entières (< 100 m²,
   SURFACE_MAXIMALE_MICRO_ECART_M2 — séparée de la constante équivalente de
   "Reporter depuis BDFv2", passée à 0,25 ha pour cet autre outil) : chaque
   entité entière sous le seuil est fusionnée avec son meilleur voisin
   (commun_topologie.meilleur_voisin_par_contact, déjà utilisée par les
   panneaux Surfaces < 0,5 ha et Trous) puis supprimée.

3. Comblement des trous (< 100 m²) : mêmes fonctions que le panneau
   "Trous dans la couche" (verification_trous.py) pour rester cohérent avec
   ce qu'il détecte — construire_geometrie_emprise_locale (déjà utilisée en
   production, pas le calcul refait spécifiquement pour l'étape 3 de
   l'alignement, aujourd'hui retirée) puis emprise moins l'union de toute la
   couverture. Calculé une seule fois pour toute la couche (comme l'ancienne
   découpe à l'emprise), le résultat est ensuite reversé par petits lots :
   chaque trou sous le seuil est comblé dans son meilleur voisin
   (meilleur_voisin_par_contact accepte explicitement une géométrie sans
   entité, comme un trou). Un trou plus grand n'est pas touché, laissé à
   l'arbitrage humain via le panneau.

4. Recouvrements (< 100 m²) : verification_recouvrements.corriger_micro_recouvrement
   absorbe le recouvrement dans le plus grand des deux polygones, déjà
   écrite et documentée "utilisée par le nettoyage automatique" mais restée
   orpheline jusqu'ici. Paires candidates trouvées via un index spatial sur
   toute la couche (même principe que la recherche de recouvrements du
   panneau : chaque paire n'est examinée qu'une fois).

5. Parties isolées de multiparties (< 100 m²) : pour chaque entité encore
   multipartie, chaque petite partie isolée est fusionnée avec son meilleur
   voisin externe (même schéma que l'étape 2) et retirée de l'entité
   d'origine ; une partie sans voisin externe reste rattachée à sa géométrie
   d'origine plutôt que d'être perdue. Même principe que le recollage de
   "Reporter depuis BDFv2" (_recoller_parties_isolees), simplifié : ici une
   seule entité existante à la fois, pas un lot de nouvelles pièces à
   recoller entre elles.

6. Suppression hors emprise : tout polygone (ou toute partie de polygone)
   hors de l'emprise est supprimé — l'algorithme natif QGIS « Couper »
   (native:clip, optimisé en C++) calcule en une fois la couche de travail
   découpée par l'emprise, sur une couche mémoire minimale (jamais la vraie
   couche en édition). C'est le même principe que l'ancienne étape 2
   (« découpe à l'emprise », retirée avec l'alignement entre voisins) : ce
   n'était pas cette étape-là qui posait problème, mais son interaction avec
   l'alignement, qui déplaçait ensuite des entités hors de la bordure que
   cette étape venait de fixer. Placée en dernier ici (une fois la couche
   déjà propre), donc plus aucune étape suivante ne peut la redéfaire.

7. Synchronisation des alertes : commun_compteur_alertes.py (indépendant de
   ce module, toujours actif) réaligne normalement les points "alertes" sur
   la bonne géométrie après chaque modification, mais reste volontairement
   silencieux pendant tout le nettoyage (verification.py suspend son écoute
   via suspendre_synchronisation_geometrique, pour ne pas relancer ce calcul
   à chaque écriture des étapes précédentes — c'est justement ce qui causait
   les 10 minutes d'origine). Cette étape déclenche donc explicitement, une
   seule fois, le recalcul que le nettoyage a différé (synchroniser_modification_geometrique,
   sur l'étendue de la couche) : c'est un vrai calcul (pas un bug), qui peut
   prendre du temps sur une grosse couche puisque le nettoyage touche
   souvent la quasi-totalité des entités. Si décochée, les alertes restent
   dans l'état où elles étaient avant le nettoyage jusqu'à la prochaine
   modification qui les concerne.

Tout tourne par petits lots (``QTimer.singleShot``) sur le thread principal,
jamais dans un ``QgsTask`` séparé : un vrai thread a été essayé, mais un
calcul GEOS massif ne répond pas à une demande d'annulation avant la fin de
l'appel C++ en cours — à la fermeture de QGIS, l'application attend que la
tâche se termine ou réponde à l'annulation, ce qui a bloqué la fermeture
complète de QGIS en pratique. Le découpage en petits lots garde l'interface
réactive sans ce risque : chaque lot rend la main à Qt entre deux étapes, et
fermer le panneau ou QGIS pendant un nettoyage abandonne proprement la suite
(rien n'est à annuler de force).

Le panneau affiche une ligne par étape : celles déjà terminées restent
affichées (texte final, position = total), l'étape en cours est la dernière
ligne et avance seule (voir progression_nettoyage).
"""

from qgis import processing
from qgis.analysis import QgsGeometrySnapper
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorLayer,
)

from .commun_couches import couche_est_disponible
from .commun_parametres import SURFACE_MAXIMALE_MICRO_ECART_M2
from .commun_topologie import (
    construire_geometrie_emprise_locale,
    extraire_parties_polygonales,
    meilleur_voisin_par_contact,
    nettoyer_geometrie_base,
)
from .verification_recouvrements import corriger_micro_recouvrement

LIBELLES_ETAPES = {
    "conformite": "mise en conformité OGC",
    "petites_surfaces": "petites surfaces entières fusionnées au meilleur voisin (< 100 m²)",
    "trous": "trous comblés en les intégrant au meilleur voisin (< 100 m²)",
    "recouvrements": "recouvrements absorbés par le plus grand polygone (< 100 m²)",
    "parties_isolees": "parties isolées de multiparties fusionnées au meilleur voisin (< 100 m²)",
    "hors_emprise": "suppression des polygones (ou parties) hors de l'emprise",
    "synchronisation_alertes": "synchronisation des alertes",
}
NUMEROS_ETAPES = {
    "conformite": 1,
    "petites_surfaces": 2,
    "trous": 3,
    "recouvrements": 4,
    "parties_isolees": 5,
    "hors_emprise": 6,
    "synchronisation_alertes": 7,
}
# Ordre d'exécution : source unique de vérité, utilisée à la fois par le menu
# de sélection des étapes (verification_panneau.py) et par _phase_suivante()
# pour enchaîner sur la prochaine étape ACTIVÉE (pas forcément la suivante
# dans cette liste, si l'utilisateur en a décoché certaines).
ORDRE_ETAPES = [
    "conformite",
    "petites_surfaces",
    "trous",
    "recouvrements",
    "parties_isolees",
    "hors_emprise",
    "synchronisation_alertes",
]

# Précision du projet (1 cm) pour aligner les sommets avant fusion : évite
# qu'une fusion locale laisse une pointe résiduelle si les deux géométries
# n'ont pas exactement les mêmes sommets sur leur bord commun.
TOLERANCE_FUSION_VOISIN_M = 0.01


def preparer_nettoyage(self, etapes_activees=None):
    """Prépare le parcours de toute la couche, sans lancer de gros calcul.

    ``etapes_activees`` : sous-ensemble de ORDRE_ETAPES à exécuter (menu de
    personnalisation du bouton "Nettoyer la couche") ; ``None`` = toutes.

    Retourne ``None`` si la couche de travail est introuvable, n'est pas
    éditable (le nettoyage a besoin d'écrire), ou si ``etapes_activees`` ne
    contient aucune étape connue ; l'appelant décide alors quoi afficher.
    """
    couche = self._trouver_couche()
    if not couche_est_disponible(couche) or not couche.isEditable():
        return None

    if etapes_activees is None:
        etapes_activees = set(ORDRE_ETAPES)
    else:
        etapes_activees = set(etapes_activees) & set(ORDRE_ETAPES)
    premiere_phase = next((e for e in ORDRE_ETAPES if e in etapes_activees), None)
    if premiere_phase is None:
        return None

    try:
        # setNoAttributes() seul ne dispense pas de lire la géométrie de
        # chaque entité : ici on ne veut que les fid, NoGeometry évite de
        # charger inutilement des dizaines de milliers de géométries pour
        # les rejeter aussitôt.
        requete = QgsFeatureRequest().setNoAttributes()
        requete.setFlags(QgsFeatureRequest.NoGeometry)
        fids = [int(feature.id()) for feature in couche.getFeatures(requete)]
    except RuntimeError:
        return None
    return {
        "phase": premiere_phase,
        "etapes_activees": etapes_activees,
        "couche_id": couche.id(),
        "fids": fids,
        "position": 0,
        "corriges": 0,
        "supprimes": 0,
        "fusionnes": 0,
        "termine": False,
        "lignes_terminees": [],
        "resultats_trous": None,
        "index_recouvrements": None,
        "geometries_recouvrements": None,
        "resultats_hors_emprise": None,
        "synchronisation_demarree": False,
    }


def _phase_suivante(etat):
    """Prochaine étape ACTIVÉE après la phase courante, ou ``None`` si finie."""
    etapes_activees = etat.get("etapes_activees") or set(ORDRE_ETAPES)
    try:
        index_actuel = ORDRE_ETAPES.index(etat.get("phase"))
    except ValueError:
        return None
    for phase in ORDRE_ETAPES[index_actuel + 1:]:
        if phase in etapes_activees:
            return phase
    return None


def _passer_a_etape_suivante(etat):
    """Clôt l'étape courante et enchaîne sur la prochaine étape ACTIVÉE.

    Termine le nettoyage (``etat["termine"] = True``) s'il n'en reste aucune —
    que ce soit parce que toutes les étapes ont tourné, ou parce que
    l'utilisateur avait décoché celles qui suivaient dans le menu.
    """
    suivante = _phase_suivante(etat)
    etat["lignes_terminees"].append(_ligne_etape(etat))
    if suivante is None:
        etat["termine"] = True
    else:
        etat["phase"] = suivante
        etat["position"] = 0


def traiter_lot_nettoyage(self, etat, taille_lot=200):
    """Avance le nettoyage par petits lots et rend vite la main à Qt."""
    if not etat or etat.get("termine"):
        return True

    couche = self._trouver_couche()
    if not couche_est_disponible(couche) or couche.id() != etat.get("couche_id") or not couche.isEditable():
        etat["termine"] = True
        return True

    phase = etat.get("phase")
    if phase == "conformite":
        _traiter_lot_conformite(couche, etat, taille_lot)
    elif phase == "petites_surfaces":
        _traiter_lot_petites_surfaces(couche, etat, taille_lot)
    elif phase == "trous":
        _traiter_lot_trous(self, couche, etat, taille_lot)
    elif phase == "recouvrements":
        _traiter_lot_recouvrements(couche, etat, taille_lot)
    elif phase == "parties_isolees":
        _traiter_lot_parties_isolees(couche, etat, taille_lot)
    elif phase == "hors_emprise":
        _traiter_lot_hors_emprise(self, couche, etat, taille_lot)
    elif phase == "synchronisation_alertes":
        _traiter_lot_synchronisation_alertes(self, couche, etat, taille_lot)
    else:
        etat["termine"] = True

    return etat.get("termine", False)


def _traiter_lot_conformite(couche, etat, taille_lot):
    """Corrige les géométries encore invalides d'un lot (étape 1), puis avance/termine.

    Purement local (pas de dépendance aux voisins) : une seule passe suffit.
    Une entité déjà valide (le cas courant) est ignorée sans aucun calcul,
    isGeosValid() étant bien moins coûteux qu'un makeValid().
    """
    fids = etat["fids"]
    position = int(etat.get("position", 0))
    limite = min(len(fids), position + max(1, int(taille_lot)))
    lot_fids = fids[position:limite]

    request = QgsFeatureRequest().setFilterFids(lot_fids)
    for feature in couche.getFeatures(request):
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        geometrie_avant = feature.geometry()
        if geometrie_avant.isGeosValid():
            continue
        fid = int(feature.id())
        valide = nettoyer_geometrie_base(geometrie_avant)
        if valide is None or valide.isEmpty():
            continue
        if couche.changeGeometry(fid, valide):
            etat["corriges"] += 1

    etat["position"] = limite
    if limite >= len(fids):
        _passer_a_etape_suivante(etat)


def _fusionner_dans_voisin(couche, petite_geometrie, fid_voisin):
    """Fusionne ``petite_geometrie`` dans le voisin ``fid_voisin``, ou ``None``.

    Même schéma léger que le recollage de petites parties isolées de
    "Reporter depuis BDFv2" (edition_reporter_bdfv2.py) : le voisin (souvent
    bien plus grand) est aligné SUR la petite géométrie, pas l'inverse — un
    index bon marché à reconstruire pour QgsGeometrySnapper à chaque appel.
    """
    feature_voisin = couche.getFeature(fid_voisin)
    if feature_voisin is None or not feature_voisin.hasGeometry():
        return None
    geometrie_voisin = feature_voisin.geometry()
    try:
        voisin_aligne = QgsGeometrySnapper.snapGeometry(
            geometrie_voisin, TOLERANCE_FUSION_VOISIN_M, [petite_geometrie]
        )
    except (AttributeError, TypeError, RuntimeError):
        voisin_aligne = geometrie_voisin
    try:
        fusion = QgsGeometry.unaryUnion([petite_geometrie, voisin_aligne])
    except (TypeError, RuntimeError):
        return None
    return nettoyer_geometrie_base(fusion)


def _traiter_lot_petites_surfaces(couche, etat, taille_lot):
    """Fusionne un lot de petites entités entières (< 100 m²) avec leur
    meilleur voisin (étape 2), puis avance ou termine.

    Purement local (chaque fusion relit l'état courant du voisin sur la
    couche, jamais un cache) : pas de dépendance d'ordre entre entités, une
    seule passe suffit.
    """
    fids = etat["fids"]
    position = int(etat.get("position", 0))
    limite = min(len(fids), position + max(1, int(taille_lot)))
    lot_fids = fids[position:limite]

    request = QgsFeatureRequest().setFilterFids(lot_fids)
    for feature in couche.getFeatures(request):
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        geometrie = feature.geometry()
        if geometrie.area() >= SURFACE_MAXIMALE_MICRO_ECART_M2:
            continue
        fid = int(feature.id())
        fid_voisin = meilleur_voisin_par_contact(couche, geometrie, fid_exclu=fid)
        if fid_voisin is None:
            continue
        fusion = _fusionner_dans_voisin(couche, geometrie, fid_voisin)
        if fusion is None or fusion.isEmpty():
            continue
        if couche.changeGeometry(fid_voisin, fusion) and couche.deleteFeature(fid):
            etat["fusionnes"] += 1

    etat["position"] = limite
    if limite >= len(fids):
        _passer_a_etape_suivante(etat)


def _executer_recherche_trous(self, couche):
    """Tous les trous de la couche (emprise - couverture), sans seuil.

    Mêmes fonctions que verification_trous.preparer_recherche_trous, pour
    détecter exactement les mêmes trous que le panneau "Trous dans la
    couche" — sans quoi le nettoyage automatique pourrait "réussir" tout en
    laissant des trous que le panneau continuerait de signaler autrement.
    """
    couche_emprise = self._trouver_couche_emprise()
    if not couche_est_disponible(couche_emprise):
        raise RuntimeError("couche d'emprise introuvable ou vide (comblement des trous)")

    try:
        etendue = QgsRectangle(couche.extent())
    except (AttributeError, RuntimeError, TypeError):
        raise RuntimeError("emprise de la couche de travail introuvable")
    if etendue.isEmpty():
        return []

    emprise_geom = construire_geometrie_emprise_locale(couche_emprise, etendue, couche.crs())
    if emprise_geom is None or emprise_geom.isEmpty():
        return []

    couverture = [
        QgsGeometry(feature.geometry())
        for feature in couche.getFeatures(QgsFeatureRequest().setNoAttributes())
        if feature.hasGeometry() and not feature.geometry().isEmpty()
    ]
    try:
        couverture_union = QgsGeometry.unaryUnion(couverture) if couverture else QgsGeometry()
        trou = emprise_geom if couverture_union.isEmpty() else emprise_geom.difference(couverture_union)
    except (AttributeError, TypeError, RuntimeError):
        return []
    if trou is None or trou.isEmpty():
        return []

    return [partie for partie in extraire_parties_polygonales(trou) if partie.area() > 0.0]


def _traiter_lot_trous(self, couche, etat, taille_lot):
    """Comble un lot de petits trous (< 100 m², étape 3), puis avance ou termine.

    Le calcul complet des trous (_executer_recherche_trous) se fait en un
    seul appel, comme l'ancienne découpe à l'emprise : c'est le report par
    petits lots qui garde l'interface réactive, pas le calcul lui-même.
    """
    if etat.get("resultats_trous") is None:
        tous_les_trous = _executer_recherche_trous(self, couche)
        etat["resultats_trous"] = [
            trou for trou in tous_les_trous if trou.area() < SURFACE_MAXIMALE_MICRO_ECART_M2
        ]
        etat["position"] = 0

    trous = etat["resultats_trous"]
    position = int(etat.get("position", 0))
    limite = min(len(trous), position + max(1, int(taille_lot)))
    lot_trous = trous[position:limite]

    for trou in lot_trous:
        fid_voisin = meilleur_voisin_par_contact(couche, trou)
        if fid_voisin is None:
            continue
        fusion = _fusionner_dans_voisin(couche, trou, fid_voisin)
        if fusion is None or fusion.isEmpty():
            continue
        if couche.changeGeometry(fid_voisin, fusion):
            etat["fusionnes"] += 1

    etat["position"] = limite
    if limite >= len(trous):
        # Même ordre que pour l'ancienne découpe à l'emprise : la ligne finale
        # (via _ligne_etape) a encore besoin de resultats_trous pour ne pas
        # afficher "calcul en cours" à tort sur l'étape pourtant terminée.
        _passer_a_etape_suivante(etat)
        etat["resultats_trous"] = None


def _construire_cache_travail(couche):
    """Index spatial + géométries courantes de toute la couche (une fois)."""
    index = QgsSpatialIndex()
    geometries = {}
    for feature in couche.getFeatures(QgsFeatureRequest().setNoAttributes()):
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        geometries[int(feature.id())] = QgsGeometry(feature.geometry())
        index.addFeature(feature)
    return index, geometries


def _traiter_lot_recouvrements(couche, etat, taille_lot):
    """Absorbe un lot de petits recouvrements (< 100 m², étape 4) dans le
    plus grand des deux polygones, puis avance ou termine.

    Même principe que la recherche de recouvrements du panneau : un index
    spatial sur toute la couche, chaque paire de voisins proches (bbox)
    n'étant examinée qu'une fois (candidat_fid > fid). Chaque correction
    relit l'état courant dans le cache (jamais la couche à nouveau) : une
    entité déjà rétrécie par une paire précédente dans la même passe est vue
    correctement par la paire suivante.
    """
    if etat.get("index_recouvrements") is None:
        index, geometries = _construire_cache_travail(couche)
        etat["index_recouvrements"] = index
        etat["geometries_recouvrements"] = geometries

    index = etat["index_recouvrements"]
    geometries = etat["geometries_recouvrements"]
    fids = etat["fids"]
    position = int(etat.get("position", 0))
    limite = min(len(fids), position + max(1, int(taille_lot)))
    lot_fids = fids[position:limite]

    for fid in lot_fids:
        geometrie = geometries.get(fid)
        if geometrie is None or geometrie.isEmpty():
            continue
        for candidat_fid in index.intersects(geometrie.boundingBox()):
            candidat_fid = int(candidat_fid)
            if candidat_fid <= fid:
                continue
            geometrie_candidate = geometries.get(candidat_fid)
            if geometrie_candidate is None or geometrie_candidate.isEmpty():
                continue
            resultat = corriger_micro_recouvrement(geometrie, geometrie_candidate)
            if resultat is None:
                continue
            cote_perdant, geometrie_corrigee = resultat
            fid_perdant = fid if cote_perdant == "a" else candidat_fid
            if not couche.changeGeometry(fid_perdant, geometrie_corrigee):
                continue
            geometries[fid_perdant] = geometrie_corrigee
            if fid_perdant == fid:
                geometrie = geometrie_corrigee
            etat["corriges"] += 1

    etat["position"] = limite
    if limite >= len(fids):
        etat["index_recouvrements"] = None
        etat["geometries_recouvrements"] = None
        _passer_a_etape_suivante(etat)


def _traiter_lot_parties_isolees(couche, etat, taille_lot):
    """Détache les petites parties isolées d'un lot de multiparties (étape 5).

    Purement local à chaque entité (comme l'étape 2) : une seule passe
    suffit. Une partie sans voisin externe reste attachée à sa géométrie
    d'origine plutôt que d'être perdue (même principe prudent que "Reporter
    depuis BDFv2").
    """
    fids = etat["fids"]
    position = int(etat.get("position", 0))
    limite = min(len(fids), position + max(1, int(taille_lot)))
    lot_fids = fids[position:limite]

    request = QgsFeatureRequest().setFilterFids(lot_fids)
    for feature in couche.getFeatures(request):
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        geometrie = feature.geometry()
        if not geometrie.isMultipart():
            continue
        parties = [
            QgsGeometry(partie)
            for partie in geometrie.asGeometryCollection()
            if partie is not None and not partie.isEmpty()
        ]
        if len(parties) <= 1:
            continue
        parties.sort(key=lambda g: g.area(), reverse=True)

        fid = int(feature.id())
        restantes = [parties[0]]
        detachee = False
        for partie in parties[1:]:
            if partie.area() >= SURFACE_MAXIMALE_MICRO_ECART_M2:
                restantes.append(partie)
                continue
            fid_voisin = meilleur_voisin_par_contact(couche, partie, fid_exclu=fid)
            if fid_voisin is not None:
                fusion = _fusionner_dans_voisin(couche, partie, fid_voisin)
                if fusion is not None and not fusion.isEmpty() and couche.changeGeometry(fid_voisin, fusion):
                    etat["fusionnes"] += 1
                    detachee = True
                    continue
            # Aucun voisin externe trouvé : gardée plutôt que perdue.
            restantes.append(partie)

        if not detachee:
            continue

        nouvelle_geometrie = restantes[0] if len(restantes) == 1 else QgsGeometry.collectGeometry(restantes)
        nouvelle_geometrie = nettoyer_geometrie_base(nouvelle_geometrie)
        if nouvelle_geometrie is None or nouvelle_geometrie.isEmpty():
            continue
        if couche.changeGeometry(fid, nouvelle_geometrie):
            etat["corriges"] += 1

    etat["position"] = limite
    if limite >= len(fids):
        _passer_a_etape_suivante(etat)


CHAMP_FID_ORIGINE = "fid_origine"
# Sentinelle distincte de None : None (absent du dict de résultat) veut dire
# "entièrement hors emprise, à supprimer", alors qu'INCHANGEE veut dire "déjà
# entièrement dans l'emprise, rien à écrire" (voir _executer_decoupe_emprise).
INCHANGEE = object()


def _reparer_couche_native(couche_memoire):
    """Répare en bloc les géométries non valides d'une couche mémoire jetable.

    native:fixgeometries (C++) au lieu d'une boucle Python entité par
    entité : seulement appelé en repli, quand native:clip vient d'échouer
    (donc rare en pratique, l'étape 1 ayant déjà réparé la couche de travail
    dans le pipeline complet). Préserve les attributs (donc CHAMP_FID_ORIGINE)
    un par un, sans fusionner ni éclater les entités.
    """
    resultat = processing.run(
        "native:fixgeometries", {"INPUT": couche_memoire, "OUTPUT": "memory:"}
    )
    return resultat["OUTPUT"]


def _executer_decoupe_emprise(self, couche):
    """Découpe toute la couche par l'emprise en un seul appel natif QGIS.

    Reprend le principe de l'ancienne étape 2 (découpe à l'emprise, retirée
    avec l'alignement entre voisins) : ce n'était pas native:clip qui posait
    problème, mais l'alignement qui déplaçait ensuite des entités hors de la
    bordure que cette découpe venait de fixer. Construit une couche mémoire
    minimale (fid d'origine + géométrie) à partir de la couche de travail —
    jamais la vraie couche en édition, l'algorithme "Couper" produit une
    nouvelle couche de toute façon.

    Retourne un dict {fid d'origine: géométrie découpée}, absent pour toute
    entité entièrement hors emprise (à supprimer par l'appelant).
    """
    couche_emprise = self._trouver_couche_emprise()
    if not couche_est_disponible(couche_emprise):
        raise RuntimeError("couche d'emprise introuvable ou vide")

    # Copie brute, SANS validation systématique : isGeosValid()/makeValid()
    # sur chaque entité en Python (nettoyer_geometrie_base) coûtait cher sur
    # une grosse couche (signalé très lent), pour un cas rare en pratique —
    # l'étape "mise en conformité OGC" (1) a déjà réparé la couche de travail
    # avant que cette étape (6) ne s'exécute dans le pipeline complet. Le CRS
    # est assigné directement depuis l'objet (setCrs), jamais via une chaîne
    # crs=<authid> dans l'URI (robuste même sans code EPSG enregistré). Type
    # déclaré en MultiPolygon (accepte aussi les Polygon simples) : une
    # couche BD Forêt réelle mélange souvent les deux.
    couche_source = QgsVectorLayer(
        f"MultiPolygon?field={CHAMP_FID_ORIGINE}:integer",
        "source_decoupe_nettoyage",
        "memory",
    )
    couche_source.setCrs(couche.crs())
    champs_source = couche_source.fields()
    features_source = []
    # Conservées pour repérer ensuite les entités que native:clip renvoie
    # inchangées (entièrement dans l'emprise, le cas le plus courant) : pas
    # la peine de les réécrire dans la vraie couche pour rien.
    geometries_originales = {}
    for feature in couche.getFeatures(QgsFeatureRequest().setNoAttributes()):
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        fid = int(feature.id())
        geometries_originales[fid] = QgsGeometry(feature.geometry())
        nouvelle = QgsFeature(champs_source)
        nouvelle.setGeometry(feature.geometry())
        nouvelle.setAttribute(CHAMP_FID_ORIGINE, fid)
        features_source.append(nouvelle)
    couche_source.dataProvider().addFeatures(features_source)
    couche_source.updateExtents()

    couche_emprise_validee = QgsVectorLayer("MultiPolygon", "emprise_validee_nettoyage", "memory")
    couche_emprise_validee.setCrs(couche_emprise.crs())
    features_emprise = []
    for feature in couche_emprise.getFeatures(QgsFeatureRequest().setNoAttributes()):
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        nouvelle = QgsFeature(couche_emprise_validee.fields())
        nouvelle.setGeometry(feature.geometry())
        features_emprise.append(nouvelle)
    couche_emprise_validee.dataProvider().addFeatures(features_emprise)
    couche_emprise_validee.updateExtents()

    try:
        resultat = processing.run(
            "native:clip",
            {"INPUT": couche_source, "OVERLAY": couche_emprise_validee, "OUTPUT": "memory:"},
        )
    except Exception:
        # Repli seulement si le chemin rapide échoue vraiment (géométrie
        # encore invalide, cas rare) : réparation groupée par un algorithme
        # natif (native:fixgeometries, C++), jamais une boucle Python
        # entité par entité — même logique que le passage à native:clip et
        # native:dissolve plus tôt dans cette étape/le nettoyage.
        couche_source = _reparer_couche_native(couche_source)
        couche_emprise_validee = _reparer_couche_native(couche_emprise_validee)
        resultat = processing.run(
            "native:clip",
            {"INPUT": couche_source, "OVERLAY": couche_emprise_validee, "OUTPUT": "memory:"},
        )
    couche_resultat = resultat["OUTPUT"]

    geometries_par_fid = {}
    for feature in couche_resultat.getFeatures():
        if not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        fid_origine = feature.attribute(CHAMP_FID_ORIGINE)
        if fid_origine is None:
            continue
        fid_origine = int(fid_origine)
        geometrie = QgsGeometry(feature.geometry())
        # native:clip conserve normalement une seule entité par entité
        # d'origine (même scindée, en un seul multi-polygone) ; par sécurité,
        # si plusieurs morceaux portaient malgré tout le même fid d'origine,
        # ils sont réunis plutôt que de s'écraser l'un l'autre.
        if fid_origine in geometries_par_fid:
            geometries_par_fid[fid_origine] = geometries_par_fid[fid_origine].combine(geometrie)
        else:
            geometries_par_fid[fid_origine] = geometrie

    # La plupart des entités sont entièrement dans l'emprise : native:clip
    # les renvoie alors identiques à l'original (aucune découpe nécessaire).
    # Les marquer INCHANGEE (plutôt que de les retirer du dict, ce qui les
    # confondrait avec les entités entièrement hors emprise, absentes du
    # dict) évite à l'appelant de les réécrire pour rien dans la vraie
    # couche — la plupart des dizaines de milliers d'écritures évitées.
    # Comparaison topologique (isGeosEqual), pas octet à octet : le repli de
    # réparation (native:fixgeometries, ci-dessus) peut réordonner les
    # sommets d'un anneau sans changer la forme, ce qui casserait une
    # comparaison WKB même pour une entité restée géométriquement identique.
    for fid_origine, geometrie_finale in geometries_par_fid.items():
        originale = geometries_originales.get(fid_origine)
        if originale is not None and geometrie_finale.isGeosEqual(originale):
            geometries_par_fid[fid_origine] = INCHANGEE

    # Garde-fou : la couche de travail est par définition censée être
    # presque entièrement dans son emprise. Un résultat vide ou très
    # minoritaire ne doit jamais se traduire par une suppression en masse
    # silencieuse — on préfère échouer bruyamment (bug réel déjà rencontré :
    # CRS mal transmis à la couche temporaire -> tout traité comme hors
    # emprise).
    if features_source:
        proportion_conservee = len(geometries_par_fid) / len(features_source)
        if len(geometries_par_fid) == 0 or (len(features_source) > 20 and proportion_conservee < 0.1):
            raise RuntimeError(
                "la suppression hors emprise n'a conservé que "
                f"{len(geometries_par_fid)}/{len(features_source)} entité(s) — probablement un "
                "problème de système de coordonnées ou de couche d'emprise, pas une vraie "
                "suppression en masse. Rien n'a été modifié, annulez l'édition en cours par "
                "sécurité et vérifiez la couche d'emprise avant de relancer."
            )

    return geometries_par_fid


def _traiter_lot_hors_emprise(self, couche, etat, taille_lot):
    """Reverse un lot du résultat de la découpe (étape 6), puis avance ou termine."""
    if etat.get("resultats_hors_emprise") is None:
        etat["resultats_hors_emprise"] = _executer_decoupe_emprise(self, couche)
        etat["position"] = 0

    resultats = etat["resultats_hors_emprise"]
    fids = etat["fids"]
    position = int(etat.get("position", 0))
    limite = min(len(fids), position + max(1, int(taille_lot)))
    lot_fids = fids[position:limite]

    for fid in lot_fids:
        nouvelle_geometrie = resultats.get(fid)
        if nouvelle_geometrie is INCHANGEE:
            # Déjà entièrement dans l'emprise : rien à écrire (voir
            # _executer_decoupe_emprise), la grande majorité des cas.
            continue
        if nouvelle_geometrie is None or nouvelle_geometrie.isEmpty():
            if couche.deleteFeature(fid):
                etat["supprimes"] += 1
            continue
        if couche.changeGeometry(fid, nouvelle_geometrie):
            etat["corriges"] += 1

    etat["position"] = limite
    if limite >= len(fids):
        # L'ordre compte : _ligne_etape (appelée par _passer_a_etape_suivante)
        # regarde encore resultats_hors_emprise pour savoir si la ligne finale
        # doit afficher "calcul en cours" ou "X/Y" — le réinitialiser avant
        # afficherait à tort "calcul en cours" sur la ligne pourtant terminée.
        _passer_a_etape_suivante(etat)
        etat["resultats_hors_emprise"] = None


def _traiter_lot_synchronisation_alertes(self, couche, etat, taille_lot):
    """Déclenche le recalcul des alertes différé pendant tout le nettoyage
    (étape 7), en un seul appel bloquant — pas de granularité par lot
    possible pour ce calcul. Deux passages : le premier ne fait que se
    signaler "en cours" (sinon le texte de progression n'aurait jamais
    l'occasion de s'afficher avant l'appel bloquant qui suit) ; le second
    déclenche vraiment le calcul.

    verification.py a suspendu l'écoute automatique de
    commun_compteur_alertes au tout début du nettoyage (voir la docstring du
    module) : cette étape déclenche explicitement le recalcul que cette
    suspension a différé. Si commun_compteur_alertes n'est pas chargé,
    l'étape ne fait rien et se termine directement.
    """
    if not etat.get("synchronisation_demarree"):
        etat["synchronisation_demarree"] = True
        return

    compteur = getattr(self.manager, "compteur_alertes", None) if getattr(self, "manager", None) else None
    fonction = getattr(compteur, "synchroniser_modification_geometrique", None)
    if callable(fonction):
        try:
            etendue = couche.extent()
            if etendue is not None and not etendue.isEmpty():
                fonction(couche, QgsGeometry.fromRect(etendue), "Nettoyage automatique")
        except (AttributeError, RuntimeError, TypeError):
            pass

    etat["synchronisation_demarree"] = False
    _passer_a_etape_suivante(etat)


def _ligne_etape(etat):
    """Ligne (colonne Étape, colonne Détail) pour l'étape en cours dans ``etat``."""
    phase = etat.get("phase", "conformite")
    numero = NUMEROS_ETAPES.get(phase, "?")
    libelle = LIBELLES_ETAPES.get(phase, phase)
    position = int(etat.get("position", 0))
    etape_colonne = str(numero)
    if phase == "trous":
        if etat.get("resultats_trous") is None and not etat.get("termine"):
            # _executer_recherche_trous n'a pas de granularité par lot : rien
            # à afficher en position/total tant que ce calcul n'est pas fini.
            return (etape_colonne, f"{libelle}… calcul en cours")
        trous = etat.get("resultats_trous") or []
        if not trous:
            # max(1, ...) plus bas évite un "0/0" partout ailleurs, mais
            # afficherait ici "0/1" alors qu'il n'y a réellement aucun trou
            # sous le seuil à combler — signalé confus, corrigé.
            return (etape_colonne, f"{libelle}… aucun trou à combler")
        return (etape_colonne, f"{libelle}… {position}/{len(trous)}")
    if phase == "hors_emprise" and etat.get("resultats_hors_emprise") is None and not etat.get("termine"):
        # native:clip traite toute la couche en un seul appel, sans
        # granularité par lot : rien à afficher en position/total tant que
        # ce calcul n'est pas terminé.
        return (etape_colonne, f"{libelle}… calcul en cours")
    if phase == "synchronisation_alertes":
        # Pas de notion de position/total pour cette étape (un seul appel
        # bloquant, pas de parcours par fid) : "calcul en cours" pendant
        # l'appel, "terminé" une fois fait, jamais une fraction trompeuse.
        if etat.get("synchronisation_demarree") and not etat.get("termine"):
            return (etape_colonne, f"{libelle}… calcul en cours")
        return (etape_colonne, f"{libelle}… terminé")
    total = max(1, len(etat.get("fids", [])))
    return (etape_colonne, f"{libelle}… {position}/{total}")


def progression_nettoyage(etat):
    """Lignes (étape, détail) affichées dans le panneau pendant le nettoyage.

    Une ligne par étape : les étapes déjà terminées restent affichées
    (voir _passer_a_etape_suivante), seule la dernière ligne avance.
    """
    if not etat:
        return [_ligne_etape({"phase": "conformite", "fids": [], "position": 0})]
    lignes = list(etat.get("lignes_terminees", []))
    if not etat.get("termine"):
        # Une fois terminé, la ligne de la dernière étape est déjà dans
        # lignes_terminees (ajoutée par _passer_a_etape_suivante) : comme
        # etat["phase"] ne change plus après ça, la recalculer ici la
        # dupliquerait (vu en pratique avec l'étape 7, affichée deux fois).
        lignes.append(_ligne_etape(etat))
    return lignes


def nombre_etapes_prevues(etat):
    """Nombre total de lignes que le nettoyage affichera une fois fini.

    Sert à réserver tout de suite la bonne hauteur pour le tableau de
    progression (voir verification.py) : sans ça, il grandissait ligne par
    ligne au fur et à mesure des étapes, au lieu d'avoir sa taille finale
    dès le départ. +1 pour la ligne finale "Terminé" (résumé chiffré, ajoutée
    à part par verification.py une fois finaliser_nettoyage() appelé — pas
    une étape du pipeline elle-même).
    """
    if not etat:
        return 1
    return len(etat.get("etapes_activees") or ORDRE_ETAPES) + 1


def finaliser_nettoyage(etat):
    """Retourne ``(entités corrigées, entités supprimées, écarts fusionnés)``."""
    if not etat:
        return 0, 0, 0
    return etat.get("corriges", 0), etat.get("supprimes", 0), etat.get("fusionnes", 0)
