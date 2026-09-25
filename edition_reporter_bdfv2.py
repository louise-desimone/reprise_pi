# -*- coding: utf-8 -*-
"""Reporter des polygones de BD Forêt v2 dans la couche de travail (v3).

BDFv2 a parfois un découpage plus fin ou plus juste que v3 sur une zone
donnée. L'opérateur sélectionne un ou plusieurs polygones de v2 par clic
gauche (surbrillance bleue), comme avec « Fusionner », puis valide par clic
droit : chaque polygone sélectionné est collé dans v3 l'un après l'autre — sa
géométrie (découpée à l'emprise) retire la surface correspondante aux
polygones v3 existants qu'elle recouvre, sans créer de vide ni de
recouvrement, sur le même principe que « Créer un nouveau polygone ». La
fiche de chaque nouveau polygone s'ouvre ensuite en surbrillance jaune (le
jaune habituel de tous les outils, pour signaler qu'on est bien repassé côté
v3), l'une après l'autre.
"""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QApplication
from qgis.analysis import QgsGeometrySnapper
from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsSpatialIndex
from qgis.gui import QgsMapToolIdentify

from .commun_affichage import (
    creer_surbrillance_polygone,
    definir_action_cochee,
    remplacer_surbrillance_polygone,
    supprimer_surbrillances_polygones,
    supprimer_surbrillance_polygone,
)
from .commun_couches import est_couche_polygonale, normaliser_nom, trouver_couche_emprise
from .commun_edition import (
    AttenteDebutEdition,
    SurveillanceCoucheActive,
    avertir_message_bar,
    basculer_outil_geometrique,
    creer_action_outil,
    creer_entite_nouvelle,
    detruire_action_outil,
    exiger_fid_valide,
    obtenir_couche_editable,
    recuperer_entite,
    sans_reentrance,
    surface_ha,
)
from .commun_parametres import (
    COULEUR_REMPLISSAGE_SURBRILLANCE_BDFV2,
    COULEUR_SURBRILLANCE_BDFV2,
    MOT_CLE_COUCHE_BDFV2,
    SURFACE_MAXIMALE_PARTIE_ISOLEE_REPORT_M2,
)
from .commun_protection_vue import vue_stable_pendant_modification
from .commun_synchronisation_alertes import synchroniser_zone_outil
from .commun_topologie import (
    compter_parties_polygonales,
    construire_geometrie_emprise_locale,
    meilleur_voisin_par_contact,
    nettoyer_geometrie_base,
    trouver_entites_intersectees,
)


# Déplacée depuis commun_couches.py (audit de placement avant transmission du
# code) : n'était utilisée que par cet outil.
def _trouver_couche_bdfv2():
    """Retourne la couche BD Forêt v2, source pour le report de limites vers v3.

    Cherche ``bdfv2`` dans le nom, indépendamment de la couche active : à la
    différence de la couche de travail (v3), l'opérateur n'a pas besoin de
    l'avoir activée pour cliquer dessus avec l'outil de report.
    """
    for couche in QgsProject.instance().mapLayers().values():
        if not est_couche_polygonale(couche):
            continue
        if MOT_CLE_COUCHE_BDFV2 in normaliser_nom(couche.name()):
            return couche
    return None


def _extraire_local(grande_geometrie, geometrie_reference, marge=1.0):
    """Extrait, en mémoire, la portion de ``grande_geometrie`` utile près de
    ``geometrie_reference``.

    Un gros polygone BDFv2 peut recouper des centaines de polygones v3 :
    ``nouvelle_geometrie`` (union de tout ce qui est collé) peut alors avoir
    des milliers de sommets. Une ``difference()`` entre un petit polygone v3
    et cette grande géométrie complète est mathématiquement identique à une
    ``difference()`` avec seulement la portion de la grande géométrie qui
    touche le rectangle englobant du petit polygone (le reste ne peut de toute
    façon rien y retirer) — mais nettement moins coûteuse à calculer. Même
    principe que ``_masque_local`` dans le nettoyage automatique.
    """
    try:
        rect = geometrie_reference.boundingBox()
        rect.grow(marge)
        locale = grande_geometrie.intersection(QgsGeometry.fromRect(rect))
    except (AttributeError, TypeError, RuntimeError):
        return grande_geometrie
    if locale is None or locale.isEmpty():
        return grande_geometrie
    return locale


