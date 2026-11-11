"""Fixtures communes : contrat d'exemple et client Anthropic factice.

Le client factice permet d'exercer la boucle agentique, l'anonymisation et
l'export sans appel réseau ni clé d'API. Il rejoue un scénario d'appels
d'outils et fabrique des extractions à partir du texte réellement reçu, ce qui
permet de vérifier que les citations restent recoupables après restauration.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from clauseagent.config import Configuration
from clauseagent.models import ElementExtrait, ExtractionClause, TypeElement

RACINE = Path(__file__).resolve().parents[1]
CONTRAT_EXEMPLE = RACINE / "exemples" / "contrat_maintenance.txt"


@pytest.fixture
def chemin_contrat() -> Path:
    return CONTRAT_EXEMPLE


@pytest.fixture
def texte_contrat() -> str:
    return CONTRAT_EXEMPLE.read_text(encoding="utf-8")


@pytest.fixture
def configuration(tmp_path: Path) -> Configuration:
    return Configuration(
        modele="modele-de-test",
        effort="low",
        anonymisation=True,
        max_iterations=12,
        max_tokens=4096,
        repertoire_sorties=tmp_path / "sorties",
        cle_api="cle-de-test",
    )


def bloc_outil(nom: str, entree: dict[str, Any], identifiant: str) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=nom, input=entree, id=identifiant)


def bloc_texte(texte: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texte)


def reponse(blocs: list[SimpleNamespace], motif: str) -> SimpleNamespace:
    return SimpleNamespace(content=blocs, stop_reason=motif, stop_details=None)


def tour_outil(
    nom: str, entree: dict[str, Any] | None = None, identifiant: str = "t"
) -> SimpleNamespace:
    """Tour où le modèle appelle un seul outil."""
    return reponse([bloc_outil(nom, entree or {}, identifiant)], "tool_use")


def tour_final(texte: str) -> SimpleNamespace:
    """Tour de clôture : le modèle rend sa synthèse."""
    return reponse([bloc_texte(texte)], "end_turn")


class MessagesFactices:
    """Rejoue un scénario d'appels d'outils et fabrique les extractions."""

    def __init__(self, scenario: list[SimpleNamespace]) -> None:
        self.scenario = scenario
        self.tour = 0
        self.appels_create: list[dict[str, Any]] = []
        self.appels_parse: list[dict[str, Any]] = []

    def create(self, **parametres: Any) -> SimpleNamespace:
        # L'agent fait grossir sa liste de messages en place : on en garde une
        # photographie, sinon tous les appels enregistrés pointeraient vers
        # l'état final de la conversation.
        self.appels_create.append({**parametres, "messages": list(parametres["messages"])})
        if self.tour >= len(self.scenario):
            return reponse([bloc_texte("Analyse terminée.")], "end_turn")
        prochaine = self.scenario[self.tour]
        self.tour += 1
        return prochaine

    def parse(self, **parametres: Any) -> SimpleNamespace:
        self.appels_parse.append(parametres)
        invite = parametres["messages"][0]["content"]
        corps = invite.split("Texte :", 1)[-1].strip()
        phrases = [p.strip() for p in re.split(r"(?<=\.)\s+", corps) if len(p.strip()) > 25]
        citation = phrases[0] if phrases else corps[:120]

        extraction = ExtractionClause(
            synthese="Synthèse factice.",
            elements=[
                ElementExtrait(
                    type=TypeElement.OBLIGATION,
                    partie_concernee="le Prestataire",
                    description="Engagement relevé par le client factice.",
                    echeance_textuelle="30 jours à compter de la réception de la facture",
                    citation=citation,
                )
            ],
        )
        return SimpleNamespace(parsed_output=extraction, stop_reason="end_turn")


class ClientFactice:
    def __init__(self, scenario: list[SimpleNamespace] | None = None) -> None:
        self.messages = MessagesFactices(scenario or [])


@pytest.fixture
def scenario_complet(chemin_contrat: Path) -> list[SimpleNamespace]:
    """Enchaînement nominal : lecture, découpage, dates, extraction, export."""
    return [
        reponse([bloc_outil("lire_document", {"chemin": str(chemin_contrat)}, "t1")], "tool_use"),
        reponse([bloc_outil("decouper_clauses", {}, "t2")], "tool_use"),
        reponse(
            [
                bloc_outil(
                    "definir_evenement",
                    {"nom": "prise_effet", "date": "2026-03-01", "source": "Préambule"},
                    "t3a",
                ),
                bloc_outil(
                    "definir_evenement",
                    {"nom": "facture", "date": "2026-04-15", "source": "Article 4.2"},
                    "t3b",
                ),
            ],
            "tool_use",
        ),
        reponse(
            [
                bloc_outil("extraire_clause", {"clause_identifiant": "Article 4.2"}, "t4"),
                bloc_outil("extraire_clause", {"clause_identifiant": "Article 5.1"}, "t5"),
            ],
            "tool_use",
        ),
        reponse(
            [
                bloc_outil(
                    "calculer_echeance",
                    {
                        "expression": "30 jours à compter de la réception de la facture",
                        "clause_identifiant": "Article 4.2",
                    },
                    "t6",
                )
            ],
            "tool_use",
        ),
        reponse([bloc_outil("signaler_risque", {}, "t7")], "tool_use"),
        reponse(
            [bloc_outil("exporter_excel", {"nom_fichier": "suivi_test.xlsx"}, "t8")],
            "tool_use",
        ),
        reponse([bloc_texte("Inventaire terminé : 2 obligations relevées.")], "end_turn"),
    ]
