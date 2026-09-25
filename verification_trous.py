# -*- coding: utf-8 -*-
"""Recherche et correction des trous dans la couverture BD Forêt."""

from qgis.core import (
    QgsFeature, QgsFeatureRequest, QgsGeometry, QgsProject, QgsRectangle,
)

from .commun_affichage import creer_surbrillance_polygone, supprimer_surbrillance_polygone
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_edition import (
    ouvrir_formulaire_ou_annuler,
    prochain_id_foret,
    recuperer_entite,
)
from .commun_parametres import CHAMP_ID_FORET, TOLERANCE_ADJACENCE_M
from .commun_synchronisation_alertes import synchroniser_zone
from .commun_topologie import (
    construire_geometrie_emprise_locale,
    extraire_parties_polygonales,
    meilleur_voisin_par_contact,
    nettoyer_geometrie_decoupee_protegee,
    nettoyer_geometrie_base,
)


def mettre_a_jour_trous_locaux(self, rect):
    """Met à jour les lacunes dans la seule emprise touchée par l'édition."""
    margin = max(rect.width(), rect.height()) * 0.01 + TOLERANCE_ADJACENCE_M
    rect.grow(margin)
    emprise_locale = geometrie_emprise_locale(self, rect)
    if emprise_locale is None or emprise_locale.isEmpty():
        return
    region = QgsGeometry.fromRect(rect).intersection(emprise_locale)
    if region.isEmpty():
        return

    preserved = []
    for gap in self._cached_gap_geometries:
        if not gap.intersects(region):
            preserved.append(gap)
            continue
        remainder = gap.difference(region)
        preserved.extend(extraire_parties_polygonales(remainder))

    coverage = []
    for fid in self._spatial_index.intersects(rect):
        feature = self._cached_feature_by_id.get(fid)
        if feature is not None and feature.hasGeometry():
            # Pour la recherche des trous, la géométrie réelle de la couche
            # est la seule source de vérité. Une géométrie nettoyée pour le
            # diagnostic des parasites peut retirer une micro-composante et
            # fabriquer artificiellement un faux trou.
            geom_couverture = feature.geometry()
            if geom_couverture is not None and not geom_couverture.isEmpty():
                coverage.append(QgsGeometry(geom_couverture))
    coverage_union = QgsGeometry.unaryUnion(coverage) if coverage else QgsGeometry()
    local_gap = region if coverage_union.isEmpty() else region.difference(coverage_union)
    preserved.extend(extraire_parties_polygonales(local_gap))
    self._cached_gap_geometries = fusionner_parties_trous(preserved)


def fusionner_parties_trous(geometries):
    """Fusionne les morceaux contigus afin qu'un trou réel forme une seule anomalie."""
    valid_parts = [
        QgsGeometry(geom)
        for geom in geometries
        if geom and not geom.isEmpty() and geom.area() > 0.0
    ]
    if not valid_parts:
        return []

    merged = (
        QgsGeometry(valid_parts[0])
        if len(valid_parts) == 1
        else QgsGeometry.unaryUnion(valid_parts)
    )
    if merged.isEmpty():
        return []
    if not merged.isGeosValid():
        merged = merged.makeValid()

    return [
        part
        for part in extraire_parties_polygonales(merged)
        if part.area() > 0.0
    ]


