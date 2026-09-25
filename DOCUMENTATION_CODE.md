# Reprise PI, documentation technique générée depuis le code

Ce document donne une carte à jour des fichiers, classes et fonctions : signature, numéro de ligne (dans cette version du plugin) et première ligne de la docstring. En cas de doute sur une fonction précise, se référer directement au fichier source à la ligne indiquée plutôt qu'à ce document. Pour une lecture guidée et plus pédagogique, commencer par `README_CODE.md`.

## Flux général

`__init__.py` → `commun_outils.py` → outil choisi → fonctions communes (`commun_edition.py`, `commun_topologie.py`, `commun_affichage.py`) → `commun_synchronisation_alertes.py` → rafraîchissement QGIS.

Le panneau Vérification suit : `verification_panneau.py` (UI) → `verification.py` (orchestration) → `verification_*.py` (règles). Les relations spatiales lourdes sont isolées dans `verification_tache_relations.py`, qui ne reçoit que des données sérialisées (WKB), jamais d'objets QGIS liés à un thread.

## Gestion des identifiants

Deux identifiants distincts coexistent sur chaque entité de `Bdfv3 Priorites`, avec des rôles et des origines différents.

### id_foret

`id_foret` est un identifiant de travail local, pas un identifiant définitif IGN (voir README section 0). C'est aussi la clé de la relation QGIS avec `Alertes Centroides` (voir README.md). Son nom est déclaré une seule fois (`CHAMP_ID_FORET`, `commun_parametres.py`), mais il est produit ou réparé à quatre endroits distincts :