def _fusionner_localement(grande_geometrie, petite_geometrie):
    """Fusionne ``petite_geometrie`` dans ``grande_geometrie``, sans jamais
    faire porter à ce recollage un coût proportionnel à la taille totale
    d'une ``grande_geometrie`` potentiellement énorme (un "gros" polygone
    BDFv2 peut avoir des milliers de sommets).

    ``fusionner_geometries`` (utilisée par l'outil Fusionner) est pensée pour
    fusionner des polygones indépendamment digitalisés : en plus d'aligner
    les sommets, elle nettoie aussi les anneaux intérieurs, les contacts
    ponctuels et les pointes résiduelles sur le résultat ENTIER — un coût qui
    grandit avec la taille totale de ``grande_geometrie``, répété à chaque
    petite partie recollée. Ici, on ne fait que réparer un vrai défaut
    ponctuel (une micro-partie isolée par une découpe, pas deux polygones
    séparément digitalisés) : on se limite à l'alignement des sommets (pour
    éviter la pointe résiduelle d'un ``unaryUnion`` brut, déjà rencontrée) et
    à une validation minimale, sans repasser tout ``grande_geometrie`` dans
    les nettoyages plus lourds.

    ``QgsGeometrySnapper`` reconstruit son index spatial sur sa RÉFÉRENCE à
    chaque appel (même principe que le nettoyage automatique ce matin) : on
    aligne donc ``grande_geometrie`` (potentiellement énorme) SUR
    ``petite_geometrie`` (l'index se construit sur la petite, pas l'inverse).
    """
    try:
        grande_alignee = QgsGeometrySnapper.snapGeometry(
            grande_geometrie, 0.01, [petite_geometrie]
        )
    except (AttributeError, TypeError, RuntimeError):
        grande_alignee = grande_geometrie
    if grande_alignee is None or grande_alignee.isEmpty():
        grande_alignee = grande_geometrie

    try:
        fusion = QgsGeometry.unaryUnion([petite_geometrie, grande_alignee])
    except (TypeError, RuntimeError):
        return None
    return nettoyer_geometrie_base(fusion)


def _mapper_attributs(couche_v3, entite_v2):
    """Reprend les valeurs de v2 dont le champ correspond à v3 par son nom et son type.

    Insensible à la casse (les deux couches ne nomment pas forcément leurs
    champs avec la même casse). Un champ v3 sans correspondance en v2, ou dont
    le type diffère, reste à ``None`` : l'opérateur le renseigne dans la fiche
    ouverte juste après.
    """
    champs_v3 = couche_v3.fields()
    champs_v2 = entite_v2.fields()
    attributs_v2 = entite_v2.attributes()
    index_par_nom_v2 = {champ.name().lower(): i for i, champ in enumerate(champs_v2)}

    attributs = [None] * champs_v3.count()
    for index_v3, champ_v3 in enumerate(champs_v3):
        index_v2 = index_par_nom_v2.get(champ_v3.name().lower())
        if index_v2 is None:
            continue
        if champs_v2[index_v2].type() != champ_v3.type():
            continue
        attributs[index_v3] = attributs_v2[index_v2]
    return attributs