def valider_trous_contre_couche_actuelle(self):
    """Retire des trous en cache toute surface actuellement couverte par la BD Forêt.

    Cette passe finale est volontairement locale et indépendante de l'index
    spatial du vérificateur. Elle protège notamment contre un cache devenu
    obsolète après plusieurs opérations d'édition : un ancien trou ne doit
    jamais rester affiché s'il est désormais couvert par une entité réelle.
    """
    if self.layer is None or not self._cached_gap_geometries:
        return

    resultats = []
    for gap in self._cached_gap_geometries:
        if gap is None or gap.isEmpty():
            continue

        reste = QgsGeometry(gap)
        try:
            request = (
                QgsFeatureRequest()
                .setFilterRect(gap.boundingBox())
                .setNoAttributes()
            )
            couvertures = []
            for feature in self.layer.getFeatures(request):
                if not feature.hasGeometry():
                    continue
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                try:
                    if not geom.intersects(gap):
                        continue
                except (TypeError, RuntimeError):
                    continue
                couvertures.append(QgsGeometry(geom))

            if couvertures:
                couverture = (
                    couvertures[0]
                    if len(couvertures) == 1
                    else QgsGeometry.unaryUnion(couvertures)
                )
                if couverture is not None and not couverture.isEmpty():
                    reste = reste.difference(couverture)
        except (TypeError, RuntimeError):
            # En cas d'échec ponctuel, on ne supprime pas arbitrairement
            # l'anomalie : elle restera visible pour contrôle manuel.
            reste = QgsGeometry(gap)

        if reste is None or reste.isEmpty():
            continue
        for partie in extraire_parties_polygonales(reste):
            if partie.area() > 0.0:
                resultats.append(partie)

    self._cached_gap_geometries = fusionner_parties_trous(resultats)


def preparer_recherche_trous(self, emprise_layer, feature_by_id, index):
    """Calcule directement ``Emprise - BD Forêt``, sans découpage en tuiles.

    Une seule union de la couverture forestière puis une seule différence
    GEOS avec l'emprise : sur les volumes réels de BD Forêt, ce calcul direct
    reste largement praticable et bien plus simple à suivre qu'un découpage
    spatial incrémental. Le résultat est déjà entièrement prêt à la sortie de
    cette fonction ; ``traiter_lot_recherche_trous`` n'a donc plus rien à
    avancer par la suite.
    """
    if emprise_layer is None or self.layer is None:
        return None
    try:
        etendue = QgsRectangle(self.layer.extent())
    except (AttributeError, RuntimeError, TypeError):
        return None
    if etendue.isEmpty():
        return None

    emprise_geom = construire_geometrie_emprise_locale(
        emprise_layer, etendue, self.layer.crs()
    )
    if emprise_geom is None or emprise_geom.isEmpty():
        return {"gaps": []}

    couverture = [
        QgsGeometry(feature.geometry())
        for feature in feature_by_id.values()
        if feature is not None and feature.hasGeometry() and not feature.geometry().isEmpty()
    ]
    couverture_union = _union_geometries(couverture)
    try:
        gap = emprise_geom if couverture_union.isEmpty() else emprise_geom.difference(couverture_union)
    except (AttributeError, TypeError, RuntimeError):
        return {"gaps": []}
    if gap is None or gap.isEmpty():
        return {"gaps": []}

    return {"gaps": [partie for partie in extraire_parties_polygonales(gap) if partie.area() > 0.0]}


def _union_geometries(geometries):
    """Union locale avec un chemin rapide lorsqu'il n'y a qu'une géométrie."""
    if not geometries:
        return QgsGeometry()
    if len(geometries) == 1:
        return QgsGeometry(geometries[0])
    try:
        resultat = QgsGeometry.unaryUnion(geometries)
        return resultat if resultat is not None else QgsGeometry()
    except (AttributeError, TypeError, RuntimeError):
        return QgsGeometry()


def traiter_lot_recherche_trous(self, etat, taille_lot=1):
    """Le calcul est déjà entièrement fait par :func:`preparer_recherche_trous`."""
    return True


def progression_recherche_trous(etat):
    """Texte court affiché dans le panneau pendant la recherche des trous."""
    return "Recherche des trous…"


def finaliser_recherche_trous(etat):
    """Valide une dernière fois les morceaux trouvés et les numérote."""
    if not etat:
        return []
    parties = fusionner_parties_trous(etat.get("gaps", []))
    return [(i + 1, geom) for i, geom in enumerate(parties)]


def couche_emprise_cachee(self):
    """Retourne la couche d'emprise utilisée lors du dernier contrôle complet."""
    if not self._cached_emprise_layer_id:
        return None
    return QgsProject.instance().mapLayer(self._cached_emprise_layer_id)


