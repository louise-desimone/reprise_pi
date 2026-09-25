# -*- coding: utf-8 -*-
"""Détecte les entités multiparties et propose de les fusionner ou séparer.

Fusionner réunit les parties en un seul polygone continu avec le même moteur
géométrique que l'outil Fusionner (préserve fid et attributs). Séparer garde
la plus grande partie sous l'entité d'origine et crée une nouvelle entité par
autre partie, avec un nouvel id_foret.
"""

from qgis.analysis import QgsGeometrySnapper
from qgis.core import QgsGeometry

from .commun_affichage import creer_surbrillance_polygone, supprimer_surbrillance_polygone
from .commun_edition import (
    creer_entite_nouvelle,
    exiger_fid_valide,
    ouvrir_formulaire_ou_annuler,
    recuperer_entite,
    valeur_champ_texte,
)
from .commun_parametres import TOLERANCE_SNAP_PARTIES_MULTIPARTIE_M
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_synchronisation_alertes import synchroniser_zone
from .commun_topologie import (
    compter_parties_polygonales,
    extraire_parties_multipartie_brutes,
    fusionner_geometries,
    preparer_fusion_protegee,
)


def _aligner_parties(parties):
    """Aligne chaque partie sur les précédentes avant preparer_fusion_protegee.

    Snap dédié à la fusion de parties d'UNE MÊME multipartie, plus généreux
    (voir TOLERANCE_SNAP_PARTIES_MULTIPARTIE_M, commun_parametres.py) que
    l'alignement interne de fusionner_geometries (1 cm, pensé pour deux
    entités distinctes déjà bien numérisées) : deux parties d'une même
    multipartie peuvent avoir été numérisées séparément (import, correction
    manuelle) avec un écart de quelques centimètres sur leur limite commune,
    alors qu'elles se touchent visiblement à l'écran.
    """
    parties = list(parties)
    if len(parties) < 2:
        return parties
    alignees = [QgsGeometry(parties[0])]
    for partie in parties[1:]:
        try:
            alignee = QgsGeometrySnapper.snapGeometry(
                partie, TOLERANCE_SNAP_PARTIES_MULTIPARTIE_M, alignees
            )
        except (AttributeError, TypeError, RuntimeError):
            alignee = partie
        alignees.append(alignee)
    return alignees


def _message_echec_fusion_parties(parties_alignees):
    """Distingue pourquoi la fusion des parties a échoué, pour un message utile.

    ``preparer_fusion_protegee`` ne dit pas lui-même à quelle étape il a
    échoué. On refait juste la première étape (fusionner_geometries, sans
    redécoupage) pour savoir si les parties se touchent vraiment : si oui, le
    blocage vient forcément du redécoupage qui suit (recouvrement avec un
    autre polygone de la couche, ou dépassement de l'emprise) — un cas réel
    rencontré en test, une même entité à la fois multipartie ET en
    recouvrement avec une autre.
    """
    brut = fusionner_geometries(parties_alignees)
    if brut is None or brut.isEmpty() or compter_parties_polygonales(brut) != 1:
        return "Les parties ne se touchent pas assez pour former un seul polygone continu."
    return (
        "Les parties se touchent bien, mais le résultat recoupe un autre polygone de la "
        "couche ou dépasse l'emprise. Résolvez d'abord ce recouvrement (panneau Vérifier, "
        "catégorie Recouvrements) avant de fusionner les parties."
    )


def detecter(feature):
    """Retourne ``(fid, nombre_parties)`` pour une vraie multipartie."""
    if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
        return None
    nombre = compter_parties_polygonales(feature.geometry())
    return (int(feature.id()), nombre) if nombre > 1 else None


def peut_fusionner_multipartie(self, fid):
    """Retourne True si les parties peuvent devenir un seul polygone continu.

    Utilise exactement la même chaîne (:func:`preparer_fusion_protegee`) que
    :func:`fusionner_multipartie` ci-dessous, jusqu'au retrait des zones hors
    emprise et des recouvrements avec un autre polygone de la couche — pas
    seulement l'union brute (:func:`fusionner_geometries`). Un bridge étroit
    entre deux parties peut former un seul polygone après l'union, mais être
    ensuite coupé par ce redécoupage : sans ça, ce contrôle répondait "oui"
    à tort sur un cas que la vraie fusion refusait ensuite.
    """
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        return False

    couche = self._trouver_couche()
    entite = self._cached_feature_by_id.get(fid)
    if entite is None:
        entite = recuperer_entite(couche, fid) if couche is not None else None
    if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
        return False

    parties = extraire_parties_multipartie_brutes(QgsGeometry(entite.geometry()))
    if len(parties) < 2:
        return False

    parties = _aligner_parties(parties)
    geometrie_fusionnee = preparer_fusion_protegee(couche, parties, [fid])
    return (
        geometrie_fusionnee is not None
        and not geometrie_fusionnee.isEmpty()
        and compter_parties_polygonales(geometrie_fusionnee) == 1
    )


