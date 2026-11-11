"""Évaluation de ClauseAgent sur le jeu annoté CUAD."""

from clauseagent.evaluation.cuad import ContratAnnote, charger_cuad
from clauseagent.evaluation.executer import evaluer_sur_cuad
from clauseagent.evaluation.metriques import RapportEvaluation, Score, evaluer_contrat

__all__ = [
    "ContratAnnote",
    "RapportEvaluation",
    "Score",
    "charger_cuad",
    "evaluer_contrat",
    "evaluer_sur_cuad",
]
