"""Campagne d'évaluation sur CUAD.

L'évaluation porte sur la chaîne déterministe (découpage puis signalement) et
ne consomme aucun appel au modèle : elle est donc reproductible à l'identique
et gratuite, ce qui permet de la relancer à chaque modification du lexique.

## Pourquoi deux échantillons

Le lexique et le seuil de signalement ont été réglés en regardant les erreurs
commises sur CUAD. Mesurer ensuite la performance sur ces mêmes contrats
reviendrait à noter une copie sur les exercices qui ont servi à la réviser.

Le jeu est donc coupé en deux moitiés tirées à graine fixe : `mise-au-point`,
sur laquelle les réglages ont été choisis, et `validation`, qui n'a servi qu'à
la mesure finale. Les chiffres publiés sont ceux de la validation. L'option
`tout` reste disponible pour un inventaire complet, mais son résultat est
optimiste et ne doit pas être présenté comme une performance.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from clauseagent.evaluation.cuad import ContratAnnote, charger_cuad
from clauseagent.evaluation.metriques import RapportEvaluation, Score, evaluer_contrat
from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.risques import SEUIL_DEFAUT, signaler_risque

ECHANTILLONS = ("validation", "mise-au-point", "tout")
GRAINE_PARTAGE = 1


def evaluer_sur_cuad(
    chemin_jeu: str | Path,
    nombre_contrats: int | None = None,
    chemin_rapport: str | Path | None = None,
    graine: int = 0,
    echantillon: str = "validation",
    seuil: int = SEUIL_DEFAUT,
) -> RapportEvaluation:
    """Mesure la précision et le rappel sur CUAD.

    Args:
        chemin_jeu: Chemin de `CUAD_v1.json`.
        nombre_contrats: Taille de l'échantillon évalué. Tous si None.
        chemin_rapport: Si fourni, chemin du rapport JSON détaillé à écrire.
        graine: Graine du tirage, pour pouvoir rejouer le même échantillon.
        echantillon: `validation`, `mise-au-point` ou `tout`.
        seuil: Score minimal de signalement.

    Raises:
        ValueError: `echantillon` n'est pas une valeur reconnue.

    Returns:
        Le rapport agrégé, catégorie par catégorie.
    """
    if echantillon not in ECHANTILLONS:
        attendus = ", ".join(ECHANTILLONS)
        raise ValueError(f"Échantillon inconnu : {echantillon}. Valeurs : {attendus}.")

    contrats = charger_cuad(chemin_jeu)
    exploitables = [contrat for contrat in contrats if contrat.annotations]
    retenus = _partager(exploitables, echantillon)

    if nombre_contrats is not None and nombre_contrats < len(retenus):
        retenus = random.Random(graine).sample(retenus, nombre_contrats)

    rapport = RapportEvaluation(
        nombre_contrats=len(retenus), echantillon=echantillon, seuil=seuil
    )
    rapport.contrats_ignores = [
        contrat.titre for contrat in contrats if not contrat.annotations
    ]

    for contrat in retenus:
        clauses = decouper_clauses(contrat.texte)
        risques = signaler_risque(clauses, seuil=seuil)
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


def _partager(contrats: list[ContratAnnote], echantillon: str) -> list[ContratAnnote]:
    """Coupe le jeu en deux moitiés stables d'une exécution à l'autre."""
    if echantillon == "tout":
        return list(contrats)

    melange = list(contrats)
    random.Random(GRAINE_PARTAGE).shuffle(melange)
    coupure = len(melange) // 2
    return melange[:coupure] if echantillon == "mise-au-point" else melange[coupure:]