@vue_stable_pendant_modification
def fusionner_multipartie(self, fid):
    """Réunit les parties contiguës d'une multipartie en un seul polygone.

    La géométrie passe par la même chaîne que l'outil Fusionner
    (:func:`preparer_fusion_protegee`) : alignement des sommets, union,
    suppression des limites/anneaux internes, nettoyage anti-parasites,
    retrait de tout recouvrement avec un autre polygone de la couche et de
    toute zone hors de l'emprise. L'entité, ses attributs, son fid et son
    id_foret sont conservés.
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
            "La couche BD Forêt doit être en mode édition pour fusionner les parties.",
        )
        return

    entite = recuperer_entite(couche, fid)
    if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette entité n'est plus disponible. Relancez la recherche des anomalies.",
        )
        return

    geometrie_source = QgsGeometry(entite.geometry())
    parties = extraire_parties_multipartie_brutes(geometrie_source)
    if len(parties) < 2:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette entité n'est plus multipartie.",
        )
        self._pending_fids.add(int(fid))
        self._refresh_timer.start(50)
        return

    parties = _aligner_parties(parties)
    geometrie_fusionnee = preparer_fusion_protegee(couche, parties, [int(fid)])
    if (
        geometrie_fusionnee is None
        or geometrie_fusionnee.isEmpty()
        or compter_parties_polygonales(geometrie_fusionnee) != 1
    ):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            _message_echec_fusion_parties(parties),
        )
        return

    commande_ouverte = False
    try:
        couche.beginEditCommand("Fusionner les parties d'une multipartie")
        commande_ouverte = True

        exiger_fid_valide(couche, fid, "fusionner les parties")
        if not couche.changeGeometry(int(fid), geometrie_fusionnee):
            raise RuntimeError("la géométrie de l'entité n'a pas pu être modifiée")

        try:
            geometrie_zone = QgsGeometry.unaryUnion([
                QgsGeometry(geometrie_source),
                QgsGeometry(geometrie_fusionnee),
            ])
        except (TypeError, RuntimeError):
            geometrie_zone = QgsGeometry(geometrie_fusionnee)

        synchroniser_zone(
            self.iface,
            couche,
            geometrie_zone,
            "Fusionner les parties d'une multipartie",
        )

        couche.endEditCommand()
        commande_ouverte = False

        couche.triggerRepaint(True)
        self.iface.mapCanvas().refresh()
        self._pending_fids.add(int(fid))
        self._refresh_timer.start(50)

        self.iface.messageBar().pushSuccess(
            "Vérification BD Forêt",
            "Les parties ont été fusionnées : les limites internes ont été supprimées.",
        )

    except Exception as erreur:
        if commande_ouverte:
            try:
                couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"La fusion des parties a échoué : {erreur}",
        )


@vue_stable_pendant_modification
def separer_multipartie(self, fid):
    """Transforme chaque partie d'une multipartie en entité indépendante.

    Comme l'outil Séparer, la plus petite nouvelle entité est hachurée en
    jaune et son formulaire attributaire est ouvert ; l'annuler défait toute
    la séparation (:func:`ouvrir_formulaire_ou_annuler`).
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
            "La couche BD Forêt doit être en mode édition pour séparer une multipartie.",
        )
        return

    entite = recuperer_entite(couche, fid)
    if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette entité n'est plus disponible. Relancez la recherche des anomalies.",
        )
        return

    geometrie_source = QgsGeometry(entite.geometry())
    parties = extraire_parties_multipartie_brutes(geometrie_source)
    parties = [QgsGeometry(partie) for partie in parties if partie and not partie.isEmpty()]
    if len(parties) < 2:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette entité n'est plus multipartie.",
        )
        self._pending_fids.add(int(fid))
        self._refresh_timer.start(50)
        return

    # La plus grande partie conserve l'entité d'origine et donc son id_foret.
    # Toutes les autres héritent des attributs du parent mais reçoivent un
    # nouveau fid technique et un nouvel id_foret. La dernière créée est la
    # plus petite et sera présentée à l'opérateur dans le formulaire.
    parties.sort(key=lambda geom: abs(geom.area()), reverse=True)
    partie_conservee = parties[0]
    nouvelles_geometries = parties[1:]
    attributs_reference = list(entite.attributes())

    commande_ouverte = False
    nouvelles_entites = []
    surbrillance = None
    try:
        couche.beginEditCommand("Séparer une multipartie")
        commande_ouverte = True

        exiger_fid_valide(couche, fid, "séparer la multipartie")
        if not couche.changeGeometry(int(fid), partie_conservee):
            raise RuntimeError("la géométrie de l'entité d'origine n'a pas pu être modifiée")

        for geometrie in nouvelles_geometries:
            nouvelle_entite = creer_entite_nouvelle(
                couche, geometrie, attributs_reference
            )
            if not couche.addFeature(nouvelle_entite):
                raise RuntimeError("une partie n'a pas pu être créée comme nouvelle entité")
            nouvelles_entites.append(nouvelle_entite)

        if not nouvelles_entites:
            raise RuntimeError("aucune nouvelle partie n'a été créée")

        synchroniser_zone(
            self.iface,
            couche,
            geometrie_source,
            "Séparer une multipartie",
        )

        couche.endEditCommand()
        commande_ouverte = False

        couche.triggerRepaint(True)
        self.iface.mapCanvas().refresh()

        # Les parties sont triées de la plus grande à la plus petite : la
        # dernière nouvelle entité correspond donc à la plus petite partie.
        petite_entite = recuperer_entite(couche, nouvelles_entites[-1].id())
        if petite_entite is None:
            raise RuntimeError("la plus petite nouvelle entité est introuvable")

        surbrillance = creer_surbrillance_polygone(
            self.iface.mapCanvas(),
            petite_entite.geometry(),
            couche,
        )
        if not ouvrir_formulaire_ou_annuler(
            self.iface, couche, self.iface.mapCanvas(), petite_entite, "Vérification BD Forêt"
        ):
            return

        self._pending_fids.add(int(fid))
        for nouvelle_entite in nouvelles_entites:
            try:
                self._pending_fids.add(int(nouvelle_entite.id()))
            except (TypeError, ValueError):
                pass
        self._refresh_timer.start(50)

        self.iface.messageBar().pushSuccess(
            "Vérification BD Forêt",
            f"Multipartie séparée en {len(parties)} entités distinctes.",
        )

    except Exception as erreur:
        if commande_ouverte:
            try:
                couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"La séparation de la multipartie a échoué : {erreur}",
        )
    finally:
        supprimer_surbrillance_polygone(self.iface.mapCanvas(), surbrillance)


