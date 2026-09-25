# -*- coding: utf-8 -*-
"""Protection commune de la vue cartographique pendant les éditions.

Le plugin ne doit jamais décider où l'opérateur travaille sur la carte.
Cette classe protège uniquement la courte phase où une modification est
réellement appliquée (géométries, attributs, alertes, formulaires associés).

La vue de référence est prise au début de cette phase, donc après les éventuels
zooms/panoramiques faits volontairement par l'utilisateur pendant la sélection
ou le tracé. Les déplacements provoqués ensuite par QGIS sont masqués pendant
l'opération et annulés avant de rendre la main à l'utilisateur.

Aucun signal permanent, timer ou suivi de souris n'est installé : le mécanisme
n'a donc aucun coût lorsque le plugin ne modifie rien.
"""

from contextlib import contextmanager
from functools import wraps

from qgis.PyQt.QtCore import QEventLoop, QTimer
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsRectangle


class ProtectionVueCarte:
    """Service partagé qui conserve la vue pendant une modification interne."""

    def __init__(self, canvas):
        self.canvas = canvas
        # Compteur de réentrance : un outil peut appeler modification() alors
        # qu'il est déjà à l'intérieur d'un bloc modification() englobant (ex.
        # Fusionner qui délègue une partie du travail à une autre méthode
        # elle-même protégée). Seul le premier appel (profondeur 1) capture la
        # vue et gèle le canevas ; seul le dernier à se terminer (retour à 0)
        # la restaure.
        self._profondeur = 0
        self._contexte = None

    @contextmanager
    def modification(self):
        """Protège la vue pendant une opération, avec support des appels imbriqués."""
        self._commencer()
        try:
            yield
        finally:
            self._terminer()

    def _commencer(self):
        if self.canvas is None:
            return

        self._profondeur += 1
        if self._profondeur != 1:
            return

        try:
            self._contexte = (
                QgsRectangle(self.canvas.extent()),
                float(self.canvas.rotation()),
                bool(self.canvas.isFrozen()),
            )
            if not self._contexte[2]:
                self.canvas.freeze(True)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self._contexte = None

    def _terminer(self):
        if self.canvas is None or self._profondeur <= 0:
            return

        self._profondeur -= 1
        if self._profondeur != 0:
            return

        contexte = self._contexte
        self._contexte = None
        if contexte is None:
            return

        emprise, rotation, etait_deja_fige = contexte
        try:
            # Les formulaires et les relations QGIS programment plusieurs actions
            # avec QTimer.singleShot(0) (reconstruction d'un QgsDualView, choix
            # automatique d'une nouvelle fiche, puis pan/zoom éventuel). Un simple
            # processEvents() ne suffit pas toujours : un callback exécuté pendant
            # ce tour peut lui-même programmer le zoom pour le tour suivant.
            #
            # On laisse donc finir quelques tours de boucle Qt, uniquement pendant
            # la très courte phase de validation de l'édition et avec le canevas
            # encore gelé. Cette logique est commune à TOUS les outils géométriques.
            for _ in range(3):
                self._laisser_finir_evenements_differees()
                self._restaurer_vue_si_necessaire(emprise, rotation)

            # Un dernier passage couvre les notifications émises par la restauration
            # elle-même, sans installer de timer permanent ni de surveillance.
            self._laisser_finir_evenements_differees()
            self._restaurer_vue_si_necessaire(emprise, rotation)
        finally:
            try:
                if not bool(etait_deja_fige):
                    self.canvas.freeze(False)
                    self.canvas.refresh()
            except (AttributeError, RuntimeError):
                pass


    @staticmethod
    def _laisser_finir_evenements_differees():
        """Exécute un tour complet de la boucle Qt puis rend immédiatement la main.

        QTimer.singleShot(0) est très utilisé par les formulaires QGIS. Une boucle
        locale d'un seul tour est plus déterministe qu'un délai arbitraire et ne
        ralentit pas la navigation normale : elle n'existe que pendant une édition.
        """
        try:
            boucle = QEventLoop()
            QTimer.singleShot(0, boucle.quit)
            executer = getattr(boucle, "exec", None)
            if executer is None:
                executer = boucle.exec_
            executer()
        except (AttributeError, RuntimeError, TypeError):
            try:
                QApplication.processEvents()
            except (AttributeError, RuntimeError):
                pass

    def _restaurer_vue_si_necessaire(self, emprise, rotation):
        """Restaure uniquement si QGIS a réellement déplacé/rotaté le canevas."""
        try:
            rotation_actuelle = float(self.canvas.rotation())
            if abs(rotation_actuelle - float(rotation)) > 1e-9:
                self.canvas.setRotation(float(rotation))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

        try:
            actuelle = QgsRectangle(self.canvas.extent())
            if not _rectangles_equivalents(actuelle, emprise):
                self._restaurer_emprise(emprise)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass

    def _restaurer_emprise(self, emprise):
        """Restaure l'emprise en préservant autant que possible l'historique QGIS.

        Les zooms automatiques de QGIS passent généralement par setExtent(), qui
        les ajoute à l'historique. On remonte donc cet historique jusqu'à la vue
        de départ, puis un setExtent sur cette même vue supprime seulement les
        entrées automatiques placées devant elle sans ajouter de nouveau zoom.
        """
        cible = QgsRectangle(emprise)
        pas_retour = 0
        trouvee = False

        # Quelques notifications peuvent provoquer plusieurs auto-zooms de suite
        # (formulaire puis mise à jour des alertes). Une petite borne suffit et
        # évite de parcourir un historique utilisateur ancien en cas inhabituel.
        for _ in range(12):
            avant = QgsRectangle(self.canvas.extent())
            try:
                self.canvas.zoomToPreviousExtent()
            except (AttributeError, RuntimeError):
                break
            apres = QgsRectangle(self.canvas.extent())
            if _rectangles_equivalents(apres, avant):
                break
            pas_retour += 1
            if _rectangles_equivalents(apres, cible):
                trouvee = True
                break

        if trouvee:
            # Dans QgsMapCanvas::setExtent, appeler setExtent sur l'emprise
            # courante avec magnified=False purge les entrées "suivantes" sans
            # en ajouter une nouvelle si l'emprise est identique.
            self.canvas.setExtent(cible)
            return

        # Cas de secours : la vue de départ n'était pas dans l'historique. On
        # remet d'abord l'index là où il était avant notre recherche, puis on
        # restaure normalement l'emprise.
        for _ in range(pas_retour):
            try:
                self.canvas.zoomToNextExtent()
            except (AttributeError, RuntimeError):
                break
        self.canvas.setExtent(cible)


