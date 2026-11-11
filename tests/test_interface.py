"""Tests de l'interface graphique, exécutés sans affichage.

On ne teste pas l'apparence mais le câblage : le travailleur produit-il une
analyse exploitable, et la fenêtre la restitue-t-elle intégralement dans ses
tableaux ? Le mode « inspecter » suffit pour cela et n'exige aucune clé d'API.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="interface graphique facultative")

from PySide6.QtWidgets import QApplication  # noqa: E402

from clauseagent.config import Configuration  # noqa: E402
from clauseagent.interface.application import FenetrePrincipale  # noqa: E402
from clauseagent.interface.travailleur import Travailleur  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_le_travailleur_produit_une_analyse(
    chemin_contrat: Path, configuration: Configuration
):
    etapes: list[str] = []
    resultats: list[tuple] = []

    travailleur = Travailleur(chemin_contrat, configuration, avec_modele=False)
    travailleur.etape.connect(etapes.append)
    travailleur.termine.connect(lambda analyse, export: resultats.append((analyse, export)))
    travailleur.executer()

    assert etapes
    analyse, export = resultats[0]
    assert len(analyse.clauses) > 15
    assert analyse.risques
    assert export is None


def test_le_travailleur_signale_les_erreurs(configuration: Configuration):
    erreurs: list[str] = []

    travailleur = Travailleur(Path("absent.pdf"), configuration, avec_modele=False)
    travailleur.echoue.connect(erreurs.append)
    travailleur.executer()

    assert erreurs and "introuvable" in erreurs[0].lower()


def test_la_fenetre_restitue_l_analyse(
    application: QApplication, chemin_contrat: Path, configuration: Configuration
):
    fenetre = FenetrePrincipale()
    fenetre.configuration = configuration

    resultats: list[tuple] = []
    travailleur = Travailleur(chemin_contrat, configuration, avec_modele=False)
    travailleur.termine.connect(lambda analyse, export: resultats.append((analyse, export)))
    travailleur.executer()

    analyse, export = resultats[0]
    fenetre._afficher_resultat(analyse, export)

    assert fenetre.table_clauses.rowCount() == len(analyse.clauses)
    assert fenetre.table_risques.rowCount() == len(analyse.risques)
    assert fenetre.bouton_exporter.isEnabled()
    assert "clauses signalées" in fenetre.zone_synthese.toPlainText()


def test_l_export_depuis_l_interface(
    application: QApplication, chemin_contrat: Path, configuration: Configuration
):
    from clauseagent.outils.export import exporter_excel

    resultats: list[tuple] = []
    travailleur = Travailleur(chemin_contrat, configuration, avec_modele=False)
    travailleur.termine.connect(lambda analyse, export: resultats.append((analyse, export)))
    travailleur.executer()

    chemin = exporter_excel(resultats[0][0], configuration.repertoire_sorties / "ui.xlsx")
    assert chemin.exists()
