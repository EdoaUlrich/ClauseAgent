"""Configuration de l'agent, lue depuis l'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MODELE_DEFAUT = "claude-opus-5"
EFFORTS_VALIDES = ("low", "medium", "high", "xhigh", "max")


def _booleen(nom: str, defaut: bool) -> bool:
    valeur = os.getenv(nom)
    if valeur is None:
        return defaut
    return valeur.strip().lower() in {"1", "true", "vrai", "oui", "yes", "on"}


def _entier(nom: str, defaut: int) -> int:
    valeur = os.getenv(nom)
    if not valeur:
        return defaut
    try:
        return int(valeur)
    except ValueError:
        return defaut


@dataclass(slots=True)
class Configuration:
    """Parametres d'execution de l'agent."""

    modele: str = MODELE_DEFAUT
    effort: str = "high"
    anonymisation: bool = True
    max_iterations: int = 24
    max_tokens: int = 16000
    repertoire_sorties: Path = Path("sorties")
    cle_api: str | None = None

    @classmethod
    def depuis_environnement(cls) -> Configuration:
        effort = os.getenv("CLAUSEAGENT_EFFORT", "high").strip().lower()
        if effort not in EFFORTS_VALIDES:
            effort = "high"
        return cls(
            modele=os.getenv("CLAUSEAGENT_MODELE", MODELE_DEFAUT).strip() or MODELE_DEFAUT,
            effort=effort,
            anonymisation=_booleen("CLAUSEAGENT_ANONYMISATION", True),
            max_iterations=_entier("CLAUSEAGENT_MAX_ITERATIONS", 24),
            max_tokens=_entier("CLAUSEAGENT_MAX_TOKENS", 16000),
            repertoire_sorties=Path(os.getenv("CLAUSEAGENT_SORTIES", "sorties")),
            cle_api=os.getenv("ANTHROPIC_API_KEY") or None,
        )

    def verifier_cle(self) -> None:
        """Leve une erreur explicite si aucune cle d'API n'est disponible."""
        if not self.cle_api:
            raise RuntimeError(
                "Aucune cle d'API trouvee. Renseignez ANTHROPIC_API_KEY dans "
                "l'environnement ou dans un fichier .env (voir .env.example)."
            )
