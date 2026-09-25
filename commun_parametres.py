# -*- coding: utf-8 -*-
"""Paramètres communs du plugin Reprise PI.

Point d'entrée unique pour adapter le plugin à un autre projet : les sections
sont volontairement rangées dans l'ordre où un nouvel utilisateur doit les
lire pour reprendre l'outil sur ses propres couches — 1) quelles couches du
projet QGIS utiliser, 2) quels champs de la couche de travail lire/écrire,
3) quelles règles métier appliquer (seuils BD Forêt v3), 4) le reste des
paramètres techniques (tolérances de calcul, performance, affichage), qu'un
nouvel utilisateur n'a en général pas besoin de toucher. Modifier une valeur
ici suffit à appliquer le changement à l'ensemble du plugin.
"""

from qgis.PyQt.QtCore import QVariant

# -----------------------------------------------------------------------------
# 1. Couches
# -----------------------------------------------------------------------------

# Mots-clés cherchés (normalisés : minuscules, sans accents) dans le nom
# d'une couche du projet QGIS pour identifier automatiquement son rôle.
# Uniquement utilisés par trouver_couche_emprise() (commun_couches.py), pour
# prioriser une couche d'emprise dont le nom contient aussi "bdfv3"/"foret"
# (ex. "Bdfv3 Emprise") sur une couche d'emprise générique.
MOTS_CLES_COUCHE_TRAVAIL = ("bdfv3", "foret")
MOT_CLE_COUCHE_EMPRISE = "emprise"
MOT_CLE_COUCHE_BDFV2 = "bdfv2"

# Utilisés par trouver_couche_alertes() et trouver_couche_travail()
# (commun_couches.py), une recherche par préfixe plutôt que par mot-clé : la
# couche d'alertes ne doit jamais être confondue avec la couche de travail
# elle-même. PREFIXE_COUCHE_PARENT sert la règle de trouver_couche_travail()
# pour la couche de travail éditée par les 5 outils, qui est aussi la couche
# parente de la relation, puisque Bdfv3 Priorites est une seule et même
# couche des deux côtés.
PREFIXE_COUCHE_ALERTES = "alertes centroides"
PREFIXE_COUCHE_PARENT = "bdfv3 priorites"

# -----------------------------------------------------------------------------
# 2. Champs de la couche de travail
# -----------------------------------------------------------------------------
# Nom et normalisation des champs lus/écrits par le plugin. Point d'entrée
# pour adapter le plugin à une couche dont les champs porteraient d'autres
# noms (autre projet, autre version du schéma BD Forêt).

# Identifiant de travail local (voir README section 0 : ce n'est pas un
# identifiant définitif IGN). Utilisé partout où une nouvelle entité doit
# recevoir un id_foret, ou où deux couches (BD Forêt / alertes) doivent être
# reliées par ce champ.
CHAMP_ID_FORET = "id_foret"

# Champs comparés pour juger deux polygones voisins "identiques" (règle
# "Polygones adjacents aux attributs identiques", verification_polygones_
# adjacents_attributs_identiques.py) et pour les règles de cohérence essence/
# TFF (verification_coherence_essence_tff.py), avec leurs variantes de nom
# tolérées selon la version de couche. resoudre_champs() ci-dessous construit
# le "field_map" (nom logique -> vrai nom de champ) que signature_attributs()
# lit ensuite : ajouter un champ à un contrôle d'attribut suppose d'abord
# qu'il figure ici (ou dans CHAMPS_BOOLEENS un peu plus bas, s'il doit être
# comparé comme un booléen normalisé).
ALIAS_ATTRIBUTS = {
    "nouvelle_essence": ("nouvelle_essence",),
    "libelle_essence": ("libelle_essence",),
    "code_tff": ("code_tff",),
    "dominante_feuillu": ("dominante_feuillu", "dominante_feuillus", "Dominante feuillus"),
    "dominante_conifere": ("dominante_conifere", "dominante_coniferes", "Dominante conifère"),
    "crjp": ("CRJP", "crjp"),
    "ouvert": ("ouvert", "Ouvert"),
    "ferme": ("ferme", "Fermé"),
    "non_foret": ("non_foret", "Non forêt", "non forêt"),
    "lande": ("lande", "Lande"),
}