def geometrie_emprise_locale(self, rect):
    """Construit seulement la portion d'emprise utile autour d'un rectangle."""
    emprise_layer = couche_emprise_cachee(self)
    if emprise_layer is None or rect is None or rect.isEmpty():
        return None
    return construire_geometrie_emprise_locale(
        emprise_layer, rect, crs_cible=self.layer.crs()
    )


def decouper_a_emprise_locale(self, geometrie):
    """Découpe une géométrie à la portion d'emprise qui la concerne."""
    if geometrie is None or geometrie.isEmpty():
        return geometrie
    emprise = geometrie_emprise_locale(self, geometrie.boundingBox())
    if emprise is None or emprise.isEmpty():
        return QgsGeometry()
    try:
        return geometrie.intersection(emprise)
    except (TypeError, RuntimeError):
        return QgsGeometry()


def _preparer_geometrie_trou(self, couche, gap_index):
    """Nettoie et valide la géométrie d'un trou avant sa matérialisation.

    Retourne la géométrie prête à devenir une nouvelle entité, ou ``None``
    si le trou n'est plus exploitable (message déjà affiché dans ce cas).
    """
    if not isinstance(gap_index, int) or not (0 <= gap_index < len(self._cached_gap_geometries)):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Ce trou n'est plus disponible. Relancez la recherche des anomalies.",
        )
        return None

    geometrie = QgsGeometry(self._cached_gap_geometries[gap_index])
    if geometrie.isEmpty():
        return None
    if not geometrie.isGeosValid():
        geometrie = geometrie.makeValid()
    parties = extraire_parties_polygonales(geometrie)
    if not parties:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La géométrie du trou n'est pas exploitable.",
        )
        return None
    geometrie = parties[0] if len(parties) == 1 else QgsGeometry.unaryUnion(parties)

    # Le trou provient déjà du calcul Emprise - Forêt : il est donc libre
    # par construction. Ne surtout pas soustraire une seconde fois tous les
    # voisins ici : de minuscules imprécisions numériques sur les frontières
    # peuvent sinon vider entièrement un trou pourtant réel.
    #
    # On applique uniquement le nettoyage conservateur de la géométrie du
    # trou (sans couche de référence), puis on contrôle les éventuels
    # recouvrements *significatifs* avec les polygones actuels. Les simples
    # contacts de bord et poussières numériques sont ignorés.
    geometrie = nettoyer_geometrie_decoupee_protegee(
        None, geometrie, fids_exclus=[]
    )
    if geometrie is None or geometrie.isEmpty():
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "La géométrie du trou n'est plus exploitable après nettoyage.",
        )
        self._refresh_timer.start(50)
        return None

    # Protection contre un résultat de vérification devenu obsolète après
    # une édition : si une vraie surface est désormais occupée, on la retire.
    # Un seuil très faible évite de traiter les contacts de frontière comme
    # des recouvrements.
    try:
        seuil_recouvrement_m2 = max(1e-6, abs(float(geometrie.area())) * 1e-12)
        requete = QgsFeatureRequest().setFilterRect(geometrie.boundingBox())
        for entite_existante in couche.getFeatures(requete):
            if not entite_existante.hasGeometry():
                continue
            autre = entite_existante.geometry()
            if autre is None or autre.isEmpty():
                continue
            intersection = geometrie.intersection(autre)
            if (
                intersection is None
                or intersection.isEmpty()
                or abs(float(intersection.area())) <= seuil_recouvrement_m2
            ):
                continue
            geometrie = geometrie.difference(autre)
            geometrie = nettoyer_geometrie_base(geometrie)
            if geometrie is None or geometrie.isEmpty():
                self.iface.messageBar().pushWarning(
                    "Vérification BD Forêt",
                    "Ce trou a déjà été occupé par une autre entité. Relancez la vérification.",
                )
                self._refresh_timer.start(50)
                return None
    except (AttributeError, TypeError, ValueError, RuntimeError):
        # Le trou détecté reste la source de vérité si le simple contrôle de
        # fraîcheur échoue ; on évite de perdre une géométrie valide à cause
        # d'une erreur de robustesse secondaire.
        pass

    return geometrie


