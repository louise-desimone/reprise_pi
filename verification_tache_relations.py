# -*- coding: utf-8 -*-
"""Calcul asynchrone sûr des adjacences et recouvrements.

IMPORTANT : cette tâche ne reçoit aucune QgsVectorLayer, QgsProject, widget Qt,
aucun index spatial et aucune QgsGeometry provenant du thread principal. Les
géométries traversent la frontière du thread uniquement sous forme de WKB
(``bytes``), puis sont reconstruites localement dans ``run()``.
"""

from qgis.core import QgsGeometry, QgsTask

from .commun_parametres import (
    SURFACE_BRUIT_NUMERIQUE_GEOS_M2,
    TOLERANCE_ADJACENCE_M,
)
from .commun_topologie import (
    extraire_intersection_surfacique_significative,
    limite_polygone,
    partage_une_limite,
)


class TacheRelationsVoisines(QgsTask):
    """Calcule les diagnostics et intersections sans toucher aux objets de couche."""

    def __init__(self, donnees, paires_candidates, regles_activees, callback):
        super().__init__("Vérification BD Forêt — relations spatiales", QgsTask.CanCancel)
        # ``donnees`` contient uniquement des bytes WKB, tuples et chaînes.
        # Aucun objet lié à une couche ou à l'interface n'est conservé ici.
        # ``regles_activees`` : copie figée (frozenset de str) des règles
        # cochées au lancement, jamais une référence vers l'état du panneau
        # (même raison : rien qui touche l'UI ne doit entrer dans le thread).
        self._donnees = donnees
        self._paires = paires_candidates
        self._regles_activees = frozenset(regles_activees)
        self._callback = callback
        self.resultats = None
        self.erreur = None

    @staticmethod
    def _geometrie_depuis_wkb(wkb):
        """Construit une QgsGeometry appartenant uniquement au thread de tâche."""
        if not wkb:
            return None
        try:
            geometrie = QgsGeometry()
            geometrie.fromWkb(wkb)
        except (AttributeError, RuntimeError, TypeError):
            return None
        if geometrie.isEmpty():
            return None
        return geometrie

    def run(self):
        """Exécuté en arrière-plan ; aucune API liée à une couche ou à l'UI.

        Les WKB sont reconstruits une seule fois au début de la tâche. Cela
        évite de refaire ``fromWkb`` pour chaque paire de voisins.
        """
        try:
            adjacences = []
            recouvrements = []

            # 1) Reconstruire un instantané géométrique local au thread.
            geometries = {}
            metadonnees = {}
            fids = sorted(self._donnees)
            total_fids = max(1, len(fids))
            # On retire chaque WKB de la structure d'entrée dès qu'il est
            # reconstruit. Le pic mémoire reste ainsi proche de deux copies des
            # géométries au lieu de trois (cache principal + WKB + QgsGeometry
            # du thread). C'est important sur les gros groupes.
            donnees_entree = self._donnees
            for position, fid in enumerate(fids):
                if self.isCanceled():
                    return False
                donnees_fid = donnees_entree.pop(fid, None)
                if donnees_fid is None:
                    continue
                wkb, signature, detail_adjacence = donnees_fid
                geometrie = self._geometrie_depuis_wkb(wkb)
                if geometrie is None:
                    continue
                geometries[fid] = geometrie
                metadonnees[fid] = (signature, detail_adjacence)
                if position % 100 == 0:
                    self.setProgress(20.0 * position / total_fids)

            # Le dictionnaire a été vidé progressivement pendant la lecture.
            self._donnees = {}

            # 2) Le recouvrement se calcule sur les géométries brutes ; l'adjacence
            #    se calcule séparément sur les limites alignées (cf. partage_une_limite),
            #    sinon deux polygones voisins mais pas tout à fait jointifs (numérisés
            #    séparément) ne seraient jamais détectés comme adjacents.
            limites = {}

            def limite_cachee(fid_cle, geometrie):
                if fid_cle not in limites:
                    limites[fid_cle] = limite_polygone(geometrie)
                return limites[fid_cle]

            total_paires = max(1, len(self._paires))
            for position, (fid, autre_fid) in enumerate(self._paires):
                if self.isCanceled():
                    return False
                geom = geometries.get(fid)
                autre_geom = geometries.get(autre_fid)
                meta = metadonnees.get(fid)
                autre_meta = metadonnees.get(autre_fid)
                if geom is None or autre_geom is None or meta is None or autre_meta is None:
                    continue
                signature, detail_adjacence = meta
                autre_signature, _ = autre_meta

                try:
                    intersection = geom.intersection(autre_geom)
                except (AttributeError, TypeError, RuntimeError):
                    intersection = None

                if intersection is not None and not intersection.isEmpty():
                    recouvrement = extraire_intersection_surfacique_significative(
                        intersection, SURFACE_BRUIT_NUMERIQUE_GEOS_M2
                    )
                    if recouvrement is not None and not recouvrement.isEmpty():
                        # Le recouvrement sert à décider s'il faut passer au
                        # test d'adjacence (continue) : calculé même si
                        # "overlaps" est décoché, seul son ajout au résultat
                        # dépend de la règle.
                        if "overlaps" in self._regles_activees:
                            try:
                                recouvrements.append(
                                    (fid, autre_fid, bytes(recouvrement.asWkb()))
                                )
                            except (AttributeError, RuntimeError, TypeError):
                                pass
                        continue

                if "adjacent" in self._regles_activees and autre_signature == signature:
                    # Distance d'alignement des sommets (précision du projet,
                    # 1 cm), distincte de TOLERANCE_ADJACENCE_M qui fixe elle
                    # la longueur de contact minimale pour compter comme une
                    # vraie adjacence.
                    contact = partage_une_limite(
                        limite_cachee(fid, geom),
                        limite_cachee(autre_fid, autre_geom),
                        0.01,
                        TOLERANCE_ADJACENCE_M,
                    )
                    if contact is not None:
                        adjacences.append((fid, autre_fid, detail_adjacence or ""))

                if position % 100 == 0:
                    self.setProgress(20.0 + 80.0 * position / total_paires)

            self.setProgress(100.0)
            self.resultats = (adjacences, recouvrements)
            return True
        except Exception as exc:
            # Ne jamais laisser une exception Python sortir de run(): QGIS
            # documente que cela peut faire tomber l'application.
            self.erreur = exc
            return False

    def finished(self, succes):
        """Toujours rappelé par QGIS dans le thread principal."""
        callback = self._callback
        resultats = self.resultats
        erreur = self.erreur
        self._callback = None
        # Ne rien conserver dans l'objet QgsTask après sa fin : le gestionnaire
        # de tâches QGIS peut garder l'objet Python vivant un peu plus longtemps
        # que le panneau. Les gros WKB de résultats sont donc détachés avant le
        # callback afin de limiter la mémoire résiduelle.
        self.resultats = None
        self.erreur = None
        self._donnees = {}
        self._paires = []
        if callback is not None:
            callback(self, bool(succes), resultats, erreur)