# Sous-ensemble de ALIAS_ATTRIBUTS dont la valeur est un booléen (comparé via
# normaliser_booleen) plutôt qu'un texte (normaliser_valeur) : nouvelle_essence,
# libelle_essence et code_tff en sont volontairement absents.
CHAMPS_BOOLEENS = {
    "dominante_feuillu", "dominante_conifere", "crjp",
    "ouvert", "ferme", "non_foret", "lande",
}


def resoudre_champs(self):
    """Associe chaque nom logique de ALIAS_ATTRIBUTS au vrai nom de champ de la couche."""
    names = {field.name(): field.name() for field in self.layer.fields()}
    names_lower = {field.name().casefold(): field.name() for field in self.layer.fields()}
    resolved = {}
    missing = []

    for logical_name, aliases in ALIAS_ATTRIBUTS.items():
        actual = None
        for alias in aliases:
            if alias in names:
                actual = names[alias]
                break
            actual = names_lower.get(alias.casefold())
            if actual:
                break
        if actual is None:
            missing.append("/".join(aliases))
        else:
            resolved[logical_name] = actual
    return resolved, missing


def normaliser_valeur(value):
    """Texte comparable pour un champ non booléen (NULL/None -> chaîne vide)."""
    if value is None or value == QVariant():
        return ""
    return str(value).strip()


def normaliser_booleen(value):
    """Booléen comparable pour un champ coché/texte/entier selon la couche source."""
    if value is None or value == QVariant():
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() in {"1", "true", "vrai", "yes", "oui", "t"}


def signature_attributs(feature, field_map):
    """Retourne la signature normalisée utilisée pour comparer deux entités.

    ``field_map`` vient de resoudre_champs() : chaque nom logique y est déjà
    résolu vers le vrai nom de champ de la couche, quelle que soit la variante
    utilisée. Deux entités ayant la même signature sont considérées comme
    portant les mêmes attributs, indépendamment de leur géométrie.
    """
    signature = []
    for logical_name, field_name in field_map.items():
        value = feature[field_name]
        if logical_name in CHAMPS_BOOLEENS:
            signature.append(normaliser_booleen(value))
        else:
            signature.append(normaliser_valeur(value))
    return tuple(signature)


# -----------------------------------------------------------------------------
# 3. Règles métier BD Forêt v3
# -----------------------------------------------------------------------------

# Seuil de la règle "Surfaces < 0,5 ha" (verification_surface05ha.py) : 5000 m².
SURFACE_MINIMALE_M2 = 5000.0

# Précision du projet (1 mm) utilisée par les contrôles d'adjacence pour
# décider si deux limites sont communes malgré les micro-écarts numériques.
TOLERANCE_ADJACENCE_M = 0.001

# Seuil du nettoyage automatique (verification_nettoyage_automatique.py) :
# un recouvrement ou un trou de moins de 100 m² est fusionné avec son
# meilleur voisin sans arbitrage humain. Le panneau Vérifier affiche lui
# tous les recouvrements et tous les trous, sans seuil.
SURFACE_MAXIMALE_MICRO_ECART_M2 = 100.0

# Seuil dédié à "Reporter depuis BDFv2" (edition_reporter_bdfv2.py) : une
# partie isolée par la découpe (le nouveau polygone collé ou le reste d'un
# polygone v3 découpé) est recollée automatiquement si elle fait moins de
# 0,25 ha ; au-delà, c'est une vraie scission laissée telle quelle, juste
# signalée. Volontairement séparé de SURFACE_MAXIMALE_MICRO_ECART_M2 : ce
# seuil-ci ne doit pas influencer le nettoyage automatique, qui continue de
# fusionner sans arbitrage humain uniquement en dessous de 100 m².
SURFACE_MAXIMALE_PARTIE_ISOLEE_REPORT_M2 = 2500.0  # 0,25 ha

# Fusion des parties d'une multipartie (verification_entites_multiparties.py) :
# tolérance d'alignement des sommets AVANT fusionner_geometries, plus généreuse
# que son propre alignement interne (1 cm). Deux parties d'une même entité
# multipartie peuvent avoir été numérisées séparément (import, correction
# manuelle) avec un écart de quelques centimètres sur leur limite commune,
# alors qu'elles se touchent visiblement ; sans ce pré-alignement, l'union
# reste en 2 polygones distincts et la fusion est refusée à tort.
TOLERANCE_SNAP_PARTIES_MULTIPARTIE_M = 0.05  # 5 cm

# -----------------------------------------------------------------------------
# Classement des polygones dans la reprise PI
# -----------------------------------------------------------------------------

