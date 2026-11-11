"""Outils que l'agent peut appeler pour analyser un contrat."""

from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.echeances import calculer_echeance
from clauseagent.outils.export import exporter_excel
from clauseagent.outils.extraction import extraire_clause
from clauseagent.outils.lecture import lire_document
from clauseagent.outils.risques import signaler_risque

__all__ = [
    "calculer_echeance",
    "decouper_clauses",
    "exporter_excel",
    "extraire_clause",
    "lire_document",
    "signaler_risque",
]
