# -*- coding: utf-8 -*-
"""Mémoire légère de la dernière fiche consultée entre deux sessions QGIS.

Ce service ne contrôle jamais l'interface :
- il n'ouvre pas de table attributaire ;
- il ne change pas de vue ;
- il ne touche ni au zoom, ni au tri, ni à la sélection.

Il conserve seulement le dernier FID connu pour la couche BD Forêt du projet.
La restauration de ce FID est faite par ``HistoriqueFormulaires`` uniquement
quand l'utilisateur ouvre lui-même une vue formulaire.
"""

import hashlib
import json

from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsProject

from .commun_couches import normaliser_nom
from .commun_parametres import PREFIXE_COUCHE_PARENT


class EtatSessionProjet:
    """Persiste uniquement le dernier FID de travail du projet."""

    # Préfixe des clés QSettings : évite toute collision avec les réglages
    # d'un autre plugin ou de QGIS lui-même.
    RACINE_REGLAGES = "reprise_pi/etat_session"

    def __init__(self, iface):
        self.iface = iface
        self.projet = QgsProject.instance()
        self._connecte = False
        # État en RAM seulement, jamais lu directement : la persistance passe
        # toujours par QSettings (voir _sauvegarder_etat/_lire_etat), pour
        # survivre à une fermeture de QGIS.
        self._dernier_formulaire = None

    def initGui(self):
        if self._connecte:
            return
        try:
            # aboutToBeCleared : le projet va être remplacé (fermeture ou
            # ouverture d'un autre .qgz) — dernière chance d'écrire l'état
            # courant avant qu'il ne soit plus accessible.
            self.projet.aboutToBeCleared.connect(self._sauvegarder_etat)
            # projectSaved : sauvegarde explicite par l'utilisateur (Ctrl+S).
            self.projet.projectSaved.connect(self._sauvegarder_etat)
            # readProject : un nouveau projet vient d'être chargé, l'ancien
            # état en RAM ne correspond plus à rien.
            self.projet.readProject.connect(self._projet_lu)
            self._connecte = True
        except (AttributeError, TypeError, RuntimeError):
            self._connecte = False

    def unload(self):
        # Une seule écriture à la fermeture/rechargement du plugin.
        self._sauvegarder_etat()
        if not self._connecte:
            return
        for signal, slot in (
            (self.projet.aboutToBeCleared, self._sauvegarder_etat),
            (self.projet.projectSaved, self._sauvegarder_etat),
            (self.projet.readProject, self._projet_lu),
        ):
            try:
                signal.disconnect(slot)
            except (AttributeError, TypeError, RuntimeError):
                pass
        self._connecte = False

    # ------------------------------------------------------------------
    # Projet et persistance
    # ------------------------------------------------------------------

    def _chemin_projet(self):
        try:
            return str(self.projet.absoluteFilePath() or self.projet.fileName() or "").strip()
        except (AttributeError, RuntimeError):
            return ""

    @classmethod
    def _cle_reglage(cls, chemin):
        # Empreinte plutôt que le chemin en clair : un chemin de fichier peut
        # contenir des caractères que QSettings gère mal comme clé, et le
        # hash reste stable même si le nom du projet contient des accents ou
        # des espaces. .lower() ignore la casse du système de fichiers
        # (Windows n'est pas sensible à la casse).
        empreinte = hashlib.sha1(chemin.lower().encode("utf-8")).hexdigest()
        return f"{cls.RACINE_REGLAGES}/{empreinte}"

    def _sauvegarder_etat(self, *args):
        """Écrit le dernier FID connu, sans inspecter l'interface QGIS."""
        chemin = self._chemin_projet()
        if not chemin or not isinstance(self._dernier_formulaire, dict):
            return
        try:
            # QSettings persiste au niveau du système (registre Windows,
            # fichier .conf sur Linux/Mac), indépendamment du projet QGIS
            # lui-même : l'état survit même si le .qgz n'est jamais resauvegardé.
            QSettings().setValue(
                self._cle_reglage(chemin),
                json.dumps(
                    {"formulaire": dict(self._dernier_formulaire)},
                    ensure_ascii=False,
                ),
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _lire_etat(self):
        chemin = self._chemin_projet()
        if not chemin:
            return None
        try:
            brut = QSettings().value(self._cle_reglage(chemin), "")
            if not brut:
                return None
            etat = json.loads(str(brut))
            return etat if isinstance(etat, dict) else None
        except (TypeError, ValueError, RuntimeError):
            return None

    def _projet_lu(self, *args):
        """Oublie seulement la mémoire RAM de l'ancien projet.

        Aucune table n'est ouverte ici. Le FID persistant sera consulté plus
        tard, uniquement si l'utilisateur ouvre lui-même une vue formulaire.
        """
        self._dernier_formulaire = None

    # ------------------------------------------------------------------
    # Dernier FID
    # ------------------------------------------------------------------

    def _est_couche_parent(self, couche):
        if couche is None:
            return False
        try:
            return normaliser_nom(couche.name()).startswith(
                normaliser_nom(PREFIXE_COUCHE_PARENT)
            )
        except (AttributeError, RuntimeError):
            return False

    def memoriser_formulaire(self, couche, fid, _vue_formulaire=True):
        """Mémorise le dernier FID en RAM, sans écriture disque immédiate."""
        if couche is None or not self._est_couche_parent(couche):
            return
        try:
            # layer_id ET layer_name : l'id QGIS change si la couche est
            # rechargée dans une autre session, mais le nom seul pourrait
            # matcher la mauvaise couche si le projet en a plusieurs
            # similaires. fid_memorise_pour_couche() accepte l'un OU l'autre.
            self._dernier_formulaire = {
                "layer_id": str(couche.id()),
                "layer_name": str(couche.name()),
                "fid": int(fid),
            }
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def fid_memorise_pour_couche(self, couche):
        """Retourne le FID persistant de la couche s'il existe encore.

        Si le FID a disparu, ``None`` est renvoyé et QGIS reste sur sa première
        fiche. Aucun identifiant métier n'est utilisé en secours.
        """
        if couche is None or not self._est_couche_parent(couche):
            return None

        etat = self._lire_etat()
        if not etat:
            return None
        formulaire = etat.get("formulaire") or {}

        try:
            # Coïncidence sur l'id OU le nom : l'id QGIS n'est stable que dans
            # la même session (il inclut un suffixe généré à l'ajout de la
            # couche), donc rouvrir le même projet plus tard ne le retrouve
            # que par le nom.
            meme_couche = (
                str(formulaire.get("layer_id") or "") == str(couche.id())
                or normaliser_nom(str(formulaire.get("layer_name") or ""))
                == normaliser_nom(str(couche.name()))
            )
        except (AttributeError, RuntimeError):
            return None
        if not meme_couche:
            return None

        try:
            # L'entité a pu être supprimée depuis la dernière session : on ne
            # retourne jamais un FID qui n'existe plus, pour ne pas faire
            # échouer l'ouverture du formulaire au démarrage.
            fid = int(formulaire.get("fid"))
            entite = couche.getFeature(fid)
            return fid if entite is not None and entite.isValid() else None
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