@vue_stable_pendant_modification
def attribuer_partie_multipartie(self, fid, index_partie):
    """Délègue l'attribution d'une partie isolée à un voisin à l'outil Fusionner.

    Même principe que « Fusionner avec… » sur une petite surface ou
    « Attribuer à… » sur un trou (verification_trous.attribuer_trou) : la
    partie ciblée est d'abord détachée dans sa propre entité temporaire (le
    reste de la multipartie garde l'entité d'origine), puis l'outil Fusionner
    est activé avec cette entité présélectionnée — l'utilisateur choisit le
    voisin d'un clic, la fusion (et son éventuelle annulation) restent
    entièrement gérées par l'outil Fusionner lui-même. Si l'utilisateur
    annule la sélection du voisin, la partie reste une entité indépendante
    valide (mêmes attributs que le parent) plutôt qu'un état incohérent.
    """
    couche = self._trouver_couche()
    if couche is None:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "La couche BD Forêt est introuvable."
        )
        return
    if not couche.isEditable():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La couche BD Forêt doit être en mode édition pour attribuer une partie.",
        )
        return

    fusionner = getattr(self.manager, "fusionner", None) if self.manager else None
    if fusionner is None or not hasattr(fusionner, "activer_avec_fids"):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "L'outil Fusionner n'est pas disponible."
        )
        return

    entite = recuperer_entite(couche, fid)
    if entite is None or not entite.hasGeometry() or entite.geometry().isEmpty():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette entité n'est plus disponible. Relancez la recherche des anomalies.",
        )
        return

    geometrie_source = QgsGeometry(entite.geometry())
    # Même tri (aire décroissante) que celui qui a construit "Partie N" dans
    # le panneau (ajouter_au_panneau) : index_partie ne veut dire quelque
    # chose que dans cet ordre-là.
    parties = sorted(
        extraire_parties_multipartie_brutes(geometrie_source),
        key=lambda geom: abs(geom.area()), reverse=True,
    )
    if len(parties) < 2 or not (0 <= index_partie < len(parties)):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette partie n'est plus disponible. Relancez la recherche des anomalies.",
        )
        self._pending_fids.add(int(fid))
        self._refresh_timer.start(50)
        return

    partie_ciblee = parties[index_partie]
    parties_restantes = [p for i, p in enumerate(parties) if i != index_partie]
    geometrie_restante = (
        parties_restantes[0] if len(parties_restantes) == 1
        else QgsGeometry.collectGeometry(parties_restantes)
    )
    attributs_reference = list(entite.attributes())

    commande_ouverte = False
    fid_nouvelle_partie = None
    try:
        couche.beginEditCommand("Préparer une partie isolée pour attribution")
        commande_ouverte = True

        exiger_fid_valide(couche, fid, "détacher la partie")
        if not couche.changeGeometry(int(fid), geometrie_restante):
            raise RuntimeError("le reste de la multipartie n'a pas pu être modifié")

        nouvelle_entite = creer_entite_nouvelle(couche, partie_ciblee, attributs_reference)
        if not couche.addFeature(nouvelle_entite):
            raise RuntimeError("la partie n'a pas pu être détachée comme nouvelle entité")
        fid_nouvelle_partie = int(nouvelle_entite.id())

        synchroniser_zone(
            self.iface, couche, geometrie_source, "Préparer une partie isolée pour attribution"
        )

        couche.endEditCommand()
        commande_ouverte = False

        couche.triggerRepaint(True)
        self.iface.mapCanvas().refresh()
    except Exception as erreur:
        if commande_ouverte:
            try:
                couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"La préparation de la partie isolée a échoué : {erreur}",
        )
        return

    try:
        self.iface.setActiveLayer(couche)
    except RuntimeError:
        pass
    if not fusionner.activer_avec_fids(
        [fid_nouvelle_partie],
        ouvrir_formulaire_apres=False,
        finaliser_au_deuxieme_clic=True,
        callback_fin=lambda fids, ref: _apres_attribution_partie(self, fids, ref, int(fid)),
    ):
        return
    self.iface.messageBar().pushInfo(
        "Fusionner BD Forêt",
        "La partie isolée est présélectionnée. Cliquez sur le polygone voisin à fusionner.",
    )


