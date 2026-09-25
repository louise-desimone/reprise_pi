# -*- coding: utf-8 -*-
"""Détecte des groupes de polygones adjacents portant les mêmes attributs.

Un groupe connexe (A touche B, B touche C, donc A/B/C forment un groupe même
si A et C ne se touchent pas) est proposé à la fusion. La fusion délègue
entièrement au moteur commun de l'outil Fusionner (fusionner_fids_direct).
"""

from .commun_affichage import creer_surbrillance_polygone, supprimer_surbrillance_polygone
from .commun_edition import recuperer_entite, recuperer_entites, valeur_champ_texte
from .commun_parametres import normaliser_valeur, signature_attributs
from .commun_protection_vue import vue_stable_pendant_modification


def regrouper_adjacences(adjacent_pairs):
    """Transforme les paires d'adjacence en groupes connexes sans doublons.

    Si A touche B et B touche C, A/B/C appartiennent au même groupe même
    si A et C ne partagent pas directement de segment. Les paires restent
    le format du cache interne pour permettre les recalculs locaux rapides.
    """
    graphe = {}
    details = {}
    for fid_a, fid_b, detail in adjacent_pairs:
        try:
            fid_a = int(fid_a)
            fid_b = int(fid_b)
        except (TypeError, ValueError):
            continue
        if fid_a == fid_b:
            continue
        graphe.setdefault(fid_a, set()).add(fid_b)
        graphe.setdefault(fid_b, set()).add(fid_a)
        details.setdefault(fid_a, detail)
        details.setdefault(fid_b, detail)

    groupes = []
    visites = set()
    for depart in sorted(graphe):
        if depart in visites:
            continue
        pile = [depart]
        composante = []
        while pile:
            fid = pile.pop()
            if fid in visites:
                continue
            visites.add(fid)
            composante.append(fid)
            pile.extend(sorted(graphe.get(fid, ()), reverse=True))

        if len(composante) >= 2:
            composante.sort()
            detail = next((details.get(fid) for fid in composante if details.get(fid)), "")
            groupes.append((composante, detail))

    groupes.sort(key=lambda item: item[0])
    return groupes


def detail_adjacence(feature, field_map):
    """Texte affiché dans le panneau pour une paire/un groupe d'adjacents identiques."""
    essence = normaliser_valeur(feature[field_map["nouvelle_essence"]])
    code_tff = normaliser_valeur(feature[field_map["code_tff"]])
    return f"{essence} — {code_tff}" if code_tff else essence


@vue_stable_pendant_modification
def fusionner_groupe_adjacents(self, fids_groupe, silencieux=False, planifier_refresh=True):
    """Fusionne en une seule opération un groupe connexe d'adjacents identiques.

    La fusion est entièrement déléguée au moteur commun de l'outil Fusionner
    (:func:`preparer_fusion_protegee`) : alignement des sommets, anti-parasites,
    retrait de tout recouvrement avec un autre polygone et de toute zone hors
    de l'emprise.
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
            "La couche BD Forêt doit être en mode édition pour fusionner le groupe.",
        )
        return

    try:
        fids = list(dict.fromkeys(int(fid) for fid in fids_groupe))
    except (TypeError, ValueError):
        return
    if len(fids) < 2:
        return

    entites = recuperer_entites(couche, fids)
    if len(entites) != len(fids):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Une ou plusieurs entités du groupe ne sont plus disponibles. Relancez la recherche des anomalies.",
        )
        self._refresh_timer.start(50)
        return

    # Le groupe est issu du contrôle des attributs identiques. On refait
    # néanmoins cette vérification juste avant la fusion pour éviter de
    # fusionner un groupe devenu obsolète après une modification de fiche.
    field_map = self._field_map
    if field_map:
        signatures = [signature_attributs(entites[fid], field_map) for fid in fids]
        if any(signature != signatures[0] for signature in signatures[1:]):
            self.iface.messageBar().pushWarning(
                "Vérification BD Forêt",
                "Les attributs du groupe ont changé. Relancez la recherche des anomalies.",
            )
            self._pending_fids.update(fids)
            self._refresh_timer.start(50)
            return

    # Les champs contrôlés étant identiques, la première entité peut fournir
    # les attributs. Toute l'opération est déléguée au moteur Fusionner central :
    # même nettoyage, même clip emprise, mêmes alertes et même Ctrl+Z.
    fusionner = getattr(self.manager, "fusionner", None) if self.manager else None
    if fusionner is None or not hasattr(fusionner, "fusionner_fids_direct"):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Le moteur commun Fusionner n'est pas disponible.",
        )
        return

    succes, fid_reference = fusionner.fusionner_fids_direct(
        fids,
        fid_reference=fids[0],
        ouvrir_formulaire=False,
        nom_commande="Fusionner un groupe de polygones adjacents",
    )
    self._pending_fids.update(fids)
    if fid_reference is not None:
        self._pending_fids.add(int(fid_reference))
    if planifier_refresh:
        self._refresh_timer.start(50)

    if succes and not silencieux:
        self.iface.messageBar().pushSuccess(
            "Vérification BD Forêt",
            f"Le groupe de {len(fids)} polygones a été fusionné.",
        )
    return bool(succes)


def fusionner_tous_groupes_adjacents(self):
    """Fusionne tous les groupes d'adjacents identiques encore valides.

    Chaque groupe connexe est traité par ``fusionner_groupe_adjacents`` et donc
    par le moteur Fusionner commun. Les groupes sont disjoints par construction,
    ce qui évite qu'une fusion en invalide une autre par simple chevauchement de
    FID. Les attributs sont recontrôlés juste avant chaque fusion.
    """
    groupes = regrouper_adjacences([
        (a, b, detail) for (a, b), detail in self._cached_adjacent.items()
    ])
    if not groupes:
        return

    groupes_fusionnes = 0
    polygones_fusionnes = 0
    ignores = 0
    for fids_groupe, _detail in groupes:
        fids = [int(fid) for fid in fids_groupe]
        succes = fusionner_groupe_adjacents(
            self,
            fids,
            silencieux=True,
            planifier_refresh=False,
        )
        if succes:
            groupes_fusionnes += 1
            polygones_fusionnes += len(fids)
        else:
            ignores += 1

    self._refresh_timer.start(50)
    if groupes_fusionnes:
        texte = (
            f"{polygones_fusionnes} polygone(s) fusionné(s) "
            f"dans {groupes_fusionnes} groupe(s)."
        )
        if ignores:
            texte += f" {ignores} groupe(s) ignoré(s) car ils avaient changé."
        self.iface.messageBar().pushSuccess("Vérification BD Forêt", texte)
    elif ignores:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Aucun groupe n'a été fusionné ; relancez la recherche des anomalies.",
        )


def modifier_attributs_entite(self, fid):
    """Ouvre directement la fiche attributaire d'un polygone du groupe."""
    couche = self._trouver_couche()
    if couche is None:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La couche BD Forêt est introuvable.",
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
        fid = int(fid)
    except (TypeError, ValueError):
        return
    entite = recuperer_entite(couche, fid)
    if entite is None:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Cette entité n'est plus disponible. Relancez la recherche des anomalies.",
        )
        self._refresh_timer.start(50)
        return

    self.iface.setActiveLayer(couche)
    surbrillance = None
    if entite.hasGeometry() and not entite.geometry().isEmpty():
        surbrillance = creer_surbrillance_polygone(
            self.iface.mapCanvas(), entite.geometry(), couche
        )
    try:
        self.iface.openFeatureForm(couche, entite, False, True)
    finally:
        supprimer_surbrillance_polygone(self.iface.mapCanvas(), surbrillance)
    self._pending_fids.add(fid)
    self._refresh_timer.start(50)


