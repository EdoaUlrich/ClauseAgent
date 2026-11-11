"""Campagne d'évaluation sur CUAD.

L'évaluation porte sur la chaîne déterministe (découpage puis signalement) et
ne consomme aucun appel au modèle : elle est donc reproductible à l'identique
et gratuite, ce qui permet de la relancer à chaque modification du lexique.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from clauseagent.evaluation.cuad import charger_cuad
from clauseagent.evaluation.metriques import RapportEvaluation, Score, evaluer_contrat
from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.risques import signaler_risque


def evaluer_sur_cuad(
    chemin_jeu: str | Path,
    nombre_contrats: int = 10,
    chemin_rapport: str | Path | None = None,
    graine: int = 0,
) -> RapportEvaluation:
    """Mesure la précision et le rappel sur un échantillon de CUAD.

    Args:
        chemin_jeu: Chemin de `CUAD_v1.json`.
        nombre_contrats: Taille de l'échantillon évalué.
        chemin_rapport: Si fourni, chemin du rapport JSON détaillé à écrire.
        graine: Graine du tirage, pour pouvoir rejouer le même échantillon.

    Returns:
        Le rapport agrégé, catégorie par catégorie.
    """
    contrats = charger_cuad(chemin_jeu)
    exploitables = [contrat for contrat in contrats if contrat.annotations]

    tirage = random.Random(graine)
    echantillon = (
        tirage.sample(exploitables, nombre_contrats)
        if nombre_contrats < len(exploitables)
        else exploitables
    )

    rapport = RapportEvaluation(nombre_contrats=len(echantillon))
    rapport.contrats_ignores = [
        contrat.titre for contrat in contrats if not contrat.annotations
    ]

    for contrat in echantillon:
        clauses = decouper_clauses(contrat.texte)
        risques = signaler_risque(clauses)
        for categorie, score in evaluer_contrat(contrat, clauses, risques).items():
            rapport.scores.setdefault(categorie, Score()).ajouter(score)

    if chemin_rapport:
        destination = Path(chemin_rapport).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(rapport.en_dictionnaire(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return rapport
