"""Schemas metier de ClauseAgent.

Ces modeles servent a la fois de contrat de donnees interne et de schema de
sortie structuree pour le modele de langage : `ExtractionClause` est envoye tel
quel a l'API, qui garantit alors un JSON conforme.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TypeElement(str, Enum):
    """Nature juridique d'un element extrait."""

    OBLIGATION = "obligation"
    DROIT = "droit"
    PENALITE = "penalite"
    AUTRE = "autre"


class CategorieRisque(str, Enum):
    """Familles de clauses qui justifient une relecture humaine."""

    PENALITE = "penalite"
    RESILIATION = "resiliation"
    RESPONSABILITE = "responsabilite"
    CONFIDENTIALITE = "confidentialite"
    PROPRIETE_INTELLECTUELLE = "propriete_intellectuelle"
    ASSURANCE = "assurance"
    FORCE_MAJEURE = "force_majeure"
    RENOUVELLEMENT_TACITE = "renouvellement_tacite"


class Gravite(str, Enum):
    """Niveau d'attention requis sur une clause sensible."""

    FAIBLE = "faible"
    MOYENNE = "moyenne"
    ELEVEE = "elevee"


class Clause(BaseModel):
    """Un article ou une clause numerotee du contrat."""

    model_config = ConfigDict(extra="forbid")

    identifiant: str = Field(description="Reference de la clause, par exemple 'Article 4.2'")
    titre: str = Field(default="", description="Intitule de la clause s'il existe")
    texte: str = Field(description="Texte integral de la clause")
    debut: int = Field(default=0, description="Position du premier caractere dans le document")
    fin: int = Field(default=0, description="Position du dernier caractere dans le document")

    @property
    def apercu(self) -> str:
        texte = " ".join(self.texte.split())
        return texte if len(texte) <= 160 else texte[:157] + "..."


class ElementExtrait(BaseModel):
    """Un engagement, un droit ou une penalite rattache a une clause."""

    model_config = ConfigDict(extra="forbid")

    type: TypeElement = Field(description="Nature de l'element")
    partie_concernee: str = Field(
        description="Partie qui porte l'engagement ou beneficie du droit, telle que nommee "
        "dans le contrat"
    )
    description: str = Field(description="Reformulation courte et factuelle de l'element")
    echeance_textuelle: str | None = Field(
        default=None,
        description="Echeance telle qu'ecrite dans le contrat, par exemple "
        "'30 jours apres la livraison'. Null si la clause n'en mentionne aucune.",
    )
    citation: str = Field(
        description="Extrait verbatim de la clause qui justifie l'element, copie sans "
        "aucune modification"
    )
    clause_identifiant: str = Field(default="", description="Reference de la clause d'origine")
    echeance_calculee: date | None = Field(
        default=None, description="Date reelle derivee de l'echeance textuelle"
    )
    base_calcul: str | None = Field(
        default=None, description="Evenement de depart utilise pour le calcul de la date"
    )
    citation_verifiee: bool = Field(
        default=False,
        description="Vrai si la citation a ete retrouvee mot pour mot dans la clause",
    )


class ExtractionClause(BaseModel):
    """Sortie structuree attendue du modele pour une clause donnee."""

    model_config = ConfigDict(extra="forbid")

    elements: list[ElementExtrait] = Field(
        default_factory=list,
        description="Elements identifies dans la clause. Liste vide si la clause est "
        "purement declarative.",
    )
    synthese: str = Field(default="", description="Resume de la clause en une phrase")


class Risque(BaseModel):
    """Signalement d'une clause a relire par un humain."""

    model_config = ConfigDict(extra="forbid")

    clause_identifiant: str
    categorie: CategorieRisque
    gravite: Gravite
    justification: str
    citation: str = ""


class AnalyseContrat(BaseModel):
    """Resultat complet d'une analyse de contrat."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Chemin du document analyse")
    nombre_caracteres: int = 0
    clauses: list[Clause] = Field(default_factory=list)
    elements: list[ElementExtrait] = Field(default_factory=list)
    risques: list[Risque] = Field(default_factory=list)
    synthese: str = ""
    anonymisation_active: bool = True
    journal: list[str] = Field(
        default_factory=list, description="Trace des outils appeles par l'agent"
    )

    def elements_par_type(self, type_element: TypeElement) -> list[ElementExtrait]:
        return [element for element in self.elements if element.type is type_element]

    @property
    def taux_citations_verifiees(self) -> float:
        if not self.elements:
            return 0.0
        verifiees = sum(1 for element in self.elements if element.citation_verifiee)
        return verifiees / len(self.elements)