def _materialiser_trou(self, couche, geometrie, nom_commande):
    """Crée une entité BD Forêt à partir d'une géométrie de trou déjà préparée.

    Retourne le fid créé, ou ``None`` si la création échoue (message déjà
    affiché dans ce cas).
    """
    index_id_foret = couche.fields().indexOf(CHAMP_ID_FORET)
    if index_id_foret < 0:
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"Le champ {CHAMP_ID_FORET} est introuvable dans la couche BD Forêt.",
        )
        return None

    # id_foret est un identifiant de travail local (cf. README section 0) :
    # les autres attributs restent vides, à renseigner par l'opérateur.
    nouvelle_entite = QgsFeature(couche.fields())
    nouvelle_entite.setGeometry(geometrie)
    nouvelle_entite.setAttribute(index_id_foret, prochain_id_foret(couche))

    commande_ouverte = False
    try:
        couche.beginEditCommand(nom_commande)
        commande_ouverte = True
        if not couche.addFeature(nouvelle_entite):
            raise RuntimeError("la nouvelle entité n'a pas pu être créée")

        synchroniser_zone(self.iface, couche, geometrie, nom_commande)
        couche.endEditCommand()
        commande_ouverte = False

        couche.triggerRepaint(True)
        self.iface.mapCanvas().refresh()
        return int(nouvelle_entite.id())
    except Exception as erreur:
        if commande_ouverte:
            try:
                couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            f"La préparation du trou a échoué : {erreur}",
        )
        return None


@vue_stable_pendant_modification
def reboucher_trou(self, gap_index):
    """Crée une entité BD Forêt à partir de la géométrie d'un trou détecté."""
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
            "La couche BD Forêt doit être en mode édition pour reboucher un trou.",
        )
        return

    geometrie = _preparer_geometrie_trou(self, couche, gap_index)
    if geometrie is None:
        return

    fid = _materialiser_trou(self, couche, geometrie, "Reboucher un trou")
    if fid is None:
        return

    entite = recuperer_entite(couche, fid)
    if entite is None:
        self.iface.messageBar().pushCritical(
            "Vérification BD Forêt",
            "La nouvelle entité est introuvable après sa création.",
        )
        return

    surbrillance = None
    if entite.hasGeometry() and not entite.geometry().isEmpty():
        surbrillance = creer_surbrillance_polygone(
            self.iface.mapCanvas(), entite.geometry(), couche
        )
    try:
        accepte = ouvrir_formulaire_ou_annuler(
            self.iface, couche, self.iface.mapCanvas(), entite, "Vérification BD Forêt"
        )
    finally:
        supprimer_surbrillance_polygone(self.iface.mapCanvas(), surbrillance)

    if accepte:
        # Les signaux d'édition mettent normalement le cache à jour ; cette
        # relance différée garantit que le trou disparaît immédiatement du panneau.
        self._pending_fids.add(fid)
        self._refresh_timer.start(50)


