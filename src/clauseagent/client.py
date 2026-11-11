"""Création du client Anthropic partagé par l'agent et ses outils."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clauseagent.config import Configuration

if TYPE_CHECKING:  # pragma: no cover - import différé pour alléger le démarrage
    from anthropic import Anthropic


def creer_client(configuration: Configuration | None = None) -> Anthropic:
    """Retourne un client Anthropic prêt à l'emploi.

    La clé est lue dans l'environnement par le SDK lui-même ; on la vérifie en
    amont pour échouer avec un message utile plutôt qu'au premier appel réseau.
    """
    from anthropic import Anthropic

    configuration = configuration or Configuration.depuis_environnement()
    configuration.verifier_cle()
    return Anthropic(api_key=configuration.cle_api)
