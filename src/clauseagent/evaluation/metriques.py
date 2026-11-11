"""Précision, rappel et F1 par type de clause.

**Ce qui est mesuré.** CUAD annote des passages ; ClauseAgent signale des
clauses entières. On ne peut donc pas comparer caractère par caractère. La
règle retenue : un passage annoté compte comme retrouvé si une clause signalée
dans la même catégorie recouvre sa position, et une clause signalée compte
comme correcte si elle recouvre au moins un passage annoté de cette catégorie.

C'est une mesure au niveau de la clause, plus permissive que la métrique
officielle de CUAD (recouvrement de Jaccard supérieur à 0,5). Elle correspond
à l'usage réel de l'outil : orienter un gestionnaire vers les clauses à relire,
pas surligner un passage au mot près. Les chiffres obtenus ne sont donc pas
comparables aux publications sur CUAD, et l'indiquer fait partie du résultat.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clauseagent.evaluation.cuad import CATEGORIES_EVALUEES, ContratAnnote
from clauseagent.models import CategorieRisque, Clause, Risque


@dataclass(slots=True)
class Score:
    """Comptages et métriques dérivées pour une catégorie."""

    vrais_positifs: int = 0
    faux_positifs: int = 0
    faux_negatifs: int = 0

    def ajouter(self, autre: Score) -> None:
        self.vrais_positifs += autre.vrais_positifs
        self.faux_positifs += autre.faux_positifs
        self.faux_negatifs += autre.faux_negatifs

    @property
    def precision(self) -> float:
        predits = self.vrais_positifs + self.faux_positifs
        return self.vrais_positifs / predits if predits else 0.0

    @property
    def rappel(self) -> float:
        attendus = self.vrais_positifs + self.faux_negatifs
        return self.vrais_positifs / attendus if attendus else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.rappel
        return 2 * self.precision * self.rappel / total if total else 0.0

    @property
    def attendus(self) -> int:
        return self.vrais_positifs + self.faux_negatifs


@dataclass(slots=True)
class RapportEvaluation:
    """Résultat agrégé d'une campagne d'évaluation."""

    nombre_contrats: int = 0
    scores: dict[CategorieRisque, Score] = field(default_factory=dict)
    contrats_ignores: list[str] = field(default_factory=list)

    @property
    def global_(self) -> Score:
        total = Score()
        for score in self.scores.values():
            total.ajouter(score)
        return total

    def en_dictionnaire(self) -> dict:
        return {
            "contrats_evalues": self.nombre_contrats,
            "contrats_ignores": self.contrats_ignores,
            "global": _mesures(self.global_),
            "par_categorie": {
                categorie.value: _mesures(score)
                for categorie, score in self.scores.items()
            },
        }

    def rendu_texte(self) -> str:
        lignes = [
            f"Évaluation sur {self.nombre_contrats} contrats CUAD",
            "",
            f"{'Catégorie':<26}{'Attendus':>9}{'Précision':>11}{'Rappel':>9}{'F1':>8}",
            "-" * 63,
        ]
        for categorie in CATEGORIES_EVALUEES:
            score = self.scores.get(categorie, Score())
            lignes.append(
                f"{categorie.value:<26}{score.attendus:>9}"
                f"{score.precision:>10.0%}{score.rappel:>9.0%}{score.f1:>8.2f}"
            )

        total = self.global_
        lignes += [
            "-" * 63,
            f"{'Ensemble':<26}{total.attendus:>9}"
            f"{total.precision:>10.0%}{total.rappel:>9.0%}{total.f1:>8.2f}",
            "",
            "Mesure au niveau de la clause : un passage annoté est considéré comme",
            "retrouvé dès qu'une clause signalée de la même catégorie le recouvre.",
        ]
        if self.contrats_ignores:
            lignes.append(
                f"{len(self.contrats_ignores)} contrats écartés faute d'annotation "
                "sur les catégories couvertes."
            )
        return "\n".join(lignes)


def evaluer_contrat(
    contrat: ContratAnnote, clauses: list[Clause], risques: list[Risque]
) -> dict[CategorieRisque, Score]:
    """Compare les signalements produits aux annotations d'un contrat."""
    positions = {clause.identifiant: (clause.debut, clause.fin) for clause in clauses}
    scores: dict[CategorieRisque, Score] = {}

    for categorie in CATEGORIES_EVALUEES:
        attendus = contrat.annotations.get(categorie, [])
        predits = [
            positions[risque.clause_identifiant]
            for risque in risques
            if risque.categorie is categorie and risque.clause_identifiant in positions
        ]

        if not attendus and not predits:
            continue

        score = Score()
        score.vrais_positifs = sum(
            1
            for passage in attendus
            if any(passage.chevauche(debut, fin) for debut, fin in predits)
        )
        score.faux_negatifs = len(attendus) - score.vrais_positifs
        score.faux_positifs = sum(
            1
            for debut, fin in predits
            if not any(passage.chevauche(debut, fin) for passage in attendus)
        )
        scores[categorie] = score

    return scores


def _mesures(score: Score) -> dict:
    return {
        "attendus": score.attendus,
        "vrais_positifs": score.vrais_positifs,
        "faux_positifs": score.faux_positifs,
        "faux_negatifs": score.faux_negatifs,
        "precision": round(score.precision, 4),
        "rappel": round(score.rappel, 4),
        "f1": round(score.f1, 4),
    }