class _OutilSelectionReport(QgsMapToolIdentify):
    """Sélectionne des polygones de BDFv2 par clic, comme « Fusionner »."""

    def __init__(self, canvas, plugin):
        super().__init__(canvas)
        self.plugin = plugin
        self.setCursor(Qt.ArrowCursor)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.plugin.reporter_selection()
        elif event.button() == Qt.LeftButton:
            self.plugin.basculer_entite_cliquee(
                event.x(), event.y(),
                bool(event.modifiers() & Qt.ControlModifier),
            )


class ReporterBdFv2Plugin:
    """Colle un polygone de BDFv2 dans v3 en découpant ce qu'il recouvre."""

    NOM_OUTIL = "Reporter un polygone depuis BDFv2"

    def __init__(self, iface, manager=None):
        self.iface = iface
        self.manager = manager
        self.canvas = iface.mapCanvas()
        self.action = None
        self.actif = False
        self.couche = None
        self.outil_carte = None
        self.fids_v2 = []
        self.surbrillances_v2 = {}
        self.surbrillance = None
        self.traitement_en_cours = False
        self._changement_outil = False
        self._attente_edition = AttenteDebutEdition(self._edition_demarree)
        self._surveillance = SurveillanceCoucheActive(self._desactiver)

    # ------------------------------------------------------------------
    # Chargement / activation
    # ------------------------------------------------------------------

    def initGui(self):
        chemin_icone = os.path.join(os.path.dirname(__file__), "icon_reporter_bdfv2.svg")
        self.action = creer_action_outil(
            self.iface, self.canvas, self.NOM_OUTIL, chemin_icone,
            self.NOM_OUTIL, self._basculer_outil,
        )
        self.canvas.mapToolSet.connect(self._outil_carte_change)
        self._surveillance.demarrer()

    def unload(self):
        self._attente_edition.annuler()
        self._surveillance.arreter()
        try:
            self.canvas.mapToolSet.disconnect(self._outil_carte_change)
        except (TypeError, RuntimeError):
            pass
        self.action = detruire_action_outil(
            self.iface, self.action, self.NOM_OUTIL, self._basculer_outil
        )

    def _basculer_outil(self, coche):
        basculer_outil_geometrique(self, coche)

    def _activer(self):
        couche, editable = obtenir_couche_editable(
            self.iface, self.NOM_OUTIL, manager=self.manager, outil=self
        )
        if couche is None:
            return False
        self.couche = couche
        if not editable:
            self.actif = False
            self._attente_edition.attendre(couche)
            return True

        if _trouver_couche_bdfv2() is None:
            avertir_message_bar(
                self.iface, self.NOM_OUTIL,
                "Aucune couche BDFv2 trouvée dans le projet (nom contenant « bdfv2 »).",
            )
            return False

        self._attente_edition.annuler()
        self.actif = True
        self._surveillance.surveiller_couche(couche)
        self.effacer_selection_v2(rafraichir=False)
        self._activer_outil_carte()
        return True

    def _edition_demarree(self, couche):
        """Termine l'activation si le bouton est toujours coché."""
        if self.action is None or not self.action.isChecked():
            return
        if self.couche is not couche:
            return
        if not self._activer():
            definir_action_cochee(self.action, False)

    def _activer_outil_carte(self):
        if not self.actif or self.couche is None or not self.couche.isEditable():
            return
        if self.outil_carte is None:
            self.outil_carte = _OutilSelectionReport(self.canvas, self)
        self._changement_outil = True
        try:
            self.canvas.setMapTool(self.outil_carte)
        finally:
            self._changement_outil = False

    def _desactiver(self):
        self._attente_edition.annuler()
        self._surveillance.oublier_couche()
        self.actif = False
        self.effacer_selection_v2(rafraichir=False)
        self.surbrillance = remplacer_surbrillance_polygone(
            self.canvas, self.surbrillance, None, self.couche
        )
        self.couche = None
        self.outil_carte = None
        definir_action_cochee(self.action, False)

    def desactiver_pour_autre_outil(self):
        self._desactiver()

    def _outil_carte_change(self, nouvel_outil, ancien_outil=None):
        """QGIS a changé d'outil de carte : si ce n'est pas nous, on se désactive."""
        if self._changement_outil or not self.actif:
            return
        if nouvel_outil is not self.outil_carte:
            self._desactiver()

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def basculer_entite_cliquee(self, x, y, ctrl_appuye):
        """Ajoute ou retire, sous le clic, un polygone BDFv2 de la sélection bleue.

        Même règle que « Fusionner » : un clic simple sur une entité déjà
        sélectionnée la retire ; Ctrl+clic n'est qu'un geste de retrait (il
        n'ajoute jamais).
        """
        if not self.actif:
            return
        couche_v2 = _trouver_couche_bdfv2()
        if couche_v2 is None:
            self._avertir("Couche BDFv2 introuvable dans le projet.")
            return

        resultats = self.outil_carte.identify(
            x, y, [couche_v2], QgsMapToolIdentify.TopDownStopAtFirst,
        )
        if not resultats:
            return
        entite = resultats[0].mFeature
        fid = int(entite.id())

        if fid in self.surbrillances_v2:
            self._retirer_fid_v2(fid)
            return
        if ctrl_appuye:
            return

        self.fids_v2.append(fid)
        self.surbrillances_v2[fid] = creer_surbrillance_polygone(
            self.canvas, entite.geometry(), couche_v2,
            couleur=COULEUR_SURBRILLANCE_BDFV2,
            couleur_remplissage=COULEUR_REMPLISSAGE_SURBRILLANCE_BDFV2,
        )
        try:
            self.canvas.refresh()
        except RuntimeError:
            pass

    def _retirer_fid_v2(self, fid):
        supprimer_surbrillance_polygone(self.canvas, self.surbrillances_v2.pop(int(fid), None))
        self.fids_v2 = [f for f in self.fids_v2 if int(f) != int(fid)]
        try:
            self.canvas.refresh()
        except RuntimeError:
            pass

    def effacer_selection_v2(self, rafraichir=True):
        supprimer_surbrillances_polygones(self.canvas, self.surbrillances_v2.values())
        self.surbrillances_v2.clear()
        self.fids_v2 = []
        if rafraichir:
            try:
                self.canvas.refresh()
            except RuntimeError:
                pass

    @sans_reentrance
    def reporter_selection(self):
        """Colle chaque polygone BDFv2 sélectionné dans v3, l'un après l'autre.

        Chaque report ouvre sa propre fiche (surbrillance jaune) avant de
        passer au suivant : les collages ne se chevauchent jamais entre eux
        puisque chacun relit l'état courant de v3 (déjà mis à jour par le
        report précédent) avant de calculer sa découpe.
        """
        if not self.actif or not self.fids_v2:
            return

        couche_v2 = _trouver_couche_bdfv2()
        if couche_v2 is None:
            self._avertir("Couche BDFv2 introuvable dans le projet.")
            self.effacer_selection_v2()
            return

        fids_a_traiter = list(self.fids_v2)
        self.effacer_selection_v2()
        total = len(fids_a_traiter)

        for position, fid in enumerate(fids_a_traiter, start=1):
            # Un seul gros polygone BDFv2 peut déjà recouper des dizaines de
            # polygones v3 : sans texte de progression à l'intérieur même du
            # traitement d'UN polygone, ça peut sembler figer QGIS pendant
            # plusieurs secondes alors que ça avance normalement.
            prefixe = f"Report BDFv2 {position}/{total}"
            self._rapporter(f"{prefixe}…")

            entite_v2 = recuperer_entite(couche_v2, fid)
            if entite_v2 is None:
                continue
            try:
                geometrie_v2 = QgsGeometry(entite_v2.geometry())
            except (TypeError, RuntimeError, AttributeError):
                self._avertir(f"Le polygone BDFv2 {fid} n'a pas pu être lu.")
                continue

            # Sablier pendant le calcul géométrique (peut prendre plusieurs
            # secondes sur un gros polygone très détaillé) : le texte de la
            # barre d'état est facile à rater, le curseur saute aux yeux tout
            # de suite. Retiré avant d'ouvrir la fiche, pour ne pas laisser un
            # sablier pendant que l'opérateur remplit le formulaire.
            historique = getattr(self.manager, "historique", None) if self.manager is not None else None
            contexte_formulaire = []
            gels_fiche = []
            fid_nouvelle_entite = None

            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                preparation = self._preparer_report(geometrie_v2, entite_v2, prefixe)
                if preparation is None:
                    continue

                # Un polygone v3 peut être entièrement absorbé par le collage
                # (preparation["suppressions"]) : si sa fiche est ouverte, on
                # mémorise sa position et on s'en écarte avant la suppression,
                # pour rouvrir ensuite sur le bon voisin plutôt que de perdre
                # la navigation (sinon QGIS revient par défaut en haut de la
                # table).
                if historique is not None and preparation["suppressions"]:
                    try:
                        contexte_formulaire = historique.capturer_contexte_visuel_couche(
                            self.couche, preparation["suppressions"]
                        )
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        contexte_formulaire = []
                    try:
                        historique.deplacer_fiche_avant_suppression(
                            self.couche, contexte_formulaire
                        )
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                    try:
                        gels_fiche = historique.geler_fiche_si_fid_supprime(
                            self.couche, preparation["suppressions"]
                        )
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        gels_fiche = []

                nouvelle_entite = self._appliquer_report(preparation)
                fid_nouvelle_entite = int(nouvelle_entite.id())
            except Exception as erreur:
                self.iface.messageBar().pushCritical(
                    self.NOM_OUTIL,
                    f"Le report du polygone {fid} a échoué : {erreur}",
                )
                continue
            finally:
                QApplication.restoreOverrideCursor()

            # _ouvrir_formulaire referme (ou détruit) la commande encore
            # ouverte par _appliquer_report : le gel/la restauration de la
            # fiche ne doivent intervenir qu'une fois ce sort réellement
            # scellé (formulaire annulé = suppression annulée elle aussi).
            try:
                self._ouvrir_formulaire(fid_nouvelle_entite)
            except Exception as erreur:
                self.iface.messageBar().pushCritical(
                    self.NOM_OUTIL,
                    f"Le report du polygone {fid} a échoué : {erreur}",
                )
            finally:
                if historique is not None and gels_fiche:
                    try:
                        historique.liberer_gel_fiche(gels_fiche)
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                if historique is not None and contexte_formulaire:
                    try:
                        historique.restaurer_contexte_visuel_couche(
                            self.couche, contexte_formulaire, fid_remplacement=fid_nouvelle_entite,
                        )
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass

        try:
            self.iface.statusBarIface().clearMessage()
        except (AttributeError, RuntimeError):
            pass
        self.surbrillance = remplacer_surbrillance_polygone(
            self.canvas, self.surbrillance, None, self.couche
        )
        try:
            if self.couche is not None:
                self.iface.setActiveLayer(self.couche)
            self.canvas.setFocus()
        except (AttributeError, RuntimeError):
            pass

    def _rapporter(self, texte):
        """Affiche un texte de progression dans la barre d'état QGIS.

        Force aussi le traitement des évènements Qt : sans ça, le texte ne
        s'afficherait qu'une fois tout le calcul terminé, puisque rien d'autre
        ne rend la main à Qt entre deux sous-étapes.
        """
        try:
            self.iface.statusBarIface().showMessage(texte)
            QCoreApplication.processEvents()
        except (AttributeError, RuntimeError):
            pass

    def _preparer_report(self, geometrie_v2, entite_v2, prefixe="Report BDFv2"):
        """Calcule les géométries à appliquer sans modifier la couche."""
        couche_emprise = trouver_couche_emprise()
        if couche_emprise is not None:
            masque_local = construire_geometrie_emprise_locale(
                couche_emprise, geometrie_v2.boundingBox(), self.couche.crs()
            )
            if masque_local is None or masque_local.isEmpty():
                self._avertir("Ce polygone BDFv2 est en dehors de l'emprise.")
                return None
            geometrie_v2 = nettoyer_geometrie_base(
                geometrie_v2.intersection(masque_local)
            )
            if geometrie_v2 is None or geometrie_v2.isEmpty():
                self._avertir("Ce polygone BDFv2 ne contient aucune surface dans l'emprise.")
                return None

        self._rapporter(f"{prefixe}… recherche des polygones recouverts")
        sources = trouver_entites_intersectees(self.couche, geometrie_v2)
        if not sources:
            self._avertir("Ce polygone BDFv2 ne recoupe aucune entité de la couche de travail.")
            return None

        self._rapporter(f"{prefixe}… fusion de {len(sources)} polygone(s) recouvert(s)")
        geometries_sources = [QgsGeometry(entite.geometry()) for entite in sources]
        couverture_avant = nettoyer_geometrie_base(
            QgsGeometry.unaryUnion(geometries_sources)
        )
        if couverture_avant is None:
            self._avertir("Les polygones recouverts ne forment pas une géométrie valide.")
            return None

        # Comme pour « Créer », on ne laisse jamais le report agrandir la
        # couverture totale de v3 : seule la partie de v2 qui recoupe déjà des
        # polygones v3 existants est collée.
        nouvelle_geometrie = nettoyer_geometrie_base(
            geometrie_v2.intersection(couverture_avant)
        )
        if nouvelle_geometrie is None:
            self._avertir("Ce polygone BDFv2 ne produit aucune nouvelle surface dans v3.")
            return None

        fids_sources = {int(entite.id()) for entite in sources}
        modifications = {}
        suppressions = []
        fids_avec_reste = []

        self._rapporter(f"{prefixe}… découpe de {len(sources)} polygone(s) existant(s)")
        for entite in sources:
            geometrie_source = entite.geometry()
            nouvelle_locale = _extraire_local(nouvelle_geometrie, geometrie_source)
            reste = geometrie_source.difference(nouvelle_locale)
            if reste is None or reste.isEmpty():
                suppressions.append(int(entite.id()))
                continue

            reste = nettoyer_geometrie_base(reste)
            if reste is None:
                self._avertir(
                    f"Le polygone {entite.id()} deviendrait invalide après le report."
                )
                return None
            modifications[int(entite.id())] = reste
            fids_avec_reste.append(int(entite.id()))

        # Pas de verifier_partition ici (contrairement à « Créer ») : deux
        # polygones v3 déjà voisins du polygone reporté peuvent avoir un
        # micro-recouvrement préexistant entre eux, indépendant de ce report
        # (une anomalie déjà présente dans la donnée, du ressort de
        # "Recouvrements" dans Vérifier). Un contrôle qui exige une partition
        # parfaite bloquerait alors le report à cause d'un défaut qu'il n'a
        # pas introduit. Seule la validité de chaque morceau individuellement
        # (nouvelle_geometrie, chaque reste) est encore garantie ci-dessus.

        # Recolle localement toute partie de moins de 0,25 ha (SURFACE_MAXIMALE_PARTIE_ISOLEE_REPORT_M2)
        # qu'une découpe aurait isolée (jamais une vraie scission, laissée à
        # l'opérateur — voir l'avertissement plus bas).
        self._rapporter(f"{prefixe}… nettoyage des petites parties isolées")
        pieces = [nouvelle_geometrie] + [modifications[fid] for fid in fids_avec_reste]
        pieces, modifications_externes = self._recoller_parties_isolees(pieces, fids_sources)
        nouvelle_geometrie = pieces[0]
        for index, fid in enumerate(fids_avec_reste):
            modifications[fid] = pieces[index + 1]
        modifications.update(modifications_externes)

        # Ni bloquant ni corrigé : juste un avertissement, comme pour « Créer ».
        # Ne signale qu'une vraie scission restante (>= 0,25 ha) : le recollage
        # ci-dessus a déjà absorbé les micro-parties numériques.
        if any(
            compter_parties_polygonales(geometrie) != 1
            for geometrie in [nouvelle_geometrie] + list(modifications.values())
        ):
            self._avertir(
                "Le résultat produit une entité composée de plusieurs parties."
            )

        return {
            "nouvelle_geometrie": nouvelle_geometrie,
            "modifications": modifications,
            "suppressions": suppressions,
            "attributs_reference": _mapper_attributs(self.couche, entite_v2),
            "geometrie_zone": couverture_avant,
        }

    def _recoller_parties_isolees(self, pieces, fids_a_exclure):
        """Fusionne, dans le meilleur voisin, toute partie < 0,25 ha isolée
        par la découpe (jamais une vraie scission, laissée à l'opérateur).

        Cherche d'abord parmi les autres pièces du même report (une autre
        partie du lot touche souvent la partie isolée, puisque c'est la même
        découpe qui les a produites), via un index spatial plutôt qu'un
        parcours de toutes les pièces (un gros polygone BDFv2 peut en recouper
        des centaines : un parcours linéaire par orpheline deviendrait
        quadratique) ; sinon parmi les polygones v3 déjà en place (jamais
        l'une des sources en cours de remplacement, via ``fids_a_exclure``).
        Retourne ``(pieces_corrigees, modifications_externes)`` où
        ``modifications_externes`` est ``{fid: géométrie}`` pour les voisins
        v3 externes mis à jour.
        """
        pieces = list(pieces)
        modifications_externes = {}

        index_pieces = QgsSpatialIndex()
        for i, p in enumerate(pieces):
            if p is not None and not p.isEmpty():
                feature = QgsFeature(i)
                feature.setGeometry(p)
                index_pieces.addFeature(feature)

        for index_piece, piece in enumerate(pieces):
            if piece is None or compter_parties_polygonales(piece) <= 1:
                continue

            parties = [
                QgsGeometry(partie)
                for partie in piece.asGeometryCollection()
                if partie is not None and not partie.isEmpty()
            ]
            parties.sort(key=lambda g: g.area(), reverse=True)
            principale = parties[0]

            for orpheline in parties[1:]:
                if abs(float(orpheline.area())) >= SURFACE_MAXIMALE_PARTIE_ISOLEE_REPORT_M2:
                    fusion = _fusionner_localement(principale, orpheline)
                    principale = fusion if fusion is not None else principale
                    continue

                fusionnee_localement = False
                rect_recherche = orpheline.boundingBox()
                rect_recherche.grow(1.0)
                for autre_index in index_pieces.intersects(rect_recherche):
                    autre_index = int(autre_index)
                    if autre_index == index_piece:
                        continue
                    autre = pieces[autre_index]
                    if autre is None or autre.isEmpty():
                        continue
                    if orpheline.intersects(autre) or orpheline.touches(autre):
                        fusion = _fusionner_localement(autre, orpheline)
                        if fusion is not None:
                            pieces[autre_index] = fusion
                            fusionnee_localement = True
                            break
                if fusionnee_localement:
                    continue

                voisin_fid = meilleur_voisin_par_contact(self.couche, orpheline)
                if voisin_fid is not None and int(voisin_fid) not in fids_a_exclure:
                    voisin_fid = int(voisin_fid)
                    geometrie_voisin = modifications_externes.get(voisin_fid)
                    if geometrie_voisin is None:
                        entite_voisin = recuperer_entite(self.couche, voisin_fid)
                        if entite_voisin is not None:
                            geometrie_voisin = QgsGeometry(entite_voisin.geometry())
                    if geometrie_voisin is not None:
                        fusion = _fusionner_localement(geometrie_voisin, orpheline)
                        if fusion is not None:
                            modifications_externes[voisin_fid] = fusion
                            continue

                # Aucun voisin trouvé (local ou externe) : on garde la partie
                # rattachée à sa géométrie d'origine plutôt que de la perdre.
                fusion = _fusionner_localement(principale, orpheline)
                principale = fusion if fusion is not None else principale

            pieces[index_piece] = principale

        return pieces, modifications_externes

    @vue_stable_pendant_modification
    def _appliquer_report(self, preparation):
        """Applique géométries et surfaces, sans encore refermer la commande.

        La commande reste volontairement ouverte : elle n'est refermée qu'après
        le formulaire (cf. ``_ouvrir_formulaire``), pour que le collage et
        l'attribut saisi dans le formulaire ne fassent qu'un seul Ctrl+Z.
        """
        nouvelle_entite = creer_entite_nouvelle(
            self.couche,
            preparation["nouvelle_geometrie"],
            preparation["attributs_reference"],
        )

        commande_ouverte = False
        index_surface = self.couche.fields().indexOf("surface")

        try:
            self.couche.beginEditCommand(self.NOM_OUTIL)
            commande_ouverte = True

            for fid, geometrie in preparation["modifications"].items():
                exiger_fid_valide(self.couche, fid, "modifier la géométrie")
                if not self.couche.changeGeometry(fid, geometrie):
                    raise RuntimeError(f"échec de la modification du polygone {fid}")
                if index_surface >= 0:
                    surface = surface_ha(geometrie)
                    if not self.couche.changeAttributeValue(fid, index_surface, surface):
                        raise RuntimeError(
                            f"la surface du polygone {fid} n'a pas pu être recalculée"
                        )

            for fid in preparation["suppressions"]:
                exiger_fid_valide(self.couche, fid, "supprimer l'entité")
                if not self.couche.deleteFeature(fid):
                    raise RuntimeError(f"échec de la suppression du polygone {fid}")

            if index_surface >= 0:
                nouvelle_entite[index_surface] = surface_ha(preparation["nouvelle_geometrie"])
            if not self.couche.addFeature(nouvelle_entite):
                raise RuntimeError("la nouvelle entité n'a pas pu être créée")

            synchroniser_zone_outil(
                self.manager, self.iface, self.couche, preparation["geometrie_zone"], self.NOM_OUTIL
            )

            self.couche.triggerRepaint(True)
            self.canvas.refresh()
            return nouvelle_entite
        except Exception:
            if commande_ouverte:
                try:
                    self.couche.destroyEditCommand()
                except (RuntimeError, AttributeError):
                    pass
            raise

    def _ouvrir_formulaire(self, fid):
        """Ouvre le formulaire dans la commande encore ouverte de _appliquer_report.

        La commande n'est refermée (ou détruite) qu'ici, une fois le formulaire
        validé ou annulé : géométrie collée et attribut saisi ne forment ainsi
        qu'un seul Ctrl+Z, comme le ferait QGIS nativement.
        """
        try:
            entite = recuperer_entite(self.couche, fid)
            if entite is None:
                raise RuntimeError("la nouvelle entité est introuvable")

            self.surbrillance = remplacer_surbrillance_polygone(
                self.canvas, self.surbrillance, entite.geometry(), self.couche
            )
            if self.iface.openFeatureForm(self.couche, entite, False, True):
                self.couche.endEditCommand()
            else:
                self.couche.destroyEditCommand()
                self._avertir("Le report du polygone a été annulé.")
        except Exception:
            try:
                self.couche.destroyEditCommand()
            except (RuntimeError, AttributeError):
                pass
            raise

    def _avertir(self, message):
        avertir_message_bar(self.iface, self.NOM_OUTIL, message)
