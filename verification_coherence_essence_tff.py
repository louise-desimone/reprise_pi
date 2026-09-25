# -*- coding: utf-8 -*-
"""Détecte les incohérences entre l'essence et les booléens du formulaire.

Un polygone attribué (``nouvelle_essence`` renseignée) doit respecter les
contraintes du protocole des reprises : dominante feuillus/conifères
réservée aux essences mixtes, ouvert/fermé exclusifs, CRJP/lande/non forêt
exclusifs entre eux et incompatibles avec tout autre champ. La correction
ouvre directement la fiche de l'entité (avec surbrillance) pour que
l'opérateur corrige lui-même les champs concernés.
"""

from .commun_affichage import creer_surbrillance_polygone, supprimer_surbrillance_polygone
from .commun_edition import recuperer_entite, valeur_champ_texte
from .commun_parametres import normaliser_booleen, normaliser_valeur

# Essences mixtes (colonne F/C/M = "M" dans Correspondances_essences_FCM.csv) :
# seules celles-ci autorisent une dominante feuillus ou conifères.
ESSENCES_MIXTES = (
    "Hêtraie-sapinière",
    "Chênaie-pineraie",
    "Autre mélange de feuillus-conifères",
)
ESSENCE_INDETERMINEE = "Essence indéterminée"


def detecter(feature, field_map):
    """Retourne ``(fid, détail)`` si l'essence et les booléens sont incohérents.

    Une entité non encore revue par le photo-interprète (``nouvelle_essence``
    identique à ``libelle_essence``, la valeur d'origine) n'a rien à
    vérifier : ses booléens n'ont pas encore de sens à contrôler.
    """
    essence = normaliser_valeur(feature[field_map["nouvelle_essence"]])
    if not essence:
        return None
    libelle_essence = normaliser_valeur(feature[field_map["libelle_essence"]])
    if libelle_essence == essence:
        return None

    ouvert = normaliser_booleen(feature[field_map["ouvert"]])
    ferme = normaliser_booleen(feature[field_map["ferme"]])
    dominante_feuillu = normaliser_booleen(feature[field_map["dominante_feuillu"]])
    dominante_conifere = normaliser_booleen(feature[field_map["dominante_conifere"]])
    lande = normaliser_booleen(feature[field_map["lande"]])
    non_foret = normaliser_booleen(feature[field_map["non_foret"]])
    crjp = normaliser_booleen(feature[field_map["crjp"]])

    erreurs = []

    # Règle 1 : dominante feuillus/conifères réservée aux essences mixtes,
    # jamais les deux à la fois.
    if dominante_feuillu and dominante_conifere:
        erreurs.append("dominante feuillus et dominante conifères sont toutes les deux vraies")

    if (dominante_feuillu or dominante_conifere) and essence not in ESSENCES_MIXTES:
        erreurs.append("dominante renseignée alors que l'essence n'est pas une essence mixte")

    if essence in ESSENCES_MIXTES and not (dominante_feuillu or dominante_conifere):
        erreurs.append("essence mixte sans dominante feuillus ou conifères")

    # Règle 2 : ouvert/fermé exclusifs.
    if ouvert and ferme:
        erreurs.append("ouvert et fermé sont tous les deux vrais")

    # Règle 3 : CRJP/lande/non forêt exclusifs entre eux, et incompatibles
    # avec tout autre champ (dominante, ouvert/fermé) ou toute autre essence
    # que "Essence indéterminée".
    nb_cas_speciaux = sum((crjp, lande, non_foret))
    if nb_cas_speciaux > 1:
        erreurs.append("plusieurs champs parmi CRJP, lande et non forêt sont vrais")
    if nb_cas_speciaux > 0:
        if ouvert or ferme or dominante_feuillu or dominante_conifere:
            erreurs.append("CRJP/lande/non forêt est associé à un autre champ")
        if essence != ESSENCE_INDETERMINEE:
            erreurs.append("CRJP/lande/non forêt sans Essence indéterminée")

    if not erreurs:
        return None
    return int(feature.id()), ", ".join(erreurs)


def modifier_attributs_entite(self, fid):
    """Ouvre la fiche de l'entité, en surbrillance, pour corriger les champs."""
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


def ajouter_au_panneau(controleur, arbre, anomalies, groupe=None):
    """Ajoute la branche des incohérences essence/booléens au panneau."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QTreeWidgetItem

    if groupe is None:
        groupe = QTreeWidgetItem([f"Incohérence essence / TFF ({len(anomalies)})", ""])
        arbre.addTopLevelItem(groupe)

    couche = controleur._trouver_couche()
    for fid, detail in sorted(anomalies):
        feature = controleur._cached_feature_by_id.get(fid)
        essence = (
            valeur_champ_texte(couche, feature, "nouvelle_essence")
            if couche is not None and feature is not None else "Non renseigné"
        )
        item = QTreeWidgetItem([f"{essence} ({fid})", detail])
        # "coherence_fid" est la clé que _actions_pour_payload() (verification_panneau.py)
        # reconnaît pour proposer "Modifier les attributs" sur cette anomalie.
        payload = {"fids": [int(fid)], "coherence_fid": int(fid)}
        if feature is not None and feature.hasGeometry() and not feature.geometry().isEmpty():
            payload["extent"] = controleur._emprise_vers_tuple(feature.geometry().boundingBox())
        item.setData(0, Qt.UserRole, payload)
        groupe.addChild(item)
