"""Exécution de l'analyse dans un fil séparé.

Une analyse enchaîne plusieurs appels réseau et peut durer une minute ou deux.
La faire tourner dans le fil de l'interface figerait la fenêtre, ce qui est
inacceptable pour un outil de travail : l'utilisateur doit pouvoir lire le
journal pendant que l'agent avance. Seuls des signaux traversent la frontière
entre les deux fils ; aucun widget n'est manipulé depuis le travailleur.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from clauseagent.config import Configuration
from clauseagent.models import AnalyseContrat


class Travailleur(QObject):
    """Lance l'analyse d'un contrat et rend compte de son avancement."""

    etape = Signal(str)
    termine = Signal(object, object)
    echoue = Signal(str)

    def __init__(
        self,
        chemin: Path,
        configuration: Configuration,
        consigne: str | None = None,
        avec_modele: bool = True,
    ) -> None:
        super().__init__()
        self.chemin = chemin
        self.configuration = configuration
        self.consigne = consigne
        self.avec_modele = avec_modele

    def executer(self) -> None:
        try:
            if self.avec_modele:
                analyse, export = self._analyser_avec_agent()
            else:
                analyse, export = self._inspecter()
        except Exception as erreur:
            self.echoue.emit(str(erreur))
            return

        self.termine.emit(analyse, export)

    def _analyser_avec_agent(self) -> tuple[AnalyseContrat, Path | None]:
        from clauseagent.agent import Agent

        agent = Agent(configuration=self.configuration, journaliser=self.etape.emit)
        self.etape.emit(f"Analyse de {self.chemin.name} par {self.configuration.modele}")
        analyse = agent.analyser(self.chemin, consigne=self.consigne)
        return analyse, agent.chemin_export

    def _inspecter(self) -> tuple[AnalyseContrat, Path | None]:
        """Chaîne déterministe : aucun appel au modèle, aucune clé requise."""
        from clauseagent.outils.decoupage import decouper_clauses
        from clauseagent.outils.lecture import lire_document
        from clauseagent.outils.risques import signaler_risque

        self.etape.emit(f"Lecture de {self.chemin.name}")
        document = lire_document(self.chemin)

        self.etape.emit("Découpage en clauses")
        clauses = decouper_clauses(document.texte)

        self.etape.emit("Repérage des clauses sensibles")
        risques = signaler_risque(clauses)

        analyse = AnalyseContrat(
            source=document.chemin,
            nombre_caracteres=document.nombre_caracteres,
            clauses=clauses,
            risques=risques,
            synthese=(
                "Inspection sans appel au modèle : découpage et signalement des "
                "clauses sensibles uniquement."
            ),
            anonymisation_active=self.configuration.anonymisation,
            journal=["lire_document", "decouper_clauses", "signaler_risque"],
        )
        return analyse, None
