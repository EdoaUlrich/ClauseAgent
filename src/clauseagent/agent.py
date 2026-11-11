"""Boucle agentique : le modèle choisit lui-même les outils et leur ordre.

Trois principes structurent cette implémentation.

**L'état reste local.** Le texte du contrat, les clauses et les éléments
extraits vivent dans l'objet `Agent`. Les outils ne renvoient au modèle que des
références et des résumés. Le contexte ne grossit donc pas avec la taille du
contrat, et le même document n'est pas renvoyé à chaque tour.

**Tout ce qui sort passe par l'anonymiseur.** `_executer` est le seul point de
sortie vers le modèle : chaque résultat d'outil y est masqué avant envoi. Une
valeur réelle ne peut pas fuir par un chemin oublié, même si un nouvel outil
est ajouté plus tard.

**La boucle est écrite à la main.** Le SDK propose un exécuteur automatique,
mais nous avons besoin d'intercaler l'anonymisation, le journal d'audit et le
contrôle des écritures sur disque entre chaque appel. Ce sont précisément les
points qu'un gestionnaire de contrats voudra pouvoir inspecter.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clauseagent.anonymisation import Anonymiseur
from clauseagent.config import Configuration
from clauseagent.models import AnalyseContrat, Clause, ElementExtrait, Risque
from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.echeances import calculer_echeance
from clauseagent.outils.export import exporter_excel
from clauseagent.outils.extraction import extraire_clause
from clauseagent.outils.lecture import DocumentLu, lire_document
from clauseagent.outils.registre import OUTILS
from clauseagent.outils.risques import signaler_risque

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import Anthropic

CONSIGNES_AGENT = """Tu assistes un gestionnaire de contrats. À partir d'un \
contrat, tu dresses l'inventaire des obligations, des droits, des échéances et \
des pénalités, puis tu produis un tableau de suivi.

