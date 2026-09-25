# Reprise PI, guide d'utilisation

<img src="icon_outils.svg" width="48">

Ce guide s'adresse au photo-interprète qui utilise le plugin au quotidien dans QGIS. Il décrit
ce que fait chaque outil et comment s'en servir, sans entrer dans le code (pour ça, voir
`README_CODE.md`).

## Sommaire

- [Préparer son projet](#préparer-son-projet)
- [Les 5 outils d'édition](#les-5-outils-dédition)
  - [Créer un nouveau polygone BD Forêt](#-créer-un-nouveau-polygone-bd-forêt)
  - [Séparer un ou plusieurs polygones de la BD Forêt](#-séparer-un-ou-plusieurs-polygones-de-la-bd-forêt)
  - [Fusionner plusieurs polygones BD Forêt](#-fusionner-plusieurs-polygones-bd-forêt)
  - [Remodeler la limite entre 2 polygones BD Forêt](#-remodeler-la-limite-entre-2-polygones-bd-forêt)
  - [Reporter un polygone depuis BDFv2](#-reporter-un-polygone-depuis-bdfv2)
- [Le panneau « Vérification BD Forêt »](#-le-panneau-vérification-bd-forêt-)
  - [Nettoyer la couche](#nettoyer-la-couche)
  - [Vérifier les règles métier](#vérifier-les-règles-métier)
  - [Créer la couche temporaire](#créer-la-couche-temporaire)
- [Navigation et alertes, dans la table attributaire](#navigation-et-alertes-dans-la-table-attributaire)

## Préparer son projet

Le plugin retrouve seul les couches dont il a besoin, par leur nom :

- la **couche de travail** : une couche polygonale dont le nom commence par « Bdfv3 Priorites » ;
- la **couche d'emprise** : une couche polygonale dont le nom contient « emprise » ;
- la couche **Alertes Centroides** : une couche de points dont le nom commence par
  « Alertes Centroides » (pour la synchronisation des alertes et le classement) ;
- en option, une couche **BDFv2** (pour reporter des polygones v2).

Si la couche de travail n'est pas trouvée, chaque outil affiche un message clair dans la barre
QGIS plutôt que d'échouer silencieusement.

## Les 5 outils d'édition

Chaque outil se déclenche depuis la barre d'outils Reprise PI. Un seul outil géométrique peut
être actif à la fois : en activer un désactive automatiquement les autres. La couche de travail
passe en mode édition automatiquement si besoin.

### <img src="icon_creer_polygone.svg" width="24"> Créer un nouveau polygone BD Forêt

- **Clic gauche** : ajoute un sommet du contour en cours de dessin.
- **Clic droit** : termine le contour et crée le polygone.
- **Échap** : annule le dessin en cours.

La surface dessinée est retirée à tous les polygones existants qu'elle recouvre : la couverture
du territoire reste continue, sans trou ni recouvrement créé par l'opération elle-même. La
nouvelle entité ne reprend aucun attribut métier (essence, type...) des polygones qu'elle
recouvre : sa fiche s'ouvre vide (à l'exception du classement et du millésime, conservés pour
rester cohérents avec le voisinage) pour que vous la renseigniez.

### <img src="icon_separer.svg" width="24"> Séparer un ou plusieurs polygones de la BD Forêt

Sélection des polygones à découper :
- **Clic gauche** sur un polygone : l'ajoute à la sélection (surbrillance jaune) s'il n'y était
  pas déjà, ou l'en retire s'il y était.
- **Ctrl+clic gauche** : ne fait jamais qu'un retrait : sur un polygone déjà sélectionné, il le
  retire ; sur un polygone non sélectionné, il ne fait rien (Ctrl+clic n'ajoute jamais).
- **Clic droit** : passe au tracé de la ligne de coupe (au moins un polygone doit être
  sélectionné).

Tracé de la ligne de coupe :
- **Clic gauche** : ajoute un point de la ligne.
- **Clic droit** : termine la ligne et découpe tous les polygones sélectionnés le long de son
  tracé (avec moins de 2 points, annule et revient à la sélection).
- **Échap** : annule le tracé et revient à la sélection.

Chaque nouveau morceau créé hérite des attributs de son polygone d'origine (sauf `id_foret`, qui
est régénéré pour rester unique) ; sa fiche s'ouvre pour confirmation ou correction.

### <img src="icon_fusionner.svg" width="24"> Fusionner plusieurs polygones BD Forêt

- **Clic gauche** sur un polygone : l'ajoute à la sélection s'il n'y était pas déjà, ou l'en
  retire s'il y était (même règle que Séparer : Ctrl+clic ne fait jamais qu'un retrait).
- **Clic droit** : lance la fusion des polygones sélectionnés (il en faut au moins deux, sinon un
  message le rappelle).

Si les polygones sélectionnés ont des attributs différents, une fenêtre demande lequel doit
fournir les attributs conservés sur l'entité fusionnée.

### <img src="icon_remodeler.svg" width="24"> Remodeler la limite entre 2 polygones BD Forêt

- **Premier clic gauche** : doit être accroché (snapping QGIS) à un sommet ou un segment d'une
  limite **partagée entre deux polygones** de la couche de travail. Une bordure extérieure seule
  (sans second polygone voisin, par exemple contre l'emprise) n'est **pas** remodelable : un
  message l'indique explicitement. Ce premier clic verrouille la frontière trouvée (affichée en
  surbrillance) et devient aussi le premier point du nouveau tracé.
- **Clics suivants** : ajoutent les points du nouveau tracé.
- **Clic droit** : termine le tracé et applique le nouveau tracé aux deux polygones concernés,
  sans toucher au reste de leurs limites.
- **Échap** : annule le tracé et déverrouille la frontière.

Si plusieurs polygones se rejoignent au point cliqué (carrefour), un message prévient de bien
choisir un tracé qui ne modifie la limite qu'entre les deux polygones voulus.

### <img src="icon_reporter_bdfv2.svg" width="24"> Reporter un polygone depuis BDFv2

- **Clic gauche** sur un polygone de la couche BDFv2 : l'ajoute à la sélection (surbrillance
  bleue) s'il n'y était pas déjà, ou l'en retire s'il y était (même règle que Fusionner :
  Ctrl+clic ne fait jamais qu'un retrait).
- **Clic droit** : colle tous les polygones sélectionnés dans la couche de travail v3, l'un après
  l'autre, en retirant la surface correspondante aux polygones v3 qu'ils recouvrent.

Une petite partie isolée créée par ce découpage (moins de 0,25 ha) est automatiquement recollée à
son meilleur voisin plutôt que laissée comme une miette séparée ; une scission plus importante
est laissée telle quelle et simplement signalée.

## <img src="icon_verification.svg" width="24"> Le panneau « Vérification BD Forêt »

Ouvert depuis la barre d'outils, ce panneau propose trois actions dans l'ordre où elles sont
affichées : nettoyer la couche, vérifier les règles métier, créer une couche temporaire des
anomalies.

### Nettoyer la couche

Corrige automatiquement, par petits lots (sans bloquer QGIS), sept catégories de défauts
mineurs, dans cet ordre :

1. Mise en conformité géométrique (réparation des géométries invalides).
2. Petites surfaces entières (< 100 m²) fusionnées avec leur meilleur voisin.
3. Trous (< 100 m²) comblés dans leur meilleur voisin.
4. Recouvrements (< 100 m²) absorbés par le plus grand des deux polygones.
5. Parties isolées de multiparties (< 100 m²) fusionnées avec leur meilleur voisin externe.
6. Suppression de tout ce qui dépasse de l'emprise.
7. Synchronisation des alertes (recalcul différé pendant tout le nettoyage, déclenché une seule
   fois à la fin).

La petite flèche à droite du bouton ouvre un menu à cases à cocher pour désactiver une ou
plusieurs étapes avant de lancer le nettoyage. Une table affiche la progression étape par étape ;
une croix en haut à droite permet de la refermer quand vous le souhaitez : elle ne se ferme
jamais toute seule.

### Vérifier les règles métier

Recherche six catégories d'anomalies, chacune activable/désactivable via la flèche à droite du
bouton. L'arbre de résultats a jusqu'à trois niveaux (catégorie entière, groupe ou entité, parfois
partie d'entité) et chaque niveau n'offre pas forcément d'action : un double-clic sur une ligne
fait clignoter sa géométrie sur la carte, un clic droit ouvre le menu des actions disponibles à
*ce* niveau précis.

**Surfaces < 0,5 ha** : un polygone entier sous le seuil réglementaire.
- Sur la catégorie entière : *Tout fusionner avec le meilleur voisin* (traite en une fois tous les
  petits polygones qui ont un voisin, chacun avec le sien).
- Sur un polygone précis de la liste : *Fusionner avec…* (ouvre l'outil Fusionner, présélectionne
  ce polygone, attend le clic sur le voisin).
- Un petit polygone sans aucun voisin avec qui fusionner n'apparaît pas dans la liste (rien à lui
  proposer).

**Entités multiparties** : un polygone composé de plusieurs parties disjointes. L'arbre détaille
chaque partie sous l'entité.
- Sur l'entité entière : *Séparer les parties* (transforme chaque partie en entité indépendante,
  ouvre la fiche de la plus petite) ; et, seulement si les parties peuvent redevenir un seul
  polygone continu, *Fusionner les parties* (les réunit, sans toucher aux autres polygones de la
  couche).
- Sur une partie précise (sous-ligne « Partie N ») : *Fusionner avec…* détache uniquement cette
  partie dans une entité temporaire, puis ouvre l'outil Fusionner pour choisir son voisin ; le
  reste de la multipartie garde l'entité et l'id_foret d'origine.
- Pas d'action groupée pour toute la catégorie.

**Recouvrements** : deux polygones qui se chevauchent.
- Sur une paire précise (il n'y a pas d'autre niveau, chaque recouvrement est déjà une paire) :
  *Attribuer à…* (le polygone choisi reste inchangé, l'autre perd la zone commune, ou disparaît
  s'il était entièrement recouvert) ou *Découper le recouvrement* (la zone commune devient une
  nouvelle entité indépendante, les deux polygones sources la perdent).
- Pas d'action groupée pour toute la catégorie.

**Trous dans la couche** : vide entre la couverture et l'emprise.
- Sur la catégorie entière : *Tout reboucher avec le meilleur voisin* (comble en une fois tous les
  trous qui ont un voisin).
- Sur un trou précis de la liste : *Créer un nouveau polygone* (matérialise le trou tel quel, ouvre
  sa fiche) ou *Attribuer à…* (délègue à l'outil Fusionner pour le coller à un voisin choisi).

**Polygones adjacents aux attributs identiques** : un ensemble connexe (A touche B, B touche C…)
de polygones voisins portant exactement les mêmes attributs métier.
- Sur la catégorie entière : *Tout fusionner* (fusionne tous les groupes détectés, chacun pour
  son compte).
- Sur un groupe précis : *Fusionner le groupe* (réunit tous ses membres en une seule entité).
- Sur un membre précis du groupe (sous-ligne, un polygone du groupe) : *Modifier les attributs*
  (ouvre sa fiche avec surbrillance, si vous préférez corriger un attribut plutôt que fusionner).

**Incohérence essence / TFF** : essence et champs booléens du formulaire incompatibles (dominante
feuillu/conifère hors essence mixte, ouvert et fermé tous les deux vrais, CRJP/lande/non forêt mal
renseigné...).
- Sur une entité précise (il n'y a pas d'autre niveau) : *Modifier les attributs* (ouvre sa fiche
  avec surbrillance).

### Créer la couche temporaire

Crée (ou met à jour) une couche mémoire « Anomalies BD Forêt » reprenant toutes les anomalies
actuellement détectées, pour les visualiser ou les exporter. Cette couche est un instantané : elle
n'est pas maintenue automatiquement à jour au fil de vos corrections, il faut recréer la couche
pour l'actualiser.

## Navigation et alertes, dans la table attributaire

Trois boutons apparaissent dans la barre d'outils de la table attributaire de la couche de
travail dès qu'une fiche est ouverte :

- <img src="icon_precedent.svg" width="20"> **Fiche précédente** / <img src="icon_suivant.svg" width="20"> **Fiche suivante** : navigue
  dans l'historique des dix dernières fiches consultées, comme l'historique d'un navigateur.
- <img src="icon_recalculer_alertes.svg" width="20"> **Vérifier les alertes et recalculer** :
  recalcule le classement (`classement`, du plus prioritaire au moins prioritaire) et les
  indicateurs d'alertes (`nb_alertes`, `nb_alertes_vues`, `priorite_max`, `toutes_alertes_vues`)
  sur toute la couche.

Le compteur d'alertes se met normalement à jour tout seul après chaque modification géométrique
ou chaque case cochée « toutes alertes vues » ; ce bouton sert pour un recalcul complet à la
demande (par exemple après un import externe).