def _apres_attribution_partie(controleur, fids_operation, fid_reference, fid_parent):
    """Programme le rafraîchissement local après une attribution de partie déléguée."""
    try:
        controleur._pending_fids.update(int(fid) for fid in (fids_operation or []))
        controleur._pending_fids.add(int(fid_reference))
        controleur._pending_fids.add(int(fid_parent))
    except (TypeError, ValueError):
        pass
    if controleur.dock is not None and controleur.dock.isVisible():
        controleur._refresh_timer.start(50)


def ajouter_au_panneau(controleur, arbre, anomalies, groupe=None):
    """Ajoute les multiparties et chacune de leurs parties au panneau."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QTreeWidgetItem

    couche = controleur._trouver_couche()
    lignes = []
    for fid, nombre in anomalies:
        feature = controleur._cached_feature_by_id.get(fid)
        essence = (
            valeur_champ_texte(couche, feature, "nouvelle_essence")
            if couche is not None and feature is not None else "Non renseigné"
        )
        lignes.append((essence, fid, nombre, feature))
    lignes.sort(key=lambda ligne: (ligne[0].lower(), ligne[1]))

    if groupe is None:
        groupe = QTreeWidgetItem([f"Entités multiparties ({len(lignes)})", ""])
        arbre.addTopLevelItem(groupe)

    for essence, fid, nombre, feature in lignes:
        libelle = f"{essence} ({fid})"
        item = QTreeWidgetItem([libelle, f"{nombre} parties"])
        payload = {"fids": [int(fid)], "multipart_fid": int(fid)}
        if feature is not None and feature.hasGeometry() and not feature.geometry().isEmpty():
            payload["extent"] = controleur._emprise_vers_tuple(feature.geometry().boundingBox())
        item.setData(0, Qt.UserRole, payload)
        groupe.addChild(item)

        if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
            continue
        parties = sorted(
            extraire_parties_multipartie_brutes(QgsGeometry(feature.geometry())),
            key=lambda geom: abs(geom.area()), reverse=True,
        )
        for numero, partie in enumerate(parties, start=1):
            sous_item = QTreeWidgetItem([
                f"Partie {numero}", f"{abs(partie.area()) / 10000:.3f} ha"
            ])
            sous_item.setData(0, Qt.UserRole, {
                "multipart_part": [int(fid), numero - 1],
                "extent": controleur._emprise_vers_tuple(partie.boundingBox()),
            })
            item.addChild(sous_item)