Méthode attendue :
1. Lis le document.
2. Découpe-le en clauses.
3. Repère dans le texte les dates de référence (signature, prise d'effet...) et \
enregistre-les : les échéances relatives en dépendent.
4. Extrais le contenu des clauses qui portent un engagement. Passe les clauses \
de pure forme (intitulés, droit applicable, juridiction compétente).
5. Pour chaque échéance rencontrée, demande son calcul en date réelle.
6. Fais signaler les clauses sensibles.
7. Exporte le tableau de suivi.

Cet ordre est une trame, pas une contrainte : adapte-le au contrat. Tu peux \
regrouper plusieurs appels d'outils dans un même tour quand ils sont \
indépendants, ce qui est le cas de l'extraction de clauses distinctes.

Règles :
- Ne te fie qu'au texte du contrat. N'ajoute aucune obligation habituelle ou \
sous-entendue qui n'y figure pas.
- Les jetons de la forme [SOCIETE_1], [MONTANT_2] ou [PERSONNE_3] sont des \
anonymisations appliquées avant envoi. Traite-les comme des identifiants \
opaques : recopie-les sans les interpréter ni les remplacer.
- Si un outil signale qu'une information manque, ne la comble pas par \
supposition. Mentionne-la comme manquante dans ta synthèse finale.
- Termine par une synthèse courte : volume d'obligations par partie, échéances \
les plus proches, et points qui demandent une relecture humaine.
"""


@dataclass(slots=True)
class Agent:
    """Orchestre l'analyse d'un contrat par appels d'outils successifs."""

    configuration: Configuration = field(default_factory=Configuration.depuis_environnement)
    client: Anthropic | None = None
    anonymiseur: Anonymiseur | None = None
    journaliser: Callable[[str], None] | None = None

    document: DocumentLu | None = field(default=None, init=False)
    clauses: list[Clause] = field(default_factory=list, init=False)
    elements: list[ElementExtrait] = field(default_factory=list, init=False)
    risques: list[Risque] = field(default_factory=list, init=False)
    evenements: dict[str, date] = field(default_factory=dict, init=False)
    journal: list[str] = field(default_factory=list, init=False)
    synthese: str = field(default="", init=False)
    chemin_export: Path | None = field(default=None, init=False)
    _index_clauses: dict[str, Clause] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.anonymiseur is None:
            self.anonymiseur = Anonymiseur(actif=self.configuration.anonymisation)
        if self.client is None:
            from clauseagent.client import creer_client

            self.client = creer_client(self.configuration)

    # ------------------------------------------------------------------ public

    def analyser(self, chemin: str | Path, consigne: str | None = None) -> AnalyseContrat:
        """Analyse un contrat de bout en bout.

        Args:
            chemin: Chemin du contrat à traiter.
            consigne: Demande particulière à ajouter à la trame (par exemple
                « concentre-toi sur les obligations du prestataire »).

        Returns:
            L'analyse complète, exportable telle quelle.
        """
        demande = (
            f"Analyse le contrat situé à : {chemin}\n\n"
            "Produis l'inventaire des obligations, droits, échéances et pénalités, "
            "puis exporte le tableau de suivi."
        )
        if consigne:
            demande += f"\n\nDemande particulière : {consigne}"

        messages: list[dict[str, Any]] = [{"role": "user", "content": demande}]
        iteration = 0

        while iteration < self.configuration.max_iterations:
            iteration += 1
            reponse = self.client.messages.create(
                model=self.configuration.modele,
                max_tokens=self.configuration.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": CONSIGNES_AGENT,
                        # Consignes et outils sont identiques à chaque tour :
                        # les mettre en cache évite de les refacturer.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=OUTILS,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.configuration.effort},
            )

            messages.append({"role": "assistant", "content": reponse.content})

            if reponse.stop_reason == "refusal":
                raise RuntimeError(
                    "Le modèle a refusé de traiter la demande "
                    f"(motif : {getattr(reponse.stop_details, 'category', 'non précisé')})."
                )

            if reponse.stop_reason == "pause_turn":
                self._tracer("Tour interrompu par l'API, reprise automatique.")
                continue

            if reponse.stop_reason == "max_tokens":
                self._tracer(
                    "Réponse tronquée : augmentez CLAUSEAGENT_MAX_TOKENS pour ce contrat."
                )

            appels = [bloc for bloc in reponse.content if bloc.type == "tool_use"]
            if not appels:
                self.synthese = self._texte(reponse)
                break

            messages.append(
                {"role": "user", "content": [self._executer(appel) for appel in appels]}
            )
        else:
            self._tracer(
                f"Arrêt après {self.configuration.max_iterations} tours : limite atteinte. "
                "Les résultats obtenus jusque-là sont conservés."
            )

        return self.resultat()

    def resultat(self) -> AnalyseContrat:
        """Assemble l'analyse à partir de l'état courant."""
        return AnalyseContrat(
            source=self.document.chemin if self.document else "",
            nombre_caracteres=self.document.nombre_caracteres if self.document else 0,
            clauses=self.clauses,
            elements=self.elements,
            risques=self.risques,
            synthese=self.synthese,
            anonymisation_active=self.anonymiseur.actif,
            journal=list(self.journal),
        )

    # ------------------------------------------------------------- exécution

    def _executer(self, appel: Any) -> dict[str, Any]:
        """Exécute un appel d'outil et prépare le résultat à renvoyer au modèle.

        Point de sortie unique : c'est ici que tout résultat est masqué avant
        de repartir vers l'API.
        """
        nom = appel.name
        arguments = appel.input or {}
        self._tracer(f"{nom}({self._resumer_arguments(arguments)})")

        try:
            charge = self._appliquer(nom, arguments)
            erreur = False
        except Exception as exception:  # le modèle doit pouvoir corriger sa tentative
            charge = {"erreur": str(exception)}
            erreur = True
            self._tracer(f"  échec : {exception}")

        return {
            "type": "tool_result",
            "tool_use_id": appel.id,
            "content": json.dumps(
                self._masquer(charge), ensure_ascii=False, default=str
            ),
            "is_error": erreur,
        }

    def _appliquer(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if nom == "lire_document":
            return self._outil_lire_document(arguments["chemin"])
        if nom == "decouper_clauses":
            return self._outil_decouper_clauses()
        if nom == "definir_evenement":
            return self._outil_definir_evenement(
                arguments["nom"], arguments["date"], arguments.get("source", "")
            )
        if nom == "extraire_clause":
            return self._outil_extraire_clause(arguments["clause_identifiant"])
        if nom == "calculer_echeance":
            return self._outil_calculer_echeance(
                arguments["expression"], arguments.get("clause_identifiant")
            )
        if nom == "signaler_risque":
            return self._outil_signaler_risque()
        if nom == "exporter_excel":
            return self._outil_exporter_excel(arguments.get("nom_fichier"))
        raise ValueError(f"Outil inconnu : {nom}")

    # ----------------------------------------------------------------- outils

    def _outil_lire_document(self, chemin: str) -> dict[str, Any]:
        self.document = lire_document(chemin)
        return {
            "format": self.document.format,
            "caracteres": self.document.nombre_caracteres,
            "pages": self.document.nombre_pages or None,
            "apercu": self.document.texte[:1200],
            "suite": "Le texte intégral reste côté local ; utilise decouper_clauses.",
        }

    def _outil_decouper_clauses(self) -> dict[str, Any]:
        self._exiger_document()
        self.clauses = decouper_clauses(self.document.texte)
        self._index_clauses = {
            _normaliser(clause.identifiant): clause for clause in self.clauses
        }
        return {
            "nombre": len(self.clauses),
            "clauses": [
                {
                    "identifiant": clause.identifiant,
                    "intitule": clause.titre,
                    "caracteres": len(clause.texte),
                }
                for clause in self.clauses
            ],
        }

    def _outil_definir_evenement(
        self, nom: str, valeur: str, source: str
    ) -> dict[str, Any]:
        try:
            self.evenements[nom] = date.fromisoformat(valeur.strip())
        except ValueError as erreur:
            raise ValueError(
                f"Date « {valeur} » illisible : le format attendu est AAAA-MM-JJ."
            ) from erreur

        return {
            "enregistre": nom,
            "date": self.evenements[nom].isoformat(),
            "source": source,
            "evenements_connus": sorted(self.evenements),
        }

    def _outil_extraire_clause(self, identifiant: str) -> dict[str, Any]:
        clause = self._trouver_clause(identifiant)
        extraction = extraire_clause(
            clause,
            client=self.client,
            configuration=self.configuration,
            anonymiseur=self.anonymiseur,
        )

        self.elements.extend(extraction.elements)
        non_verifiees = [
            element.description
            for element in extraction.elements
            if not element.citation_verifiee
        ]

        return {
            "clause": clause.identifiant,
            "synthese": extraction.synthese,
            "elements": [
                {
                    "type": element.type.value,
                    "partie": element.partie_concernee,
                    "description": element.description,
                    "echeance_textuelle": element.echeance_textuelle,
                    "citation_verifiee": element.citation_verifiee,
                }
                for element in extraction.elements
            ],
            "citations_non_verifiees": len(non_verifiees),
            "total_elements_contrat": len(self.elements),
        }

    def _outil_calculer_echeance(
        self, expression: str, identifiant: str | None
    ) -> dict[str, Any]:
        expression_reelle = self.anonymiseur.restaurer(expression)
        resultat = calculer_echeance(
            expression_reelle,
            date_reference=self.evenements.get("signature"),
            evenements=self.evenements,
        )

        mis_a_jour = 0
        if identifiant:
            clause = self._trouver_clause(identifiant)
            for element in self.elements:
                if element.clause_identifiant != clause.identifiant:
                    continue
                if not element.echeance_textuelle:
                    continue
                if not _correspond(element.echeance_textuelle, expression_reelle):
                    continue
                element.echeance_calculee = resultat.date_calculee
                element.base_calcul = resultat.base
                mis_a_jour += 1

        return {
            "expression": expression,
            "date_calculee": (
                resultat.date_calculee.isoformat() if resultat.date_calculee else None
            ),
            "base_de_calcul": resultat.base,
            "explication": resultat.commentaire,
            "avertissements": resultat.avertissements,
            "elements_mis_a_jour": mis_a_jour,
        }

    def _outil_signaler_risque(self) -> dict[str, Any]:
        if not self.clauses:
            raise RuntimeError("Appelle decouper_clauses avant de signaler les risques.")

        self.risques = signaler_risque(self.clauses)
        return {
            "nombre": len(self.risques),
            "signalements": [
                {
                    "clause": risque.clause_identifiant,
                    "categorie": risque.categorie.value,
                    "gravite": risque.gravite.value,
                    "motif": risque.justification,
                }
                for risque in self.risques
            ],
        }

    def _outil_exporter_excel(self, nom_fichier: str | None) -> dict[str, Any]:
        if not self.elements and not self.risques:
            raise RuntimeError(
                "Rien à exporter : aucune clause n'a encore été extraite ni signalée."
            )

        destination = self.configuration.repertoire_sorties / self._nom_sortie(nom_fichier)
        self.chemin_export = exporter_excel(self.resultat(), destination)

        return {
            "chemin": str(self.chemin_export),
            "lignes_suivi": len(self.elements),
            "lignes_risques": len(self.risques),
            "feuilles": ["Suivi", "Risques", "Clauses", "Synthèse"],
        }

    # --------------------------------------------------------------- internes

    def _nom_sortie(self, propose: str | None) -> str:
        """Construit un nom de fichier sûr à partir d'une proposition du modèle.

        Seul le nom de base est retenu : un chemin fourni par le modèle ne doit
        jamais permettre d'écrire ailleurs que dans le répertoire de sorties.
        """
        defaut = (
            f"{Path(self.document.chemin).stem}_suivi.xlsx"
            if self.document
            else "suivi.xlsx"
        )
        if not propose:
            return defaut

        nom = Path(self.anonymiseur.restaurer(propose)).name.strip()
        if not nom or nom in {".", ".."}:
            return defaut
        return nom if nom.lower().endswith(".xlsx") else f"{nom}.xlsx"

    def _trouver_clause(self, identifiant: str) -> Clause:
        if not self.clauses:
            raise RuntimeError("Appelle decouper_clauses avant d'extraire une clause.")

        cherche = _normaliser(self.anonymiseur.restaurer(identifiant))
        clause = self._index_clauses.get(cherche)
        if clause is not None:
            return clause

        # Tolérance aux variantes de rédaction : « art. 4.2 » pour « Article 4.2 ».
        for cle, candidate in self._index_clauses.items():
            if cherche and (cherche in cle or cle in cherche):
                return candidate

        disponibles = ", ".join(clause.identifiant for clause in self.clauses[:20])
        raise ValueError(
            f"Clause « {identifiant} » introuvable. Références disponibles : {disponibles}."
        )

    def _exiger_document(self) -> None:
        if self.document is None:
            raise RuntimeError("Appelle lire_document avant toute autre opération.")

    def _masquer(self, valeur: Any) -> Any:
        """Applique l'anonymisation à toutes les chaînes d'une structure."""
        if isinstance(valeur, str):
            return self.anonymiseur.anonymiser(valeur)
        if isinstance(valeur, dict):
            return {cle: self._masquer(contenu) for cle, contenu in valeur.items()}
        if isinstance(valeur, list):
            return [self._masquer(contenu) for contenu in valeur]
        return valeur

    def _tracer(self, message: str) -> None:
        self.journal.append(message)
        if self.journaliser is not None:
            self.journaliser(message)

    @staticmethod
    def _resumer_arguments(arguments: dict[str, Any]) -> str:
        morceaux = []
        for cle, valeur in arguments.items():
            texte = str(valeur)
            morceaux.append(f"{cle}={texte if len(texte) <= 60 else texte[:57] + '...'}")
        return ", ".join(morceaux)

    @staticmethod
    def _texte(reponse: Any) -> str:
        return "\n".join(
            bloc.text for bloc in reponse.content if bloc.type == "text"
        ).strip()


def _normaliser(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.casefold())
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return " ".join(sans_accents.replace(".", " ").split())


def _correspond(echeance: str, expression: str) -> bool:
    """Rapproche l'échéance d'un élément de l'expression soumise au calcul."""
    gauche = _normaliser(echeance)
    droite = _normaliser(expression)
    return gauche == droite or gauche in droite or droite in gauche
