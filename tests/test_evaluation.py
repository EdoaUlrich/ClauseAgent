"""Tests du harnais d'évaluation CUAD, sur un jeu réduit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clauseagent.evaluation.cuad import CORRESPONDANCES, Passage, charger_cuad
from clauseagent.evaluation.executer import evaluer_sur_cuad
from clauseagent.evaluation.metriques import Score, evaluer_contrat
from clauseagent.models import CategorieRisque
from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.risques import signaler_risque

MINI_CUAD = Path(__file__).parent / "donnees" / "mini_cuad.json"


def test_chargement_des_annotations():
    contrats = charger_cuad(MINI_CUAD)

    assert len(contrats) == 2
    premier = contrats[0]
    assert premier.titre == "MasterServicesAgreement"
    assert CategorieRisque.PENALITE in premier.annotations
    assert CategorieRisque.ASSURANCE in premier.annotations


def test_les_categories_non_couvertes_sont_ecartees():
    """« Governing Law » n'est pas une catégorie revendiquée par ClauseAgent."""
    contrats = charger_cuad(MINI_CUAD)
    attendues = set(CORRESPONDANCES.values())

    assert all(categorie in attendues for categorie in contrats[0].annotations)


def test_les_questions_sans_reponse_sont_ignorees():
    contrats = charger_cuad(MINI_CUAD)
    assert CategorieRisque.PENALITE not in contrats[1].annotations


def test_les_positions_pointent_vers_le_texte():
    contrat = charger_cuad(MINI_CUAD)[0]
    for passages in contrat.annotations.values():
        for passage in passages:
            assert contrat.texte[passage.debut : passage.fin] == passage.texte


def test_limite_de_chargement():
    assert len(charger_cuad(MINI_CUAD, limite=1)) == 1


def test_jeu_absent():
    with pytest.raises(FileNotFoundError, match="donnees/README"):
        charger_cuad("absent.json")


def test_fichier_hors_format(tmp_path: Path):
    fichier = tmp_path / "autre.json"
    fichier.write_text(json.dumps({"autre": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="CUAD"):
        charger_cuad(fichier)


def test_chevauchement_de_passages():
    passage = Passage(debut=100, fin=200, texte="x")

    assert passage.chevauche(150, 250)
    assert passage.chevauche(0, 150)
    assert not passage.chevauche(200, 300)
    assert not passage.chevauche(0, 100)


def test_evaluation_d_un_contrat_retrouve_les_clauses_annotees():
    contrat = charger_cuad(MINI_CUAD)[0]
    clauses = decouper_clauses(contrat.texte)
    risques = signaler_risque(clauses)

    scores = evaluer_contrat(contrat, clauses, risques)

    for categorie in (
        CategorieRisque.PENALITE,
        CategorieRisque.ASSURANCE,
        CategorieRisque.RESILIATION_CONVENANCE,
        CategorieRisque.RENOUVELLEMENT_TACITE,
    ):
        assert scores[categorie].rappel == 1.0, categorie


def test_campagne_complete_et_rapport(tmp_path: Path):
    rapport_json = tmp_path / "rapport.json"
    rapport = evaluer_sur_cuad(
        MINI_CUAD, echantillon="tout", chemin_rapport=rapport_json
    )

    assert rapport.nombre_contrats == 2
    assert rapport.global_.attendus > 0
    assert 0.0 <= rapport.global_.precision <= 1.0

    contenu = json.loads(rapport_json.read_text(encoding="utf-8"))
    assert contenu["contrats_evalues"] == 2
    assert contenu["echantillon"] == "tout"
    assert "par_categorie" in contenu


def test_le_tirage_est_reproductible():
    premier = evaluer_sur_cuad(MINI_CUAD, nombre_contrats=1, graine=7, echantillon="tout")
    second = evaluer_sur_cuad(MINI_CUAD, nombre_contrats=1, graine=7, echantillon="tout")

    assert premier.en_dictionnaire() == second.en_dictionnaire()


def test_les_echantillons_sont_disjoints_et_stables():
    """Le réglage et la mesure ne doivent jamais porter sur les mêmes contrats."""
    reglage = evaluer_sur_cuad(MINI_CUAD, echantillon="mise-au-point")
    mesure = evaluer_sur_cuad(MINI_CUAD, echantillon="validation")
    tout = evaluer_sur_cuad(MINI_CUAD, echantillon="tout")

    assert reglage.nombre_contrats + mesure.nombre_contrats == tout.nombre_contrats
    assert evaluer_sur_cuad(MINI_CUAD, echantillon="validation").en_dictionnaire() == (
        mesure.en_dictionnaire()
    )


def test_echantillon_inconnu_refuse():
    with pytest.raises(ValueError, match="Échantillon inconnu"):
        evaluer_sur_cuad(MINI_CUAD, echantillon="entrainement")


def test_le_rapport_signale_un_resultat_optimiste():
    rendu = evaluer_sur_cuad(MINI_CUAD, echantillon="tout").rendu_texte()

    assert "optimiste" in rendu


def test_rendu_texte_lisible():
    rendu = evaluer_sur_cuad(MINI_CUAD, echantillon="tout").rendu_texte()

    assert "Évaluation sur 2 contrats CUAD" in rendu
    assert "Précision" in rendu
    assert "niveau de la clause" in rendu


def test_score_sans_donnees():
    score = Score()
    assert score.precision == 0.0
    assert score.rappel == 0.0
    assert score.f1 == 0.0