# Le bouton « Vérifier les alertes et recalculer » réécrit ce champ de 1 à N.
# Pour changer la logique de classement, il suffit de modifier les lignes de
# CRITERES_CLASSEMENT ci-dessous. Le second élément vaut True pour un tri
# croissant et False pour un tri décroissant. Les valeurs NULL restent toujours
# à la fin, quel que soit le sens du tri.
# Nom du champ dans la couche BD Forêt où le rang 1..N est écrit.
CHAMP_CLASSEMENT = "classement"
CRITERES_CLASSEMENT = (
    ("priorite_max", True),
    ("nouvelle_essence", True),
    ("surface", False),
)

# Si le champ ci-dessous fait partie des critères, sa valeur est recalculée à
# partir de la géométrie avant le classement. Mettre None pour désactiver ce
# recalcul automatique et utiliser la valeur déjà présente dans la table.
CHAMP_SURFACE_A_RECALCULER = "surface"
# Nombre de décimales affichées pour une surface convertie en hectares
# (commun_edition.surface_ha).
DECIMALES_SURFACE_HA = 2

# -----------------------------------------------------------------------------
# 4. Paramètres techniques (tolérances de calcul, performance, affichage)
# -----------------------------------------------------------------------------
# Un nouvel utilisateur n'a en général pas besoin de modifier cette section :
# ce sont des réglages de robustesse numérique et de rendu, pas des règles
# métier propres à un projet.

TOLERANCE_RELATIVE_AIRE = 1e-9
TOLERANCE_MIN_AIRE = 1e-4

# Fusion : tolérance extrêmement faible utilisée pour supprimer les contacts
# ponctuels parasites après l'union. 0,000001 m = 1 micromètre.
TOLERANCE_NETTOYAGE_FUSION_M = 0.000001

# Nettoyage après découpe/attribution : 1 mm. Le nettoyage est toujours
# recoupé avec la géométrie d'origine puis protégé des autres polygones,
# afin de supprimer les micro-pointes sans agrandir la couverture.
TOLERANCE_NETTOYAGE_DECOUPE_M = 0.001

# Résidu numérique GEOS insignifiant après une découpe à l'emprise. Utilisé
# comme seuil pour qu'une surface résiduelle sous ce seuil ne soit pas
# signalée comme une vraie anomalie (les trous n'ont pas de taille négligeable,
# voir SURFACE_BRUIT_NUMERIQUE_GEOS_M2 : seul le bruit GEOS pur y est filtré).
SURFACE_MINIMALE_RESIDU_NUMERIQUE_M2 = 0.01

# Bruit numérique GEOS pur (et non une taille jugée négligeable) : utilisé
# partout où une surface résiduelle ne doit être ignorée que si elle provient
# d'une imprécision de calcul, jamais d'un écart réel même minuscule.
SURFACE_BRUIT_NUMERIQUE_GEOS_M2 = 1e-8

# À partir de ce nombre de polygones, les calculs géométriques lourds du
# contrôle complet sont confiés à QgsTask pour garder l'interface réactive.
SEUIL_TACHE_RELATIONS = 500

# Géométries parasites : pointes/fentes intérieures et papillons.
SURFACE_MAXIMALE_BOUCLE_PARASITE_M2 = 0.01
TOLERANCE_RETOUR_POINTE_PARASITE_M = 0.000001
PROFONDEUR_MINIMALE_POINTE_PARASITE_M = 0.01

# Outil Remodeler : rayon de recherche des sommets/segments au clic, en pixels.
TOLERANCE_ACCROCHAGE_PIXELS_REMODELER = 12.0
# Outil Remodeler : tolérance topologique fixe du projet (1 cm en Lambert-93)
# pour décider si deux limites sont communes malgré les micro-écarts
# numériques. Volontairement indépendante du zoom et de la tolérance
# d'accrochage ci-dessus.
TOLERANCE_TOPOLOGIQUE_REMODELER_M = 0.01
# Outil Remodeler : largeur (px) de la surbrillance de la limite verrouillée
# avant le tracé de remplacement. Couleur : COULEUR_SURBRILLANCE plus bas dans
# ce fichier, la même que les surbrillances jaunes des autres outils.
LARGEUR_FRONTIERE_REMODELER = 3


# -----------------------------------------------------------------------------
# Performance / réactivité
# -----------------------------------------------------------------------------

