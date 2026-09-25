# Reprise PI, guide de lecture du code

## Sommaire

- [Principe général](#principe-général)
- [Contexte](#contexte)
- [Vue d'ensemble](#vue-densemble)
- [Point d'entrée du plugin](#point-dentrée-du-plugin)
  - [`__init__.py`](#__init__py)
- [Les outils d'édition : edition_*.py](#les-outils-dédition-edition_py)
  - [`edition_creer.py`](#edition_creerpy)
  - [`edition_separer.py`](#edition_separerpy)
  - [`edition_fusionner.py`](#edition_fusionnerpy)
  - [`edition_remodeler.py`](#edition_remodelerpy)
  - [`edition_reporter_bdfv2.py`](#edition_reporter_bdfv2py)
- [Les fonctions communes : commun_*.py](#les-fonctions-communes-commun_py)
  - [`commun_outils.py`](#commun_outilspy)
  - [`commun_couches.py`](#commun_couchespy)
  - [`commun_parametres.py`](#commun_parametrespy)
  - [`commun_edition.py`](#commun_editionpy)
  - [`commun_topologie.py`](#commun_topologiepy)
  - [`commun_affichage.py`](#commun_affichagepy)
  - [`commun_synchronisation_alertes.py`](#commun_synchronisation_alertespy)
  - [`commun_compteur_alertes.py`](#commun_compteur_alertespy)
  - [`commun_historique_formulaires.py`](#commun_historique_formulairespy)
  - [`commun_etat_session.py`](#commun_etat_sessionpy)
  - [`commun_protection_vue.py`](#commun_protection_vuepy)
- [La vérification de la BD Forêt](#la-vérification-de-la-bd-forêt)
  - [`verification.py`](#verificationpy)
  - [`verification_panneau.py`](#verification_panneaupy)
  - [Les fichiers de règles `verification_*.py`](#les-fichiers-de-règles-verification_py)
  - [`verification_nettoyage_automatique.py`](#verification_nettoyage_automatiquepy)
  - [`verification_tache_relations.py`](#verification_tache_relationspy)
- [Alertes et modification des polygones](#alertes-et-modification-des-polygones)
- [Quel fichier modifier ?](#quel-fichier-modifier-)

## Principe général

L'organisation du plugin repose sur une règle simple : le comportement propre à un outil reste
dans son fichier, tandis que les traitements partagés sont centralisés.

Cela permet de limiter les duplications et de garantir qu'une même règle métier, géométrique ou
de synchronisation est appliquée de la même manière par les différents outils.

## Contexte

Ce plugin ne modifie jamais des polygones déjà publiés par l'IGN. Il travaille sur une
couche de travail, créée pour la reprise manuelle de la BD Forêt v3 automatisée.

Conséquences directes sur le code :

- `id_foret` est un identifiant de travail, pas un identifiant définitif. Il a été créé pour
  la relation QGIS entre `Bdfv3 Priorites` et `Alertes Centroides` (voir README.md) : c'est la
  clé de liaison qui permet de retrouver les alertes d'un polygone, pas une référence IGN. Il est
  produit de deux façons, toutes deux purement locales à ce fichier de travail, sans lien avec un
  référentiel IGN externe : le cas normal, une entité neuve, reçoit le maximum déjà présent
  dans la couche GPKG plus un (`commun_edition.py`, `prochain_id_foret()`) ; le cas de secours,
  une entité déjà existante qui se retrouve sans `id_foret` pendant une synchronisation des
  alertes, reçoit directement la valeur de son `fid` GeoPackage
  (`commun_synchronisation_alertes.py`, `attribuer_nouvel_id_foret()`). Le `fid` du GeoPackage
  lui-même (identifiant natif de la couche, attribué par le fournisseur GDAL/OGR) est lui aussi
  purement local à ce fichier de travail.
- Les identifiants définitifs ne sont pas créés par ce plugin. Ils seront attribués plus
  tard, lors d'une étape de post-traitement séparée, avant la montée en base officielle.
- Les champs définitifs (nomenclature finale) ne sont pas tous garantis ici non plus. Ce
  plugin travaille avec les champs nécessaires à la photo-interprétation et à ses propres
  contrôles ; certains champs de la nomenclature finale peuvent être complétés ou corrigés lors
  du même post-traitement.
- Il reste donc toujours une étape de post-traitement après ce plugin et avant la montée en
  base (attribution des identifiants définitifs, complétion/contrôle des champs finaux). Ce
  plugin ne prétend pas produire un livrable directement injectable en base.

## Vue d'ensemble

```
reprise_pi/
│
├── __init__.py
│   └── Point d'entrée du plugin dans QGIS
│
├── commun_*.py
│   └── Fonctions partagées entre plusieurs outils
│
├── edition_*.py
│   └── Outils permettant de modifier les polygones BD Forêt
│
├── verification.py
├── verification_panneau.py
├── verification_*.py
│   └── Contrôle et correction des anomalies
│
├── icon_*.svg
│   └── Icônes utilisées dans l'interface
│
├── metadata.txt
│   └── Métadonnées utilisées par QGIS pour charger le plugin
│
├── README.md
│   └── Présentation générale du plugin et installation
│
├── README_CODE.md
│   └── Organisation du code et repères pour le développement
│
├── GUIDE_UTILISATION.md
│   └── Mode d'emploi destiné aux utilisateurs
│
└── DOCUMENTATION_CODE.md
    └── Référence détaillée des classes et fonctions
```

## Point d'entrée du plugin

### `__init__.py`

C'est le point d'entrée du plugin.

QGIS passe par ce fichier pour créer l'instance de Reprise PI lors du chargement de l'extension.
Pour comprendre ensuite comment les différents outils sont créés et activés, le fichier le plus
utile est [`commun_outils.py`](commun_outils.py).

## Les outils d'édition : edition_*.py

Ces fichiers correspondent aux actions que le photo-interprète peut effectuer sur la couche de
travail `Bdfv3 Priorites`.

### `edition_creer.py`

Gère l'outil Créer un nouveau polygone BD Forêt.

Le polygone dessiné est créé dans la couche de travail. Sa géométrie est découpée à l'emprise et
sa surface est retirée aux polygones existants qu'il recouvre.

### `edition_separer.py`

Gère l'outil Séparer.

Il permet de découper un ou plusieurs polygones le long d'une ligne tracée par l'utilisateur. Le
découpage repose sur le moteur natif de QGIS, puis le plugin prend en charge les attributs, les
nouveaux identifiants de travail, les surfaces et la synchronisation des alertes.

### `edition_fusionner.py`

Gère l'outil Fusionner.

Il permet de sélectionner plusieurs polygones, de les fusionner et de choisir l'entité dont les
attributs doivent être conservés. Le résultat est ensuite nettoyé et remis en cohérence avec
l'emprise et les alertes.

### `edition_remodeler.py`

Gère l'outil Remodeler.

Il permet de redessiner une frontière commune entre deux polygones. Il prend notamment en charge
la sélection des deux entités, l'accrochage, la modification des géométries et la synchronisation
des données après la modification.

### `edition_reporter_bdfv2.py`

Gère l'outil Reporter depuis BDFv2.

Il permet de reprendre une géométrie provenant de la BD Forêt v2 et de l'insérer dans la couche de
travail v3. La surface reportée est retirée aux polygones v3 qu'elle recouvre.

## Les fonctions communes : commun_*.py

Ces fichiers contiennent les fonctions utilisées par plusieurs outils. Le principe est d'éviter
qu'une même règle ou un même traitement soit recopié dans plusieurs fichiers `edition_*.py`.

### `commun_outils.py`

Centralise la création des actions QGIS et la gestion de leur activation.

C'est un bon point de départ pour comprendre comment les boutons de la barre d'outils sont reliés
aux différents outils du plugin.

### `commun_couches.py`

Recherche dans le projet QGIS les couches nécessaires au fonctionnement du plugin et vérifie leur
disponibilité.

Il permet notamment de retrouver :
- `Bdfv3 Priorites` ;
- `Bdfv3 Emprise` ;
- `Alertes Centroides`.

### `commun_parametres.py`

Regroupe les paramètres utilisés dans plusieurs parties du plugin :
- noms et mots-clés des couches ;
- noms des champs ;
- règles métier communes ;
- tolérances géométriques ;
- paramètres d'affichage et de performance.

Lorsqu'une valeur doit être utilisée par plusieurs outils, elle doit de préférence être définie
ici plutôt que recopiée ailleurs.

### `commun_edition.py`

Regroupe les opérations communes liées à l'édition des entités.

Il intervient notamment dans la création des entités et la gestion des `id_foret` de travail.

### `commun_topologie.py`

Regroupe les traitements géométriques communs : nettoyage des géométries, gestion des parties
polygonales, opérations de fusion et traitements liés à l'emprise.

Lorsqu'un comportement concerne la géométrie elle-même et doit être réutilisé par plusieurs
outils, c'est généralement ici qu'il faut regarder.

### `commun_affichage.py`

Gère les affichages temporaires partagés entre les outils, notamment les hachures et les
surbrillances sur la carte.

### `commun_synchronisation_alertes.py`

Assure la remise en cohérence entre les polygones et les alertes après une modification
géométrique.

Il recalcule spatialement le rattachement des alertes aux `id_foret`, puis met à jour les
indicateurs associés aux polygones.

### `commun_compteur_alertes.py`

Écoute les changements liés aux alertes et déclenche les mises à jour nécessaires des compteurs
et indicateurs.

### `commun_historique_formulaires.py`

Gère l'historique des fiches ouvertes dans la table attributaire et les boutons Précédent /
Suivant.

### `commun_etat_session.py`

Conserve certains éléments de l'état de travail pendant la session QGIS afin que les différents
outils puissent partager ces informations.

### `commun_protection_vue.py`

Regroupe les mécanismes destinés à préserver la vue de l'utilisateur pendant certaines opérations
du plugin.

## La vérification de la BD Forêt

La partie Vérification BD Forêt est séparée des outils classiques d'édition. Elle recherche des
anomalies dans la couche de travail et propose, selon les cas, des actions de correction.

### `verification.py`

C'est le fichier central de la vérification.

Il orchestre les contrôles, les résultats, les caches et les mises à jour locales. Il fait le lien
entre les différentes règles de vérification et le panneau affiché dans QGIS.

### `verification_panneau.py`

Gère l'interface Qt du panneau Vérification BD Forêt : affichage des résultats, interactions
utilisateur et menus contextuels.

La logique de calcul reste autant que possible séparée de ce fichier.

### Les fichiers de règles `verification_*.py`

Chaque fichier correspond à un type d'anomalie particulier :
- `verification_surface05ha.py` : polygones dont la surface est inférieure à 0,5 ha ;
- `verification_entites_multiparties.py` : géométries multiparties ;
- `verification_recouvrements.py` : recouvrements entre polygones ;
- `verification_trous.py` : trous dans la couverture de la couche par rapport à l'emprise ;
- `verification_polygones_adjacents_attributs_identiques.py` : polygones voisins présentant les
  mêmes attributs métier ;
- `verification_coherence_essence_tff.py` : incohérences entre l'essence renseignée et le type de
  formation forestière.

### `verification_nettoyage_automatique.py`

Gère le bouton de nettoyage automatique.

Il applique plusieurs corrections géométriques prévues par le plugin, notamment sur les petites
anomalies, les trous, les recouvrements, les parties isolées et les géométries hors emprise.

### `verification_tache_relations.py`

Gère certains calculs lourds dans une `QgsTask` afin d'éviter de bloquer l'interface de QGIS lors
des contrôles sur de grosses couches.

## Alertes et modification des polygones

Plusieurs outils d'édition peuvent modifier la géométrie ou créer de nouveaux polygones. Ces
modifications peuvent changer le rattachement des alertes.

La logique générale est donc la suivante :

```
Modification d'un polygone
        ↓
Mise à jour de la géométrie
        ↓
Recalcul de la surface
        ↓
Rattachement spatial des alertes
        ↓
Recalcul des compteurs d'alertes
        ↓
Mise à jour des indicateurs du polygone
```

Le rattachement spatial et la mise à jour des indicateurs passent principalement par :

```
commun_synchronisation_alertes.py
            ↓
commun_compteur_alertes.py
```

Cela permet d'avoir la même logique après une création, une séparation, une fusion ou un
remodelage.

## Quel fichier modifier ?

| Je veux modifier… | Fichier à regarder en premier |
|---|---|
| le comportement de Créer | `edition_creer.py` |
| le comportement de Séparer | `edition_separer.py` |
| le comportement de Fusionner | `edition_fusionner.py` |
| le comportement de Remodeler | `edition_remodeler.py` |
| le report depuis la BD Forêt v2 | `edition_reporter_bdfv2.py` |
| l'activation ou la création d'un bouton | `commun_outils.py` |
| la recherche des couches QGIS | `commun_couches.py` |
| les noms des couches, champs ou paramètres communs | `commun_parametres.py` |
| une opération d'édition utilisée par plusieurs outils | `commun_edition.py` |
| une règle géométrique commune | `commun_topologie.py` |
| les hachures ou surbrillances | `commun_affichage.py` |
| le rattachement des alertes après une modification | `commun_synchronisation_alertes.py` |
| les compteurs d'alertes | `commun_compteur_alertes.py` |
| les boutons Précédent / Suivant | `commun_historique_formulaires.py` |
| le panneau de vérification | `verification_panneau.py` |
| le fonctionnement général des contrôles | `verification.py` |
| une règle d'anomalie particulière | le fichier `verification_*.py` correspondant |
| le nettoyage automatique | `verification_nettoyage_automatique.py` |
| les traitements lourds de vérification | `verification_tache_relations.py` |