def _rectangles_equivalents(a, b):
    """Compare deux emprises avec une très petite tolérance numérique."""
    if a is None or b is None:
        return False
    try:
        valeurs_a = (a.xMinimum(), a.yMinimum(), a.xMaximum(), a.yMaximum())
        valeurs_b = (b.xMinimum(), b.yMinimum(), b.xMaximum(), b.yMaximum())
        echelle = max(1.0, *(abs(float(v)) for v in valeurs_a + valeurs_b))
        tolerance = echelle * 1e-12
        return all(abs(float(x) - float(y)) <= tolerance for x, y in zip(valeurs_a, valeurs_b))
    except (AttributeError, TypeError, ValueError):
        return False


def _service_pour_objet(objet):
    """Retourne le service partagé du gestionnaire, ou un secours local."""
    # Le service central (un seul par session QGIS, voir commun_outils.py)
    # est préféré : partager la même instance permet à _profondeur de
    # détecter correctement les appels imbriqués entre deux outils
    # différents, pas seulement à l'intérieur d'un même outil.
    manager = getattr(objet, "manager", None)
    service = getattr(manager, "protection_vue", None) if manager is not None else None
    if service is not None:
        return service

    # Repli : un outil sans manager (ex. appelé isolément dans un test) obtient
    # sa propre instance locale, moins puissante (pas de réentrance partagée
    # avec d'autres outils) mais qui fonctionne quand même.
    canvas = getattr(objet, "canvas", None)
    if canvas is None:
        iface = getattr(objet, "iface", None)
        if iface is not None:
            try:
                canvas = iface.mapCanvas()
            except (AttributeError, RuntimeError):
                canvas = None
    return ProtectionVueCarte(canvas)


def vue_stable_pendant_modification(fonction):
    """Décorateur commun pour toute action qui modifie la géométrie.

    Le code de protection est centralisé ici. Les outils ne font qu'indiquer
    quelles méthodes correspondent à une modification réelle.
    """
    @wraps(fonction)
    def enveloppe(objet, *args, **kwargs):
        service = _service_pour_objet(objet)
        with service.modification():
            return fonction(objet, *args, **kwargs)

    return enveloppe