# Les valeurs ci-dessous ne changent aucune règle métier. Elles déterminent
# seulement combien d'entités sont traitées avant de rendre la main à Qt.
TAILLE_LOT_PREPARATION_VERIFICATION = 75
TAILLE_LOT_VOISINAGE_VERIFICATION = 200

# Recherche des trous : on indexe d'abord l'emprise par lots, puis on calcule
# Emprise - Forêt sur de petites tuiles spatiales. Une seule tuile est traitée
# par passage dans la boucle Qt pour éviter les gels de l'interface.
TAILLE_LOT_INDEX_EMPRISE_TROUS = 500
CIBLE_ENTITES_PAR_TUILE_TROUS = 200
TAILLE_LOT_TROUS_VERIFICATION = 1
# Délai avant de relancer un contrôle après une édition locale (regroupe les
# modifications rapprochées en un seul recalcul au lieu d'un par entité).
DELAI_RAFRAICHISSEMENT_VERIFICATION_MS = 120
# Délai avant de retenter la connexion aux signaux d'une couche (ex. juste
# après un changement de projet, pendant que QGIS finit de la charger).
DELAI_RECONNEXION_COUCHES_MS = 200

# -----------------------------------------------------------------------------
# Surbrillance des polygones
# -----------------------------------------------------------------------------
# Jaune (RGBA) : couleur par défaut de la sélection dans tous les outils.
COULEUR_SURBRILLANCE = (255, 210, 0, 245)
# Transparent : le contour intérieur ne doit pas cacher la couche en dessous.
COULEUR_REMPLISSAGE_SURBRILLANCE = (255, 255, 255, 0)
# Sélection en cours sur BDFv2 (outil "Reporter depuis BDFv2") : bleu flashy,
# pour ne jamais la confondre avec le jaune habituel utilisé une fois la
# géométrie collée dans v3 (indique qu'on est bien repassé côté v3).
COULEUR_SURBRILLANCE_BDFV2 = (0, 255, 255, 255)
COULEUR_REMPLISSAGE_SURBRILLANCE_BDFV2 = (0, 255, 255, 60)
# Largeur (px) des deux contours de SurbrillancePolygone (commun_affichage.py) :
# extérieur fixe, intérieur qui se retire visuellement au zoom.
LARGEUR_SURBRILLANCE_EXTERIEURE = 2
LARGEUR_SURBRILLANCE_INTERIEURE = 1
# Distance (px) entre les deux contours, convertie en unités carte selon le zoom.
RETRAIT_SURBRILLANCE_PIXELS = 4
# Segments utilisés pour arrondir le buffer du contour intérieur.
FINESSE_ARRONDI_SURBRILLANCE = 8

# -----------------------------------------------------------------------------
# Affichage de la couche anomalies du vérificateur
# -----------------------------------------------------------------------------
# Nom de la couche mémoire créée par "Créer la couche temporaire" (verification.py).
NOM_COUCHE_ANOMALIES = "Anomalies BD Forêt"
# CRS de repli si la couche de travail n'en a pas (cas rare, jamais en pratique).
CRS_ANOMALIES_DEFAUT = "EPSG:2154"

# Rouge hachuré : distinct du jaune de surbrillance pour ne pas confondre une
# anomalie affichée avec une sélection active dans un outil d'édition.
COULEUR_REMPLISSAGE_ANOMALIE = (255, 255, 255, 0)
COULEUR_CONTOUR_ANOMALIE = (205, 0, 0, 230)
LARGEUR_CONTOUR_ANOMALIE = 0.9
COULEUR_HACHURE_ANOMALIE = (220, 0, 0, 175)
LARGEUR_HACHURE_ANOMALIE = 0.35
DISTANCE_HACHURE_ANOMALIE = 3.0
# Deux directions croisées (45°/135°) pour un motif de hachure en croisillon.
ANGLES_HACHURE_ANOMALIE = (45, 135)

# -----------------------------------------------------------------------------
# Clignotement des anomalies
# -----------------------------------------------------------------------------

# Chaque paire (délai en ms depuis le clic, visible) programme un
# QTimer.singleShot dans ClignotementVerification.afficher() (verification.py) :
# la géométrie clignote deux fois (cachée puis visible, deux fois de suite)
# avant de s'effacer définitivement à CLIGNOTEMENT_ANOMALIE_FIN_MS.
CLIGNOTEMENT_ANOMALIE_ETAPES_MS = (
    (180, False),
    (360, True),
    (540, False),
    (720, True),
)
CLIGNOTEMENT_ANOMALIE_FIN_MS = 1050