@vue_stable_pendant_modification
def attribuer_trou(self, gap_index):
    """Délègue l'attribution d'un trou à un voisin à l'outil Fusionner.

    Le trou est matérialisé comme une entité BD Forêt temporaire, puis l'outil
    Fusionner est activé exactement comme pour « Fusionner avec… » sur un
    petit polygone : l'entité créée est présélectionnée, l'utilisateur choisit
    le voisin d'un clic. La fusion (et son éventuelle annulation) restent
    entièrement gérées par l'outil Fusionner lui-même.
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
            "La couche BD Forêt doit être en mode édition pour attribuer un trou.",
        )
        return

    fusionner = getattr(self.manager, "fusionner", None) if self.manager else None
    if fusionner is None or not hasattr(fusionner, "activer_avec_fids"):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "L'outil Fusionner n'est pas disponible."
        )
        return

    geometrie = _preparer_geometrie_trou(self, couche, gap_index)
    if geometrie is None:
        return

    fid = _materialiser_trou(self, couche, geometrie, "Préparer un trou pour attribution")
    if fid is None:
        return

    try:
        self.iface.setActiveLayer(couche)
    except RuntimeError:
        pass
    if not fusionner.activer_avec_fids(
        [fid],
        ouvrir_formulaire_apres=False,
        finaliser_au_deuxieme_clic=True,
        callback_fin=lambda fids, ref: apres_fusion_trou(self, fids, ref),
    ):
        return
    self.iface.messageBar().pushInfo(
        "Fusionner BD Forêt",
        "Le trou est présélectionné. Cliquez sur le polygone voisin à fusionner.",
    )


def apres_fusion_trou(controleur, fids_operation, fid_reference):
    """Programme le rafraîchissement local après une attribution de trou déléguée."""
    try:
        controleur._pending_fids.update(int(fid) for fid in (fids_operation or []))
        controleur._pending_fids.add(int(fid_reference))
    except (TypeError, ValueError):
        pass
    if controleur.dock is not None and controleur.dock.isVisible():
        controleur._refresh_timer.start(50)


def reboucher_tous_les_trous(self):
    """Reboule chaque trou avec le voisin partageant sa plus longue frontière.

    Un trou sans aucun voisin en contact est ignoré : il n'y a personne à qui
    l'attribuer automatiquement, seule la création d'un nouveau polygone reste
    possible pour lui, à la main.
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
            "La couche BD Forêt doit être en mode édition.",
        )
        return

    fusionner = getattr(self.manager, "fusionner", None) if self.manager else None
    if fusionner is None or not hasattr(fusionner, "fusionner_fids_direct"):
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt", "Le moteur commun Fusionner n'est pas disponible."
        )
        return

    # Snapshot des index : la liste des trous peut évoluer au fur et à mesure
    # des corrections locales.
    indices = list(range(len(self._cached_gap_geometries)))
    if not indices:
        return

    corriges = 0
    ignores = 0
    for gap_index in indices:
        geometrie = _preparer_geometrie_trou(self, couche, gap_index)
        if geometrie is None:
            ignores += 1
            continue
        voisin = meilleur_voisin_par_contact(couche, geometrie)
        if voisin is None:
            ignores += 1
            continue
        fid_trou = _materialiser_trou(
            self, couche, geometrie, "Préparer un trou pour rebouchage automatique"
        )
        if fid_trou is None:
            ignores += 1
            continue
        succes, fid_reference = fusionner.fusionner_fids_direct(
            [int(voisin), fid_trou],
            fid_reference=int(voisin),
            ouvrir_formulaire=False,
            nom_commande="Reboucher un trou avec le meilleur voisin",
        )
        self._pending_fids.update([fid_trou, int(voisin)])
        if fid_reference is not None:
            self._pending_fids.add(int(fid_reference))
        if succes:
            corriges += 1
        else:
            ignores += 1

    self._refresh_timer.start(50)
    if corriges:
        texte = f"{corriges} trou(s) rebouché(s) avec leur meilleur voisin."
        if ignores:
            texte += f" {ignores} cas ignoré(s) (aucun voisin ou déjà changé)."
        self.iface.messageBar().pushSuccess("Vérification BD Forêt", texte)
    elif ignores:
        self.iface.messageBar().pushWarning(
            "Vérification BD Forêt",
            "Aucun trou n'a pu être rebouché automatiquement.",
        )



def ajouter_au_panneau(controleur, arbre, anomalies, emprise_trouvee, groupe=None):
    """Ajoute la branche des trous au panneau Vérifier."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QTreeWidgetItem

    titre = (
        f"Trous dans la couche ({len(anomalies)})"
        if emprise_trouvee else "Trous dans la couche (bdfv3_emprise absente)"
    )
    if groupe is None:
        groupe = QTreeWidgetItem([titre, ""])
        arbre.addTopLevelItem(groupe)
    for identifiant, geom in anomalies:
        item = QTreeWidgetItem([f"Trou {identifiant}", f"{geom.area() / 10000.0:.2f} ha"])
        item.setData(0, Qt.UserRole, {
            "gap_index": int(identifiant) - 1,
            "extent": controleur._emprise_vers_tuple(geom.boundingBox()),
        })
        groupe.addChild(item)
