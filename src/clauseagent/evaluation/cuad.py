"""Lecture du jeu CUAD (Contract Understanding Atticus Dataset).

CUAD rassemble 510 contrats commerciaux annotés par des juristes, au format
SQuAD 2.0 : à chaque contrat correspondent 41 questions, une par type de
clause, dont les réponses sont des passages repérés par leur position dans le
texte.

ClauseAgent ne couvre pas les 41 catégories. On n'évalue donc que celles qu'il
prétend traiter, en indiquant explicitement la correspondance retenue. Une
mesure sur des catégories non revendiquées ne dirait rien d'utile.

La correspondance doit aussi être de même portée des deux côtés. La catégorie
`resiliation` de ClauseAgent signale toute faculté de mettre fin au contrat,
alors que CUAD n'annote que la résiliation sans motif : mesurer l'une par
l'autre comptait comme erreurs des signalements corrects, et la précision
affichée n'avait pas de sens. C'est `resiliation_convenance`, de portée
identique, qui est désormais mise en regard. Les catégories sans équivalent
dans CUAD — résiliation générale, indemnisation, confidentialité, force
majeure — ne sont tout simplement pas mesurées ici.

Le jeu n'est pas inclus dans le dépôt : voir `donnees/README.md` pour
l'obtenir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from clauseagent.models import CategorieRisque

# Correspondance entre les catégories CUAD et celles de ClauseAgent. Plusieurs
# libellés CUAD peuvent alimenter une même catégorie : « Renewal Term » et
# « Notice Period To Terminate Renewal » relèvent tous deux du renouvellement.
CORRESPONDANCES: dict[str, CategorieRisque] = {
    "Liquidated Damages": CategorieRisque.PENALITE,
    "Termination For Convenience": CategorieRisque.RESILIATION_CONVENANCE,
    "Cap On Liability": CategorieRisque.RESPONSABILITE,
    "Uncapped Liability": CategorieRisque.RESPONSABILITE,
    "Insurance": CategorieRisque.ASSURANCE,
    "Ip Ownership Assignment": CategorieRisque.PROPRIETE_INTELLECTUELLE,
    "Joint Ip Ownership": CategorieRisque.PROPRIETE_INTELLECTUELLE,
    "License Grant": CategorieRisque.PROPRIETE_INTELLECTUELLE,
    "Irrevocable Or Perpetual License": CategorieRisque.PROPRIETE_INTELLECTUELLE,
    "Renewal Term": CategorieRisque.RENOUVELLEMENT_TACITE,
    "Notice Period To Terminate Renewal": CategorieRisque.RENOUVELLEMENT_TACITE,
}

CATEGORIES_EVALUEES: tuple[CategorieRisque, ...] = tuple(
    dict.fromkeys(CORRESPONDANCES.values())
)


@dataclass(frozen=True, slots=True)
class Passage:
    """Passage annoté : position dans le contrat et texte correspondant."""

    debut: int
    fin: int
    texte: str

    def chevauche(self, debut: int, fin: int) -> bool:
        return self.debut < fin and debut < self.fin


@dataclass(slots=True)
class ContratAnnote:
    """Un contrat CUAD et les passages attendus par catégorie."""

    titre: str
    texte: str
    annotations: dict[CategorieRisque, list[Passage]] = field(default_factory=dict)

    @property
    def nombre_annotations(self) -> int:
        return sum(len(passages) for passages in self.annotations.values())


def charger_cuad(chemin: str | Path, limite: int | None = None) -> list[ContratAnnote]:
    """Charge les contrats CUAD et leurs annotations exploitables.

    Args:
        chemin: Chemin de `CUAD_v1.json`.
        limite: Nombre maximal de contrats à charger.

    Raises:
        FileNotFoundError: Le fichier est absent.
        ValueError: Le fichier n'a pas la structure attendue.
    """
    fichier = Path(chemin).expanduser()
    if not fichier.is_file():
        raise FileNotFoundError(
            f"Jeu CUAD introuvable : {fichier}. Voir donnees/README.md pour l'obtenir."
        )

    donnees = json.loads(fichier.read_text(encoding="utf-8"))
    if "data" not in donnees:
        raise ValueError(
            f"{fichier.name} ne ressemble pas à CUAD : clé « data » absente."
        )

    contrats: list[ContratAnnote] = []
    for entree in donnees["data"]:
        contrat = _lire_contrat(entree)
        if contrat is None:
            continue
        contrats.append(contrat)
        if limite is not None and len(contrats) >= limite:
            break

    return contrats


def _lire_contrat(entree: dict) -> ContratAnnote | None:
    paragraphes = entree.get("paragraphs") or []
    if not paragraphes:
        return None

    texte = paragraphes[0].get("context", "")
    if not texte:
        return None

    annotations: dict[CategorieRisque, list[Passage]] = {}
    for question in paragraphes[0].get("qas", []):
        if question.get("is_impossible"):
            continue

        categorie = _categorie(question.get("id", ""), question.get("question", ""))
        if categorie is None:
            continue

        for reponse in question.get("answers", []):
            passage = _passage(reponse)
            if passage is not None:
                annotations.setdefault(categorie, []).append(passage)

    return ContratAnnote(
        titre=entree.get("title", "sans titre"),
        texte=texte,
        annotations=annotations,
    )


def _categorie(identifiant: str, question: str) -> CategorieRisque | None:
    """Retrouve la catégorie CUAD depuis l'identifiant ou l'intitulé.

    L'identifiant se termine par le nom de la catégorie (« ...__Insurance ») ;
    l'intitulé la cite entre guillemets. On essaie les deux, les deux formes
    coexistant selon les versions du jeu.
    """
    if "__" in identifiant:
        libelle = identifiant.rsplit("__", 1)[-1]
        categorie = CORRESPONDANCES.get(_titre(libelle))
        if categorie is not None:
            return categorie

    debut = question.find('"')
    fin = question.find('"', debut + 1)
    if debut != -1 and fin != -1:
        return CORRESPONDANCES.get(_titre(question[debut + 1 : fin]))
    return None


def _titre(libelle: str) -> str:
    """Normalise la casse d'un libellé CUAD (« IP Ownership » → « Ip Ownership »)."""
    return " ".join(mot.capitalize() for mot in libelle.replace("_", " ").split())


def _passage(reponse: dict) -> Passage | None:
    texte = reponse.get("text") or ""
    debut = reponse.get("answer_start")
    if not texte or debut is None or debut < 0:
        return None
    return Passage(debut=int(debut), fin=int(debut) + len(texte), texte=texte)