- **Génération normale** : `commun_edition.py`, `prochain_id_foret(couche)` : plus grand `id_foret` existant + 1. Appelée directement par `creer_entite_nouvelle()` (même fichier, la fonction centrale de création d'entité utilisée par `edition_creer.py`, `edition_reporter_bdfv2.py` et `verification_entites_multiparties.py`), et directement par `verification_recouvrements.py` (`decouper_recouvrement`) et `verification_trous.py` (`_materialiser_trou`).
- **Cas particulier, Séparer** : `edition_separer.py`, `_attribuer_ids_foret_uniques()` / `_cle_id_foret()` : le moteur natif QGIS (`QgsVectorLayer.splitFeatures()`) copie l'`id_foret` du parent sur chaque morceau créé sans passer par `creer_entite_nouvelle()`. Ce fichier doit donc redistribuer après coup un `id_foret` neuf et unique à chaque morceau, avec sa propre logique de comparaison.
- **Repli, synchronisation des alertes** : `commun_synchronisation_alertes.py`, `attribuer_nouvel_id_foret(couche, fid)` : pas une création, une réparation. Si un point d'alerte tombe sur un polygone dont `id_foret` est vide, ce polygone reçoit `id_foret = fid` (le fid GeoPackage, pas un compteur).

### fid

`fid` est l'identifiant natif de la couche GeoPackage, attribué par le fournisseur GDAL/OGR, jamais par le plugin. Il est lui aussi purement local à ce fichier de travail, sans lien avec un référentiel IGN. Contrairement à `id_foret`, le plugin ne le génère ni ne le répare jamais : il se contente de le lire et de le protéger avant toute écriture.

- **Champs techniques** : `commun_edition.py`, `indices_fid(couche)` : retourne les index des champs servant de clé primaire au fournisseur.
- **Barrière contre les FID fantômes** : `commun_edition.py`, `fid_est_valide(couche, fid)` / `exiger_fid_valide(couche, fid, action=...)` : vérifie qu'un FID peut encore recevoir une écriture avant de l'utiliser (une entité supprimée dans le tampon d'édition est invalide immédiatement, une entité nouvellement créée est valide dès qu'elle est visible). C'est la vérification centrale appelée avant toute modification par FID.
- **Repli pour id_foret** : `commun_synchronisation_alertes.py`, `attribuer_nouvel_id_foret(couche, fid)` : quand `id_foret` manque, le `fid` de l'entité est recopié dedans (voir ci-dessus).

## Index par mot-clé

Pour retrouver rapidement tout ce qui concerne une règle ou une notion précise, quel que soit le fichier où c'est écrit.

- [Trous](#trous) (21)
- [Recouvrements](#recouvrements) (15)
- [Entités multiparties](#entités-multiparties) (8)
- [Polygones adjacents](#polygones-adjacents) (5)
- [Essence / TFF](#essence-tff) (4)
- [Surface](#surface) (15)
- [Alertes](#alertes) (56)
- [id_foret](#id_foret) (6)
- [Fusion](#fusion) (54)
- [Emprise](#emprise) (18)
- [Couches (recherche/validation)](#couches-recherchevalidation) (83)
- [Historique des fiches](#historique-des-fiches) (49)
- [Nettoyage automatique](#nettoyage-automatique) (19)
- [Relation QGIS](#relation-qgis) (14)
- [Session](#session) (16)
- [Compteurs](#compteurs) (43)
- [Géométrie](#géométrie) (64)
- [Formulaire](#formulaire) (52)
- [Thread / tâche de fond](#thread-tâche-de-fond) (10)
- [Surbrillance / hachures](#surbrillance-hachures) (33)

### Trous

- [`VerificationBdForetPlugin._finaliser_controle_complet(self, contexte, adjacent_pairs, overlaps)` (verification.py, ligne 1242)](#_finaliser_controle_completself-contexte-adjacent_pairs-overlaps-verificationpy-ligne-1242)
- [`VerificationBdForetPlugin._continuer_recherche_trous(self)` (verification.py, ligne 1278)](#_continuer_recherche_trousself-verificationpy-ligne-1278)
- [`VerificationBdForetPlugin._terminer_controle_avec_trous(self, donnees_finales, gaps)` (verification.py, ligne 1326)](#_terminer_controle_avec_trousself-donnees_finales-gaps-verificationpy-ligne-1326)
- [`_executer_recherche_trous(self, couche)` (verification_nettoyage_automatique.py, ligne 361)](#_executer_recherche_trousself-couche-verification_nettoyage_automatiquepy-ligne-361)
- [`_traiter_lot_trous(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 400)](#_traiter_lot_trousself-couche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-400)
- [`_fusionner_petite_geometrie_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_recouvrements.py, ligne 95)](#_fusionner_petite_geometrie_dans_voisincouche-petite_geometrie-fid_voisin-verification_recouvrementspy-ligne-95)
- [`nettoyer_micro_anomalies_locales(controleur, couche, geometrie_zone, fids_proteges=None)` (verification_recouvrements.py, ligne 122)](#nettoyer_micro_anomalies_localescontroleur-couche-geometrie_zone-fids_protegesnone-verification_recouvrementspy-ligne-122)
- [`mettre_a_jour_trous_locaux(self, rect)` (verification_trous.py, ligne 26)](#mettre_a_jour_trous_locauxself-rect-verification_trouspy-ligne-26)
- [`fusionner_parties_trous(geometries)` (verification_trous.py, ligne 62)](#fusionner_parties_trousgeometries-verification_trouspy-ligne-62)
- [`valider_trous_contre_couche_actuelle(self)` (verification_trous.py, ligne 89)](#valider_trous_contre_couche_actuelleself-verification_trouspy-ligne-89)
- [`preparer_recherche_trous(self, emprise_layer, feature_by_id, index)` (verification_trous.py, ligne 148)](#preparer_recherche_trousself-emprise_layer-feature_by_id-index-verification_trouspy-ligne-148)
- [`traiter_lot_recherche_trous(self, etat, taille_lot=1)` (verification_trous.py, ligne 202)](#traiter_lot_recherche_trousself-etat-taille_lot1-verification_trouspy-ligne-202)
- [`progression_recherche_trous(etat)` (verification_trous.py, ligne 207)](#progression_recherche_trousetat-verification_trouspy-ligne-207)
- [`finaliser_recherche_trous(etat)` (verification_trous.py, ligne 212)](#finaliser_recherche_trousetat-verification_trouspy-ligne-212)
- [`_preparer_geometrie_trou(self, couche, gap_index)` (verification_trous.py, ligne 250)](#_preparer_geometrie_trouself-couche-gap_index-verification_trouspy-ligne-250)
- [`_materialiser_trou(self, couche, geometrie, nom_commande)` (verification_trous.py, ligne 335)](#_materialiser_trouself-couche-geometrie-nom_commande-verification_trouspy-ligne-335)
- [`reboucher_trou(self, gap_index)` (verification_trous.py, ligne 383)](#reboucher_trouself-gap_index-vue_stable_pendant_modification-verification_trouspy-ligne-383)
- [`attribuer_trou(self, gap_index)` (verification_trous.py, ligne 435)](#attribuer_trouself-gap_index-vue_stable_pendant_modification-verification_trouspy-ligne-435)
- [`apres_fusion_trou(controleur, fids_operation, fid_reference)` (verification_trous.py, ligne 489)](#apres_fusion_troucontroleur-fids_operation-fid_reference-verification_trouspy-ligne-489)
- [`reboucher_tous_les_trous(self)` (verification_trous.py, ligne 500)](#reboucher_tous_les_trousself-verification_trouspy-ligne-500)
- [`ajouter_au_panneau(controleur, arbre, anomalies, emprise_trouvee, groupe=None)` (verification_trous.py, ligne 578)](#ajouter_au_panneaucontroleur-arbre-anomalies-emprise_trouvee-groupenone-verification_trouspy-ligne-578)

### Recouvrements

- [`redecouper_polygones_inclus(couche, geometrie_fusionnee, fids_fusionnes)` (commun_topologie.py, ligne 680)](#redecouper_polygones_incluscouche-geometrie_fusionnee-fids_fusionnes-commun_topologiepy-ligne-680)
- [Classe `ReporterBdFv2Plugin` (edition_reporter_bdfv2.py, ligne 185)](#classe-reporterbdfv2plugin-edition_reporter_bdfv2py-ligne-185)
- [`VerificationBdForetPlugin._geometries_recouvrements_depuis_wkb(cls, recouvrements)` (verification.py, ligne 1234)](#_geometries_recouvrements_depuis_wkbcls-recouvrements-classmethod-verificationpy-ligne-1234)
- [`VerificationBdForetPlugin._chercher_relations_voisines(self, features, feature_by_id, field_map, index)` (verification.py, ligne 1450)](#_chercher_relations_voisinesself-features-feature_by_id-field_map-index-verificationpy-ligne-1450)
- [`VerificationBdForetPlugin._recalculer_relations_locales(self, affected)` (verification.py, ligne 1679)](#_recalculer_relations_localesself-affected-verificationpy-ligne-1679)
- [`_traiter_lot_recouvrements(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 450)](#_traiter_lot_recouvrementscouche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-450)
- [`recouvrement_depuis_intersection(intersection)` (verification_recouvrements.py, ligne 36)](#recouvrement_depuis_intersectionintersection-verification_recouvrementspy-ligne-36)
- [`intersection_recouvrement(geom_a, geom_b)` (verification_recouvrements.py, ligne 51)](#intersection_recouvrementgeom_a-geom_b-verification_recouvrementspy-ligne-51)
- [`corriger_micro_recouvrement(geom_a, geom_b)` (verification_recouvrements.py, ligne 62)](#corriger_micro_recouvrementgeom_a-geom_b-verification_recouvrementspy-ligne-62)
- [`_fusionner_petite_geometrie_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_recouvrements.py, ligne 95)](#_fusionner_petite_geometrie_dans_voisincouche-petite_geometrie-fid_voisin-verification_recouvrementspy-ligne-95)
- [`nettoyer_micro_anomalies_locales(controleur, couche, geometrie_zone, fids_proteges=None)` (verification_recouvrements.py, ligne 122)](#nettoyer_micro_anomalies_localescontroleur-couche-geometrie_zone-fids_protegesnone-verification_recouvrementspy-ligne-122)
- [`choisir_fid_attribution_recouvrement(controleur, couche, fids, entites)` (verification_recouvrements.py, ligne 255)](#choisir_fid_attribution_recouvrementcontroleur-couche-fids-entites-verification_recouvrementspy-ligne-255)
- [`attribuer_recouvrement(self, fids_recouvrement)` (verification_recouvrements.py, ligne 288)](#attribuer_recouvrementself-fids_recouvrement-vue_stable_pendant_modification-verification_recouvrementspy-ligne-288)
- [`decouper_recouvrement(self, fids_recouvrement)` (verification_recouvrements.py, ligne 518)](#decouper_recouvrementself-fids_recouvrement-vue_stable_pendant_modification-verification_recouvrementspy-ligne-518)
- [`ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_recouvrements.py, ligne 756)](#ajouter_au_panneaucontroleur-arbre-anomalies-groupenone-verification_recouvrementspy-ligne-756)

### Entités multiparties

- [`extraire_parties_multipartie_brutes(geometrie)` (commun_topologie.py, ligne 855)](#extraire_parties_multipartie_brutesgeometrie-commun_topologiepy-ligne-855)
- [`_traiter_lot_parties_isolees(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 503)](#_traiter_lot_parties_isoleescouche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-503)
- [`detecter(feature)` (verification_entites_multiparties.py, ligne 79)](#detecterfeature-verification_entites_multipartiespy-ligne-79)
- [`peut_fusionner_multipartie(self, fid)` (verification_entites_multiparties.py, ligne 87)](#peut_fusionner_multipartieself-fid-verification_entites_multipartiespy-ligne-87)
- [`fusionner_multipartie(self, fid)` (verification_entites_multiparties.py, ligne 124)](#fusionner_multipartieself-fid-vue_stable_pendant_modification-verification_entites_multipartiespy-ligne-124)
- [`separer_multipartie(self, fid)` (verification_entites_multiparties.py, ligne 230)](#separer_multipartieself-fid-vue_stable_pendant_modification-verification_entites_multipartiespy-ligne-230)
- [`attribuer_partie_multipartie(self, fid, index_partie)` (verification_entites_multiparties.py, ligne 359)](#attribuer_partie_multipartieself-fid-index_partie-vue_stable_pendant_modification-verification_entites_multipartiespy-ligne-359)
- [`ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_entites_multiparties.py, ligne 490)](#ajouter_au_panneaucontroleur-arbre-anomalies-groupenone-verification_entites_multipartiespy-ligne-490)

### Polygones adjacents

- [`regrouper_adjacences(adjacent_pairs)` (verification_polygones_adjacents_attributs_identiques.py, ligne 15)](#regrouper_adjacencesadjacent_pairs-verification_polygones_adjacents_attributs_identiquespy-ligne-15)
- [`detail_adjacence(feature, field_map)` (verification_polygones_adjacents_attributs_identiques.py, ligne 61)](#detail_adjacencefeature-field_map-verification_polygones_adjacents_attributs_identiquespy-ligne-61)
- [`fusionner_groupe_adjacents(self, fids_groupe, silencieux=False, planifier_refresh=True)` (verification_polygones_adjacents_attributs_identiques.py, ligne 69)](#fusionner_groupe_adjacentsself-fids_groupe-silencieuxfalse-planifier_refreshtrue-vue_stable_pendant_modification-verification_polygones_adjacents_attributs_identiquespy-ligne-69)
- [`fusionner_tous_groupes_adjacents(self)` (verification_polygones_adjacents_attributs_identiques.py, ligne 153)](#fusionner_tous_groupes_adjacentsself-verification_polygones_adjacents_attributs_identiquespy-ligne-153)
- [`ajouter_au_panneau(controleur, arbre, groupes, groupe=None)` (verification_polygones_adjacents_attributs_identiques.py, ligne 248)](#ajouter_au_panneaucontroleur-arbre-groupes-groupenone-verification_polygones_adjacents_attributs_identiquespy-ligne-248)

### Essence / TFF

- [`FusionnerBdForetPlugin._libelle_choix_attributs(self, entite)` (edition_fusionner.py, ligne 620)](#_libelle_choix_attributsself-entite-edition_fusionnerpy-ligne-620)
- [`libelle_entite_essence_surface(couche, entite)` (verification_recouvrements.py, ligne 233)](#libelle_entite_essence_surfacecouche-entite-verification_recouvrementspy-ligne-233)
- [`detecter(feature, field_map)` (verification_coherence_essence_tff.py, ligne 26)](#detecterfeature-field_map-verification_coherence_essence_tffpy-ligne-26)
- [`ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_coherence_essence_tff.py, ligne 129)](#ajouter_au_panneaucontroleur-arbre-anomalies-groupenone-verification_coherence_essence_tffpy-ligne-129)

### Surface

- [`surface_ha(geometrie)` (commun_edition.py, ligne 39)](#surface_hageometrie-commun_editionpy-ligne-39)
- [`nettoyer_pointes_interieures(anneau)` (commun_topologie.py, ligne 917)](#nettoyer_pointes_interieuresanneau-commun_topologiepy-ligne-917)
- [Classe `CreerPolygonePlugin` (edition_creer.py, ligne 109)](#classe-creerpolygoneplugin-edition_creerpy-ligne-109)
- [`CreerPolygonePlugin._appliquer_creation(self, preparation)` (edition_creer.py, ligne 403)](#_appliquer_creationself-preparation-vue_stable_pendant_modification-edition_creerpy-ligne-403)
- [`SeparerPolygonePlugin._recalculer_surfaces(self, fids)` (edition_separer.py, ligne 724)](#_recalculer_surfacesself-fids-edition_separerpy-ligne-724)
- [`FusionnerBdForetPlugin._libelle_choix_attributs(self, entite)` (edition_fusionner.py, ligne 620)](#_libelle_choix_attributsself-entite-edition_fusionnerpy-ligne-620)
- [`RemodelerBdForetPlugin._appliquer_remodelage(self, nouvelles, zone_sync)` (edition_remodeler.py, ligne 562)](#_appliquer_remodelageself-nouvelles-zone_sync-vue_stable_pendant_modification-edition_remodelerpy-ligne-562)
- [`ReporterBdFv2Plugin._appliquer_report(self, preparation)` (edition_reporter_bdfv2.py, ligne 696)](#_appliquer_reportself-preparation-vue_stable_pendant_modification-edition_reporter_bdfv2py-ligne-696)
- [`VerificationBdForetPlugin._creer_mesure_surface(self)` (verification.py, ligne 1441)](#_creer_mesure_surfaceself-verificationpy-ligne-1441)
- [`_traiter_lot_petites_surfaces(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 326)](#_traiter_lot_petites_surfacescouche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-326)
- [`detecter(feature, mesure_surface)` (verification_surface05ha.py, ligne 14)](#detecterfeature-mesure_surface-verification_surface05hapy-ligne-14)
- [`ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_surface05ha.py, ligne 211)](#ajouter_au_panneaucontroleur-arbre-anomalies-groupenone-verification_surface05hapy-ligne-211)
- [`libelle_entite_essence_surface(couche, entite)` (verification_recouvrements.py, ligne 233)](#libelle_entite_essence_surfacecouche-entite-verification_recouvrementspy-ligne-233)
- [`ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_recouvrements.py, ligne 756)](#ajouter_au_panneaucontroleur-arbre-anomalies-groupenone-verification_recouvrementspy-ligne-756)
- [`valider_trous_contre_couche_actuelle(self)` (verification_trous.py, ligne 89)](#valider_trous_contre_couche_actuelleself-verification_trouspy-ligne-89)

### Alertes

- [`trouver_couche_alertes(iface=None)` (commun_couches.py, ligne 161)](#trouver_couche_alertesifacenone-commun_couchespy-ligne-161)
- [`marquer_edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 57)](#marquer_edition_alertes_ouverte_par_plugincouche-commun_synchronisation_alertespy-ligne-57)
- [`edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 64)](#edition_alertes_ouverte_par_plugincouche-commun_synchronisation_alertespy-ligne-64)
- [`oublier_edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 71)](#oublier_edition_alertes_ouverte_par_plugincouche-commun_synchronisation_alertespy-ligne-71)
- [Classe `ResultatSynchronisation` (commun_synchronisation_alertes.py, ligne 121)](#classe-resultatsynchronisation-commun_synchronisation_alertespy-ligne-121)
- [`_trouver_couche_alertes_associee(couche_parent, iface=None)` (commun_synchronisation_alertes.py, ligne 334)](#_trouver_couche_alertes_associeecouche_parent-ifacenone-commun_synchronisation_alertespy-ligne-334)
- [`trouver_couche_alertes_associee(couche_parent, iface=None)` (commun_synchronisation_alertes.py, ligne 373)](#trouver_couche_alertes_associeecouche_parent-ifacenone-commun_synchronisation_alertespy-ligne-373)
- [`_widgets_relation_alertes_ouverts(iface)` (commun_synchronisation_alertes.py, ligne 394)](#_widgets_relation_alertes_ouvertsiface-commun_synchronisation_alertespy-ligne-394)
- [`rafraichir_vue_relation_alertes(iface, couche_parent, couche_alertes, fids_parents)` (commun_synchronisation_alertes.py, ligne 430)](#rafraichir_vue_relation_alertesiface-couche_parent-couche_alertes-fids_parents-commun_synchronisation_alertespy-ligne-430)
- [`synchroniser_zone(iface, couche_parent, geometrie_zone, nom_commande='Synchroniser les alertes')` (commun_synchronisation_alertes.py, ligne 475)](#synchroniser_zoneiface-couche_parent-geometrie_zone-nom_commandesynchroniser-les-alertes-commun_synchronisation_alertespy-ligne-475)
- [Classe `CompteurAlertes` (commun_compteur_alertes.py, ligne 112)](#classe-compteuralertes-commun_compteur_alertespy-ligne-112)
- [`CompteurAlertes.__init__(self, iface, historique=None)` (commun_compteur_alertes.py, ligne 134)](#__init__self-iface-historiquenone-commun_compteur_alertespy-ligne-134)
- [`CompteurAlertes.initGui(self)` (commun_compteur_alertes.py, ligne 202)](#initguiself-commun_compteur_alertespy-ligne-202)
- [`CompteurAlertes.unload(self)` (commun_compteur_alertes.py, ligne 218)](#unloadself-commun_compteur_alertespy-ligne-218)
- [`CompteurAlertes._programmer_connexion(self, *args)` (commun_compteur_alertes.py, ligne 242)](#_programmer_connexionself-args-commun_compteur_alertespy-ligne-242)
- [`CompteurAlertes._projet_vide(self, *args)` (commun_compteur_alertes.py, ligne 247)](#_projet_videself-args-commun_compteur_alertespy-ligne-247)
- [`CompteurAlertes.connecter_couches(self)` (commun_compteur_alertes.py, ligne 254)](#connecter_couchesself-commun_compteur_alertespy-ligne-254)
- [`CompteurAlertes.deconnecter_couches(self)` (commun_compteur_alertes.py, ligne 340)](#deconnecter_couchesself-commun_compteur_alertespy-ligne-340)
- [`CompteurAlertes.suspendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 397)](#suspendre_synchronisation_geometriqueself-commun_compteur_alertespy-ligne-397)
- [`CompteurAlertes.reprendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 411)](#reprendre_synchronisation_geometriqueself-commun_compteur_alertespy-ligne-411)
- [`CompteurAlertes._synchronisation_geometrique_suspendue(self)` (commun_compteur_alertes.py, ligne 419)](#_synchronisation_geometrique_suspendueself-commun_compteur_alertespy-ligne-419)
- [`CompteurAlertes.synchroniser_modification_geometrique(self, couche_parent, geometrie_zone, nom_commande)` (commun_compteur_alertes.py, ligne 422)](#synchroniser_modification_geometriqueself-couche_parent-geometrie_zone-nom_commande-commun_compteur_alertespy-ligne-422)
- [`CompteurAlertes._trouver_relation(self)` (commun_compteur_alertes.py, ligne 466)](#_trouver_relationself-commun_compteur_alertespy-ligne-466)
- [`CompteurAlertes._avant_enregistrement_parent(self, *args)` (commun_compteur_alertes.py, ligne 485)](#_avant_enregistrement_parentself-args-commun_compteur_alertespy-ligne-485)
- [`CompteurAlertes._terminer_garde_commit_parent(self)` (commun_compteur_alertes.py, ligne 495)](#_terminer_garde_commit_parentself-commun_compteur_alertespy-ligne-495)
- [`CompteurAlertes._reinitialiser_suivi_apres_commit_parent(self)` (commun_compteur_alertes.py, ligne 500)](#_reinitialiser_suivi_apres_commit_parentself-commun_compteur_alertespy-ligne-500)
- [`CompteurAlertes._apres_enregistrement_parent(self, *args)` (commun_compteur_alertes.py, ligne 510)](#_apres_enregistrement_parentself-args-commun_compteur_alertespy-ligne-510)
- [`CompteurAlertes._emprise_originale_parent(self, fid)` (commun_compteur_alertes.py, ligne 590)](#_emprise_originale_parentself-fid-commun_compteur_alertespy-ligne-590)
- [`CompteurAlertes._fusionner_rectangles(rectangle_a, rectangle_b)` (commun_compteur_alertes.py, ligne 623)](#_fusionner_rectanglesrectangle_a-rectangle_b-staticmethod-commun_compteur_alertespy-ligne-623)
- [`CompteurAlertes._commande_parent_demarre(self, _texte=None)` (commun_compteur_alertes.py, ligne 631)](#_commande_parent_demarreself-_textenone-commun_compteur_alertespy-ligne-631)
- [`CompteurAlertes._commande_parent_terminee(self)` (commun_compteur_alertes.py, ligne 648)](#_commande_parent_termineeself-commun_compteur_alertespy-ligne-648)
- [`CompteurAlertes._commande_parent_detruite(self)` (commun_compteur_alertes.py, ligne 670)](#_commande_parent_detruiteself-commun_compteur_alertespy-ligne-670)
- [`CompteurAlertes._memoriser_zone_geometrique(self, rectangle)` (commun_compteur_alertes.py, ligne 691)](#_memoriser_zone_geometriqueself-rectangle-commun_compteur_alertespy-ligne-691)
- [`CompteurAlertes._terminer_recalcul_hors_commande(self)` (commun_compteur_alertes.py, ligne 721)](#_terminer_recalcul_hors_commandeself-commun_compteur_alertespy-ligne-721)
- [`CompteurAlertes._executer_recalcul_geometrique_differe(self, rectangle, *_args)` (commun_compteur_alertes.py, ligne 735)](#_executer_recalcul_geometrique_differeself-rectangle-_args-commun_compteur_alertespy-ligne-735)
- [`CompteurAlertes._geometrie_parent_modifiee(self, fid, geometrie)` (commun_compteur_alertes.py, ligne 786)](#_geometrie_parent_modifieeself-fid-geometrie-commun_compteur_alertespy-ligne-786)
- [`CompteurAlertes._entite_parent_ajoutee(self, fid)` (commun_compteur_alertes.py, ligne 816)](#_entite_parent_ajouteeself-fid-commun_compteur_alertespy-ligne-816)
- [`CompteurAlertes._entite_parent_supprimee(self, fid)` (commun_compteur_alertes.py, ligne 833)](#_entite_parent_supprimeeself-fid-commun_compteur_alertespy-ligne-833)
- [`CompteurAlertes._attribut_alerte_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 865)](#_attribut_alerte_modifieself-fid-index_champ-nouvelle_valeur-commun_compteur_alertespy-ligne-865)
- [`CompteurAlertes._attribut_parent_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 890)](#_attribut_parent_modifieself-fid-index_champ-nouvelle_valeur-commun_compteur_alertespy-ligne-890)
- [`CompteurAlertes._commande_edition_active(couche)` (commun_compteur_alertes.py, ligne 938)](#_commande_edition_activecouche-staticmethod-commun_compteur_alertespy-ligne-938)
- [`CompteurAlertes._traiter_commandes_parent_en_attente(self)` (commun_compteur_alertes.py, ligne 947)](#_traiter_commandes_parent_en_attenteself-commun_compteur_alertespy-ligne-947)
- [`CompteurAlertes._traiter_toutes_alertes_vues_parent(self, fid_parent, valeur_demandee)` (commun_compteur_alertes.py, ligne 981)](#_traiter_toutes_alertes_vues_parentself-fid_parent-valeur_demandee-commun_compteur_alertespy-ligne-981)
- [`CompteurAlertes._marquer_toutes_alertes_vues(self, fid_parent)` (commun_compteur_alertes.py, ligne 1021)](#_marquer_toutes_alertes_vuesself-fid_parent-commun_compteur_alertespy-ligne-1021)
- [`CompteurAlertes.recalculer_tous_les_compteurs(self)` (commun_compteur_alertes.py, ligne 1090)](#recalculer_tous_les_compteursself-vue_stable_pendant_modification-commun_compteur_alertespy-ligne-1090)
- [`CompteurAlertes._cle_identifiant(valeur)` (commun_compteur_alertes.py, ligne 1704)](#_cle_identifiantvaleur-staticmethod-commun_compteur_alertespy-ligne-1704)
- [`CompteurAlertes._valeurs_compteur_identiques(self, actuelle, attendue, booleen=False)` (commun_compteur_alertes.py, ligne 1725)](#_valeurs_compteur_identiquesself-actuelle-attendue-booleenfalse-commun_compteur_alertespy-ligne-1725)
- [`CompteurAlertes._recalculer_parent(self, fid_alerte)` (commun_compteur_alertes.py, ligne 1737)](#_recalculer_parentself-fid_alerte-commun_compteur_alertespy-ligne-1737)
- [`CompteurAlertes._recalculer_parent_direct(self, fid_parent)` (commun_compteur_alertes.py, ligne 1757)](#_recalculer_parent_directself-fid_parent-commun_compteur_alertespy-ligne-1757)
- [`CompteurAlertes._convertir_en_booleen(valeur)` (commun_compteur_alertes.py, ligne 1836)](#_convertir_en_booleenvaleur-staticmethod-commun_compteur_alertespy-ligne-1836)
- [`CompteurAlertes._rafraichir_formulaire_parent(self, fid_parent)` (commun_compteur_alertes.py, ligne 1846)](#_rafraichir_formulaire_parentself-fid_parent-commun_compteur_alertespy-ligne-1846)
- [`CompteurAlertes._avertir(self, message)` (commun_compteur_alertes.py, ligne 1856)](#_avertirself-message-commun_compteur_alertespy-ligne-1856)
- [`HistoriqueFormulaires.definir_recalcul_alertes(self, callback)` (commun_historique_formulaires.py, ligne 515)](#definir_recalcul_alertesself-callback-commun_historique_formulairespy-ligne-515)
- [`HistoriqueFormulaires.recalculer_alertes(self)` (commun_historique_formulaires.py, ligne 527)](#recalculer_alertesself-commun_historique_formulairespy-ligne-527)
- [`RemodelerBdForetPlugin._appliquer_remodelage(self, nouvelles, zone_sync)` (edition_remodeler.py, ligne 562)](#_appliquer_remodelageself-nouvelles-zone_sync-vue_stable_pendant_modification-edition_remodelerpy-ligne-562)
- [`_traiter_lot_synchronisation_alertes(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 756)](#_traiter_lot_synchronisation_alertesself-couche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-756)

### id_foret

- [`prochain_id_foret(couche)` (commun_edition.py, ligne 66)](#prochain_id_foretcouche-commun_editionpy-ligne-66)
- [`attribuer_nouvel_id_foret(couche, fid)` (commun_synchronisation_alertes.py, ligne 143)](#attribuer_nouvel_id_foretcouche-fid-commun_synchronisation_alertespy-ligne-143)
- [`_expression_ids_foret(nom_champ, valeurs)` (commun_synchronisation_alertes.py, ligne 296)](#_expression_ids_foretnom_champ-valeurs-commun_synchronisation_alertespy-ligne-296)
- [`CompteurAlertes._cle_identifiant(valeur)` (commun_compteur_alertes.py, ligne 1704)](#_cle_identifiantvaleur-staticmethod-commun_compteur_alertespy-ligne-1704)
- [`SeparerPolygonePlugin._cle_id_foret(valeur)` (edition_separer.py, ligne 669)](#_cle_id_foretvaleur-staticmethod-edition_separerpy-ligne-669)
- [`SeparerPolygonePlugin._attribuer_ids_foret_uniques(self, nouveaux_fids)` (edition_separer.py, ligne 684)](#_attribuer_ids_foret_uniquesself-nouveaux_fids-edition_separerpy-ligne-684)

### Fusion

- [`nettoyer_contacts_ponctuels(geometrie)` (commun_topologie.py, ligne 491)](#nettoyer_contacts_ponctuelsgeometrie-commun_topologiepy-ligne-491)
- [`fusionner_geometries(geometries)` (commun_topologie.py, ligne 609)](#fusionner_geometriesgeometries-commun_topologiepy-ligne-609)
- [`preparer_fusion_protegee(couche, geometries, fids_fusionnes)` (commun_topologie.py, ligne 738)](#preparer_fusion_protegeecouche-geometries-fids_fusionnes-commun_topologiepy-ligne-738)
- [`CompteurAlertes._fusionner_rectangles(rectangle_a, rectangle_b)` (commun_compteur_alertes.py, ligne 623)](#_fusionner_rectanglesrectangle_a-rectangle_b-staticmethod-commun_compteur_alertespy-ligne-623)
- [`HistoriqueFormulaires.restaurer_contexte_visuel_couche(self, couche, contexte, fid_remplacement=None, restaurer_fid=True)` (commun_historique_formulaires.py, ligne 1122)](#restaurer_contexte_visuel_coucheself-couche-contexte-fid_remplacementnone-restaurer_fidtrue-commun_historique_formulairespy-ligne-1122)
- [Classe `EchecFusionNative(RuntimeError)` (edition_fusionner.py, ligne 94)](#classe-echecfusionnativeruntimeerror-edition_fusionnerpy-ligne-94)
- [Classe `_OutilSelectionFusion(QgsMapToolIdentify)` (edition_fusionner.py, ligne 98)](#classe-_outilselectionfusionqgsmaptoolidentify-edition_fusionnerpy-ligne-98)
- [`_OutilSelectionFusion.__init__(self, canvas, plugin)` (edition_fusionner.py, ligne 101)](#__init__self-canvas-plugin-edition_fusionnerpy-ligne-101)
- [`_OutilSelectionFusion.canvasReleaseEvent(self, event)` (edition_fusionner.py, ligne 106)](#canvasreleaseeventself-event-edition_fusionnerpy-ligne-106)
- [Classe `FusionnerBdForetPlugin` (edition_fusionner.py, ligne 117)](#classe-fusionnerbdforetplugin-edition_fusionnerpy-ligne-117)
- [`FusionnerBdForetPlugin.__init__(self, iface, manager=None)` (edition_fusionner.py, ligne 122)](#__init__self-iface-managernone-edition_fusionnerpy-ligne-122)
- [`FusionnerBdForetPlugin.initGui(self)` (edition_fusionner.py, ligne 145)](#initguiself-edition_fusionnerpy-ligne-145)
- [`FusionnerBdForetPlugin.unload(self)` (edition_fusionner.py, ligne 154)](#unloadself-edition_fusionnerpy-ligne-154)
- [`FusionnerBdForetPlugin._basculer_outil(self, coche)` (edition_fusionner.py, ligne 165)](#_basculer_outilself-coche-edition_fusionnerpy-ligne-165)
- [`FusionnerBdForetPlugin._activer(self)` (edition_fusionner.py, ligne 168)](#_activerself-edition_fusionnerpy-ligne-168)
- [`FusionnerBdForetPlugin._edition_demarree(self, couche)` (edition_fusionner.py, ligne 192)](#_edition_demarreeself-couche-edition_fusionnerpy-ligne-192)
- [`FusionnerBdForetPlugin._desactiver(self)` (edition_fusionner.py, ligne 201)](#_desactiverself-edition_fusionnerpy-ligne-201)
- [`FusionnerBdForetPlugin.desactiver_pour_autre_outil(self)` (edition_fusionner.py, ligne 216)](#desactiver_pour_autre_outilself-edition_fusionnerpy-ligne-216)
- [`FusionnerBdForetPlugin._outil_carte_change(self, nouvel_outil, ancien_outil=None)` (edition_fusionner.py, ligne 219)](#_outil_carte_changeself-nouvel_outil-ancien_outilnone-edition_fusionnerpy-ligne-219)
- [`FusionnerBdForetPlugin.basculer_entite_cliquee(self, x, y, ctrl_appuye)` (edition_fusionner.py, ligne 230)](#basculer_entite_cliqueeself-x-y-ctrl_appuye-edition_fusionnerpy-ligne-230)
- [`FusionnerBdForetPlugin._retirer_fid(self, fid)` (edition_fusionner.py, ligne 239)](#_retirer_fidself-fid-edition_fusionnerpy-ligne-239)
- [`FusionnerBdForetPlugin.effacer_selection_visuelle(self, rafraichir=True)` (edition_fusionner.py, ligne 242)](#effacer_selection_visuelleself-rafraichirtrue-edition_fusionnerpy-ligne-242)
- [`FusionnerBdForetPlugin.activer_avec_fids(self, fids, ouvrir_formulaire_apres=True, finaliser_au_deuxieme_clic=False, callback_fin=None)` (edition_fusionner.py, ligne 249)](#activer_avec_fidsself-fids-ouvrir_formulaire_aprestrue-finaliser_au_deuxieme_clicfalse-callback_finnone-edition_fusionnerpy-ligne-249)
- [`FusionnerBdForetPlugin.fusionner_selection(self)` (edition_fusionner.py, ligne 311)](#fusionner_selectionself-sans_reentrance-edition_fusionnerpy-ligne-311)
- [`FusionnerBdForetPlugin.fusionner_fids_direct(self, fids, fid_reference=None, ouvrir_formulaire=False, nom_commande=None, nettoyer_parasites=False)` (edition_fusionner.py, ligne 421)](#fusionner_fids_directself-fids-fid_referencenone-ouvrir_formulairefalse-nom_commandenone-nettoyer_parasitesfalse-edition_fusionnerpy-ligne-421)
- [`FusionnerBdForetPlugin._preparer_fusion(self, fids=None)` (edition_fusionner.py, ligne 511)](#_preparer_fusionself-fidsnone-edition_fusionnerpy-ligne-511)
- [`FusionnerBdForetPlugin._choisir_fid_reference(self, fids, entites)` (edition_fusionner.py, ligne 563)](#_choisir_fid_referenceself-fids-entites-edition_fusionnerpy-ligne-563)
- [`FusionnerBdForetPlugin._libelle_choix_attributs(self, entite)` (edition_fusionner.py, ligne 620)](#_libelle_choix_attributsself-entite-edition_fusionnerpy-ligne-620)
- [`FusionnerBdForetPlugin._choisir_fid_technique_stable(fids, fid_source_attributs)` (edition_fusionner.py, ligne 644)](#_choisir_fid_technique_stablefids-fid_source_attributs-staticmethod-edition_fusionnerpy-ligne-644)
- [`FusionnerBdForetPlugin._fid_fiche_active(fids_fusionnes, contexte_formulaire)` (edition_fusionner.py, ligne 662)](#_fid_fiche_activefids_fusionnes-contexte_formulaire-staticmethod-edition_fusionnerpy-ligne-662)
- [`FusionnerBdForetPlugin._appliquer_fusion(self, fid_reference, geometrie, autres_fids, geometrie_zone, fid_source_attributs, nom_commande=None, fid_classement=None)` (edition_fusionner.py, ligne 673)](#_appliquer_fusionself-fid_reference-geometrie-autres_fids-geometrie_zone-fid_source_attributs-nom_commandenone-fid_classementnone-vue_stable_pendant_modification-edition_fusionnerpy-ligne-673)
- [`FusionnerBdForetPlugin._fusionner_avec_moteur_qgis(self, fid_reference, autres_fids, attributs, geometrie)` (edition_fusionner.py, ligne 759)](#_fusionner_avec_moteur_qgisself-fid_reference-autres_fids-attributs-geometrie-edition_fusionnerpy-ligne-759)
- [`FusionnerBdForetPlugin._ouvrir_formulaire(self, fid_reference)` (edition_fusionner.py, ligne 794)](#_ouvrir_formulaireself-fid_reference-edition_fusionnerpy-ligne-794)
- [`FusionnerBdForetPlugin._avertir(self, message)` (edition_fusionner.py, ligne 803)](#_avertirself-message-edition_fusionnerpy-ligne-803)
- [`_fusionner_localement(grande_geometrie, petite_geometrie)` (edition_reporter_bdfv2.py, ligne 104)](#_fusionner_localementgrande_geometrie-petite_geometrie-edition_reporter_bdfv2py-ligne-104)
- [Classe `_OutilSelectionReport(QgsMapToolIdentify)` (edition_reporter_bdfv2.py, ligne 167)](#classe-_outilselectionreportqgsmaptoolidentify-edition_reporter_bdfv2py-ligne-167)
- [`ReporterBdFv2Plugin._recoller_parties_isolees(self, pieces, fids_a_exclure)` (edition_reporter_bdfv2.py, ligne 610)](#_recoller_parties_isoleesself-pieces-fids_a_exclure-edition_reporter_bdfv2py-ligne-610)
- [`_fusionner_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_nettoyage_automatique.py, ligne 301)](#_fusionner_dans_voisincouche-petite_geometrie-fid_voisin-verification_nettoyage_automatiquepy-ligne-301)
- [`_traiter_lot_petites_surfaces(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 326)](#_traiter_lot_petites_surfacescouche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-326)
- [`finaliser_nettoyage(etat)` (verification_nettoyage_automatique.py, ligne 856)](#finaliser_nettoyageetat-verification_nettoyage_automatiquepy-ligne-856)
- [`fusionner_avec(controleur, fid)` (verification_surface05ha.py, ligne 55)](#fusionner_aveccontroleur-fid-vue_stable_pendant_modification-verification_surface05hapy-ligne-55)
- [`apres_fusion(controleur, fids_operation, fid_reference)` (verification_surface05ha.py, ligne 122)](#apres_fusioncontroleur-fids_operation-fid_reference-verification_surface05hapy-ligne-122)
- [`fusionner_tous_avec_meilleur_voisin(controleur)` (verification_surface05ha.py, ligne 144)](#fusionner_tous_avec_meilleur_voisincontroleur-verification_surface05hapy-ligne-144)
- [`_aligner_parties(parties)` (verification_entites_multiparties.py, ligne 32)](#_aligner_partiesparties-verification_entites_multipartiespy-ligne-32)
- [`_message_echec_fusion_parties(parties_alignees)` (verification_entites_multiparties.py, ligne 58)](#_message_echec_fusion_partiesparties_alignees-verification_entites_multipartiespy-ligne-58)
- [`peut_fusionner_multipartie(self, fid)` (verification_entites_multiparties.py, ligne 87)](#peut_fusionner_multipartieself-fid-verification_entites_multipartiespy-ligne-87)
- [`fusionner_multipartie(self, fid)` (verification_entites_multiparties.py, ligne 124)](#fusionner_multipartieself-fid-vue_stable_pendant_modification-verification_entites_multipartiespy-ligne-124)
- [`attribuer_partie_multipartie(self, fid, index_partie)` (verification_entites_multiparties.py, ligne 359)](#attribuer_partie_multipartieself-fid-index_partie-vue_stable_pendant_modification-verification_entites_multipartiespy-ligne-359)
- [`_fusionner_petite_geometrie_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_recouvrements.py, ligne 95)](#_fusionner_petite_geometrie_dans_voisincouche-petite_geometrie-fid_voisin-verification_recouvrementspy-ligne-95)
- [`fusionner_parties_trous(geometries)` (verification_trous.py, ligne 62)](#fusionner_parties_trousgeometries-verification_trouspy-ligne-62)
- [`attribuer_trou(self, gap_index)` (verification_trous.py, ligne 435)](#attribuer_trouself-gap_index-vue_stable_pendant_modification-verification_trouspy-ligne-435)
- [`apres_fusion_trou(controleur, fids_operation, fid_reference)` (verification_trous.py, ligne 489)](#apres_fusion_troucontroleur-fids_operation-fid_reference-verification_trouspy-ligne-489)
- [`fusionner_groupe_adjacents(self, fids_groupe, silencieux=False, planifier_refresh=True)` (verification_polygones_adjacents_attributs_identiques.py, ligne 69)](#fusionner_groupe_adjacentsself-fids_groupe-silencieuxfalse-planifier_refreshtrue-vue_stable_pendant_modification-verification_polygones_adjacents_attributs_identiquespy-ligne-69)
- [`fusionner_tous_groupes_adjacents(self)` (verification_polygones_adjacents_attributs_identiques.py, ligne 153)](#fusionner_tous_groupes_adjacentsself-verification_polygones_adjacents_attributs_identiquespy-ligne-153)

### Emprise

- [`trouver_couche_emprise()` (commun_couches.py, ligne 76)](#trouver_couche_emprise-commun_couchespy-ligne-76)
- [`ProtectionVueCarte._restaurer_emprise(self, emprise)` (commun_protection_vue.py, ligne 145)](#_restaurer_empriseself-emprise-commun_protection_vuepy-ligne-145)
- [`_rectangles_equivalents(a, b)` (commun_protection_vue.py, ligne 192)](#_rectangles_equivalentsa-b-commun_protection_vuepy-ligne-192)
- [`construire_geometrie_emprise_locale(couche_emprise, rectangle_cible, crs_cible=None)` (commun_topologie.py, ligne 395)](#construire_geometrie_emprise_localecouche_emprise-rectangle_cible-crs_ciblenone-commun_topologiepy-ligne-395)
- [`CompteurAlertes._emprise_originale_parent(self, fid)` (commun_compteur_alertes.py, ligne 590)](#_emprise_originale_parentself-fid-commun_compteur_alertespy-ligne-590)
- [`CompteurAlertes._geometrie_parent_modifiee(self, fid, geometrie)` (commun_compteur_alertes.py, ligne 786)](#_geometrie_parent_modifieeself-fid-geometrie-commun_compteur_alertespy-ligne-786)
- [`zoomer_sur_emprise(canvas, emprise, facteur=1.25)` (verification.py, ligne 69)](#zoomer_sur_emprisecanvas-emprise-facteur125-verificationpy-ligne-69)
- [`VerificationBdForetPlugin._trouver_couche_emprise()` (verification.py, ligne 539)](#_trouver_couche_emprise-staticmethod-verificationpy-ligne-539)
- [`VerificationBdForetPlugin._ajouter_emprise(emprise, emprise_initialisee, nouvelle_emprise)` (verification.py, ligne 1635)](#_ajouter_empriseemprise-emprise_initialisee-nouvelle_emprise-staticmethod-verificationpy-ligne-1635)
- [`VerificationBdForetPlugin._emprise_vers_tuple(rectangle)` (verification.py, ligne 2001)](#_emprise_vers_tuplerectangle-staticmethod-verificationpy-ligne-2001)
- [`_executer_recherche_trous(self, couche)` (verification_nettoyage_automatique.py, ligne 361)](#_executer_recherche_trousself-couche-verification_nettoyage_automatiquepy-ligne-361)
- [`_executer_decoupe_emprise(self, couche)` (verification_nettoyage_automatique.py, ligne 586)](#_executer_decoupe_empriseself-couche-verification_nettoyage_automatiquepy-ligne-586)
- [`_traiter_lot_hors_emprise(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 721)](#_traiter_lot_hors_empriseself-couche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-721)
- [`mettre_a_jour_trous_locaux(self, rect)` (verification_trous.py, ligne 26)](#mettre_a_jour_trous_locauxself-rect-verification_trouspy-ligne-26)
- [`preparer_recherche_trous(self, emprise_layer, feature_by_id, index)` (verification_trous.py, ligne 148)](#preparer_recherche_trousself-emprise_layer-feature_by_id-index-verification_trouspy-ligne-148)
- [`couche_emprise_cachee(self)` (verification_trous.py, ligne 220)](#couche_emprise_cacheeself-verification_trouspy-ligne-220)
- [`geometrie_emprise_locale(self, rect)` (verification_trous.py, ligne 227)](#geometrie_emprise_localeself-rect-verification_trouspy-ligne-227)
- [`decouper_a_emprise_locale(self, geometrie)` (verification_trous.py, ligne 237)](#decouper_a_emprise_localeself-geometrie-verification_trouspy-ligne-237)

### Couches (recherche/validation)

- [`resoudre_champs(self)` (commun_parametres.py, ligne 83)](#resoudre_champsself-commun_parametrespy-ligne-83)
- [`normaliser_booleen(value)` (commun_parametres.py, ligne 113)](#normaliser_booleenvalue-commun_parametrespy-ligne-113)
- [`couche_est_disponible(couche)` (commun_couches.py, ligne 17)](#couche_est_disponiblecouche-commun_couchespy-ligne-17)
- [`est_couche_polygonale(couche)` (commun_couches.py, ligne 46)](#est_couche_polygonalecouche-commun_couchespy-ligne-46)
- [`trouver_couche_travail(iface=None)` (commun_couches.py, ligne 56)](#trouver_couche_travailifacenone-commun_couchespy-ligne-56)
- [`trouver_couche_emprise()` (commun_couches.py, ligne 76)](#trouver_couche_emprise-commun_couchespy-ligne-76)
- [`message_couche_travail_absente()` (commun_couches.py, ligne 101)](#message_couche_travail_absente-commun_couchespy-ligne-101)
- [`valider_couche_modifiable(couche)` (commun_couches.py, ligne 109)](#valider_couche_modifiablecouche-commun_couchespy-ligne-109)
- [`_trouver_couche_par_prefixe(prefixe, iface=None, couche_valide=None, prioriser_edition=False)` (commun_couches.py, ligne 118)](#_trouver_couche_par_prefixeprefixe-ifacenone-couche_validenone-prioriser_editionfalse-commun_couchespy-ligne-118)
- [`trouver_couche_alertes(iface=None)` (commun_couches.py, ligne 161)](#trouver_couche_alertesifacenone-commun_couchespy-ligne-161)
- [`EtatSessionProjet._est_couche_parent(self, couche)` (commun_etat_session.py, ligne 137)](#_est_couche_parentself-couche-commun_etat_sessionpy-ligne-137)
- [`EtatSessionProjet.fid_memorise_pour_couche(self, couche)` (commun_etat_session.py, ligne 164)](#fid_memorise_pour_coucheself-couche-commun_etat_sessionpy-ligne-164)
- [`fid_est_valide(couche, fid)` (commun_edition.py, ligne 219)](#fid_est_validecouche-fid-commun_editionpy-ligne-219)
- [`activer_couche_travail(iface)` (commun_edition.py, ligne 351)](#activer_couche_travailiface-commun_editionpy-ligne-351)
- [`obtenir_couche_editable(iface, nom_outil, couche_attendue=None, manager=None, outil=None)` (commun_edition.py, ligne 371)](#obtenir_couche_editableiface-nom_outil-couche_attenduenone-managernone-outilnone-commun_editionpy-ligne-371)
- [Classe `SurveillanceCoucheActive` (commun_edition.py, ligne 415)](#classe-surveillancecoucheactive-commun_editionpy-ligne-415)
- [`SurveillanceCoucheActive.__init__(self, callback_perte)` (commun_edition.py, ligne 423)](#__init__self-callback_perte-commun_editionpy-ligne-423)
- [`SurveillanceCoucheActive.demarrer(self)` (commun_edition.py, ligne 427)](#demarrerself-commun_editionpy-ligne-427)
- [`SurveillanceCoucheActive.arreter(self)` (commun_edition.py, ligne 433)](#arreterself-commun_editionpy-ligne-433)
- [`SurveillanceCoucheActive.surveiller_couche(self, couche)` (commun_edition.py, ligne 446)](#surveiller_coucheself-couche-commun_editionpy-ligne-446)
- [`SurveillanceCoucheActive.oublier_couche(self)` (commun_edition.py, ligne 457)](#oublier_coucheself-commun_editionpy-ligne-457)
- [`SurveillanceCoucheActive._couches_supprimees(self, ids_couches)` (commun_edition.py, ligne 467)](#_couches_supprimeesself-ids_couches-commun_editionpy-ligne-467)
- [`SurveillanceCoucheActive._projet_vide(self, *args)` (commun_edition.py, ligne 475)](#_projet_videself-args-commun_editionpy-ligne-475)
- [`SurveillanceCoucheActive._edition_arretee(self, *args)` (commun_edition.py, ligne 480)](#_edition_arreteeself-args-commun_editionpy-ligne-480)
- [`SurveillanceCoucheActive._declencher(self)` (commun_edition.py, ligne 484)](#_declencherself-commun_editionpy-ligne-484)
- [`AttenteDebutEdition.attendre(self, couche)` (commun_edition.py, ligne 507)](#attendreself-couche-commun_editionpy-ligne-507)
- [`ouvrir_formulaire_ou_annuler(iface, couche, canvas, entite, nom_outil)` (commun_edition.py, ligne 623)](#ouvrir_formulaire_ou_annuleriface-couche-canvas-entite-nom_outil-commun_editionpy-ligne-623)
- [`meilleur_voisin_par_contact(couche, geometrie, fid_exclu=None)` (commun_topologie.py, ligne 260)](#meilleur_voisin_par_contactcouche-geometrie-fid_exclunone-commun_topologiepy-ligne-260)
- [`redecouper_polygones_inclus(couche, geometrie_fusionnee, fids_fusionnes)` (commun_topologie.py, ligne 680)](#redecouper_polygones_incluscouche-geometrie_fusionnee-fids_fusionnes-commun_topologiepy-ligne-680)
- [`_distance_retrait_surbrillance(canvas, geometrie, couche)` (commun_affichage.py, ligne 90)](#_distance_retrait_surbrillancecanvas-geometrie-couche-commun_affichagepy-ligne-90)
- [`marquer_edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 57)](#marquer_edition_alertes_ouverte_par_plugincouche-commun_synchronisation_alertespy-ligne-57)
- [`oublier_edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 71)](#oublier_edition_alertes_ouverte_par_plugincouche-commun_synchronisation_alertespy-ligne-71)
- [`ecriture_parent_interne_en_cours(couche)` (commun_synchronisation_alertes.py, ligne 78)](#ecriture_parent_interne_en_courscouche-commun_synchronisation_alertespy-ligne-78)
- [`_cle_couche(couche)` (commun_synchronisation_alertes.py, ligne 89)](#_cle_couchecouche-commun_synchronisation_alertespy-ligne-89)
- [`_suffixe_groupe(nom)` (commun_synchronisation_alertes.py, ligne 324)](#_suffixe_groupenom-commun_synchronisation_alertespy-ligne-324)
- [`_trouver_couche_alertes_associee(couche_parent, iface=None)` (commun_synchronisation_alertes.py, ligne 334)](#_trouver_couche_alertes_associeecouche_parent-ifacenone-commun_synchronisation_alertespy-ligne-334)
- [`trouver_couche_alertes_associee(couche_parent, iface=None)` (commun_synchronisation_alertes.py, ligne 373)](#trouver_couche_alertes_associeecouche_parent-ifacenone-commun_synchronisation_alertespy-ligne-373)
- [`CompteurAlertes.connecter_couches(self)` (commun_compteur_alertes.py, ligne 254)](#connecter_couchesself-commun_compteur_alertespy-ligne-254)
- [`CompteurAlertes.deconnecter_couches(self)` (commun_compteur_alertes.py, ligne 340)](#deconnecter_couchesself-commun_compteur_alertespy-ligne-340)
- [`CompteurAlertes._attribut_alerte_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 865)](#_attribut_alerte_modifieself-fid-index_champ-nouvelle_valeur-commun_compteur_alertespy-ligne-865)
- [`HistoriqueFormulaires.definir_etat_formulaire(self, callback)` (commun_historique_formulaires.py, ligne 491)](#definir_etat_formulaireself-callback-commun_historique_formulairespy-ligne-491)
- [`HistoriqueFormulaires._couche_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 540)](#_couche_fenetreself-fenetre-commun_historique_formulairespy-ligne-540)
- [`HistoriqueFormulaires._cle_couche(couche)` (commun_historique_formulaires.py, ligne 555)](#_cle_couchecouche-staticmethod-commun_historique_formulairespy-ligne-555)
- [`HistoriqueFormulaires._memoriser_derniere_fiche(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 562)](#_memoriser_derniere_ficheself-fenetre-fid-commun_historique_formulairespy-ligne-562)
- [`HistoriqueFormulaires.capturer_contexte_visuel_couche(self, couche, fids_supprimes_prevus=None)` (commun_historique_formulaires.py, ligne 805)](#capturer_contexte_visuel_coucheself-couche-fids_supprimes_prevusnone-commun_historique_formulairespy-ligne-805)
- [`HistoriqueFormulaires.restaurer_contexte_visuel_couche(self, couche, contexte, fid_remplacement=None, restaurer_fid=True)` (commun_historique_formulaires.py, ligne 1122)](#restaurer_contexte_visuel_coucheself-couche-contexte-fid_remplacementnone-restaurer_fidtrue-commun_historique_formulairespy-ligne-1122)
- [`CreerPolygonePlugin._preparer_creation(self, geometrie_dessinee)` (edition_creer.py, ligne 301)](#_preparer_creationself-geometrie_dessinee-edition_creerpy-ligne-301)
- [`SeparerPolygonePlugin._appliquer_separation_native(self, preparation, points)` (edition_separer.py, ligne 438)](#_appliquer_separation_nativeself-preparation-points-vue_stable_pendant_modification-edition_separerpy-ligne-438)
- [`FusionnerBdForetPlugin._preparer_fusion(self, fids=None)` (edition_fusionner.py, ligne 511)](#_preparer_fusionself-fidsnone-edition_fusionnerpy-ligne-511)
- [`RemodelerBdForetPlugin._point_vers_couche(self, point_carte)` (edition_remodeler.py, ligne 317)](#_point_vers_coucheself-point_carte-edition_remodelerpy-ligne-317)
- [`_trouver_couche_bdfv2()` (edition_reporter_bdfv2.py, ligne 65)](#_trouver_couche_bdfv2-edition_reporter_bdfv2py-ligne-65)
- [`ReporterBdFv2Plugin._preparer_report(self, geometrie_v2, entite_v2, prefixe='Report BDFv2')` (edition_reporter_bdfv2.py, ligne 506)](#_preparer_reportself-geometrie_v2-entite_v2-prefixereport-bdfv2-edition_reporter_bdfv2py-ligne-506)
- [`PanneauVerification.etapes_nettoyage_activees(self)` (verification_panneau.py, ligne 217)](#etapes_nettoyage_activeesself-verification_panneaupy-ligne-217)
- [`PanneauVerification.closeEvent(self, event)` (verification_panneau.py, ligne 229)](#closeeventself-event-verification_panneaupy-ligne-229)
- [`_creer_symbole_anomalies()` (verification.py, ligne 92)](#_creer_symbole_anomalies-verificationpy-ligne-92)
- [Classe `CoucheSurbrillanceVerification` (verification.py, ligne 120)](#classe-couchesurbrillanceverification-verificationpy-ligne-120)
- [`CoucheSurbrillanceVerification.__init__(self)` (verification.py, ligne 123)](#__init__self-verificationpy-ligne-123)
- [`CoucheSurbrillanceVerification.detacher(self)` (verification.py, ligne 126)](#detacherself-verificationpy-ligne-126)
- [`CoucheSurbrillanceVerification.courante(self)` (verification.py, ligne 130)](#couranteself-verificationpy-ligne-130)
- [`CoucheSurbrillanceVerification.prochain_nom()` (verification.py, ligne 141)](#prochain_nom-staticmethod-verificationpy-ligne-141)
- [`CoucheSurbrillanceVerification.assurer(self, couche_travail)` (verification.py, ligne 156)](#assurerself-couche_travail-verificationpy-ligne-156)
- [`CoucheSurbrillanceVerification._ajouter_au_projet(couche, couche_travail)` (verification.py, ligne 195)](#_ajouter_au_projetcouche-couche_travail-staticmethod-verificationpy-ligne-195)
- [`CoucheSurbrillanceVerification.remplacer_entites(self, couche_travail, entites)` (verification.py, ligne 215)](#remplacer_entitesself-couche_travail-entites-verificationpy-ligne-215)
- [`VerificationBdForetPlugin._trouver_couche(self)` (verification.py, ligne 534)](#_trouver_coucheself-verificationpy-ligne-534)
- [`VerificationBdForetPlugin._trouver_couche_emprise()` (verification.py, ligne 539)](#_trouver_couche_emprise-staticmethod-verificationpy-ligne-539)
- [`VerificationBdForetPlugin._connecter_signaux_couche(self, layer)` (verification.py, ligne 543)](#_connecter_signaux_coucheself-layer-verificationpy-ligne-543)
- [`VerificationBdForetPlugin._deconnecter_signaux_couche(self)` (verification.py, ligne 571)](#_deconnecter_signaux_coucheself-verificationpy-ligne-571)
- [`VerificationBdForetPlugin.lancer_nettoyage_automatique(self)` (verification.py, ligne 728)](#lancer_nettoyage_automatiqueself-verificationpy-ligne-728)
- [`VerificationBdForetPlugin._indiquer_progression_nettoyage(self, etat, ligne_finale=None)` (verification.py, ligne 1409)](#_indiquer_progression_nettoyageself-etat-ligne_finalenone-verificationpy-ligne-1409)
- [`VerificationBdForetPlugin._obtenir_entite_cachee(self, fid)` (verification.py, ligne 1757)](#_obtenir_entite_cacheeself-fid-verificationpy-ligne-1757)
- [`VerificationBdForetPlugin.creer_couche_temporaire(self)` (verification.py, ligne 2029)](#creer_couche_temporaireself-verificationpy-ligne-2029)
- [`VerificationBdForetPlugin._synchroniser_couche_surbrillance(self)` (verification.py, ligne 2053)](#_synchroniser_couche_surbrillanceself-verificationpy-ligne-2053)
- [`VerificationBdForetPlugin._ajouter_geometrie_surbrillance(self, layer, entites, cles_traitees, cle, categorie, geometrie, decouper_emprise=True)` (verification.py, ligne 2134)](#_ajouter_geometrie_surbrillanceself-layer-entites-cles_traitees-cle-categorie-geometrie-decouper_emprisetrue-verificationpy-ligne-2134)
- [`VerificationBdForetPlugin._reinitialiser_resultats_panneau(self)` (verification.py, ligne 2236)](#_reinitialiser_resultats_panneauself-verificationpy-ligne-2236)
- [Classe `TacheRelationsVoisines(QgsTask)` (verification_tache_relations.py, ligne 23)](#classe-tacherelationsvoisinesqgstask-verification_tache_relationspy-ligne-23)
- [`TacheRelationsVoisines.run(self)` (verification_tache_relations.py, ligne 54)](#runself-verification_tache_relationspy-ligne-54)
- [`preparer_nettoyage(self, etapes_activees=None)` (verification_nettoyage_automatique.py, ligne 159)](#preparer_nettoyageself-etapes_activeesnone-verification_nettoyage_automatiquepy-ligne-159)
- [`_executer_recherche_trous(self, couche)` (verification_nettoyage_automatique.py, ligne 361)](#_executer_recherche_trousself-couche-verification_nettoyage_automatiquepy-ligne-361)
- [`_construire_cache_travail(couche)` (verification_nettoyage_automatique.py, ligne 438)](#_construire_cache_travailcouche-verification_nettoyage_automatiquepy-ligne-438)
- [`_reparer_couche_native(couche_memoire)` (verification_nettoyage_automatique.py, ligne 571)](#_reparer_couche_nativecouche_memoire-verification_nettoyage_automatiquepy-ligne-571)
- [`_executer_decoupe_emprise(self, couche)` (verification_nettoyage_automatique.py, ligne 586)](#_executer_decoupe_empriseself-couche-verification_nettoyage_automatiquepy-ligne-586)
- [`valider_trous_contre_couche_actuelle(self)` (verification_trous.py, ligne 89)](#valider_trous_contre_couche_actuelleself-verification_trouspy-ligne-89)
- [`couche_emprise_cachee(self)` (verification_trous.py, ligne 220)](#couche_emprise_cacheeself-verification_trouspy-ligne-220)

### Historique des fiches

- [`ProtectionVueCarte._restaurer_emprise(self, emprise)` (commun_protection_vue.py, ligne 145)](#_restaurer_empriseself-emprise-commun_protection_vuepy-ligne-145)
- [`ouvrir_formulaire_ou_annuler(iface, couche, canvas, entite, nom_outil)` (commun_edition.py, ligne 623)](#ouvrir_formulaire_ou_annuleriface-couche-canvas-entite-nom_outil-commun_editionpy-ligne-623)
- [`CompteurAlertes._rafraichir_formulaire_parent(self, fid_parent)` (commun_compteur_alertes.py, ligne 1846)](#_rafraichir_formulaire_parentself-fid_parent-commun_compteur_alertespy-ligne-1846)
- [Classe `HistoriqueFormulaires` (commun_historique_formulaires.py, ligne 24)](#classe-historiqueformulaires-commun_historique_formulairespy-ligne-24)
- [`HistoriqueFormulaires.__init__(self, iface)` (commun_historique_formulaires.py, ligne 32)](#__init__self-iface-commun_historique_formulairespy-ligne-32)
- [`HistoriqueFormulaires.initGui(self)` (commun_historique_formulaires.py, ligne 57)](#initguiself-commun_historique_formulairespy-ligne-57)
- [`HistoriqueFormulaires.unload(self)` (commun_historique_formulaires.py, ligne 79)](#unloadself-commun_historique_formulairespy-ligne-79)
- [`HistoriqueFormulaires._focus_change(self, _ancien, nouveau)` (commun_historique_formulaires.py, ligne 98)](#_focus_changeself-_ancien-nouveau-commun_historique_formulairespy-ligne-98)
- [`HistoriqueFormulaires._verifier_fenetre_differee(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 129)](#_verifier_fenetre_differeeself-reference_fenetre-commun_historique_formulairespy-ligne-129)
- [`HistoriqueFormulaires.detecter_tables(self)` (commun_historique_formulaires.py, ligne 148)](#detecter_tablesself-commun_historique_formulairespy-ligne-148)
- [`HistoriqueFormulaires.connecter_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 185)](#connecter_fenetreself-fenetre-commun_historique_formulairespy-ligne-185)
- [`HistoriqueFormulaires._memoriser_scroll_avant_reset(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 283)](#_memoriser_scroll_avant_resetself-reference_fenetre-commun_historique_formulairespy-ligne-283)
- [`HistoriqueFormulaires._restaurer_scroll_apres_reset(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 303)](#_restaurer_scroll_apres_resetself-reference_fenetre-commun_historique_formulairespy-ligne-303)
- [`HistoriqueFormulaires._appliquer_scroll_si_valide(self, reference_fenetre, valeur)` (commun_historique_formulaires.py, ligne 321)](#_appliquer_scroll_si_valideself-reference_fenetre-valeur-commun_historique_formulairespy-ligne-321)
- [`HistoriqueFormulaires._trouver_composants_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 342)](#_trouver_composants_fenetreself-fenetre-commun_historique_formulairespy-ligne-342)
- [`HistoriqueFormulaires._trouver_liste_principale(main_view_widget)` (commun_historique_formulaires.py, ligne 363)](#_trouver_liste_principalemain_view_widget-staticmethod-commun_historique_formulairespy-ligne-363)
- [`HistoriqueFormulaires._trouver_barre_outils(fenetre)` (commun_historique_formulaires.py, ligne 402)](#_trouver_barre_outilsfenetre-staticmethod-commun_historique_formulairespy-ligne-402)
- [`HistoriqueFormulaires._creer_actions(self, fenetre, toolbar)` (commun_historique_formulaires.py, ligne 419)](#_creer_actionsself-fenetre-toolbar-commun_historique_formulairespy-ligne-419)
- [`HistoriqueFormulaires._creer_action(self, fenetre, icone, texte, nom_objet, info_bulle)` (commun_historique_formulaires.py, ligne 474)](#_creer_actionself-fenetre-icone-texte-nom_objet-info_bulle-commun_historique_formulairespy-ligne-474)
- [`HistoriqueFormulaires._trouver_action(toolbar, nom)` (commun_historique_formulaires.py, ligne 482)](#_trouver_actiontoolbar-nom-staticmethod-commun_historique_formulairespy-ligne-482)
- [`HistoriqueFormulaires.definir_etat_formulaire(self, callback)` (commun_historique_formulaires.py, ligne 491)](#definir_etat_formulaireself-callback-commun_historique_formulairespy-ligne-491)
- [`HistoriqueFormulaires.definir_fid_persistant(self, callback)` (commun_historique_formulaires.py, ligne 495)](#definir_fid_persistantself-callback-commun_historique_formulairespy-ligne-495)
- [`HistoriqueFormulaires._notifier_etat_formulaire(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 499)](#_notifier_etat_formulaireself-fenetre-fid-commun_historique_formulairespy-ligne-499)
- [`HistoriqueFormulaires.definir_recalcul_alertes(self, callback)` (commun_historique_formulaires.py, ligne 515)](#definir_recalcul_alertesself-callback-commun_historique_formulairespy-ligne-515)
- [`HistoriqueFormulaires.recalculer_alertes(self)` (commun_historique_formulaires.py, ligne 527)](#recalculer_alertesself-commun_historique_formulairespy-ligne-527)
- [`HistoriqueFormulaires._couche_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 540)](#_couche_fenetreself-fenetre-commun_historique_formulairespy-ligne-540)
- [`HistoriqueFormulaires._cle_couche(couche)` (commun_historique_formulaires.py, ligne 555)](#_cle_couchecouche-staticmethod-commun_historique_formulairespy-ligne-555)
- [`HistoriqueFormulaires._memoriser_derniere_fiche(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 562)](#_memoriser_derniere_ficheself-fenetre-fid-commun_historique_formulairespy-ligne-562)
- [`HistoriqueFormulaires._restaurer_derniere_fiche(self, fenetre)` (commun_historique_formulaires.py, ligne 573)](#_restaurer_derniere_ficheself-fenetre-commun_historique_formulairespy-ligne-573)
- [`HistoriqueFormulaires.fiche_changee(self, fenetre, feature)` (commun_historique_formulaires.py, ligne 623)](#fiche_changeeself-fenetre-feature-commun_historique_formulairespy-ligne-623)
- [`HistoriqueFormulaires.enregistrer_fiche_initiale(self, fenetre)` (commun_historique_formulaires.py, ligne 636)](#enregistrer_fiche_initialeself-fenetre-commun_historique_formulairespy-ligne-636)
- [`HistoriqueFormulaires.ajouter_fid_historique(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 649)](#ajouter_fid_historiqueself-fenetre-fid-commun_historique_formulairespy-ligne-649)
- [`HistoriqueFormulaires.revenir_precedent(self, fenetre)` (commun_historique_formulaires.py, ligne 678)](#revenir_precedentself-fenetre-commun_historique_formulairespy-ligne-678)
- [`HistoriqueFormulaires.aller_suivant(self, fenetre)` (commun_historique_formulaires.py, ligne 683)](#aller_suivantself-fenetre-commun_historique_formulairespy-ligne-683)
- [`HistoriqueFormulaires.ouvrir_position(self, fenetre, nouvelle_position)` (commun_historique_formulaires.py, ligne 690)](#ouvrir_positionself-fenetre-nouvelle_position-commun_historique_formulairespy-ligne-690)
- [`HistoriqueFormulaires.mettre_a_jour_actions(self, fenetre)` (commun_historique_formulaires.py, ligne 718)](#mettre_a_jour_actionsself-fenetre-commun_historique_formulairespy-ligne-718)
- [`HistoriqueFormulaires.geler_fiche_si_fid_supprime(self, couche, fids_supprimes)` (commun_historique_formulaires.py, ligne 735)](#geler_fiche_si_fid_supprimeself-couche-fids_supprimes-commun_historique_formulairespy-ligne-735)
- [`HistoriqueFormulaires.liberer_gel_fiche(self, gels)` (commun_historique_formulaires.py, ligne 778)](#liberer_gel_ficheself-gels-commun_historique_formulairespy-ligne-778)
- [`HistoriqueFormulaires.capturer_contexte_visuel_couche(self, couche, fids_supprimes_prevus=None)` (commun_historique_formulaires.py, ligne 805)](#capturer_contexte_visuel_coucheself-couche-fids_supprimes_prevusnone-commun_historique_formulairespy-ligne-805)
- [`HistoriqueFormulaires.deplacer_fiche_avant_suppression(self, couche, contexte)` (commun_historique_formulaires.py, ligne 891)](#deplacer_fiche_avant_suppressionself-couche-contexte-commun_historique_formulairespy-ligne-891)
- [`HistoriqueFormulaires.assainir_fiche_apres_suppression(self, couche, fid_supprime)` (commun_historique_formulaires.py, ligne 956)](#assainir_fiche_apres_suppressionself-couche-fid_supprime-commun_historique_formulairespy-ligne-956)
- [`HistoriqueFormulaires._restaurer_contexte_visuel_une_fois(self, couche, contexte, fid_remplacement=None)` (commun_historique_formulaires.py, ligne 1028)](#_restaurer_contexte_visuel_une_foisself-couche-contexte-fid_remplacementnone-commun_historique_formulairespy-ligne-1028)
- [`HistoriqueFormulaires.restaurer_contexte_visuel_couche(self, couche, contexte, fid_remplacement=None, restaurer_fid=True)` (commun_historique_formulaires.py, ligne 1122)](#restaurer_contexte_visuel_coucheself-couche-contexte-fid_remplacementnone-restaurer_fidtrue-commun_historique_formulairespy-ligne-1122)
- [`HistoriqueFormulaires.fenetre_detruite(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 1158)](#fenetre_detruiteself-reference_fenetre-commun_historique_formulairespy-ligne-1158)
- [`HistoriqueFormulaires._objet_qt_valide(objet)` (commun_historique_formulaires.py, ligne 1167)](#_objet_qt_valideobjet-staticmethod-commun_historique_formulairespy-ligne-1167)
- [`HistoriqueFormulaires.deconnecter_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 1181)](#deconnecter_fenetreself-fenetre-commun_historique_formulairespy-ligne-1181)
- [`FusionnerBdForetPlugin._fid_fiche_active(fids_fusionnes, contexte_formulaire)` (edition_fusionner.py, ligne 662)](#_fid_fiche_activefids_fusionnes-contexte_formulaire-staticmethod-edition_fusionnerpy-ligne-662)
- [`modifier_attributs_entite(self, fid)` (verification_polygones_adjacents_attributs_identiques.py, ligne 200)](#modifier_attributs_entiteself-fid-verification_polygones_adjacents_attributs_identiquespy-ligne-200)
- [`modifier_attributs_entite(self, fid)` (verification_coherence_essence_tff.py, ligne 82)](#modifier_attributs_entiteself-fid-verification_coherence_essence_tffpy-ligne-82)

### Nettoyage automatique

- [`nettoyer_geometrie_base(geometrie)` (commun_topologie.py, ligne 33)](#nettoyer_geometrie_basegeometrie-commun_topologiepy-ligne-33)
- [`nettoyer_contacts_ponctuels(geometrie)` (commun_topologie.py, ligne 491)](#nettoyer_contacts_ponctuelsgeometrie-commun_topologiepy-ligne-491)
- [`nettoyer_geometrie_decoupee_protegee(couche, geometrie, fids_exclus=None, tolerance_m=None)` (commun_topologie.py, ligne 518)](#nettoyer_geometrie_decoupee_protegeecouche-geometrie-fids_exclusnone-tolerance_mnone-commun_topologiepy-ligne-518)
- [`fusionner_geometries(geometries)` (commun_topologie.py, ligne 609)](#fusionner_geometriesgeometries-commun_topologiepy-ligne-609)
- [`nettoyer_pointes_interieures(anneau)` (commun_topologie.py, ligne 917)](#nettoyer_pointes_interieuresanneau-commun_topologiepy-ligne-917)
- [`nettoyer_excroissances_parasites_anneau(anneau)` (commun_topologie.py, ligne 1236)](#nettoyer_excroissances_parasites_anneauanneau-commun_topologiepy-ligne-1236)
- [`nettoyer_geometrie_avance(geometrie)` (commun_topologie.py, ligne 1260)](#nettoyer_geometrie_avancegeometrie-commun_topologiepy-ligne-1260)
- [`PanneauVerification.etapes_nettoyage_activees(self)` (verification_panneau.py, ligne 217)](#etapes_nettoyage_activeesself-verification_panneaupy-ligne-217)
- [`VerificationBdForetPlugin.lancer_nettoyage_automatique(self)` (verification.py, ligne 728)](#lancer_nettoyage_automatiqueself-verificationpy-ligne-728)
- [`VerificationBdForetPlugin._continuer_nettoyage_automatique(self)` (verification.py, ligne 838)](#_continuer_nettoyage_automatiqueself-verificationpy-ligne-838)
- [`VerificationBdForetPlugin._indiquer_progression_nettoyage(self, etat, ligne_finale=None)` (verification.py, ligne 1409)](#_indiquer_progression_nettoyageself-etat-ligne_finalenone-verificationpy-ligne-1409)
- [`preparer_nettoyage(self, etapes_activees=None)` (verification_nettoyage_automatique.py, ligne 159)](#preparer_nettoyageself-etapes_activeesnone-verification_nettoyage_automatiquepy-ligne-159)
- [`traiter_lot_nettoyage(self, etat, taille_lot=200)` (verification_nettoyage_automatique.py, ligne 239)](#traiter_lot_nettoyageself-etat-taille_lot200-verification_nettoyage_automatiquepy-ligne-239)
- [`_traiter_lot_synchronisation_alertes(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 756)](#_traiter_lot_synchronisation_alertesself-couche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-756)
- [`progression_nettoyage(etat)` (verification_nettoyage_automatique.py, ligne 823)](#progression_nettoyageetat-verification_nettoyage_automatiquepy-ligne-823)
- [`nombre_etapes_prevues(etat)` (verification_nettoyage_automatique.py, ligne 841)](#nombre_etapes_prevuesetat-verification_nettoyage_automatiquepy-ligne-841)
- [`finaliser_nettoyage(etat)` (verification_nettoyage_automatique.py, ligne 856)](#finaliser_nettoyageetat-verification_nettoyage_automatiquepy-ligne-856)
- [`nettoyer_micro_anomalies_locales(controleur, couche, geometrie_zone, fids_proteges=None)` (verification_recouvrements.py, ligne 122)](#nettoyer_micro_anomalies_localescontroleur-couche-geometrie_zone-fids_protegesnone-verification_recouvrementspy-ligne-122)
- [`_preparer_geometrie_trou(self, couche, gap_index)` (verification_trous.py, ligne 250)](#_preparer_geometrie_trouself-couche-gap_index-verification_trouspy-ligne-250)

### Relation QGIS

- [`_widgets_relation_alertes_ouverts(iface)` (commun_synchronisation_alertes.py, ligne 394)](#_widgets_relation_alertes_ouvertsiface-commun_synchronisation_alertespy-ligne-394)
- [`rafraichir_vue_relation_alertes(iface, couche_parent, couche_alertes, fids_parents)` (commun_synchronisation_alertes.py, ligne 430)](#rafraichir_vue_relation_alertesiface-couche_parent-couche_alertes-fids_parents-commun_synchronisation_alertespy-ligne-430)
- [`CompteurAlertes._trouver_relation(self)` (commun_compteur_alertes.py, ligne 466)](#_trouver_relationself-commun_compteur_alertespy-ligne-466)
- [`CompteurAlertes._recalculer_parent(self, fid_alerte)` (commun_compteur_alertes.py, ligne 1737)](#_recalculer_parentself-fid_alerte-commun_compteur_alertespy-ligne-1737)
- [`HistoriqueFormulaires._trouver_liste_principale(main_view_widget)` (commun_historique_formulaires.py, ligne 363)](#_trouver_liste_principalemain_view_widget-staticmethod-commun_historique_formulairespy-ligne-363)
- [`VerificationBdForetPlugin._tache_relations_terminee(self, generation, task, succes, resultats, erreur)` (verification.py, ligne 1171)](#_tache_relations_termineeself-generation-task-succes-resultats-erreur-verificationpy-ligne-1171)
- [`VerificationBdForetPlugin._annuler_tache_relations(self)` (verification.py, ligne 1376)](#_annuler_tache_relationsself-verificationpy-ligne-1376)
- [`VerificationBdForetPlugin._chercher_relations_voisines(self, features, feature_by_id, field_map, index)` (verification.py, ligne 1450)](#_chercher_relations_voisinesself-features-feature_by_id-field_map-index-verificationpy-ligne-1450)
- [`VerificationBdForetPlugin._recalculer_relations_locales(self, affected)` (verification.py, ligne 1679)](#_recalculer_relations_localesself-affected-verificationpy-ligne-1679)
- [Classe `TacheRelationsVoisines(QgsTask)` (verification_tache_relations.py, ligne 23)](#classe-tacherelationsvoisinesqgstask-verification_tache_relationspy-ligne-23)
- [`TacheRelationsVoisines.__init__(self, donnees, paires_candidates, regles_activees, callback)` (verification_tache_relations.py, ligne 26)](#__init__self-donnees-paires_candidates-regles_activees-callback-verification_tache_relationspy-ligne-26)
- [`TacheRelationsVoisines._geometrie_depuis_wkb(wkb)` (verification_tache_relations.py, ligne 41)](#_geometrie_depuis_wkbwkb-staticmethod-verification_tache_relationspy-ligne-41)
- [`TacheRelationsVoisines.run(self)` (verification_tache_relations.py, ligne 54)](#runself-verification_tache_relationspy-ligne-54)
- [`TacheRelationsVoisines.finished(self, succes)` (verification_tache_relations.py, ligne 165)](#finishedself-succes-verification_tache_relationspy-ligne-165)

### Session

- [Classe `EtatSessionProjet` (commun_etat_session.py, ligne 24)](#classe-etatsessionprojet-commun_etat_sessionpy-ligne-24)
- [`EtatSessionProjet.__init__(self, iface)` (commun_etat_session.py, ligne 31)](#__init__self-iface-commun_etat_sessionpy-ligne-31)
- [`EtatSessionProjet.initGui(self)` (commun_etat_session.py, ligne 40)](#initguiself-commun_etat_sessionpy-ligne-40)
- [`EtatSessionProjet.unload(self)` (commun_etat_session.py, ligne 57)](#unloadself-commun_etat_sessionpy-ligne-57)
- [`EtatSessionProjet._chemin_projet(self)` (commun_etat_session.py, ligne 77)](#_chemin_projetself-commun_etat_sessionpy-ligne-77)
- [`EtatSessionProjet._cle_reglage(cls, chemin)` (commun_etat_session.py, ligne 84)](#_cle_reglagecls-chemin-classmethod-commun_etat_sessionpy-ligne-84)
- [`EtatSessionProjet._sauvegarder_etat(self, *args)` (commun_etat_session.py, ligne 93)](#_sauvegarder_etatself-args-commun_etat_sessionpy-ligne-93)
- [`EtatSessionProjet._lire_etat(self)` (commun_etat_session.py, ligne 112)](#_lire_etatself-commun_etat_sessionpy-ligne-112)
- [`EtatSessionProjet._projet_lu(self, *args)` (commun_etat_session.py, ligne 125)](#_projet_luself-args-commun_etat_sessionpy-ligne-125)
- [`EtatSessionProjet._est_couche_parent(self, couche)` (commun_etat_session.py, ligne 137)](#_est_couche_parentself-couche-commun_etat_sessionpy-ligne-137)
- [`EtatSessionProjet.memoriser_formulaire(self, couche, fid, _vue_formulaire=True)` (commun_etat_session.py, ligne 147)](#memoriser_formulaireself-couche-fid-_vue_formulairetrue-commun_etat_sessionpy-ligne-147)
- [`EtatSessionProjet.fid_memorise_pour_couche(self, couche)` (commun_etat_session.py, ligne 164)](#fid_memorise_pour_coucheself-couche-commun_etat_sessionpy-ligne-164)
- [`edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 64)](#edition_alertes_ouverte_par_plugincouche-commun_synchronisation_alertespy-ligne-64)
- [`HistoriqueFormulaires.definir_fid_persistant(self, callback)` (commun_historique_formulaires.py, ligne 495)](#definir_fid_persistantself-callback-commun_historique_formulairespy-ligne-495)
- [`HistoriqueFormulaires._cle_couche(couche)` (commun_historique_formulaires.py, ligne 555)](#_cle_couchecouche-staticmethod-commun_historique_formulairespy-ligne-555)
- [`VerificationBdForetPlugin._obtenir_date_premiere_detection(self, cle)` (verification.py, ligne 2165)](#_obtenir_date_premiere_detectionself-cle-verificationpy-ligne-2165)

### Compteurs

- [Classe `CompteurAlertes` (commun_compteur_alertes.py, ligne 112)](#classe-compteuralertes-commun_compteur_alertespy-ligne-112)
- [`CompteurAlertes.__init__(self, iface, historique=None)` (commun_compteur_alertes.py, ligne 134)](#__init__self-iface-historiquenone-commun_compteur_alertespy-ligne-134)
- [`CompteurAlertes.initGui(self)` (commun_compteur_alertes.py, ligne 202)](#initguiself-commun_compteur_alertespy-ligne-202)
- [`CompteurAlertes.unload(self)` (commun_compteur_alertes.py, ligne 218)](#unloadself-commun_compteur_alertespy-ligne-218)
- [`CompteurAlertes._programmer_connexion(self, *args)` (commun_compteur_alertes.py, ligne 242)](#_programmer_connexionself-args-commun_compteur_alertespy-ligne-242)
- [`CompteurAlertes._projet_vide(self, *args)` (commun_compteur_alertes.py, ligne 247)](#_projet_videself-args-commun_compteur_alertespy-ligne-247)
- [`CompteurAlertes.connecter_couches(self)` (commun_compteur_alertes.py, ligne 254)](#connecter_couchesself-commun_compteur_alertespy-ligne-254)
- [`CompteurAlertes.deconnecter_couches(self)` (commun_compteur_alertes.py, ligne 340)](#deconnecter_couchesself-commun_compteur_alertespy-ligne-340)
- [`CompteurAlertes.suspendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 397)](#suspendre_synchronisation_geometriqueself-commun_compteur_alertespy-ligne-397)
- [`CompteurAlertes.reprendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 411)](#reprendre_synchronisation_geometriqueself-commun_compteur_alertespy-ligne-411)
- [`CompteurAlertes._synchronisation_geometrique_suspendue(self)` (commun_compteur_alertes.py, ligne 419)](#_synchronisation_geometrique_suspendueself-commun_compteur_alertespy-ligne-419)
- [`CompteurAlertes.synchroniser_modification_geometrique(self, couche_parent, geometrie_zone, nom_commande)` (commun_compteur_alertes.py, ligne 422)](#synchroniser_modification_geometriqueself-couche_parent-geometrie_zone-nom_commande-commun_compteur_alertespy-ligne-422)
- [`CompteurAlertes._trouver_relation(self)` (commun_compteur_alertes.py, ligne 466)](#_trouver_relationself-commun_compteur_alertespy-ligne-466)
- [`CompteurAlertes._avant_enregistrement_parent(self, *args)` (commun_compteur_alertes.py, ligne 485)](#_avant_enregistrement_parentself-args-commun_compteur_alertespy-ligne-485)
- [`CompteurAlertes._terminer_garde_commit_parent(self)` (commun_compteur_alertes.py, ligne 495)](#_terminer_garde_commit_parentself-commun_compteur_alertespy-ligne-495)
- [`CompteurAlertes._reinitialiser_suivi_apres_commit_parent(self)` (commun_compteur_alertes.py, ligne 500)](#_reinitialiser_suivi_apres_commit_parentself-commun_compteur_alertespy-ligne-500)
- [`CompteurAlertes._apres_enregistrement_parent(self, *args)` (commun_compteur_alertes.py, ligne 510)](#_apres_enregistrement_parentself-args-commun_compteur_alertespy-ligne-510)
- [`CompteurAlertes._emprise_originale_parent(self, fid)` (commun_compteur_alertes.py, ligne 590)](#_emprise_originale_parentself-fid-commun_compteur_alertespy-ligne-590)
- [`CompteurAlertes._fusionner_rectangles(rectangle_a, rectangle_b)` (commun_compteur_alertes.py, ligne 623)](#_fusionner_rectanglesrectangle_a-rectangle_b-staticmethod-commun_compteur_alertespy-ligne-623)
- [`CompteurAlertes._commande_parent_demarre(self, _texte=None)` (commun_compteur_alertes.py, ligne 631)](#_commande_parent_demarreself-_textenone-commun_compteur_alertespy-ligne-631)
- [`CompteurAlertes._commande_parent_terminee(self)` (commun_compteur_alertes.py, ligne 648)](#_commande_parent_termineeself-commun_compteur_alertespy-ligne-648)
- [`CompteurAlertes._commande_parent_detruite(self)` (commun_compteur_alertes.py, ligne 670)](#_commande_parent_detruiteself-commun_compteur_alertespy-ligne-670)
- [`CompteurAlertes._memoriser_zone_geometrique(self, rectangle)` (commun_compteur_alertes.py, ligne 691)](#_memoriser_zone_geometriqueself-rectangle-commun_compteur_alertespy-ligne-691)
- [`CompteurAlertes._terminer_recalcul_hors_commande(self)` (commun_compteur_alertes.py, ligne 721)](#_terminer_recalcul_hors_commandeself-commun_compteur_alertespy-ligne-721)
- [`CompteurAlertes._executer_recalcul_geometrique_differe(self, rectangle, *_args)` (commun_compteur_alertes.py, ligne 735)](#_executer_recalcul_geometrique_differeself-rectangle-_args-commun_compteur_alertespy-ligne-735)
- [`CompteurAlertes._geometrie_parent_modifiee(self, fid, geometrie)` (commun_compteur_alertes.py, ligne 786)](#_geometrie_parent_modifieeself-fid-geometrie-commun_compteur_alertespy-ligne-786)
- [`CompteurAlertes._entite_parent_ajoutee(self, fid)` (commun_compteur_alertes.py, ligne 816)](#_entite_parent_ajouteeself-fid-commun_compteur_alertespy-ligne-816)
- [`CompteurAlertes._entite_parent_supprimee(self, fid)` (commun_compteur_alertes.py, ligne 833)](#_entite_parent_supprimeeself-fid-commun_compteur_alertespy-ligne-833)
- [`CompteurAlertes._attribut_alerte_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 865)](#_attribut_alerte_modifieself-fid-index_champ-nouvelle_valeur-commun_compteur_alertespy-ligne-865)
- [`CompteurAlertes._attribut_parent_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 890)](#_attribut_parent_modifieself-fid-index_champ-nouvelle_valeur-commun_compteur_alertespy-ligne-890)
- [`CompteurAlertes._commande_edition_active(couche)` (commun_compteur_alertes.py, ligne 938)](#_commande_edition_activecouche-staticmethod-commun_compteur_alertespy-ligne-938)
- [`CompteurAlertes._traiter_commandes_parent_en_attente(self)` (commun_compteur_alertes.py, ligne 947)](#_traiter_commandes_parent_en_attenteself-commun_compteur_alertespy-ligne-947)
- [`CompteurAlertes._traiter_toutes_alertes_vues_parent(self, fid_parent, valeur_demandee)` (commun_compteur_alertes.py, ligne 981)](#_traiter_toutes_alertes_vues_parentself-fid_parent-valeur_demandee-commun_compteur_alertespy-ligne-981)
- [`CompteurAlertes._marquer_toutes_alertes_vues(self, fid_parent)` (commun_compteur_alertes.py, ligne 1021)](#_marquer_toutes_alertes_vuesself-fid_parent-commun_compteur_alertespy-ligne-1021)
- [`CompteurAlertes.recalculer_tous_les_compteurs(self)` (commun_compteur_alertes.py, ligne 1090)](#recalculer_tous_les_compteursself-vue_stable_pendant_modification-commun_compteur_alertespy-ligne-1090)
- [`CompteurAlertes._cle_identifiant(valeur)` (commun_compteur_alertes.py, ligne 1704)](#_cle_identifiantvaleur-staticmethod-commun_compteur_alertespy-ligne-1704)
- [`CompteurAlertes._valeurs_compteur_identiques(self, actuelle, attendue, booleen=False)` (commun_compteur_alertes.py, ligne 1725)](#_valeurs_compteur_identiquesself-actuelle-attendue-booleenfalse-commun_compteur_alertespy-ligne-1725)
- [`CompteurAlertes._recalculer_parent(self, fid_alerte)` (commun_compteur_alertes.py, ligne 1737)](#_recalculer_parentself-fid_alerte-commun_compteur_alertespy-ligne-1737)
- [`CompteurAlertes._recalculer_parent_direct(self, fid_parent)` (commun_compteur_alertes.py, ligne 1757)](#_recalculer_parent_directself-fid_parent-commun_compteur_alertespy-ligne-1757)
- [`CompteurAlertes._convertir_en_booleen(valeur)` (commun_compteur_alertes.py, ligne 1836)](#_convertir_en_booleenvaleur-staticmethod-commun_compteur_alertespy-ligne-1836)
- [`CompteurAlertes._rafraichir_formulaire_parent(self, fid_parent)` (commun_compteur_alertes.py, ligne 1846)](#_rafraichir_formulaire_parentself-fid_parent-commun_compteur_alertespy-ligne-1846)
- [`CompteurAlertes._avertir(self, message)` (commun_compteur_alertes.py, ligne 1856)](#_avertirself-message-commun_compteur_alertespy-ligne-1856)
- [`HistoriqueFormulaires.definir_recalcul_alertes(self, callback)` (commun_historique_formulaires.py, ligne 515)](#definir_recalcul_alertesself-callback-commun_historique_formulairespy-ligne-515)

### Géométrie

- [`OutilsBdForet.desactiver_autres_outils_geometriques(self, outil_actif)` (commun_outils.py, ligne 99)](#desactiver_autres_outils_geometriquesself-outil_actif-commun_outilspy-ligne-99)
- [`vue_stable_pendant_modification(fonction)` (commun_protection_vue.py, ligne 231)](#vue_stable_pendant_modificationfonction-commun_protection_vuepy-ligne-231)
- [`surface_ha(geometrie)` (commun_edition.py, ligne 39)](#surface_hageometrie-commun_editionpy-ligne-39)
- [`creer_action_outil(iface, canvas, nom_outil, chemin_icone, info_bulle, callback_toggled)` (commun_edition.py, ligne 300)](#creer_action_outiliface-canvas-nom_outil-chemin_icone-info_bulle-callback_toggled-commun_editionpy-ligne-300)
- [`basculer_outil_geometrique(outil, coche)` (commun_edition.py, ligne 336)](#basculer_outil_geometriqueoutil-coche-commun_editionpy-ligne-336)
- [`nettoyer_geometrie_base(geometrie)` (commun_topologie.py, ligne 33)](#nettoyer_geometrie_basegeometrie-commun_topologiepy-ligne-33)
- [`calculer_tolerance_aire(geometrie)` (commun_topologie.py, ligne 70)](#calculer_tolerance_airegeometrie-commun_topologiepy-ligne-70)
- [`limite_polygone(geometrie)` (commun_topologie.py, ligne 112)](#limite_polygonegeometrie-commun_topologiepy-ligne-112)
- [`morceaux_lineaires(geometrie)` (commun_topologie.py, ligne 163)](#morceaux_lineairesgeometrie-commun_topologiepy-ligne-163)
- [`longueur_lineaire(geometrie)` (commun_topologie.py, ligne 204)](#longueur_lineairegeometrie-commun_topologiepy-ligne-204)
- [`trouver_entites_intersectees(couche, geometrie, fids_exclus=None)` (commun_topologie.py, ligne 372)](#trouver_entites_intersecteescouche-geometrie-fids_exclusnone-commun_topologiepy-ligne-372)
- [`construire_geometrie_emprise_locale(couche_emprise, rectangle_cible, crs_cible=None)` (commun_topologie.py, ligne 395)](#construire_geometrie_emprise_localecouche_emprise-rectangle_cible-crs_ciblenone-commun_topologiepy-ligne-395)
- [`_supprimer_anneaux_interieurs(geometrie)` (commun_topologie.py, ligne 454)](#_supprimer_anneaux_interieursgeometrie-commun_topologiepy-ligne-454)
- [`nettoyer_geometrie_decoupee_protegee(couche, geometrie, fids_exclus=None, tolerance_m=None)` (commun_topologie.py, ligne 518)](#nettoyer_geometrie_decoupee_protegeecouche-geometrie-fids_exclusnone-tolerance_mnone-commun_topologiepy-ligne-518)
- [`fusionner_geometries(geometries)` (commun_topologie.py, ligne 609)](#fusionner_geometriesgeometries-commun_topologiepy-ligne-609)
- [`extraire_parties_polygonales(geometrie, surface_minimale=0.0, rendre_valide=True)` (commun_topologie.py, ligne 809)](#extraire_parties_polygonalesgeometrie-surface_minimale00-rendre_validetrue-commun_topologiepy-ligne-809)
- [`reunir_parties_polygonales(geometrie, surface_minimale=0.0, rendre_valide=True)` (commun_topologie.py, ligne 886)](#reunir_parties_polygonalesgeometrie-surface_minimale00-rendre_validetrue-commun_topologiepy-ligne-886)
- [`_decomposer_polygones_xy(geometrie)` (commun_topologie.py, ligne 1099)](#_decomposer_polygones_xygeometrie-commun_topologiepy-ligne-1099)
- [`nettoyer_geometrie_avance(geometrie)` (commun_topologie.py, ligne 1260)](#nettoyer_geometrie_avancegeometrie-commun_topologiepy-ligne-1260)
- [`_creer_contour_polygone(canvas, geometrie, couche, largeur, couleur=None, couleur_remplissage=None)` (commun_affichage.py, ligne 72)](#_creer_contour_polygonecanvas-geometrie-couche-largeur-couleurnone-couleur_remplissagenone-commun_affichagepy-ligne-72)
- [`SurbrillancePolygone.definir_visible(self, visible)` (commun_affichage.py, ligne 222)](#definir_visibleself-visible-commun_affichagepy-ligne-222)
- [`remplacer_surbrillance_polygone(canvas, surbrillance, geometrie, couche=None)` (commun_affichage.py, ligne 364)](#remplacer_surbrillance_polygonecanvas-surbrillance-geometrie-couchenone-commun_affichagepy-ligne-364)
- [`synchroniser_zone_outil(manager, iface, couche_parent, geometrie_zone, nom_commande)` (commun_synchronisation_alertes.py, ligne 102)](#synchroniser_zone_outilmanager-iface-couche_parent-geometrie_zone-nom_commande-commun_synchronisation_alertespy-ligne-102)
- [`_transformer_geometrie(geometrie, crs_source, crs_destination)` (commun_synchronisation_alertes.py, ligne 177)](#_transformer_geometriegeometrie-crs_source-crs_destination-commun_synchronisation_alertespy-ligne-177)
- [`CompteurAlertes.suspendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 397)](#suspendre_synchronisation_geometriqueself-commun_compteur_alertespy-ligne-397)
- [`CompteurAlertes.reprendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 411)](#reprendre_synchronisation_geometriqueself-commun_compteur_alertespy-ligne-411)
- [`CompteurAlertes._synchronisation_geometrique_suspendue(self)` (commun_compteur_alertes.py, ligne 419)](#_synchronisation_geometrique_suspendueself-commun_compteur_alertespy-ligne-419)
- [`CompteurAlertes.synchroniser_modification_geometrique(self, couche_parent, geometrie_zone, nom_commande)` (commun_compteur_alertes.py, ligne 422)](#synchroniser_modification_geometriqueself-couche_parent-geometrie_zone-nom_commande-commun_compteur_alertespy-ligne-422)
- [`CompteurAlertes._commande_parent_demarre(self, _texte=None)` (commun_compteur_alertes.py, ligne 631)](#_commande_parent_demarreself-_textenone-commun_compteur_alertespy-ligne-631)
- [`CompteurAlertes._commande_parent_terminee(self)` (commun_compteur_alertes.py, ligne 648)](#_commande_parent_termineeself-commun_compteur_alertespy-ligne-648)
- [`CompteurAlertes._memoriser_zone_geometrique(self, rectangle)` (commun_compteur_alertes.py, ligne 691)](#_memoriser_zone_geometriqueself-rectangle-commun_compteur_alertespy-ligne-691)
- [`CompteurAlertes._executer_recalcul_geometrique_differe(self, rectangle, *_args)` (commun_compteur_alertes.py, ligne 735)](#_executer_recalcul_geometrique_differeself-rectangle-_args-commun_compteur_alertespy-ligne-735)
- [`CompteurAlertes._geometrie_parent_modifiee(self, fid, geometrie)` (commun_compteur_alertes.py, ligne 786)](#_geometrie_parent_modifieeself-fid-geometrie-commun_compteur_alertespy-ligne-786)
- [`CreerPolygonePlugin._preparer_creation(self, geometrie_dessinee)` (edition_creer.py, ligne 301)](#_preparer_creationself-geometrie_dessinee-edition_creerpy-ligne-301)
- [`CreerPolygonePlugin._appliquer_creation(self, preparation)` (edition_creer.py, ligne 403)](#_appliquer_creationself-preparation-vue_stable_pendant_modification-edition_creerpy-ligne-403)
- [`FusionnerBdForetPlugin._preparer_fusion(self, fids=None)` (edition_fusionner.py, ligne 511)](#_preparer_fusionself-fidsnone-edition_fusionnerpy-ligne-511)
- [`_distance_point_geometrie(point, geometrie)` (edition_remodeler.py, ligne 51)](#_distance_point_geometriepoint-geometrie-edition_remodelerpy-ligne-51)
- [`_creer_ligne_surbrillance(canvas, geometrie, couche, couleur, largeur)` (edition_remodeler.py, ligne 63)](#_creer_ligne_surbrillancecanvas-geometrie-couche-couleur-largeur-edition_remodelerpy-ligne-63)
- [`RemodelerBdForetPlugin._appliquer_remodelage(self, nouvelles, zone_sync)` (edition_remodeler.py, ligne 562)](#_appliquer_remodelageself-nouvelles-zone_sync-vue_stable_pendant_modification-edition_remodelerpy-ligne-562)
- [`_extraire_local(grande_geometrie, geometrie_reference, marge=1.0)` (edition_reporter_bdfv2.py, ligne 80)](#_extraire_localgrande_geometrie-geometrie_reference-marge10-edition_reporter_bdfv2py-ligne-80)
- [`_fusionner_localement(grande_geometrie, petite_geometrie)` (edition_reporter_bdfv2.py, ligne 104)](#_fusionner_localementgrande_geometrie-petite_geometrie-edition_reporter_bdfv2py-ligne-104)
- [`ReporterBdFv2Plugin._preparer_report(self, geometrie_v2, entite_v2, prefixe='Report BDFv2')` (edition_reporter_bdfv2.py, ligne 506)](#_preparer_reportself-geometrie_v2-entite_v2-prefixereport-bdfv2-edition_reporter_bdfv2py-ligne-506)
- [`ReporterBdFv2Plugin._appliquer_report(self, preparation)` (edition_reporter_bdfv2.py, ligne 696)](#_appliquer_reportself-preparation-vue_stable_pendant_modification-edition_reporter_bdfv2py-ligne-696)
- [`ClignotementVerification.afficher(self, geometries, couche_reference=None)` (verification.py, ligne 272)](#afficherself-geometries-couche_referencenone-verificationpy-ligne-272)
- [`VerificationBdForetPlugin._memoriser_ancienne_geometrie(self, fid)` (verification.py, ligne 625)](#_memoriser_ancienne_geometrieself-fid-verificationpy-ligne-625)
- [`VerificationBdForetPlugin._geometrie_modifiee(self, fid, _geometry)` (verification.py, ligne 640)](#_geometrie_modifieeself-fid-_geometry-verificationpy-ligne-640)
- [`VerificationBdForetPlugin._geometrie_depuis_wkb(wkb)` (verification.py, ligne 1215)](#_geometrie_depuis_wkbwkb-staticmethod-verificationpy-ligne-1215)
- [`VerificationBdForetPlugin._geometries_recouvrements_depuis_wkb(cls, recouvrements)` (verification.py, ligne 1234)](#_geometries_recouvrements_depuis_wkbcls-recouvrements-classmethod-verificationpy-ligne-1234)
- [`VerificationBdForetPlugin._recharger_entites_modifiees(self, pending, affected, affected_rect, has_rect)` (verification.py, ligne 1616)](#_recharger_entites_modifieesself-pending-affected-affected_rect-has_rect-verificationpy-ligne-1616)
- [`VerificationBdForetPlugin._ajouter_geometrie_surbrillance(self, layer, entites, cles_traitees, cle, categorie, geometrie, decouper_emprise=True)` (verification.py, ligne 2134)](#_ajouter_geometrie_surbrillanceself-layer-entites-cles_traitees-cle-categorie-geometrie-decouper_emprisetrue-verificationpy-ligne-2134)
- [`VerificationBdForetPlugin.faire_clignoter(self, payload)` (verification.py, ligne 2178)](#faire_clignoterself-payload-verificationpy-ligne-2178)
- [`VerificationBdForetPlugin.zoomer_sur_entites(self, fids)` (verification.py, ligne 2276)](#zoomer_sur_entitesself-fids-verificationpy-ligne-2276)
- [`TacheRelationsVoisines._geometrie_depuis_wkb(wkb)` (verification_tache_relations.py, ligne 41)](#_geometrie_depuis_wkbwkb-staticmethod-verification_tache_relationspy-ligne-41)
- [`_traiter_lot_conformite(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 270)](#_traiter_lot_conformitecouche-etat-taille_lot-verification_nettoyage_automatiquepy-ligne-270)
- [`_fusionner_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_nettoyage_automatique.py, ligne 301)](#_fusionner_dans_voisincouche-petite_geometrie-fid_voisin-verification_nettoyage_automatiquepy-ligne-301)
- [`_construire_cache_travail(couche)` (verification_nettoyage_automatique.py, ligne 438)](#_construire_cache_travailcouche-verification_nettoyage_automatiquepy-ligne-438)
- [`_reparer_couche_native(couche_memoire)` (verification_nettoyage_automatique.py, ligne 571)](#_reparer_couche_nativecouche_memoire-verification_nettoyage_automatiquepy-ligne-571)
- [`_fusionner_petite_geometrie_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_recouvrements.py, ligne 95)](#_fusionner_petite_geometrie_dans_voisincouche-petite_geometrie-fid_voisin-verification_recouvrementspy-ligne-95)
- [`_union_geometries(geometries)` (verification_trous.py, ligne 189)](#_union_geometriesgeometries-verification_trouspy-ligne-189)
- [`geometrie_emprise_locale(self, rect)` (verification_trous.py, ligne 227)](#geometrie_emprise_localeself-rect-verification_trouspy-ligne-227)
- [`decouper_a_emprise_locale(self, geometrie)` (verification_trous.py, ligne 237)](#decouper_a_emprise_localeself-geometrie-verification_trouspy-ligne-237)
- [`_preparer_geometrie_trou(self, couche, gap_index)` (verification_trous.py, ligne 250)](#_preparer_geometrie_trouself-couche-gap_index-verification_trouspy-ligne-250)
- [`_materialiser_trou(self, couche, geometrie, nom_commande)` (verification_trous.py, ligne 335)](#_materialiser_trouself-couche-geometrie-nom_commande-verification_trouspy-ligne-335)
- [`reboucher_trou(self, gap_index)` (verification_trous.py, ligne 383)](#reboucher_trouself-gap_index-vue_stable_pendant_modification-verification_trouspy-ligne-383)

### Formulaire

- [`EtatSessionProjet.memoriser_formulaire(self, couche, fid, _vue_formulaire=True)` (commun_etat_session.py, ligne 147)](#memoriser_formulaireself-couche-fid-_vue_formulairetrue-commun_etat_sessionpy-ligne-147)
- [`ouvrir_formulaire_ou_annuler(iface, couche, canvas, entite, nom_outil)` (commun_edition.py, ligne 623)](#ouvrir_formulaire_ou_annuleriface-couche-canvas-entite-nom_outil-commun_editionpy-ligne-623)
- [`_widgets_relation_alertes_ouverts(iface)` (commun_synchronisation_alertes.py, ligne 394)](#_widgets_relation_alertes_ouvertsiface-commun_synchronisation_alertespy-ligne-394)
- [`CompteurAlertes._traiter_commandes_parent_en_attente(self)` (commun_compteur_alertes.py, ligne 947)](#_traiter_commandes_parent_en_attenteself-commun_compteur_alertespy-ligne-947)
- [`CompteurAlertes._rafraichir_formulaire_parent(self, fid_parent)` (commun_compteur_alertes.py, ligne 1846)](#_rafraichir_formulaire_parentself-fid_parent-commun_compteur_alertespy-ligne-1846)
- [Classe `HistoriqueFormulaires` (commun_historique_formulaires.py, ligne 24)](#classe-historiqueformulaires-commun_historique_formulairespy-ligne-24)
- [`HistoriqueFormulaires.__init__(self, iface)` (commun_historique_formulaires.py, ligne 32)](#__init__self-iface-commun_historique_formulairespy-ligne-32)
- [`HistoriqueFormulaires.initGui(self)` (commun_historique_formulaires.py, ligne 57)](#initguiself-commun_historique_formulairespy-ligne-57)
- [`HistoriqueFormulaires.unload(self)` (commun_historique_formulaires.py, ligne 79)](#unloadself-commun_historique_formulairespy-ligne-79)
- [`HistoriqueFormulaires._focus_change(self, _ancien, nouveau)` (commun_historique_formulaires.py, ligne 98)](#_focus_changeself-_ancien-nouveau-commun_historique_formulairespy-ligne-98)
- [`HistoriqueFormulaires._verifier_fenetre_differee(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 129)](#_verifier_fenetre_differeeself-reference_fenetre-commun_historique_formulairespy-ligne-129)
- [`HistoriqueFormulaires.detecter_tables(self)` (commun_historique_formulaires.py, ligne 148)](#detecter_tablesself-commun_historique_formulairespy-ligne-148)
- [`HistoriqueFormulaires.connecter_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 185)](#connecter_fenetreself-fenetre-commun_historique_formulairespy-ligne-185)
- [`HistoriqueFormulaires._memoriser_scroll_avant_reset(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 283)](#_memoriser_scroll_avant_resetself-reference_fenetre-commun_historique_formulairespy-ligne-283)
- [`HistoriqueFormulaires._restaurer_scroll_apres_reset(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 303)](#_restaurer_scroll_apres_resetself-reference_fenetre-commun_historique_formulairespy-ligne-303)
- [`HistoriqueFormulaires._appliquer_scroll_si_valide(self, reference_fenetre, valeur)` (commun_historique_formulaires.py, ligne 321)](#_appliquer_scroll_si_valideself-reference_fenetre-valeur-commun_historique_formulairespy-ligne-321)
- [`HistoriqueFormulaires._trouver_composants_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 342)](#_trouver_composants_fenetreself-fenetre-commun_historique_formulairespy-ligne-342)
- [`HistoriqueFormulaires._trouver_liste_principale(main_view_widget)` (commun_historique_formulaires.py, ligne 363)](#_trouver_liste_principalemain_view_widget-staticmethod-commun_historique_formulairespy-ligne-363)
- [`HistoriqueFormulaires._trouver_barre_outils(fenetre)` (commun_historique_formulaires.py, ligne 402)](#_trouver_barre_outilsfenetre-staticmethod-commun_historique_formulairespy-ligne-402)
- [`HistoriqueFormulaires._creer_actions(self, fenetre, toolbar)` (commun_historique_formulaires.py, ligne 419)](#_creer_actionsself-fenetre-toolbar-commun_historique_formulairespy-ligne-419)
- [`HistoriqueFormulaires._creer_action(self, fenetre, icone, texte, nom_objet, info_bulle)` (commun_historique_formulaires.py, ligne 474)](#_creer_actionself-fenetre-icone-texte-nom_objet-info_bulle-commun_historique_formulairespy-ligne-474)
- [`HistoriqueFormulaires._trouver_action(toolbar, nom)` (commun_historique_formulaires.py, ligne 482)](#_trouver_actiontoolbar-nom-staticmethod-commun_historique_formulairespy-ligne-482)
- [`HistoriqueFormulaires.definir_etat_formulaire(self, callback)` (commun_historique_formulaires.py, ligne 491)](#definir_etat_formulaireself-callback-commun_historique_formulairespy-ligne-491)
- [`HistoriqueFormulaires.definir_fid_persistant(self, callback)` (commun_historique_formulaires.py, ligne 495)](#definir_fid_persistantself-callback-commun_historique_formulairespy-ligne-495)
- [`HistoriqueFormulaires._notifier_etat_formulaire(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 499)](#_notifier_etat_formulaireself-fenetre-fid-commun_historique_formulairespy-ligne-499)
- [`HistoriqueFormulaires.definir_recalcul_alertes(self, callback)` (commun_historique_formulaires.py, ligne 515)](#definir_recalcul_alertesself-callback-commun_historique_formulairespy-ligne-515)
- [`HistoriqueFormulaires.recalculer_alertes(self)` (commun_historique_formulaires.py, ligne 527)](#recalculer_alertesself-commun_historique_formulairespy-ligne-527)
- [`HistoriqueFormulaires._couche_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 540)](#_couche_fenetreself-fenetre-commun_historique_formulairespy-ligne-540)
- [`HistoriqueFormulaires._cle_couche(couche)` (commun_historique_formulaires.py, ligne 555)](#_cle_couchecouche-staticmethod-commun_historique_formulairespy-ligne-555)
- [`HistoriqueFormulaires._memoriser_derniere_fiche(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 562)](#_memoriser_derniere_ficheself-fenetre-fid-commun_historique_formulairespy-ligne-562)
- [`HistoriqueFormulaires._restaurer_derniere_fiche(self, fenetre)` (commun_historique_formulaires.py, ligne 573)](#_restaurer_derniere_ficheself-fenetre-commun_historique_formulairespy-ligne-573)
- [`HistoriqueFormulaires.fiche_changee(self, fenetre, feature)` (commun_historique_formulaires.py, ligne 623)](#fiche_changeeself-fenetre-feature-commun_historique_formulairespy-ligne-623)
- [`HistoriqueFormulaires.enregistrer_fiche_initiale(self, fenetre)` (commun_historique_formulaires.py, ligne 636)](#enregistrer_fiche_initialeself-fenetre-commun_historique_formulairespy-ligne-636)
- [`HistoriqueFormulaires.ajouter_fid_historique(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 649)](#ajouter_fid_historiqueself-fenetre-fid-commun_historique_formulairespy-ligne-649)
- [`HistoriqueFormulaires.revenir_precedent(self, fenetre)` (commun_historique_formulaires.py, ligne 678)](#revenir_precedentself-fenetre-commun_historique_formulairespy-ligne-678)
- [`HistoriqueFormulaires.aller_suivant(self, fenetre)` (commun_historique_formulaires.py, ligne 683)](#aller_suivantself-fenetre-commun_historique_formulairespy-ligne-683)
- [`HistoriqueFormulaires.ouvrir_position(self, fenetre, nouvelle_position)` (commun_historique_formulaires.py, ligne 690)](#ouvrir_positionself-fenetre-nouvelle_position-commun_historique_formulairespy-ligne-690)
- [`HistoriqueFormulaires.mettre_a_jour_actions(self, fenetre)` (commun_historique_formulaires.py, ligne 718)](#mettre_a_jour_actionsself-fenetre-commun_historique_formulairespy-ligne-718)
- [`HistoriqueFormulaires.geler_fiche_si_fid_supprime(self, couche, fids_supprimes)` (commun_historique_formulaires.py, ligne 735)](#geler_fiche_si_fid_supprimeself-couche-fids_supprimes-commun_historique_formulairespy-ligne-735)
- [`HistoriqueFormulaires.liberer_gel_fiche(self, gels)` (commun_historique_formulaires.py, ligne 778)](#liberer_gel_ficheself-gels-commun_historique_formulairespy-ligne-778)
- [`HistoriqueFormulaires.capturer_contexte_visuel_couche(self, couche, fids_supprimes_prevus=None)` (commun_historique_formulaires.py, ligne 805)](#capturer_contexte_visuel_coucheself-couche-fids_supprimes_prevusnone-commun_historique_formulairespy-ligne-805)
- [`HistoriqueFormulaires.deplacer_fiche_avant_suppression(self, couche, contexte)` (commun_historique_formulaires.py, ligne 891)](#deplacer_fiche_avant_suppressionself-couche-contexte-commun_historique_formulairespy-ligne-891)
- [`HistoriqueFormulaires.assainir_fiche_apres_suppression(self, couche, fid_supprime)` (commun_historique_formulaires.py, ligne 956)](#assainir_fiche_apres_suppressionself-couche-fid_supprime-commun_historique_formulairespy-ligne-956)
- [`HistoriqueFormulaires._restaurer_contexte_visuel_une_fois(self, couche, contexte, fid_remplacement=None)` (commun_historique_formulaires.py, ligne 1028)](#_restaurer_contexte_visuel_une_foisself-couche-contexte-fid_remplacementnone-commun_historique_formulairespy-ligne-1028)
- [`HistoriqueFormulaires.restaurer_contexte_visuel_couche(self, couche, contexte, fid_remplacement=None, restaurer_fid=True)` (commun_historique_formulaires.py, ligne 1122)](#restaurer_contexte_visuel_coucheself-couche-contexte-fid_remplacementnone-restaurer_fidtrue-commun_historique_formulairespy-ligne-1122)
- [`HistoriqueFormulaires.fenetre_detruite(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 1158)](#fenetre_detruiteself-reference_fenetre-commun_historique_formulairespy-ligne-1158)
- [`HistoriqueFormulaires._objet_qt_valide(objet)` (commun_historique_formulaires.py, ligne 1167)](#_objet_qt_valideobjet-staticmethod-commun_historique_formulairespy-ligne-1167)
- [`HistoriqueFormulaires.deconnecter_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 1181)](#deconnecter_fenetreself-fenetre-commun_historique_formulairespy-ligne-1181)
- [`CreerPolygonePlugin._ouvrir_formulaire(self, fid)` (edition_creer.py, ligne 459)](#_ouvrir_formulaireself-fid-edition_creerpy-ligne-459)
- [`SeparerPolygonePlugin._ouvrir_formulaire(self, fid)` (edition_separer.py, ligne 759)](#_ouvrir_formulaireself-fid-edition_separerpy-ligne-759)
- [`FusionnerBdForetPlugin._ouvrir_formulaire(self, fid_reference)` (edition_fusionner.py, ligne 794)](#_ouvrir_formulaireself-fid_reference-edition_fusionnerpy-ligne-794)
- [`ReporterBdFv2Plugin._ouvrir_formulaire(self, fid)` (edition_reporter_bdfv2.py, ligne 752)](#_ouvrir_formulaireself-fid-edition_reporter_bdfv2py-ligne-752)

### Thread / tâche de fond

- [`VerificationBdForetPlugin._demarrer_preparation_paires(self, etat)` (verification.py, ligne 1060)](#_demarrer_preparation_pairesself-etat-verificationpy-ligne-1060)
- [`VerificationBdForetPlugin._tache_relations_terminee(self, generation, task, succes, resultats, erreur)` (verification.py, ligne 1171)](#_tache_relations_termineeself-generation-task-succes-resultats-erreur-verificationpy-ligne-1171)
- [`VerificationBdForetPlugin._geometrie_depuis_wkb(wkb)` (verification.py, ligne 1215)](#_geometrie_depuis_wkbwkb-staticmethod-verificationpy-ligne-1215)
- [`VerificationBdForetPlugin._finaliser_controle_complet(self, contexte, adjacent_pairs, overlaps)` (verification.py, ligne 1242)](#_finaliser_controle_completself-contexte-adjacent_pairs-overlaps-verificationpy-ligne-1242)
- [`VerificationBdForetPlugin._annuler_tache_relations(self)` (verification.py, ligne 1376)](#_annuler_tache_relationsself-verificationpy-ligne-1376)
- [Classe `TacheRelationsVoisines(QgsTask)` (verification_tache_relations.py, ligne 23)](#classe-tacherelationsvoisinesqgstask-verification_tache_relationspy-ligne-23)
- [`TacheRelationsVoisines.__init__(self, donnees, paires_candidates, regles_activees, callback)` (verification_tache_relations.py, ligne 26)](#__init__self-donnees-paires_candidates-regles_activees-callback-verification_tache_relationspy-ligne-26)
- [`TacheRelationsVoisines._geometrie_depuis_wkb(wkb)` (verification_tache_relations.py, ligne 41)](#_geometrie_depuis_wkbwkb-staticmethod-verification_tache_relationspy-ligne-41)
- [`TacheRelationsVoisines.run(self)` (verification_tache_relations.py, ligne 54)](#runself-verification_tache_relationspy-ligne-54)
- [`TacheRelationsVoisines.finished(self, succes)` (verification_tache_relations.py, ligne 165)](#finishedself-succes-verification_tache_relationspy-ligne-165)

### Surbrillance / hachures

- [`basculer_cible_surbrillance(outil, x, y, ctrl_appuye, outil_identification)` (commun_edition.py, ligne 556)](#basculer_cible_surbrillanceoutil-x-y-ctrl_appuye-outil_identification-commun_editionpy-ligne-556)
- [`retirer_cible_surbrillance(outil, fid)` (commun_edition.py, ligne 594)](#retirer_cible_surbrillanceoutil-fid-commun_editionpy-ligne-594)
- [`effacer_cibles_surbrillance(outil, rafraichir=True)` (commun_edition.py, ligne 604)](#effacer_cibles_surbrillanceoutil-rafraichirtrue-commun_editionpy-ligne-604)
- [`_distance_retrait_surbrillance(canvas, geometrie, couche)` (commun_affichage.py, ligne 90)](#_distance_retrait_surbrillancecanvas-geometrie-couche-commun_affichagepy-ligne-90)
- [Classe `SurbrillancePolygone` (commun_affichage.py, ligne 159)](#classe-surbrillancepolygone-commun_affichagepy-ligne-159)
- [`SurbrillancePolygone.__init__(self, canvas, geometrie, couche=None, couleur=None, couleur_remplissage=None)` (commun_affichage.py, ligne 162)](#__init__self-canvas-geometrie-couchenone-couleurnone-couleur_remplissagenone-commun_affichagepy-ligne-162)
- [`SurbrillancePolygone.contours(self)` (commun_affichage.py, ligne 211)](#contoursself-commun_affichagepy-ligne-211)
- [`SurbrillancePolygone.definir_visible(self, visible)` (commun_affichage.py, ligne 222)](#definir_visibleself-visible-commun_affichagepy-ligne-222)
- [`SurbrillancePolygone._mettre_a_jour_interieur(self, *args)` (commun_affichage.py, ligne 231)](#_mettre_a_jour_interieurself-args-commun_affichagepy-ligne-231)
- [`SurbrillancePolygone.supprimer(self)` (commun_affichage.py, ligne 277)](#supprimerself-commun_affichagepy-ligne-277)
- [`creer_surbrillance_polygone(canvas, geometrie, couche=None, couleur=None, couleur_remplissage=None)` (commun_affichage.py, ligne 311)](#creer_surbrillance_polygonecanvas-geometrie-couchenone-couleurnone-couleur_remplissagenone-commun_affichagepy-ligne-311)
- [`supprimer_surbrillance_polygone(canvas, surbrillance)` (commun_affichage.py, ligne 326)](#supprimer_surbrillance_polygonecanvas-surbrillance-commun_affichagepy-ligne-326)
- [`supprimer_surbrillances_polygones(canvas, surbrillances)` (commun_affichage.py, ligne 358)](#supprimer_surbrillances_polygonescanvas-surbrillances-commun_affichagepy-ligne-358)
- [`remplacer_surbrillance_polygone(canvas, surbrillance, geometrie, couche=None)` (commun_affichage.py, ligne 364)](#remplacer_surbrillance_polygonecanvas-surbrillance-geometrie-couchenone-commun_affichagepy-ligne-364)
- [Classe `OutilSelectionSeparation(QgsMapToolIdentify)` (edition_separer.py, ligne 47)](#classe-outilselectionseparationqgsmaptoolidentify-edition_separerpy-ligne-47)
- [`SeparerPolygonePlugin._trouver_parent_nouveau_morceau(self, geometrie, geometries_sources)` (edition_separer.py, ligne 597)](#_trouver_parent_nouveau_morceauself-geometrie-geometries_sources-edition_separerpy-ligne-597)
- [`_creer_ligne_surbrillance(canvas, geometrie, couche, couleur, largeur)` (edition_remodeler.py, ligne 63)](#_creer_ligne_surbrillancecanvas-geometrie-couche-couleur-largeur-edition_remodelerpy-ligne-63)
- [`_supprimer_ligne_surbrillance(canvas, bande)` (edition_remodeler.py, ligne 82)](#_supprimer_ligne_surbrillancecanvas-bande-edition_remodelerpy-ligne-82)
- [`RemodelerBdForetPlugin._supprimer_surbrillance_frontiere(self)` (edition_remodeler.py, ligne 311)](#_supprimer_surbrillance_frontiereself-edition_remodelerpy-ligne-311)
- [Classe `CoucheSurbrillanceVerification` (verification.py, ligne 120)](#classe-couchesurbrillanceverification-verificationpy-ligne-120)
- [`CoucheSurbrillanceVerification.__init__(self)` (verification.py, ligne 123)](#__init__self-verificationpy-ligne-123)
- [`CoucheSurbrillanceVerification.detacher(self)` (verification.py, ligne 126)](#detacherself-verificationpy-ligne-126)
- [`CoucheSurbrillanceVerification.courante(self)` (verification.py, ligne 130)](#couranteself-verificationpy-ligne-130)
- [`CoucheSurbrillanceVerification.prochain_nom()` (verification.py, ligne 141)](#prochain_nom-staticmethod-verificationpy-ligne-141)
- [`CoucheSurbrillanceVerification.assurer(self, couche_travail)` (verification.py, ligne 156)](#assurerself-couche_travail-verificationpy-ligne-156)
- [`CoucheSurbrillanceVerification._ajouter_au_projet(couche, couche_travail)` (verification.py, ligne 195)](#_ajouter_au_projetcouche-couche_travail-staticmethod-verificationpy-ligne-195)
- [`CoucheSurbrillanceVerification.remplacer_entites(self, couche_travail, entites)` (verification.py, ligne 215)](#remplacer_entitesself-couche_travail-entites-verificationpy-ligne-215)
- [`_contours_surbrillance(surbrillance)` (verification.py, ligne 240)](#_contours_surbrillancesurbrillance-verificationpy-ligne-240)
- [`_definir_surbrillance_visible(surbrillance, visible)` (verification.py, ligne 251)](#_definir_surbrillance_visiblesurbrillance-visible-verificationpy-ligne-251)
- [`VerificationBdForetPlugin._synchroniser_couche_surbrillance(self)` (verification.py, ligne 2053)](#_synchroniser_couche_surbrillanceself-verificationpy-ligne-2053)
- [`VerificationBdForetPlugin._construire_entites_surbrillance(self, layer)` (verification.py, ligne 2061)](#_construire_entites_surbrillanceself-layer-verificationpy-ligne-2061)
- [`VerificationBdForetPlugin._ajouter_geometrie_surbrillance(self, layer, entites, cles_traitees, cle, categorie, geometrie, decouper_emprise=True)` (verification.py, ligne 2134)](#_ajouter_geometrie_surbrillanceself-layer-entites-cles_traitees-cle-categorie-geometrie-decouper_emprisetrue-verificationpy-ligne-2134)
- [`modifier_attributs_entite(self, fid)` (verification_coherence_essence_tff.py, ligne 82)](#modifier_attributs_entiteself-fid-verification_coherence_essence_tffpy-ligne-82)

## `__init__.py`

Initialisation standard du plugin QGIS.

**Dépendances internes directes :** `commun_outils.py`

### `classFactory(iface)` (__init__.py, ligne 9)

Fonction appelée par QGIS lors du chargement du plugin.

## `commun_outils.py`

Point d'entrée du plugin Reprise PI.

**Dépendances internes directes :** `commun_compteur_alertes.py`, `commun_etat_session.py`, `commun_historique_formulaires.py`, `commun_protection_vue.py`, `edition_creer.py`, `edition_fusionner.py`, `edition_remodeler.py`, `edition_reporter_bdfv2.py`, `edition_separer.py`, `verification.py`

### Classe `OutilsBdForet` (commun_outils.py, ligne 20)

Charge, coordonne et décharge les outils de Reprise PI.

#### `__init__(self, iface)` (commun_outils.py, ligne 23)

Pas de docstring.

#### `initGui(self)` (commun_outils.py, ligne 83)

Pas de docstring.

#### `unload(self)` (commun_outils.py, ligne 87)

Pas de docstring.

#### `desactiver_autres_outils_geometriques(self, outil_actif)` (commun_outils.py, ligne 99)

Désactive tous les outils géométriques sauf celui qui prend la main.

## `commun_parametres.py`

Paramètres communs du plugin Reprise PI.

### `resoudre_champs(self)` (commun_parametres.py, ligne 83)

Associe chaque nom logique de ALIAS_ATTRIBUTS au vrai nom de champ de la couche.

### `normaliser_valeur(value)` (commun_parametres.py, ligne 106)

Texte comparable pour un champ non booléen (NULL/None -> chaîne vide).

### `normaliser_booleen(value)` (commun_parametres.py, ligne 113)

Booléen comparable pour un champ coché/texte/entier selon la couche source.

### `signature_attributs(feature, field_map)` (commun_parametres.py, ligne 124)

Retourne la signature normalisée utilisée pour comparer deux entités.

## `commun_couches.py`

Recherche et validation des couches utilisées par Reprise PI.

**Dépendances internes directes :** `commun_parametres.py`

### `couche_est_disponible(couche)` (commun_couches.py, ligne 17)

Indique si le wrapper Python pointe encore vers une couche QGIS vivante.

### `normaliser_nom(nom)` (commun_couches.py, ligne 32)

Met un nom en minuscules et supprime les accents.

### `est_couche_polygonale(couche)` (commun_couches.py, ligne 46)

Indique si ``couche`` est une couche vectorielle polygonale.

### `trouver_couche_travail(iface=None)` (commun_couches.py, ligne 56)

Retourne la couche BD Forêt destinée aux reprises.

### `trouver_couche_emprise()` (commun_couches.py, ligne 76)

Retourne la couche polygonale servant d'emprise de production.

### `message_couche_travail_absente()` (commun_couches.py, ligne 101)

Message commun affiché lorsque la couche de travail est introuvable.

### `valider_couche_modifiable(couche)` (commun_couches.py, ligne 109)

Retourne ``None`` si la couche est modifiable, sinon un message d'erreur.

### `_trouver_couche_par_prefixe(prefixe, iface=None, couche_valide=None, prioriser_edition=False)` (commun_couches.py, ligne 118)

Moteur commun : retourne la couche dont le nom commence par ``prefixe``.

### `trouver_couche_alertes(iface=None)` (commun_couches.py, ligne 161)

Retourne la couche dont le nom normalisé commence par

## `commun_etat_session.py`

Mémoire légère de la dernière fiche consultée entre deux sessions QGIS.

**Dépendances internes directes :** `commun_couches.py`, `commun_parametres.py`

### Classe `EtatSessionProjet` (commun_etat_session.py, ligne 24)

Persiste uniquement le dernier FID de travail du projet.

#### `__init__(self, iface)` (commun_etat_session.py, ligne 31)

Pas de docstring.

#### `initGui(self)` (commun_etat_session.py, ligne 40)

Pas de docstring.

#### `unload(self)` (commun_etat_session.py, ligne 57)

Pas de docstring.

#### `_chemin_projet(self)` (commun_etat_session.py, ligne 77)

Pas de docstring.

#### `_cle_reglage(cls, chemin)` *(@classmethod)* (commun_etat_session.py, ligne 84)

Pas de docstring.

#### `_sauvegarder_etat(self, *args)` (commun_etat_session.py, ligne 93)

Écrit le dernier FID connu, sans inspecter l'interface QGIS.

#### `_lire_etat(self)` (commun_etat_session.py, ligne 112)

Pas de docstring.

#### `_projet_lu(self, *args)` (commun_etat_session.py, ligne 125)

Oublie seulement la mémoire RAM de l'ancien projet.

#### `_est_couche_parent(self, couche)` (commun_etat_session.py, ligne 137)

Pas de docstring.

#### `memoriser_formulaire(self, couche, fid, _vue_formulaire=True)` (commun_etat_session.py, ligne 147)

Mémorise le dernier FID en RAM, sans écriture disque immédiate.

#### `fid_memorise_pour_couche(self, couche)` (commun_etat_session.py, ligne 164)

Retourne le FID persistant de la couche s'il existe encore.

## `commun_protection_vue.py`

Protection commune de la vue cartographique pendant les éditions.

### Classe `ProtectionVueCarte` (commun_protection_vue.py, ligne 25)

Service partagé qui conserve la vue pendant une modification interne.

#### `__init__(self, canvas)` (commun_protection_vue.py, ligne 28)

Pas de docstring.

#### `modification(self)` *(@contextmanager)* (commun_protection_vue.py, ligne 40)

Protège la vue pendant une opération, avec support des appels imbriqués.

#### `_commencer(self)` (commun_protection_vue.py, ligne 48)

Pas de docstring.

#### `_terminer(self)` (commun_protection_vue.py, ligne 67)

Pas de docstring.

#### `_laisser_finir_evenements_differees()` *(@staticmethod)* (commun_protection_vue.py, ligne 109)

Exécute un tour complet de la boucle Qt puis rend immédiatement la main.

#### `_restaurer_vue_si_necessaire(self, emprise, rotation)` (commun_protection_vue.py, ligne 129)

Restaure uniquement si QGIS a réellement déplacé/rotaté le canevas.

#### `_restaurer_emprise(self, emprise)` (commun_protection_vue.py, ligne 145)

Restaure l'emprise en préservant autant que possible l'historique QGIS.

### `_rectangles_equivalents(a, b)` (commun_protection_vue.py, ligne 192)

Compare deux emprises avec une très petite tolérance numérique.

### `_service_pour_objet(objet)` (commun_protection_vue.py, ligne 206)

Retourne le service partagé du gestionnaire, ou un secours local.

### `vue_stable_pendant_modification(fonction)` (commun_protection_vue.py, ligne 231)

Décorateur commun pour toute action qui modifie la géométrie.

## `commun_edition.py`

Petites fonctions communes aux opérations d'édition QGIS.

**Dépendances internes directes :** `commun_affichage.py`, `commun_couches.py`, `commun_parametres.py`

### `surface_ha(geometrie)` (commun_edition.py, ligne 39)

Convertit l'aire d'une géométrie (m²) en hectares.

### `valeur_champ_texte(couche, feature, nom_champ, defaut='Non renseigné')` (commun_edition.py, ligne 52)

Valeur texte d'un champ d'une entité, ou un texte de repli si absente/vide.

### `prochain_id_foret(couche)` (commun_edition.py, ligne 66)

Retourne un nouvel ``id_foret`` numérique disponible.

### `indices_fid(couche)` (commun_edition.py, ligne 132)

Retourne les champs techniques servant de clé primaire au fournisseur.

### `creer_entite_nouvelle(couche, geometrie, attributs_reference)` (commun_edition.py, ligne 150)

Crée une entité en copiant les attributs utiles de l'entité source.

### `recuperer_entite(couche, fid)` (commun_edition.py, ligne 196)

Retourne une entité par FID, y compris depuis le tampon d'édition.

### `recuperer_entites(couche, fids)` (commun_edition.py, ligne 210)

Retourne un dictionnaire ``FID: entité`` pour les FID demandés.

### `fid_est_valide(couche, fid)` (commun_edition.py, ligne 219)

Indique si un FID peut encore recevoir une écriture dans la couche.

### `exiger_fid_valide(couche, fid, action="modifier l'entité")` (commun_edition.py, ligne 248)

Lève une erreur claire avant toute écriture sur un FID disparu.

### `annuler_derniere_commande(couche, canvas=None)` (commun_edition.py, ligne 259)

Annule la dernière commande d'édition et rafraîchit éventuellement la carte.

### `avertir_message_bar(iface, nom_outil, message)` (commun_edition.py, ligne 284)

Affiche un avertissement dans la barre de messages QGIS.

### `creer_action_outil(iface, canvas, nom_outil, chemin_icone, info_bulle, callback_toggled)` (commun_edition.py, ligne 300)

Crée la QAction standard d'un outil géométrique et la relie au canevas.

### `detruire_action_outil(iface, action, nom_outil, callback_toggled)` (commun_edition.py, ligne 316)

Détache et détruit la QAction créée par ``creer_action_outil``.

### `basculer_outil_geometrique(outil, coche)` (commun_edition.py, ligne 336)

Active ou désactive ``outil`` suite au basculement de sa QAction.

### `activer_couche_travail(iface)` (commun_edition.py, ligne 351)

Trouve la couche de travail et la rend immédiatement active dans QGIS.

### `obtenir_couche_editable(iface, nom_outil, couche_attendue=None, manager=None, outil=None)` (commun_edition.py, ligne 371)

Retourne ``(couche, est_editable)``, ou ``(None, False)`` si aucune

### `sans_reentrance(fonction)` (commun_edition.py, ligne 394)

Empêche une méthode de s'exécuter si un appel précédent est encore en cours.

### Classe `SurveillanceCoucheActive` (commun_edition.py, ligne 415)

Désactive un outil si sa couche sort d'édition, est supprimée, ou si le

#### `__init__(self, callback_perte)` (commun_edition.py, ligne 423)

Pas de docstring.

#### `demarrer(self)` (commun_edition.py, ligne 427)

À appeler une fois dans ``initGui()`` : écoute le projet en permanence.

#### `arreter(self)` (commun_edition.py, ligne 433)

À appeler une fois dans ``unload()``.

#### `surveiller_couche(self, couche)` (commun_edition.py, ligne 446)

À appeler dans ``_activer()``, une fois la couche en édition.

#### `oublier_couche(self)` (commun_edition.py, ligne 457)

À appeler dans ``_desactiver()``.

#### `_couches_supprimees(self, ids_couches)` (commun_edition.py, ligne 467)

Signal layersRemoved : vérifie que la couche surveillée n'y est pas.

#### `_projet_vide(self, *args)` (commun_edition.py, ligne 475)

Signal cleared : le projet entier vient d'être vidé (fermeture/nouveau projet).

#### `_edition_arretee(self, *args)` (commun_edition.py, ligne 480)

Signal editingStopped de la couche surveillée elle-même.

#### `_declencher(self)` (commun_edition.py, ligne 484)

Point commun aux trois cas de perte : oublie la couche puis prévient l'outil.

### Classe `AttenteDebutEdition` (commun_edition.py, ligne 490)

Mémorise une activation d'outil jusqu'au début de l'édition QGIS.

#### `__init__(self, callback)` (commun_edition.py, ligne 499)

Pas de docstring.

#### `en_attente(self)` *(@property)* (commun_edition.py, ligne 504)

Pas de docstring.

#### `attendre(self, couche)` (commun_edition.py, ligne 507)

Attend ``editingStarted`` sur ``couche`` sans multiplier les signaux.

#### `annuler(self)` (commun_edition.py, ligne 525)

Supprime l'attente courante, si elle existe.

#### `_edition_demarree(self, *args)` (commun_edition.py, ligne 536)

Déclenche une seule fois l'activation demandée.

### `basculer_cible_surbrillance(outil, x, y, ctrl_appuye, outil_identification)` (commun_edition.py, ligne 556)

Ajoute ou retire, sous le clic, une entité de la sélection en surbrillance.

### `retirer_cible_surbrillance(outil, fid)` (commun_edition.py, ligne 594)

Retire une cible de la sélection en surbrillance de ``outil``.

### `effacer_cibles_surbrillance(outil, rafraichir=True)` (commun_edition.py, ligne 604)

Vide entièrement la sélection en surbrillance de ``outil``.

### `ouvrir_formulaire_ou_annuler(iface, couche, canvas, entite, nom_outil)` (commun_edition.py, ligne 623)

Ouvre la fiche d'une entité déjà écrite en couche, avec annulation propre.

## `commun_topologie.py`

Fonctions géométriques communes aux outils de Reprise PI.

**Dépendances internes directes :** `commun_couches.py`, `commun_parametres.py`

### `nettoyer_geometrie_base(geometrie)` (commun_topologie.py, ligne 33)

Retourne une géométrie polygonale valide ou ``None``.

### `calculer_tolerance_aire(geometrie)` (commun_topologie.py, ligne 70)

Retourne une petite tolérance d'aire adaptée à la géométrie.

### `compter_parties_polygonales(geometrie)` (commun_topologie.py, ligne 83)

Compte uniquement les composantes polygonales ayant une aire réelle.

### `limite_polygone(geometrie)` (commun_topologie.py, ligne 112)

Reconstruit la bordure d'un polygone comme géométrie de lignes.

### `morceaux_lineaires(geometrie)` (commun_topologie.py, ligne 163)

Décompose une géométrie en une liste de morceaux linéaires simples.

### `longueur_lineaire(geometrie)` (commun_topologie.py, ligne 204)

Longueur totale des morceaux linéaires d'une géométrie.

### `epsilon_longueur(tolerance)` (commun_topologie.py, ligne 215)

Petite tolérance de longueur, proportionnelle à ``tolerance``.

### `partage_une_limite(limite_a, limite_b, tolerance_alignement_m=0.01, longueur_minimale_m=None)` (commun_topologie.py, ligne 228)

Retourne le contact (ligne) entre deux limites de polygones, si réel.

### `meilleur_voisin_par_contact(couche, geometrie, fid_exclu=None)` (commun_topologie.py, ligne 260)

Retourne le fid du polygone de la couche partageant la plus longue frontière.

### `intersection_surfacique(geometrie_a, geometrie_b, tolerance=None)` (commun_topologie.py, ligne 313)

Retourne l'intersection si elle possède une aire significative.

### `extraire_intersection_surfacique_significative(intersection, surface_minimale, surface_partie_minimale=1e-08)` (commun_topologie.py, ligne 339)

Retourne la partie polygonale d'une intersection si elle est significative.

### `trouver_entites_intersectees(couche, geometrie, fids_exclus=None)` (commun_topologie.py, ligne 372)

Retourne les entités ayant une intersection surfacique avec ``geometrie``.

### `construire_geometrie_emprise_locale(couche_emprise, rectangle_cible, crs_cible=None)` (commun_topologie.py, ligne 395)

Construit uniquement le morceau d'emprise nécessaire à une zone.

### `_supprimer_anneaux_interieurs(geometrie)` (commun_topologie.py, ligne 454)

Reconstruit une géométrie uniquement avec ses contours extérieurs.

### `nettoyer_contacts_ponctuels(geometrie)` (commun_topologie.py, ligne 491)

Supprime les contacts ponctuels parasites produits par une fusion.

### `nettoyer_geometrie_decoupee_protegee(couche, geometrie, fids_exclus=None, tolerance_m=None)` (commun_topologie.py, ligne 518)

Nettoie une géométrie issue d'une découpe sans jamais l'agrandir.

### `fusionner_geometries(geometries)` (commun_topologie.py, ligne 609)

Réunit et nettoie les polygones choisis pour une fusion.

### `redecouper_polygones_inclus(couche, geometrie_fusionnee, fids_fusionnes)` (commun_topologie.py, ligne 680)

Retire du résultat toute zone qui recouvre un autre polygone de la couche.

### `preparer_fusion_protegee(couche, geometries, fids_fusionnes)` (commun_topologie.py, ligne 738)

Prépare une fusion avec exactement les règles de l'outil Fusionner.

### `extraire_parties_polygonales(geometrie, surface_minimale=0.0, rendre_valide=True)` (commun_topologie.py, ligne 809)

Retourne les composantes polygonales significatives d'une géométrie.

### `extraire_parties_multipartie_brutes(geometrie)` (commun_topologie.py, ligne 855)

Extrait les vraies parties d'un MultiPolygon sans lancer ``makeValid``.

### `reunir_parties_polygonales(geometrie, surface_minimale=0.0, rendre_valide=True)` (commun_topologie.py, ligne 886)

Réunit les composantes polygonales significatives en une géométrie.

### `_aire_anneau(anneau)` (commun_topologie.py, ligne 908)

Pas de docstring.

### `nettoyer_pointes_interieures(anneau)` (commun_topologie.py, ligne 917)

Retire les pointes/fentes intérieures de surface quasi nulle.

### `_decomposer_polygones_xy(geometrie)` (commun_topologie.py, ligne 1099)

Retourne les polygones XY d'une géométrie polygonale.

### `supprimer_micro_residus_polygonaux(geometrie, seuil_m2=None)` (commun_topologie.py, ligne 1111)

Supprime les micro-composantes et micro-anneaux créés par une réparation.

### `_trouver_excroissance_parasite(anneau)` (commun_topologie.py, ligne 1196)

Trouve une petite branche du contour qui sort puis revient au même endroit.

### `nettoyer_excroissances_parasites_anneau(anneau)` (commun_topologie.py, ligne 1236)

Retire uniquement les branches aller-retour détectées ci-dessus.

### `nettoyer_geometrie_avance(geometrie)` (commun_topologie.py, ligne 1260)

Nettoie les pointes/fentes et répare les papillons, sans simplifier le contour.

## `commun_affichage.py`

Affichage cartographique commun du plugin Reprise PI.

**Dépendances internes directes :** `commun_parametres.py`

### `definir_action_cochee(action, coche)` (commun_affichage.py, ligne 43)

Coche ou décoche une QAction sans déclencher son signal ``toggled``.

### `_creer_contour_polygone(canvas, geometrie, couche, largeur, couleur=None, couleur_remplissage=None)` (commun_affichage.py, ligne 72)

Crée un contour temporaire autour d'une géométrie polygonale.

### `_distance_retrait_surbrillance(canvas, geometrie, couche)` (commun_affichage.py, ligne 90)

Convertit le retrait en pixels en unités de la couche.

### Classe `SurbrillancePolygone` (commun_affichage.py, ligne 159)

Double contour polygonal dont l'aspect reste stable à l'écran.

#### `__init__(self, canvas, geometrie, couche=None, couleur=None, couleur_remplissage=None)` (commun_affichage.py, ligne 162)

Pas de docstring.

#### `contours(self)` (commun_affichage.py, ligne 211)

Retourne les QgsRubberBand composant la surbrillance.

#### `definir_visible(self, visible)` (commun_affichage.py, ligne 222)

Affiche ou masque les deux contours sans perdre leur géométrie.

#### `_mettre_a_jour_interieur(self, *args)` (commun_affichage.py, ligne 231)

Recalcule le contour intérieur pour le zoom courant.

#### `supprimer(self)` (commun_affichage.py, ligne 277)

Déconnecte et retire définitivement la surbrillance du canevas.

### `creer_surbrillance_polygone(canvas, geometrie, couche=None, couleur=None, couleur_remplissage=None)` (commun_affichage.py, ligne 311)

Crée la surbrillance temporaire d'un polygone.

### `supprimer_surbrillance_polygone(canvas, surbrillance)` (commun_affichage.py, ligne 326)

Retire une surbrillance temporaire du canevas.

### `supprimer_surbrillances_polygones(canvas, surbrillances)` (commun_affichage.py, ligne 358)

Retire une collection de surbrillances temporaires.

### `remplacer_surbrillance_polygone(canvas, surbrillance, geometrie, couche=None)` (commun_affichage.py, ligne 364)

Remplace une surbrillance par celle de la nouvelle géométrie.

## `commun_synchronisation_alertes.py`

Synchronisation spatiale entre les alertes et les polygones BD Forêt.

**Dépendances internes directes :** `commun_couches.py`, `commun_edition.py`, `commun_parametres.py`

### `marquer_edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 57)

Mémorise que le plugin a lui-même démarré l'édition de ``couche``.

### `edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 64)

Indique si la session d'édition enfant appartient au plugin.

### `oublier_edition_alertes_ouverte_par_plugin(couche)` (commun_synchronisation_alertes.py, ligne 71)

Oublie le marqueur d'édition automatique d'une couche d'alertes.

### `ecriture_parent_interne_en_cours(couche)` (commun_synchronisation_alertes.py, ligne 78)

Indique si ``synchroniser_zone`` écrit actuellement sur la couche.

### `_cle_couche(couche)` (commun_synchronisation_alertes.py, ligne 89)

Identifiant stable pour indexer une couche dans les deux ensembles ci-dessus.

### `synchroniser_zone_outil(manager, iface, couche_parent, geometrie_zone, nom_commande)` (commun_synchronisation_alertes.py, ligne 102)

Synchronise une opération géométrique explicite par le service central.

### Classe `ResultatSynchronisation` (commun_synchronisation_alertes.py, ligne 121)

Polygones parents touchés par une synchronisation d'alertes.

#### `__init__(self, fids_parents=None, iface=None)` (commun_synchronisation_alertes.py, ligne 129)

Pas de docstring.

### `_est_nulle(valeur)` (commun_synchronisation_alertes.py, ligne 134)

Teste NULL/None/chaîne vide en une seule fois (QVariant NULL n'est ni

### `attribuer_nouvel_id_foret(couche, fid)` (commun_synchronisation_alertes.py, ligne 143)

Attribue à ``id_foret`` la valeur du ``fid`` de l'entité.

### `_transformer_geometrie(geometrie, crs_source, crs_destination)` (commun_synchronisation_alertes.py, ligne 177)

Copie et reprojette une géométrie, sans rien faire si les deux SCR sont identiques.

### `priorite_numerique(valeur)` (commun_synchronisation_alertes.py, ligne 191)

Convertit une priorité en nombre, en tolérant la virgule décimale.

### `_en_booleen(valeur)` (commun_synchronisation_alertes.py, ligne 208)

Normalise une valeur de champ (bool, nombre ou texte) en True/False.

### `_choisir_polygone(point, candidats, id_actuel, index_id_parent)` (commun_synchronisation_alertes.py, ligne 224)

Choisit le polygone contenant le point, de façon déterministe.

### `_polygones_intersectant_zone(couche_parent, zone)` (commun_synchronisation_alertes.py, ligne 272)

Retourne uniquement les polygones proches de ``zone``.

### `_expression_ids_foret(nom_champ, valeurs)` (commun_synchronisation_alertes.py, ligne 296)

Construit un filtre QGIS sûr pour un petit ensemble d'id_foret.

### `_suffixe_groupe(nom)` (commun_synchronisation_alertes.py, ligne 324)

Retourne le suffixe normalisé situé après « groupe » dans un nom de couche.

### `_trouver_couche_alertes_associee(couche_parent, iface=None)` (commun_synchronisation_alertes.py, ligne 334)

Choisit de préférence Alertes Centroides du même groupe que la BD Forêt.

### `trouver_couche_alertes_associee(couche_parent, iface=None)` (commun_synchronisation_alertes.py, ligne 373)

Retourne la couche Alertes Centroides associée à ``couche_parent``.

### `_valeur_cle(valeur)` (commun_synchronisation_alertes.py, ligne 383)

Normalise une valeur d'identifiant pour comparer int/str/QVariant.

### `_widgets_relation_alertes_ouverts(iface)` (commun_synchronisation_alertes.py, ligne 394)

Retourne les widgets de relation ouverts, y compris dans un formulaire modal.

### `rafraichir_vue_relation_alertes(iface, couche_parent, couche_alertes, fids_parents)` (commun_synchronisation_alertes.py, ligne 430)

Force les widgets relationnels ouverts à relire les alertes du parent.

### `synchroniser_zone(iface, couche_parent, geometrie_zone, nom_commande='Synchroniser les alertes')` (commun_synchronisation_alertes.py, ligne 475)

Réaligne les alertes et recalcule les indicateurs dans une zone.

## `commun_compteur_alertes.py`

Mise à jour automatique des compteurs d'alertes liés aux polygones BD Forêt.

**Dépendances internes directes :** `commun_couches.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`

### `valeur_nulle(valeur)` (commun_compteur_alertes.py, ligne 45)

Retourne True pour les valeurs qui doivent rester à la fin du tri.

### `cle_valeur(valeur)` (commun_compteur_alertes.py, ligne 52)

Normalise une valeur pour un tri stable numérique ou textuel.

### `trier_donnees(donnees, criteres=CRITERES_CLASSEMENT)` (commun_compteur_alertes.py, ligne 69)

Trie les éléments selon ``commun_parametres.py`` avec les NULL à la fin.

### Classe `CompteurAlertes` (commun_compteur_alertes.py, ligne 112)

Synchronise les indicateurs de lecture entre alertes et polygones.

#### `__init__(self, iface, historique=None)` (commun_compteur_alertes.py, ligne 134)

Pas de docstring.

#### `initGui(self)` (commun_compteur_alertes.py, ligne 202)

Pas de docstring.

#### `unload(self)` (commun_compteur_alertes.py, ligne 218)

Pas de docstring.

#### `_programmer_connexion(self, *args)` (commun_compteur_alertes.py, ligne 242)

Pas de docstring.

#### `_projet_vide(self, *args)` (commun_compteur_alertes.py, ligne 247)

Pas de docstring.

#### `connecter_couches(self)` (commun_compteur_alertes.py, ligne 254)

Connecte le compteur si les couches nécessaires existent.

#### `deconnecter_couches(self)` (commun_compteur_alertes.py, ligne 340)

Pas de docstring.

#### `suspendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 397)

Suspend temporairement le recalcul spatial automatique.

#### `reprendre_synchronisation_geometrique(self)` (commun_compteur_alertes.py, ligne 411)

Réactive le recalcul spatial automatique après une suspension.

#### `_synchronisation_geometrique_suspendue(self)` (commun_compteur_alertes.py, ligne 419)

Pas de docstring.

#### `synchroniser_modification_geometrique(self, couche_parent, geometrie_zone, nom_commande)` (commun_compteur_alertes.py, ligne 422)

Synchronise les alertes après une modification géométrique explicite.

#### `_trouver_relation(self)` (commun_compteur_alertes.py, ligne 466)

Pas de docstring.

#### `_avant_enregistrement_parent(self, *args)` (commun_compteur_alertes.py, ligne 485)

Protège le suivi Undo pendant le reset de pile provoqué par QGIS.

#### `_terminer_garde_commit_parent(self)` (commun_compteur_alertes.py, ligne 495)

Pas de docstring.

#### `_reinitialiser_suivi_apres_commit_parent(self)` (commun_compteur_alertes.py, ligne 500)

Oublie uniquement les index Undo devenus invalides après sauvegarde.

#### `_apres_enregistrement_parent(self, *args)` (commun_compteur_alertes.py, ligne 510)

Valide les alertes que le plugin a modifiées avec la BD Forêt.

#### `_emprise_originale_parent(self, fid)` (commun_compteur_alertes.py, ligne 590)

Lit ponctuellement l'emprise enregistrée avant le premier changement.

#### `_fusionner_rectangles(rectangle_a, rectangle_b)` *(@staticmethod)* (commun_compteur_alertes.py, ligne 623)

Pas de docstring.

#### `_commande_parent_demarre(self, _texte=None)` (commun_compteur_alertes.py, ligne 631)

Prépare une zone locale pour la commande géométrique en cours.

#### `_commande_parent_terminee(self)` (commun_compteur_alertes.py, ligne 648)

Synchronise une fois la zone après une vraie commande géométrique.

#### `_commande_parent_detruite(self)` (commun_compteur_alertes.py, ligne 670)

Resynchronise aussi lorsqu'une commande active est détruite.

#### `_memoriser_zone_geometrique(self, rectangle)` (commun_compteur_alertes.py, ligne 691)

Agrège une zone et déclenche la jointure spatiale après le signal.

#### `_terminer_recalcul_hors_commande(self)` (commun_compteur_alertes.py, ligne 721)

Traite les changements hors commande, notamment Ctrl+Z et Ctrl+Y.

#### `_executer_recalcul_geometrique_differe(self, rectangle, *_args)` (commun_compteur_alertes.py, ligne 735)

Recalcule les données dérivées sans créer de commande Ctrl+Z.

#### `_geometrie_parent_modifiee(self, fid, geometrie)` (commun_compteur_alertes.py, ligne 786)

Signal geometryChanged : accumule l'ancienne ET la nouvelle emprise.

#### `_entite_parent_ajoutee(self, fid)` (commun_compteur_alertes.py, ligne 816)

Signal featureAdded : une entité neuve (Créer, Séparer) a besoin

#### `_entite_parent_supprimee(self, fid)` (commun_compteur_alertes.py, ligne 833)

Pas de docstring.

#### `_attribut_alerte_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 865)

Signal attributeValueChanged de la couche d'alertes : ne réagit

#### `_attribut_parent_modifie(self, fid, index_champ, nouvelle_valeur)` (commun_compteur_alertes.py, ligne 890)

Traite uniquement un clic utilisateur sur ``toutes_alertes_vues``.

#### `_commande_edition_active(couche)` *(@staticmethod)* (commun_compteur_alertes.py, ligne 938)

Indique si QGIS est encore dans un beginEditCommand/endEditCommand.

#### `_traiter_commandes_parent_en_attente(self)` (commun_compteur_alertes.py, ligne 947)

Traite les clics parent hors de la pile d'appel du formulaire QGIS.

#### `_traiter_toutes_alertes_vues_parent(self, fid_parent, valeur_demandee)` (commun_compteur_alertes.py, ligne 981)

Applique une commande utilisateur sans réentrance de signaux.

#### `_marquer_toutes_alertes_vues(self, fid_parent)` (commun_compteur_alertes.py, ligne 1021)

Met ``vu = true`` sur toutes les alertes liées au polygone.

#### `recalculer_tous_les_compteurs(self)` *(@vue_stable_pendant_modification)* (commun_compteur_alertes.py, ligne 1090)

Vérifie spatialement tous les rattachements puis recalcule les compteurs.

#### `_cle_identifiant(valeur)` *(@staticmethod)* (commun_compteur_alertes.py, ligne 1704)

Normalise ``id_foret`` pour comparer sans faux écart int/texte.

#### `_valeurs_compteur_identiques(self, actuelle, attendue, booleen=False)` (commun_compteur_alertes.py, ligne 1725)

Compare une valeur de champ actuelle à la valeur recalculée, en

#### `_recalculer_parent(self, fid_alerte)` (commun_compteur_alertes.py, ligne 1737)

Retrouve le parent d'une alerte via la relation QGIS, puis délègue

#### `_recalculer_parent_direct(self, fid_parent)` (commun_compteur_alertes.py, ligne 1757)

Recalcule compteurs et ``toutes_alertes_vues`` pour un polygone.

#### `_convertir_en_booleen(valeur)` *(@staticmethod)* (commun_compteur_alertes.py, ligne 1836)

Même intention que _en_booleen() dans commun_synchronisation_alertes.py.

#### `_rafraichir_formulaire_parent(self, fid_parent)` (commun_compteur_alertes.py, ligne 1846)

Ne force jamais la sélection d'une fiche après un recalcul.

#### `_avertir(self, message)` (commun_compteur_alertes.py, ligne 1856)

Pas de docstring.

## `commun_historique_formulaires.py`

Navigation Précédent/Suivant dans les vues formulaire QGIS.

**Dépendances internes directes :** `commun_couches.py`, `commun_protection_vue.py`

### Classe `HistoriqueFormulaires` (commun_historique_formulaires.py, ligne 24)

Conserve les dix dernières fiches consultées dans chaque vue formulaire.

#### `__init__(self, iface)` (commun_historique_formulaires.py, ligne 32)

Pas de docstring.

#### `initGui(self)` (commun_historique_formulaires.py, ligne 57)

Détecte les vues formulaire sans balayage périodique.

#### `unload(self)` (commun_historique_formulaires.py, ligne 79)

Pas de docstring.

#### `_focus_change(self, _ancien, nouveau)` (commun_historique_formulaires.py, ligne 98)

Inspecte une nouvelle fenêtre seulement lorsqu'elle reçoit le focus.

#### `_verifier_fenetre_differee(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 129)

Deuxième et dernier essai pour une fenêtre nouvellement ouverte.

#### `detecter_tables(self)` (commun_historique_formulaires.py, ligne 148)

Balayage ponctuel des tables déjà ouvertes.

#### `connecter_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 185)

Prépare le suivi complet d'une fenêtre de table attributaire fraîchement détectée.

#### `_memoriser_scroll_avant_reset(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 283)

Mémorise uniquement le scroll juste avant un reset du modèle QGIS.

#### `_restaurer_scroll_apres_reset(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 303)

Restaure le scroll après le reset sans toucher à la fiche courante.

#### `_appliquer_scroll_si_valide(self, reference_fenetre, valeur)` (commun_historique_formulaires.py, ligne 321)

Applique une restauration différée seulement si la vue existe encore.

#### `_trouver_composants_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 342)

Pas de docstring.

#### `_trouver_liste_principale(main_view_widget)` *(@staticmethod)* (commun_historique_formulaires.py, ligne 363)

Écarte les listes appartenant aux sous-relations du formulaire.

#### `_trouver_barre_outils(fenetre)` *(@staticmethod)* (commun_historique_formulaires.py, ligne 402)

Repère la barre d'outils de la table (celle avec le plus de boutons).

#### `_creer_actions(self, fenetre, toolbar)` (commun_historique_formulaires.py, ligne 419)

Ajoute les boutons sans reconstruire la barre d'outils QGIS.

#### `_creer_action(self, fenetre, icone, texte, nom_objet, info_bulle)` (commun_historique_formulaires.py, ligne 474)

Pas de docstring.

#### `_trouver_action(toolbar, nom)` *(@staticmethod)* (commun_historique_formulaires.py, ligne 482)

Pas de docstring.

#### `definir_etat_formulaire(self, callback)` (commun_historique_formulaires.py, ligne 491)

Reçoit un callback léger ``(couche, fid, vue_formulaire)``.

#### `definir_fid_persistant(self, callback)` (commun_historique_formulaires.py, ligne 495)

Branche la lecture du dernier FID conservé entre deux sessions QGIS.

#### `_notifier_etat_formulaire(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 499)

Pas de docstring.

#### `definir_recalcul_alertes(self, callback)` (commun_historique_formulaires.py, ligne 515)

Branche le bouton de recalcul sur le service des compteurs.

#### `recalculer_alertes(self)` (commun_historique_formulaires.py, ligne 527)

Lance le recalcul global sans changer de fiche ni de sélection.

#### `_couche_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 540)

Retourne la couche principale associée à une vue attributaire.

#### `_cle_couche(couche)` *(@staticmethod)* (commun_historique_formulaires.py, ligne 555)

Clé stable pendant la session QGIS, sans dépendre d'un attribut métier.

#### `_memoriser_derniere_fiche(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 562)

Mémorise seulement le FID courant, sans relire la couche.

#### `_restaurer_derniere_fiche(self, fenetre)` (commun_historique_formulaires.py, ligne 573)

Rouvre le dernier FID connu ; sinon laisse QGIS sur sa première fiche.

#### `fiche_changee(self, fenetre, feature)` (commun_historique_formulaires.py, ligne 623)

Pas de docstring.

#### `enregistrer_fiche_initiale(self, fenetre)` (commun_historique_formulaires.py, ligne 636)

Pas de docstring.

#### `ajouter_fid_historique(self, fenetre, fid)` (commun_historique_formulaires.py, ligne 649)

Ajoute un FID à l'historique de navigation (même logique qu'un

#### `revenir_precedent(self, fenetre)` (commun_historique_formulaires.py, ligne 678)

Pas de docstring.

#### `aller_suivant(self, fenetre)` (commun_historique_formulaires.py, ligne 683)

Pas de docstring.

#### `ouvrir_position(self, fenetre, nouvelle_position)` (commun_historique_formulaires.py, ligne 690)

Change de fiche uniquement à la demande Précédent/Suivant.

#### `mettre_a_jour_actions(self, fenetre)` (commun_historique_formulaires.py, ligne 718)

Pas de docstring.

#### `geler_fiche_si_fid_supprime(self, couche, fids_supprimes)` (commun_historique_formulaires.py, ligne 735)

Empêche QGIS de basculer la fiche principale sur la première ligne.

#### `liberer_gel_fiche(self, gels)` (commun_historique_formulaires.py, ligne 778)

Relâche un gel de fiche après les signaux différés de QGIS.

#### `capturer_contexte_visuel_couche(self, couche, fids_supprimes_prevus=None)` (commun_historique_formulaires.py, ligne 805)

Mémorise la fiche courante et ses voisines dans l'ordre affiché.

#### `deplacer_fiche_avant_suppression(self, couche, contexte)` (commun_historique_formulaires.py, ligne 891)

Quitte une fiche dont le FID va disparaître, avant la suppression.

#### `assainir_fiche_apres_suppression(self, couche, fid_supprime)` (commun_historique_formulaires.py, ligne 956)

Filet de sécurité après toute suppression signalée par QGIS.

#### `_restaurer_contexte_visuel_une_fois(self, couche, contexte, fid_remplacement=None)` (commun_historique_formulaires.py, ligne 1028)

Applique une tentative de restauration après mise à jour du modèle QGIS.

#### `restaurer_contexte_visuel_couche(self, couche, contexte, fid_remplacement=None, restaurer_fid=True)` (commun_historique_formulaires.py, ligne 1122)

Restaure la fiche sans retour en haut après création/fusion/suppression.

#### `fenetre_detruite(self, reference_fenetre)` (commun_historique_formulaires.py, ligne 1158)

Pas de docstring.

#### `_objet_qt_valide(objet)` *(@staticmethod)* (commun_historique_formulaires.py, ligne 1167)

Indique si le wrapper Python pointe encore vers un objet Qt vivant.

#### `deconnecter_fenetre(self, fenetre)` (commun_historique_formulaires.py, ligne 1181)

Retire proprement une vue encore vivante (notamment lors de ``unload``).

## `edition_creer.py`

Créer un nouveau polygone dans la couverture BD Forêt.

**Dépendances internes directes :** `commun_affichage.py`, `commun_couches.py`, `commun_edition.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `_verifier_partition(geometrie_avant, geometries_apres, exiger_monopartie=True)` (edition_creer.py, ligne 44)

Vérifie qu'une modification conserve exactement la même couverture.

### Classe `OutilDessinNouveauPolygone(QgsMapToolCapture)` (edition_creer.py, ligne 87)

Capture le contour du nouveau polygone avec l'accrochage QGIS.

#### `__init__(self, plugin)` (edition_creer.py, ligne 90)

Pas de docstring.

#### `polygonCaptured(self, polygon)` (edition_creer.py, ligne 98)

Pas de docstring.

### Classe `CreerPolygonePlugin` (edition_creer.py, ligne 109)

Retire une surface à la couverture existante puis crée une nouvelle entité.

#### `__init__(self, iface, manager=None)` (edition_creer.py, ligne 114)

Pas de docstring.

#### `initGui(self)` (edition_creer.py, ligne 132)

Pas de docstring.

#### `unload(self)` (edition_creer.py, ligne 141)

Pas de docstring.

#### `_basculer_outil(self, coche)` (edition_creer.py, ligne 152)

Pas de docstring.

#### `_activer(self)` (edition_creer.py, ligne 155)

Pas de docstring.

#### `_edition_demarree(self, couche)` (edition_creer.py, ligne 180)

Termine l'activation si le bouton est toujours coché.

#### `_activer_outil_dessin(self)` (edition_creer.py, ligne 189)

Pas de docstring.

#### `_desactiver(self)` (edition_creer.py, ligne 200)

Pas de docstring.

#### `desactiver_pour_autre_outil(self)` (edition_creer.py, ligne 213)

Pas de docstring.

#### `_outil_carte_change(self, nouvel_outil, ancien_outil=None)` (edition_creer.py, ligne 216)

QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive.

#### `traiter_zone_dessinee(self, geometrie_dessinee)` *(@sans_reentrance)* (edition_creer.py, ligne 228)

Prépare, applique puis renseigne le nouveau polygone.

#### `_preparer_creation(self, geometrie_dessinee)` (edition_creer.py, ligne 301)

Calcule les géométries à appliquer sans modifier la couche.

#### `_appliquer_creation(self, preparation)` *(@vue_stable_pendant_modification)* (edition_creer.py, ligne 403)

Applique géométries et surfaces, sans encore refermer la commande.

#### `_ouvrir_formulaire(self, fid)` (edition_creer.py, ligne 459)

Ouvre le formulaire dans la commande encore ouverte de _appliquer_creation.

#### `_avertir(self, message)` (edition_creer.py, ligne 486)

Pas de docstring.

## `edition_separer.py`

Séparer et renseigner un ou plusieurs polygones BD Forêt.

**Dépendances internes directes :** `commun_affichage.py`, `commun_couches.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### Classe `EchecSeparationNative(RuntimeError)` (edition_separer.py, ligne 43)

Échec attendu du moteur de séparation QGIS, avec un message déjà prêt pour l'utilisateur.

### Classe `OutilSelectionSeparation(QgsMapToolIdentify)` (edition_separer.py, ligne 47)

Choisit les entités à découper, uniquement via les surbrillances du plugin.

#### `__init__(self, canvas, plugin)` (edition_separer.py, ligne 50)

Pas de docstring.

#### `canvasReleaseEvent(self, event)` (edition_separer.py, ligne 55)

Pas de docstring.

### Classe `OutilLigneSeparation(QgsMapToolCapture)` (edition_separer.py, ligne 66)

Capture la ligne comme l'outil natif ``QgsMapToolSplitFeatures``.

#### `__init__(self, plugin)` (edition_separer.py, ligne 76)

Pas de docstring.

#### `supportsTechnique(self, technique)` (edition_separer.py, ligne 90)

Seule la numérisation clic par clic a du sens pour une ligne de coupe.

#### `cadCanvasReleaseEvent(self, event)` (edition_separer.py, ligne 97)

Reproduit la capture de ``QgsMapToolSplitFeatures`` de QGIS.

#### `lineCaptured(self, line)` (edition_separer.py, ligne 147)

Filet de compatibilité : la capture normale passe par cadCanvasReleaseEvent.

#### `keyPressEvent(self, event)` (edition_separer.py, ligne 153)

Pas de docstring.

### Classe `SeparerPolygonePlugin` (edition_separer.py, ligne 165)

Découpe les polygones choisis par l'utilisateur.

#### `__init__(self, iface, manager=None)` (edition_separer.py, ligne 170)

Pas de docstring.

#### `initGui(self)` (edition_separer.py, ligne 187)

Pas de docstring.

#### `unload(self)` (edition_separer.py, ligne 196)

Pas de docstring.

#### `_basculer_outil(self, coche)` (edition_separer.py, ligne 207)

Pas de docstring.

#### `_activer(self)` (edition_separer.py, ligne 210)

Pas de docstring.

#### `_edition_demarree(self, couche)` (edition_separer.py, ligne 229)

Termine l'activation si le bouton est toujours coché.

#### `_desactiver(self)` (edition_separer.py, ligne 238)

Pas de docstring.

#### `desactiver_pour_autre_outil(self)` (edition_separer.py, ligne 249)

Pas de docstring.

#### `_outil_carte_change(self, nouvel_outil, ancien_outil=None)` (edition_separer.py, ligne 252)

QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive.

#### `_activer_outil_selection(self)` (edition_separer.py, ligne 264)

Pas de docstring.

#### `basculer_entite_cliquee(self, x, y, ctrl_appuye)` (edition_separer.py, ligne 275)

Pas de docstring.

#### `_retirer_fid(self, fid)` (edition_separer.py, ligne 278)

Pas de docstring.

#### `effacer_selection_visuelle(self, rafraichir=True)` (edition_separer.py, ligne 281)

Pas de docstring.

#### `demarrer_trace(self)` (edition_separer.py, ligne 288)

Pas de docstring.

#### `_activer_outil_dessin(self)` (edition_separer.py, ligne 298)

Pas de docstring.

#### `retour_selection_apres_annulation(self)` (edition_separer.py, ligne 313)

Pas de docstring.

#### `traiter_ligne_dessinee(self, geometrie_ligne)` *(@sans_reentrance)* (edition_separer.py, ligne 330)

Pas de docstring.

#### `_preparer_separation_native(self)` (edition_separer.py, ligne 368)

Mémorise les cibles et leur état avant l'appel au moteur natif QGIS.

#### `_decrire_resultat_split(resultat)` *(@staticmethod)* (edition_separer.py, ligne 412)

Traduit un ``Qgis.GeometryOperationResult`` sans dépendre d'une version précise.

#### `_appliquer_separation_native(self, preparation, points)` *(@vue_stable_pendant_modification)* (edition_separer.py, ligne 438)

Applique le split de couche QGIS + règles BD Forêt dans un seul Ctrl+Z.

#### `_fid_temporaire_du_tampon(self, fid)` (edition_separer.py, ligne 537)

Vrai si ``fid`` désigne une entité ajoutée mais pas encore commitée.

#### `_separer_fid_temporaire(self, fid, points)` (edition_separer.py, ligne 546)

Découpe une entité temporaire directement dans le tampon QGIS.

#### `_trouver_parent_nouveau_morceau(self, geometrie, geometries_sources)` (edition_separer.py, ligne 597)

Associe un morceau créé au polygone hachuré dont il provient.

#### `_restaurer_attributs_nouveaux_morceaux(self, nouveaux_fids, preparation)` (edition_separer.py, ligne 616)

Conserve les règles d'héritage historiques du plugin après le split natif.

#### `_cle_id_foret(valeur)` *(@staticmethod)* (edition_separer.py, ligne 669)

Normalise un ``id_foret`` pour les contrôles d'unicité.

#### `_attribuer_ids_foret_uniques(self, nouveaux_fids)` (edition_separer.py, ligne 684)

Donne un ``id_foret`` neuf et globalement unique à chaque morceau.

#### `_recalculer_surfaces(self, fids)` (edition_separer.py, ligne 724)

Pas de docstring.

#### `_ouvrir_nouveaux_morceaux_en_serie(self, fids)` (edition_separer.py, ligne 738)

Pas de docstring.

#### `_ouvrir_formulaire(self, fid)` (edition_separer.py, ligne 759)

Pas de docstring.

#### `_avertir(self, message)` (edition_separer.py, ligne 766)

Pas de docstring.

## `edition_fusionner.py`

Fusionner plusieurs polygones BD Forêt en une seule entité.

**Dépendances internes directes :** `commun_affichage.py`, `commun_couches.py`, `commun_edition.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `_securiser_attributs_pour_fid(couche, fid_cible, attributs)` (edition_fusionner.py, ligne 61)

Retourne une copie des attributs sans jamais changer une clé primaire.

### `_changements_attributaires_sans_pk(couche, attributs)` (edition_fusionner.py, ligne 84)

Construit un dictionnaire index/valeur excluant toutes les clés primaires.

### Classe `EchecFusionNative(RuntimeError)` (edition_fusionner.py, ligne 94)

Échec attendu du moteur de fusion QGIS, avec un message déjà prêt pour l'utilisateur.

### Classe `_OutilSelectionFusion(QgsMapToolIdentify)` (edition_fusionner.py, ligne 98)

Sélectionne les polygones par clic sans utiliser la sélection attributaire.

#### `__init__(self, canvas, plugin)` (edition_fusionner.py, ligne 101)

Pas de docstring.

#### `canvasReleaseEvent(self, event)` (edition_fusionner.py, ligne 106)

Pas de docstring.

### Classe `FusionnerBdForetPlugin` (edition_fusionner.py, ligne 117)

Fusionne plusieurs polygones dans une seule entité de référence.

#### `__init__(self, iface, manager=None)` (edition_fusionner.py, ligne 122)

Pas de docstring.

#### `initGui(self)` (edition_fusionner.py, ligne 145)

Pas de docstring.

#### `unload(self)` (edition_fusionner.py, ligne 154)

Pas de docstring.

#### `_basculer_outil(self, coche)` (edition_fusionner.py, ligne 165)

Pas de docstring.

#### `_activer(self)` (edition_fusionner.py, ligne 168)

Pas de docstring.

#### `_edition_demarree(self, couche)` (edition_fusionner.py, ligne 192)

Termine l'activation si le bouton est toujours coché.

#### `_desactiver(self)` (edition_fusionner.py, ligne 201)

Pas de docstring.

#### `desactiver_pour_autre_outil(self)` (edition_fusionner.py, ligne 216)

Pas de docstring.

#### `_outil_carte_change(self, nouvel_outil, ancien_outil=None)` (edition_fusionner.py, ligne 219)

QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive.

#### `basculer_entite_cliquee(self, x, y, ctrl_appuye)` (edition_fusionner.py, ligne 230)

Pas de docstring.

#### `_retirer_fid(self, fid)` (edition_fusionner.py, ligne 239)

Pas de docstring.

#### `effacer_selection_visuelle(self, rafraichir=True)` (edition_fusionner.py, ligne 242)

Pas de docstring.

#### `activer_avec_fids(self, fids, ouvrir_formulaire_apres=True, finaliser_au_deuxieme_clic=False, callback_fin=None)` (edition_fusionner.py, ligne 249)

Active l'outil Fusionner en présélectionnant des entités existantes.

#### `fusionner_selection(self)` *(@sans_reentrance)* (edition_fusionner.py, ligne 311)

Prépare, applique puis renseigne le polygone fusionné.

#### `fusionner_fids_direct(self, fids, fid_reference=None, ouvrir_formulaire=False, nom_commande=None, nettoyer_parasites=False)` (edition_fusionner.py, ligne 421)

Fusionne des FID via exactement le même moteur que le bouton Fusionner.

#### `_preparer_fusion(self, fids=None)` (edition_fusionner.py, ligne 511)

Calcule la géométrie fusionnée sans modifier la couche.

#### `_choisir_fid_reference(self, fids, entites)` (edition_fusionner.py, ligne 563)

Demande explicitement quelle entité fournit les attributs conservés.

#### `_libelle_choix_attributs(self, entite)` (edition_fusionner.py, ligne 620)

Affiche en priorité la nouvelle essence et la surface en hectares.

#### `_choisir_fid_technique_stable(fids, fid_source_attributs)` *(@staticmethod)* (edition_fusionner.py, ligne 644)

Choisit le FID technique survivant sans modifier le choix métier.

#### `_fid_fiche_active(fids_fusionnes, contexte_formulaire)` *(@staticmethod)* (edition_fusionner.py, ligne 662)

Retourne le FID affiché dans une fiche ouverte avant la fusion, s'il

#### `_appliquer_fusion(self, fid_reference, geometrie, autres_fids, geometrie_zone, fid_source_attributs, nom_commande=None, fid_classement=None)` *(@vue_stable_pendant_modification)* (edition_fusionner.py, ligne 673)

Fusionne via QGIS puis applique les traitements métier BD Forêt.

#### `_fusionner_avec_moteur_qgis(self, fid_reference, autres_fids, attributs, geometrie)` (edition_fusionner.py, ligne 759)

Appelle le moteur natif QGIS de fusion d'entités.

#### `_ouvrir_formulaire(self, fid_reference)` (edition_fusionner.py, ligne 794)

Pas de docstring.

#### `_avertir(self, message)` (edition_fusionner.py, ligne 803)

Pas de docstring.

## `edition_remodeler.py`

Remodeler une frontière commune entre deux polygones de la BD Forêt.

**Dépendances internes directes :** `commun_affichage.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `_distance_point_geometrie(point, geometrie)` (edition_remodeler.py, ligne 51)

Distance d'un point (avec ``.x()``/``.y()``) à une géométrie quelconque.

### `_creer_ligne_surbrillance(canvas, geometrie, couche, couleur, largeur)` (edition_remodeler.py, ligne 63)

Affiche une géométrie linéaire en surbrillance temporaire.

### `_supprimer_ligne_surbrillance(canvas, bande)` (edition_remodeler.py, ligne 82)

Retire une surbrillance créée par ``_creer_ligne_surbrillance``.

### Classe `OutilLigneRemodelage(QgsMapToolCapture)` (edition_remodeler.py, ligne 96)

Capture le nouveau tracé dessiné par l'utilisateur.

#### `__init__(self, plugin)` (edition_remodeler.py, ligne 99)

Pas de docstring.

#### `cadCanvasReleaseEvent(self, event)` (edition_remodeler.py, ligne 107)

Pas de docstring.

#### `lineCaptured(self, line)` (edition_remodeler.py, ligne 117)

Pas de docstring.

#### `keyPressEvent(self, event)` (edition_remodeler.py, ligne 130)

Pas de docstring.

### Classe `RemodelerBdForetPlugin` (edition_remodeler.py, ligne 141)

Remodèle une frontière partagée entre deux polygones BD Forêt.

#### `__init__(self, iface, manager=None)` (edition_remodeler.py, ligne 152)

Pas de docstring.

#### `initGui(self)` (edition_remodeler.py, ligne 172)

Pas de docstring.

#### `unload(self)` (edition_remodeler.py, ligne 181)

Pas de docstring.

#### `_basculer_outil(self, coche)` (edition_remodeler.py, ligne 192)

Pas de docstring.

#### `_activer(self)` (edition_remodeler.py, ligne 195)

Pas de docstring.

#### `_edition_demarree(self, couche)` (edition_remodeler.py, ligne 222)

Termine l'activation si le bouton est toujours coché.

#### `_desactiver(self)` (edition_remodeler.py, ligne 231)

Pas de docstring.

#### `desactiver_pour_autre_outil(self)` (edition_remodeler.py, ligne 245)

Pas de docstring.

#### `_outil_carte_change(self, nouvel_outil, ancien_outil=None)` (edition_remodeler.py, ligne 248)

QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive.

#### `preparer_frontiere(self, match, point_carte, point_original_carte)` (edition_remodeler.py, ligne 259)

Pas de docstring.

#### `_afficher_limites(self, geometries)` (edition_remodeler.py, ligne 301)

Pas de docstring.

#### `_supprimer_surbrillance_frontiere(self)` (edition_remodeler.py, ligne 311)

Pas de docstring.

#### `_point_vers_couche(self, point_carte)` (edition_remodeler.py, ligne 317)

Pas de docstring.

#### `_limites_pres_du_point(self, point)` (edition_remodeler.py, ligne 325)

Limites entre paires de polygones proches de `point`, triées du plus proche au plus loin.

#### `traiter_ligne_dessinee(self, geometrie_tracee)` *(@sans_reentrance)* (edition_remodeler.py, ligne 387)

Pas de docstring.

#### `_trouver_paire_remodelable(self, ligne)` (edition_remodeler.py, ligne 419)

Essaie chaque paire candidate (la plus proche du clic d'abord) et retient

#### `_remodeler_polygone(self, ancienne, ligne, fid, silencieux=False)` (edition_remodeler.py, ligne 453)

Applique reshapeGeometry() (le moteur natif QGIS) à un seul polygone.

#### `_reshape_secours(self, ancienne, ligne)` (edition_remodeler.py, ligne 482)

Reconstruit le contour nous-mêmes quand reshapeGeometry() refuse à tort.

#### `_appliquer_remodelage(self, nouvelles, zone_sync)` *(@vue_stable_pendant_modification)* (edition_remodeler.py, ligne 562)

Applique géométries + surfaces + alertes dans une commande annulable.

#### `reinitialiser_trace(self)` (edition_remodeler.py, ligne 600)

Pas de docstring.

#### `_avertir(self, message)` (edition_remodeler.py, ligne 605)

Pas de docstring.

## `edition_reporter_bdfv2.py`

Reporter des polygones de BD Forêt v2 dans la couche de travail (v3).

**Dépendances internes directes :** `commun_affichage.py`, `commun_couches.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `_trouver_couche_bdfv2()` (edition_reporter_bdfv2.py, ligne 65)

Retourne la couche BD Forêt v2, source pour le report de limites vers v3.

### `_extraire_local(grande_geometrie, geometrie_reference, marge=1.0)` (edition_reporter_bdfv2.py, ligne 80)

Extrait, en mémoire, la portion de ``grande_geometrie`` utile près de

### `_fusionner_localement(grande_geometrie, petite_geometrie)` (edition_reporter_bdfv2.py, ligne 104)

Fusionne ``petite_geometrie`` dans ``grande_geometrie``, sans jamais

### `_mapper_attributs(couche_v3, entite_v2)` (edition_reporter_bdfv2.py, ligne 143)

Reprend les valeurs de v2 dont le champ correspond à v3 par son nom et son type.

### Classe `_OutilSelectionReport(QgsMapToolIdentify)` (edition_reporter_bdfv2.py, ligne 167)

Sélectionne des polygones de BDFv2 par clic, comme « Fusionner ».

#### `__init__(self, canvas, plugin)` (edition_reporter_bdfv2.py, ligne 170)

Pas de docstring.

#### `canvasReleaseEvent(self, event)` (edition_reporter_bdfv2.py, ligne 175)

Pas de docstring.

### Classe `ReporterBdFv2Plugin` (edition_reporter_bdfv2.py, ligne 185)

Colle un polygone de BDFv2 dans v3 en découpant ce qu'il recouvre.

#### `__init__(self, iface, manager=None)` (edition_reporter_bdfv2.py, ligne 190)

Pas de docstring.

#### `initGui(self)` (edition_reporter_bdfv2.py, ligne 210)

Pas de docstring.

#### `unload(self)` (edition_reporter_bdfv2.py, ligne 219)

Pas de docstring.

#### `_basculer_outil(self, coche)` (edition_reporter_bdfv2.py, ligne 230)

Pas de docstring.

#### `_activer(self)` (edition_reporter_bdfv2.py, ligne 233)

Pas de docstring.

#### `_edition_demarree(self, couche)` (edition_reporter_bdfv2.py, ligne 259)

Termine l'activation si le bouton est toujours coché.

#### `_activer_outil_carte(self)` (edition_reporter_bdfv2.py, ligne 268)

Pas de docstring.

#### `_desactiver(self)` (edition_reporter_bdfv2.py, ligne 279)

Pas de docstring.

#### `desactiver_pour_autre_outil(self)` (edition_reporter_bdfv2.py, ligne 291)

Pas de docstring.

#### `_outil_carte_change(self, nouvel_outil, ancien_outil=None)` (edition_reporter_bdfv2.py, ligne 294)

QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive.

#### `basculer_entite_cliquee(self, x, y, ctrl_appuye)` (edition_reporter_bdfv2.py, ligne 305)

Ajoute ou retire, sous le clic, un polygone BDFv2 de la sélection bleue.

#### `_retirer_fid_v2(self, fid)` (edition_reporter_bdfv2.py, ligne 344)

Pas de docstring.

#### `effacer_selection_v2(self, rafraichir=True)` (edition_reporter_bdfv2.py, ligne 352)

Pas de docstring.

#### `reporter_selection(self)` *(@sans_reentrance)* (edition_reporter_bdfv2.py, ligne 363)

Colle chaque polygone BDFv2 sélectionné dans v3, l'un après l'autre.

#### `_rapporter(self, texte)` (edition_reporter_bdfv2.py, ligne 493)

Affiche un texte de progression dans la barre d'état QGIS.

#### `_preparer_report(self, geometrie_v2, entite_v2, prefixe='Report BDFv2')` (edition_reporter_bdfv2.py, ligne 506)

Calcule les géométries à appliquer sans modifier la couche.

#### `_recoller_parties_isolees(self, pieces, fids_a_exclure)` (edition_reporter_bdfv2.py, ligne 610)

Fusionne, dans le meilleur voisin, toute partie < 0,25 ha isolée

#### `_appliquer_report(self, preparation)` *(@vue_stable_pendant_modification)* (edition_reporter_bdfv2.py, ligne 696)

Applique géométries et surfaces, sans encore refermer la commande.

#### `_ouvrir_formulaire(self, fid)` (edition_reporter_bdfv2.py, ligne 752)

Ouvre le formulaire dans la commande encore ouverte de _appliquer_report.

#### `_avertir(self, message)` (edition_reporter_bdfv2.py, ligne 779)

Pas de docstring.

## `verification_panneau.py`

Interface du panneau « Vérification BD Forêt ».

**Dépendances internes directes :** `commun_couches.py`

### Classe `PanneauVerification(QDockWidget)` (verification_panneau.py, ligne 54)

Panneau latéral. Toute la logique métier est déléguée au contrôleur.

#### `__init__(self, plugin)` (verification_panneau.py, ligne 57)

Pas de docstring.

#### `etapes_nettoyage_activees(self)` (verification_panneau.py, ligne 217)

Étapes actuellement cochées dans le menu de "Nettoyer la couche".

#### `regles_metier_activees(self)` (verification_panneau.py, ligne 223)

Règles actuellement cochées dans le menu de "Vérifier les règles métier".

#### `closeEvent(self, event)` (verification_panneau.py, ligne 229)

Ferme proprement les calculs et déconnecte la couche surveillée.

#### `_faire_clignoter_element(self, item, _column)` (verification_panneau.py, ligne 240)

Pas de docstring.

#### `_zoomer_element(self, item, _column)` (verification_panneau.py, ligne 245)

Pas de docstring.

#### `_developper_categorie(self, item)` (verification_panneau.py, ligne 250)

Mémorise l'ouverture et crée les lignes détaillées si nécessaire.

#### `_replier_categorie(self, item)` (verification_panneau.py, ligne 259)

Mémorise uniquement un repli explicitement demandé par l'utilisateur.

#### `_ouvrir_menu_contextuel(self, position)` (verification_panneau.py, ligne 268)

Construit puis exécute l'action disponible pour l'anomalie choisie.

#### `_actions_pour_payload(self, payload)` (verification_panneau.py, ligne 306)

Retourne les actions applicables à un élément de l'arbre.

## `verification.py`

Panneau de recherche des anomalies et création de couches temporaires.

**Dépendances internes directes :** `commun_affichage.py`, `commun_couches.py`, `commun_parametres.py`, `commun_topologie.py`, `verification_panneau.py`, `verification_tache_relations.py`

### `zoomer_sur_emprise(canvas, emprise, facteur=1.25)` (verification.py, ligne 69)

Zoome sur une emprise QGIS en conservant une marge autour.

### `_couleur_vers_texte(couleur)` (verification.py, ligne 87)

Convertit une couleur RGBA en chaîne comprise par les symboles QGIS.

### `_creer_symbole_anomalies()` (verification.py, ligne 92)

Construit la symbologie de la couche temporaire des anomalies.

### Classe `CoucheSurbrillanceVerification` (verification.py, ligne 120)

Crée, retrouve et met à jour la couche mémoire des anomalies.

#### `__init__(self)` (verification.py, ligne 123)

Pas de docstring.

#### `detacher(self)` (verification.py, ligne 126)

Oublie la couche courante sans la supprimer du projet.

#### `courante(self)` (verification.py, ligne 130)

Retourne la couche d'anomalies courante si elle existe encore.

#### `prochain_nom()` *(@staticmethod)* (verification.py, ligne 141)

Retourne un nom disponible pour la couche d'anomalies.

#### `assurer(self, couche_travail)` (verification.py, ligne 156)

Retourne la couche d'anomalies, en la créant si nécessaire.

#### `_ajouter_au_projet(couche, couche_travail)` *(@staticmethod)* (verification.py, ligne 195)

Ajoute la couche d'anomalies juste après la couche de travail.

#### `remplacer_entites(self, couche_travail, entites)` (verification.py, ligne 215)

Remplace les anciennes anomalies par les nouvelles.

### `_contours_surbrillance(surbrillance)` (verification.py, ligne 240)

Retourne les contours d'une surbrillance sous forme de tuple.

### `_definir_surbrillance_visible(surbrillance, visible)` (verification.py, ligne 251)

Affiche ou masque une surbrillance quel que soit son ancien format.

### Classe `ClignotementVerification` (verification.py, ligne 264)

Fait clignoter temporairement les anomalies au simple clic.

#### `__init__(self, iface)` (verification.py, ligne 267)

Pas de docstring.

#### `afficher(self, geometries, couche_reference=None)` (verification.py, ligne 272)

Affiche puis fait clignoter les géométries fournies.

#### `effacer(self)` (verification.py, ligne 321)

Supprime le clignotement courant et invalide les anciens timers.

### Classe `VerificationBdForetPlugin` (verification.py, ligne 340)

Pas de docstring.

#### `__init__(self, iface, manager=None)` (verification.py, ligne 341)

Pas de docstring.

#### `initGui(self)` (verification.py, ligne 426)

Pas de docstring.

#### `unload(self)` (verification.py, ligne 435)

Décharge le plugin sans réutiliser d'objets Qt/QGIS déjà détruits.

#### `_basculer_panneau(self, checked)` (verification.py, ligne 505)

Pas de docstring.

#### `_trouver_couche(self)` (verification.py, ligne 534)

Retourne la couche BD Forêt commune aux autres outils.

#### `_trouver_couche_emprise()` *(@staticmethod)* (verification.py, ligne 539)

Retourne la couche d'emprise commune aux autres outils.

#### `_connecter_signaux_couche(self, layer)` (verification.py, ligne 543)

Écoute les modifications sans réutiliser un wrapper de couche détruit.

#### `_deconnecter_signaux_couche(self)` (verification.py, ligne 571)

Oublie la couche avant toute déconnexion Qt.

#### `_commande_edition_demarre(self, *_args)` (verification.py, ligne 603)

Regroupe les nombreux signaux d'une même commande QGIS.

#### `_commande_edition_terminee(self, *_args)` (verification.py, ligne 611)

La commande QGIS vient de se refermer : relance le contrôle local

#### `_commande_edition_annulee(self, *_args)` (verification.py, ligne 618)

Même relance qu'après une commande normale : un Ctrl+Z pendant une

#### `_memoriser_ancienne_geometrie(self, fid)` (verification.py, ligne 625)

Garde la géométrie AVANT modification, une seule fois par fid et

#### `_geometrie_modifiee(self, fid, _geometry)` (verification.py, ligne 640)

Pas de docstring.

#### `_entite_ajoutee(self, fid)` (verification.py, ligne 646)

Pas de docstring.

#### `_entite_supprimee(self, fid)` (verification.py, ligne 651)

Pas de docstring.

#### `_attribut_modifie(self, fid, _field_index, _value)` (verification.py, ligne 657)

Pas de docstring.

#### `_programmer_rafraichissement_local(self, fid)` (verification.py, ligne 662)

Pas de docstring.

#### `_rafraichir_apres_edition(self)` (verification.py, ligne 678)

Pas de docstring.

#### `rafraichir_verifications(self)` (verification.py, ligne 694)

Lance la recherche des 6 anomalies sans bloquer l'interface QGIS.

#### `lancer_nettoyage_automatique(self)` (verification.py, ligne 728)

Lance le nettoyage automatique de la couche, par petits lots (QTimer).

#### `_continuer_nettoyage_automatique(self)` (verification.py, ligne 838)

Avance le nettoyage automatique par petits lots non bloquants.

#### `_demarrer_preparation_controle(self)` (verification.py, ligne 883)

Prépare un itérateur léger puis rend immédiatement la main à Qt.

#### `_continuer_preparation_controle(self)` (verification.py, ligne 951)

Charge un petit lot d'entités puis rend la main à la boucle Qt.

#### `_demarrer_preparation_paires(self, etat)` (verification.py, ligne 1060)

Prépare les couples de voisins par petits lots dans le thread principal.

#### `_continuer_preparation_paires(self)` (verification.py, ligne 1073)

Pas de docstring.

#### `_lancer_controle_apres_preparation(self, etat)` (verification.py, ligne 1127)

Démarre le calcul spatial à partir de l'instantané déjà préparé.

#### `_tache_relations_terminee(self, generation, task, succes, resultats, erreur)` (verification.py, ligne 1171)

Récupère le résultat dans le thread principal ou l'ignore s'il est périmé.

#### `_geometrie_depuis_wkb(wkb)` *(@staticmethod)* (verification.py, ligne 1215)

Reconstruit une géométrie dans le thread principal.

#### `_geometries_recouvrements_depuis_wkb(cls, recouvrements)` *(@classmethod)* (verification.py, ligne 1234)

Pas de docstring.

#### `_finaliser_controle_complet(self, contexte, adjacent_pairs, overlaps)` (verification.py, ligne 1242)

Démarre la recherche incrémentale des trous dans le thread principal.

#### `_continuer_recherche_trous(self)` (verification.py, ligne 1278)

Avance la recherche des trous par petits lots non bloquants.

#### `_terminer_controle_avec_trous(self, donnees_finales, gaps)` (verification.py, ligne 1326)

Pas de docstring.

#### `_terminer_interface_controle(self)` (verification.py, ligne 1335)

Pas de docstring.

#### `_annuler_tache_relations(self)` (verification.py, ligne 1376)

Annule une tâche sans toucher à ses données depuis le mauvais thread.

#### `_indiquer_etape(self, texte)` (verification.py, ligne 1393)

Message d'une ligne pour "Vérifier les règles métier" (préparation,

#### `_indiquer_progression_nettoyage(self, etat, ligne_finale=None)` (verification.py, ligne 1409)

Met à jour le tableau de progression de "Nettoyer la couche".

#### `_ajuster_hauteur_tableau_progression(self, arbre, nombre_lignes)` (verification.py, ligne 1429)

Redimensionne le tableau pour tenir tout son contenu, sans barre de défilement.

#### `_creer_mesure_surface(self)` (verification.py, ligne 1441)

Configure QgsDistanceArea avec le SCR et l'ellipsoïde du projet.

#### `_chercher_relations_voisines(self, features, feature_by_id, field_map, index)` (verification.py, ligne 1450)

Recherche adjacences et recouvrements en un seul parcours spatial.

#### `_enregistrer_cache_controle(self, feature_by_id, small, multipart, coherence, adjacent_pairs, overlaps, index, field_map, gaps)` (verification.py, ligne 1535)

Mémorise les résultats nécessaires aux mises à jour locales suivantes.

#### `_recalculer_entites_modifiees(self)` (verification.py, ligne 1559)

Recalcule uniquement les entités modifiées et leurs voisines.

#### `_preparer_zone_modifiee(self, pending, old_geometries)` (verification.py, ligne 1589)

Retire les anciennes entités de l'index et récupère leur voisinage.

#### `_recharger_entites_modifiees(self, pending, affected, affected_rect, has_rect)` (verification.py, ligne 1616)

Recharge les entités courantes et réinjecte leur géométrie dans l'index.

#### `_ajouter_emprise(emprise, emprise_initialisee, nouvelle_emprise)` *(@staticmethod)* (verification.py, ligne 1635)

Ajoute une emprise à un QgsRectangle cumulatif.

#### `_mettre_a_jour_cache_entites(self, pending, current)` (verification.py, ligne 1642)

Remplace dans le cache les entités créées, modifiées ou supprimées.

#### `_recalculer_anomalies_entites(self, pending)` (verification.py, ligne 1654)

Délègue aux modules d'anomalies les seuls FID modifiés.

#### `_recalculer_relations_locales(self, affected)` (verification.py, ligne 1679)

Recalcule adjacences et recouvrements touchés en un seul parcours.

#### `_obtenir_entite_cachee(self, fid)` (verification.py, ligne 1757)

Retourne une entité du cache ou la charge ponctuellement depuis la couche.

#### `_purger_anomalies_entites_absentes(self)` (verification.py, ligne 1782)

Retire du cache les FID d'anomalies qui n'existent plus réellement.

#### `_reconstruire_depuis_cache(self, valider_trous=True)` (verification.py, ligne 1847)

Pas de docstring.

#### `_remplir_arbre(self, small, multipart, overlaps, adjacent_groups, gaps, coherence, emprise_found)` (verification.py, ligne 1899)

Affiche les catégories et conserve l'état choisi par l'utilisateur.

#### `_peupler_categorie_si_besoin(self, groupe)` (verification.py, ligne 1962)

Matérialise une catégorie du panneau lors de sa première ouverture.

#### `_emprise_vers_tuple(rectangle)` *(@staticmethod)* (verification.py, ligne 2001)

Convertit un QgsRectangle en données simples stockables dans l’arbre.

#### `creer_couche_temporaire(self)` (verification.py, ligne 2029)

Crée un nouvel instantané temporaire des anomalies courantes.

#### `_synchroniser_couche_surbrillance(self)` (verification.py, ligne 2053)

Construit puis délègue l'affichage de la couche temporaire à commun_affichage.py.

#### `_construire_entites_surbrillance(self, layer)` (verification.py, ligne 2061)

Construit les entités représentant chaque anomalie à afficher.

#### `_ajouter_geometrie_surbrillance(self, layer, entites, cles_traitees, cle, categorie, geometrie, decouper_emprise=True)` (verification.py, ligne 2134)

Ajoute une anomalie à la couche temporaire.

#### `_obtenir_date_premiere_detection(self, cle)` (verification.py, ligne 2165)

Conserve la première date de détection d'une anomalie pendant la session.

#### `faire_clignoter(self, payload)` (verification.py, ligne 2178)

Construit les géométries à signaler puis délègue le rendu à commun_affichage.py.

#### `_reinitialiser_resultats_panneau(self)` (verification.py, ligne 2236)

Vide le panneau et les résultats calculés, sans toucher aux couches créées.

#### `zoomer_sur_element(self, payload)` (verification.py, ligne 2265)

Pas de docstring.

#### `zoomer_sur_entites(self, fids)` (verification.py, ligne 2276)

Zoome sur les géométries déjà en cache plutôt que sur les FID provider.

## `verification_tache_relations.py`

Calcul asynchrone sûr des adjacences et recouvrements.

**Dépendances internes directes :** `commun_parametres.py`, `commun_topologie.py`

### Classe `TacheRelationsVoisines(QgsTask)` (verification_tache_relations.py, ligne 23)

Calcule les diagnostics et intersections sans toucher aux objets de couche.

#### `__init__(self, donnees, paires_candidates, regles_activees, callback)` (verification_tache_relations.py, ligne 26)

Pas de docstring.

#### `_geometrie_depuis_wkb(wkb)` *(@staticmethod)* (verification_tache_relations.py, ligne 41)

Construit une QgsGeometry appartenant uniquement au thread de tâche.

#### `run(self)` (verification_tache_relations.py, ligne 54)

Exécuté en arrière-plan ; aucune API liée à une couche ou à l'UI.

#### `finished(self, succes)` (verification_tache_relations.py, ligne 165)

Toujours rappelé par QGIS dans le thread principal.

## `verification_nettoyage_automatique.py`

Nettoie automatiquement la couche de travail, par petits lots (QTimer).

**Dépendances internes directes :** `commun_couches.py`, `commun_parametres.py`, `commun_topologie.py`, `verification_recouvrements.py`

### `preparer_nettoyage(self, etapes_activees=None)` (verification_nettoyage_automatique.py, ligne 159)

Prépare le parcours de toute la couche, sans lancer de gros calcul.

### `_phase_suivante(etat)` (verification_nettoyage_automatique.py, ligne 210)

Prochaine étape ACTIVÉE après la phase courante, ou ``None`` si finie.

### `_passer_a_etape_suivante(etat)` (verification_nettoyage_automatique.py, ligne 223)

Clôt l'étape courante et enchaîne sur la prochaine étape ACTIVÉE.

### `traiter_lot_nettoyage(self, etat, taille_lot=200)` (verification_nettoyage_automatique.py, ligne 239)

Avance le nettoyage par petits lots et rend vite la main à Qt.

### `_traiter_lot_conformite(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 270)

Corrige les géométries encore invalides d'un lot (étape 1), puis avance/termine.

### `_fusionner_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_nettoyage_automatique.py, ligne 301)

Fusionne ``petite_geometrie`` dans le voisin ``fid_voisin``, ou ``None``.

### `_traiter_lot_petites_surfaces(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 326)

Fusionne un lot de petites entités entières (< 100 m²) avec leur

### `_executer_recherche_trous(self, couche)` (verification_nettoyage_automatique.py, ligne 361)

Tous les trous de la couche (emprise - couverture), sans seuil.

### `_traiter_lot_trous(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 400)

Comble un lot de petits trous (< 100 m², étape 3), puis avance ou termine.

### `_construire_cache_travail(couche)` (verification_nettoyage_automatique.py, ligne 438)

Index spatial + géométries courantes de toute la couche (une fois).

### `_traiter_lot_recouvrements(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 450)

Absorbe un lot de petits recouvrements (< 100 m², étape 4) dans le

### `_traiter_lot_parties_isolees(couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 503)

Détache les petites parties isolées d'un lot de multiparties (étape 5).

### `_reparer_couche_native(couche_memoire)` (verification_nettoyage_automatique.py, ligne 571)

Répare en bloc les géométries non valides d'une couche mémoire jetable.

### `_executer_decoupe_emprise(self, couche)` (verification_nettoyage_automatique.py, ligne 586)

Découpe toute la couche par l'emprise en un seul appel natif QGIS.

### `_traiter_lot_hors_emprise(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 721)

Reverse un lot du résultat de la découpe (étape 6), puis avance ou termine.

### `_traiter_lot_synchronisation_alertes(self, couche, etat, taille_lot)` (verification_nettoyage_automatique.py, ligne 756)

Déclenche le recalcul des alertes différé pendant tout le nettoyage

### `_ligne_etape(etat)` (verification_nettoyage_automatique.py, ligne 788)

Ligne (colonne Étape, colonne Détail) pour l'étape en cours dans ``etat``.

### `progression_nettoyage(etat)` (verification_nettoyage_automatique.py, ligne 823)

Lignes (étape, détail) affichées dans le panneau pendant le nettoyage.

### `nombre_etapes_prevues(etat)` (verification_nettoyage_automatique.py, ligne 841)

Nombre total de lignes que le nettoyage affichera une fois fini.

### `finaliser_nettoyage(etat)` (verification_nettoyage_automatique.py, ligne 856)

Retourne ``(entités corrigées, entités supprimées, écarts fusionnés)``.

## `verification_surface05ha.py`

Détecte les polygones de surface inférieure à 0,5 ha.

**Dépendances internes directes :** `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_topologie.py`

### `detecter(feature, mesure_surface)` (verification_surface05ha.py, ligne 14)

Retourne ``(fid, surface_m2)`` si l'entité fait moins de 0,5 ha.

### `est_isole(controleur, fid, geometrie)` (verification_surface05ha.py, ligne 24)

Vrai si aucun autre polygone BD Forêt ne partage une vraie limite.

### `fusionner_avec(controleur, fid)` *(@vue_stable_pendant_modification)* (verification_surface05ha.py, ligne 55)

Délègue la correction au véritable outil Fusionner du plugin.

### `actualiser_visibles(controleur)` (verification_surface05ha.py, ligne 95)

Recalcule et met en cache les petits polygones à afficher.

### `visibles(controleur)` (verification_surface05ha.py, ligne 117)

Retourne le dernier résultat mis en cache par :func:`actualiser_visibles`.

### `apres_fusion(controleur, fids_operation, fid_reference)` (verification_surface05ha.py, ligne 122)

Programme le rafraîchissement local après une fusion déléguée.

### `_meilleur_voisin(controleur, fid)` (verification_surface05ha.py, ligne 133)

Retourne le voisin partageant la plus grande frontière avec ce polygone.

### `fusionner_tous_avec_meilleur_voisin(controleur)` (verification_surface05ha.py, ligne 144)

Fusionne chaque petit polygone visible avec son voisin le plus adéquat.

### `ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_surface05ha.py, ligne 211)

Ajoute la branche « Surfaces < 0,5 ha » au panneau Vérifier.

## `verification_entites_multiparties.py`

Détecte les entités multiparties et propose de les fusionner ou séparer.

**Dépendances internes directes :** `commun_affichage.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `_aligner_parties(parties)` (verification_entites_multiparties.py, ligne 32)

Aligne chaque partie sur les précédentes avant preparer_fusion_protegee.

### `_message_echec_fusion_parties(parties_alignees)` (verification_entites_multiparties.py, ligne 58)

Distingue pourquoi la fusion des parties a échoué, pour un message utile.

### `detecter(feature)` (verification_entites_multiparties.py, ligne 79)

Retourne ``(fid, nombre_parties)`` pour une vraie multipartie.

### `peut_fusionner_multipartie(self, fid)` (verification_entites_multiparties.py, ligne 87)

Retourne True si les parties peuvent devenir un seul polygone continu.

### `fusionner_multipartie(self, fid)` *(@vue_stable_pendant_modification)* (verification_entites_multiparties.py, ligne 124)

Réunit les parties contiguës d'une multipartie en un seul polygone.

### `separer_multipartie(self, fid)` *(@vue_stable_pendant_modification)* (verification_entites_multiparties.py, ligne 230)

Transforme chaque partie d'une multipartie en entité indépendante.

### `attribuer_partie_multipartie(self, fid, index_partie)` *(@vue_stable_pendant_modification)* (verification_entites_multiparties.py, ligne 359)

Délègue l'attribution d'une partie isolée à un voisin à l'outil Fusionner.

### `_apres_attribution_partie(controleur, fids_operation, fid_reference, fid_parent)` (verification_entites_multiparties.py, ligne 478)

Programme le rafraîchissement local après une attribution de partie déléguée.

### `ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_entites_multiparties.py, ligne 490)

Ajoute les multiparties et chacune de leurs parties au panneau.

## `verification_recouvrements.py`

Détection et correction des recouvrements surfaciques.

**Dépendances internes directes :** `commun_couches.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `recouvrement_depuis_intersection(intersection)` (verification_recouvrements.py, ligne 36)

Retourne la partie surfacique d'une intersection, aussi petite soit-elle.

### `intersection_recouvrement(geom_a, geom_b)` (verification_recouvrements.py, ligne 51)

Calcule l'intersection puis retourne le recouvrement, aussi petit soit-il.

### `corriger_micro_recouvrement(geom_a, geom_b)` (verification_recouvrements.py, ligne 62)

Absorbe un recouvrement trop petit pour représenter un vrai conflit.

### `_fusionner_petite_geometrie_dans_voisin(couche, petite_geometrie, fid_voisin)` (verification_recouvrements.py, ligne 95)

Fusionne ``petite_geometrie`` (trou ou micro-recouvrement) dans un voisin.

### `nettoyer_micro_anomalies_locales(controleur, couche, geometrie_zone, fids_proteges=None)` (verification_recouvrements.py, ligne 122)

Résout tout de suite les micro-trous/micro-recouvrements (< 100 m²)

### `libelle_entite_essence_surface(couche, entite)` (verification_recouvrements.py, ligne 233)

Libellé compact utilisé pour choisir un polygone dans une liste.

### `choisir_fid_attribution_recouvrement(controleur, couche, fids, entites)` (verification_recouvrements.py, ligne 255)

Demande à quel polygone doit appartenir toute la zone commune.

### `attribuer_recouvrement(self, fids_recouvrement)` *(@vue_stable_pendant_modification)* (verification_recouvrements.py, ligne 288)

Attribue toute la zone commune à l'un des deux polygones.

### `decouper_recouvrement(self, fids_recouvrement)` *(@vue_stable_pendant_modification)* (verification_recouvrements.py, ligne 518)

Transforme une zone de recouvrement en entité BD Forêt indépendante.

### `ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_recouvrements.py, ligne 756)

Ajoute les recouvrements de surface significative au panneau.

## `verification_trous.py`

Recherche et correction des trous dans la couverture BD Forêt.

**Dépendances internes directes :** `commun_affichage.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`, `commun_synchronisation_alertes.py`, `commun_topologie.py`

### `mettre_a_jour_trous_locaux(self, rect)` (verification_trous.py, ligne 26)

Met à jour les lacunes dans la seule emprise touchée par l'édition.

### `fusionner_parties_trous(geometries)` (verification_trous.py, ligne 62)

Fusionne les morceaux contigus afin qu'un trou réel forme une seule anomalie.

### `valider_trous_contre_couche_actuelle(self)` (verification_trous.py, ligne 89)

Retire des trous en cache toute surface actuellement couverte par la BD Forêt.

### `preparer_recherche_trous(self, emprise_layer, feature_by_id, index)` (verification_trous.py, ligne 148)

Calcule directement ``Emprise - BD Forêt``, sans découpage en tuiles.

### `_union_geometries(geometries)` (verification_trous.py, ligne 189)

Union locale avec un chemin rapide lorsqu'il n'y a qu'une géométrie.

### `traiter_lot_recherche_trous(self, etat, taille_lot=1)` (verification_trous.py, ligne 202)

Le calcul est déjà entièrement fait par :func:`preparer_recherche_trous`.

### `progression_recherche_trous(etat)` (verification_trous.py, ligne 207)

Texte court affiché dans le panneau pendant la recherche des trous.

### `finaliser_recherche_trous(etat)` (verification_trous.py, ligne 212)

Valide une dernière fois les morceaux trouvés et les numérote.

### `couche_emprise_cachee(self)` (verification_trous.py, ligne 220)

Retourne la couche d'emprise utilisée lors du dernier contrôle complet.

### `geometrie_emprise_locale(self, rect)` (verification_trous.py, ligne 227)

Construit seulement la portion d'emprise utile autour d'un rectangle.

### `decouper_a_emprise_locale(self, geometrie)` (verification_trous.py, ligne 237)

Découpe une géométrie à la portion d'emprise qui la concerne.

### `_preparer_geometrie_trou(self, couche, gap_index)` (verification_trous.py, ligne 250)

Nettoie et valide la géométrie d'un trou avant sa matérialisation.

### `_materialiser_trou(self, couche, geometrie, nom_commande)` (verification_trous.py, ligne 335)

Crée une entité BD Forêt à partir d'une géométrie de trou déjà préparée.

### `reboucher_trou(self, gap_index)` *(@vue_stable_pendant_modification)* (verification_trous.py, ligne 383)

Crée une entité BD Forêt à partir de la géométrie d'un trou détecté.

### `attribuer_trou(self, gap_index)` *(@vue_stable_pendant_modification)* (verification_trous.py, ligne 435)

Délègue l'attribution d'un trou à un voisin à l'outil Fusionner.

### `apres_fusion_trou(controleur, fids_operation, fid_reference)` (verification_trous.py, ligne 489)

Programme le rafraîchissement local après une attribution de trou déléguée.

### `reboucher_tous_les_trous(self)` (verification_trous.py, ligne 500)

Reboule chaque trou avec le voisin partageant sa plus longue frontière.

### `ajouter_au_panneau(controleur, arbre, anomalies, emprise_trouvee, groupe=None)` (verification_trous.py, ligne 578)

Ajoute la branche des trous au panneau Vérifier.

## `verification_polygones_adjacents_attributs_identiques.py`

Détecte des groupes de polygones adjacents portant les mêmes attributs.

**Dépendances internes directes :** `commun_affichage.py`, `commun_edition.py`, `commun_parametres.py`, `commun_protection_vue.py`

### `regrouper_adjacences(adjacent_pairs)` (verification_polygones_adjacents_attributs_identiques.py, ligne 15)

Transforme les paires d'adjacence en groupes connexes sans doublons.

### `detail_adjacence(feature, field_map)` (verification_polygones_adjacents_attributs_identiques.py, ligne 61)

Texte affiché dans le panneau pour une paire/un groupe d'adjacents identiques.

### `fusionner_groupe_adjacents(self, fids_groupe, silencieux=False, planifier_refresh=True)` *(@vue_stable_pendant_modification)* (verification_polygones_adjacents_attributs_identiques.py, ligne 69)

Fusionne en une seule opération un groupe connexe d'adjacents identiques.

### `fusionner_tous_groupes_adjacents(self)` (verification_polygones_adjacents_attributs_identiques.py, ligne 153)

Fusionne tous les groupes d'adjacents identiques encore valides.

### `modifier_attributs_entite(self, fid)` (verification_polygones_adjacents_attributs_identiques.py, ligne 200)

Ouvre directement la fiche attributaire d'un polygone du groupe.

### `ajouter_au_panneau(controleur, arbre, groupes, groupe=None)` (verification_polygones_adjacents_attributs_identiques.py, ligne 248)

Ajoute les groupes connexes de polygones adjacents au panneau.

## `verification_coherence_essence_tff.py`

Détecte les incohérences entre l'essence et les booléens du formulaire.

**Dépendances internes directes :** `commun_affichage.py`, `commun_edition.py`, `commun_parametres.py`

### `detecter(feature, field_map)` (verification_coherence_essence_tff.py, ligne 26)

Retourne ``(fid, détail)`` si l'essence et les booléens sont incohérents.

### `modifier_attributs_entite(self, fid)` (verification_coherence_essence_tff.py, ligne 82)

Ouvre la fiche de l'entité, en surbrillance, pour corriger les champs.

### `ajouter_au_panneau(controleur, arbre, anomalies, groupe=None)` (verification_coherence_essence_tff.py, ligne 129)

Ajoute la branche des incohérences essence/booléens au panneau.