def ajouter_au_panneau(controleur, arbre, groupes, groupe=None):
    """Ajoute les groupes connexes de polygones adjacents au panneau."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QTreeWidgetItem
    from qgis.core import QgsRectangle

    couche = controleur._trouver_couche()
    racine = groupe
    if racine is None:
        racine = QTreeWidgetItem([
            f"Polygones adjacents aux attributs identiques ({len(groupes)} groupes)", ""
        ])
        arbre.addTopLevelItem(racine)
    for numero, (fids_groupe, _detail) in enumerate(groupes, start=1):
        fids_groupe = [int(fid) for fid in fids_groupe]
        premiere_feature = controleur._cached_feature_by_id.get(fids_groupe[0])
        if couche is not None and premiere_feature is not None:
            essence_groupe = valeur_champ_texte(couche, premiere_feature, "nouvelle_essence")
            code_tff_groupe = valeur_champ_texte(couche, premiere_feature, "code_tff", defaut="")
        else:
            essence_groupe, code_tff_groupe = "Non renseigné", ""
        detail_texte = f"{len(fids_groupe)} polygones de {essence_groupe}"
        if code_tff_groupe:
            detail_texte += f" ({code_tff_groupe})"
        item_groupe = QTreeWidgetItem([f"Groupe {numero}", detail_texte])
        payload = {"fids": fids_groupe, "adjacent_group_fids": fids_groupe}
        emprise = QgsRectangle()
        trouve = False
        for fid in fids_groupe:
            feature = controleur._cached_feature_by_id.get(fid)
            if feature is None or not feature.hasGeometry() or feature.geometry().isEmpty():
                continue
            rect = feature.geometry().boundingBox()
            if not trouve:
                emprise = QgsRectangle(rect)
                trouve = True
            else:
                emprise.combineExtentWith(rect)
        if trouve:
            payload["extent"] = controleur._emprise_vers_tuple(emprise)
        item_groupe.setData(0, Qt.UserRole, payload)
        racine.addChild(item_groupe)

        for fid in fids_groupe:
            feature = controleur._cached_feature_by_id.get(fid)
            essence = (
                valeur_champ_texte(couche, feature, "nouvelle_essence")
                if couche is not None and feature is not None else "Non renseigné"
            )
            item = QTreeWidgetItem([f"{essence} ({fid})", ""])
            payload_entite = {"fids": [fid], "adjacent_member_fid": fid}
            if feature is not None and feature.hasGeometry() and not feature.geometry().isEmpty():
                payload_entite["extent"] = controleur._emprise_vers_tuple(feature.geometry().boundingBox())
            item.setData(0, Qt.UserRole, payload_entite)
            item_groupe.addChild(item)
