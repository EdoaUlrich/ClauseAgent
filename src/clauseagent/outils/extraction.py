"""Outil `extraire_clause` : lecture d'une clause par le modèle, en JSON strict.

C'est le seul outil qui appelle le modèle. Deux garde-fous l'encadrent :

1. **Sortie structurée.** Le schéma Pydantic `ExtractionClause` est transmis à
   l'API, qui garantit un JSON conforme. Aucune analyse de texte libre, donc
   aucune réponse à moitié exploitable.
2. **Citation vérifiée côté client.** Le modèle doit recopier l'extrait qui
   justifie chaque élément. On recherche ensuite cette citation dans la clause
   d'origine : si elle ne s'y trouve pas mot pour mot, l'élément est conservé
   mais marqué non vérifié, et le gestionnaire sait qu'il doit le contrôler.

La clause est anonymisée avant l'envoi et les jetons sont restaurés au retour.
Comme la substitution est bijective, la vérification de citation reste valable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from clauseagent.anonymisation import Anonymiseur
from clauseagent.config import Configuration
from clauseagent.models import Clause, ExtractionClause

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import Anthropic

CONSIGNES = """Tu analyses une clause de contrat pour un gestionnaire de contrats.

Règles impératives :
- N'extrais que ce que la clause énonce explicitement. N'ajoute aucune
  obligation déduite, probable ou habituelle.
- Le champ `citation` doit être un extrait recopié caractère pour caractère
  depuis la clause fournie, suffisant à lui seul pour justifier l'élément.
  N'y corrige ni l'orthographe, ni la ponctuation, ni les majuscules.
- Désigne les parties exactement comme la clause les nomme (« le Prestataire »,
  « le Client »...). N'invente pas de raison sociale.
- Les éléments de la forme [SOCIETE_1], [MONTANT_2] ou [PERSONNE_3] sont des
  jetons d'anonymisation. Recopie-les tels quels, sans les traduire ni les
  interpréter.
- `type` vaut « obligation » pour un engagement à faire ou à ne pas faire,
  « droit » pour une faculté ouverte à une partie, « penalite » pour une
  sanction financière ou une indemnité, « autre » sinon.
- `echeance_textuelle` reprend le délai tel qu'il est écrit (« 30 jours à
  compter de la réception de la facture »). Laisse le champ vide si la clause
  ne mentionne aucun délai : ne devine jamais une échéance.
- Une clause purement déclarative ou définitionnelle produit une liste
  `elements` vide. C'est un résultat valide.
"""

_GUILLEMETS = {
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "«": '"',
    "»": '"',
    "–": "-",
    "—": "-",
    "…": "...",
}


def extraire_clause(
    clause: Clause,
    client: Anthropic | None = None,
    configuration: Configuration | None = None,
    anonymiseur: Anonymiseur | None = None,
) -> ExtractionClause:
    """Extrait les obligations, droits et pénalités d'une clause.

    Args:
        clause: Clause à analyser.
        client: Client Anthropic. Créé à la demande s'il n'est pas fourni.
        configuration: Paramètres d'exécution (modèle, anonymisation).
        anonymiseur: Anonymiseur partagé, afin que les mêmes valeurs reçoivent
            les mêmes jetons dans tout le contrat.

    Raises:
        RuntimeError: Le modèle n'a pas retourné de sortie exploitable.
    """
    configuration = configuration or Configuration.depuis_environnement()
    anonymiseur = anonymiseur or Anonymiseur(actif=configuration.anonymisation)

    if client is None:
        from clauseagent.client import creer_client

        client = creer_client(configuration)

    texte_masque = anonymiseur.anonymiser(clause.texte)
    identifiant_masque = anonymiseur.anonymiser(clause.identifiant)
    titre_masque = anonymiseur.anonymiser(clause.titre)

    invite = (
        f"Clause à analyser.\n\n"
        f"Référence : {identifiant_masque}\n"
        f"Intitulé : {titre_masque or '(aucun)'}\n\n"
        f"Texte :\n{texte_masque}"
    )

    reponse = client.messages.parse(
        model=configuration.modele,
        max_tokens=configuration.max_tokens,
        system=CONSIGNES,
        messages=[{"role": "user", "content": invite}],
        output_format=ExtractionClause,
    )

    extraction = reponse.parsed_output
    if extraction is None:
        raise RuntimeError(
            f"Le modèle n'a pas produit de sortie structurée pour {clause.identifiant} "
            f"(motif d'arrêt : {reponse.stop_reason})."
        )

    return _restaurer_et_verifier(extraction, clause, anonymiseur)


def _restaurer_et_verifier(
    extraction: ExtractionClause, clause: Clause, anonymiseur: Anonymiseur
) -> ExtractionClause:
    """Remet les valeurs réelles puis contrôle chaque citation."""
    extraction.synthese = anonymiseur.restaurer(extraction.synthese)

    for element in extraction.elements:
        element.citation = anonymiseur.restaurer(element.citation).strip()
        element.description = anonymiseur.restaurer(element.description)
        element.partie_concernee = anonymiseur.restaurer(element.partie_concernee)
        if element.echeance_textuelle:
            element.echeance_textuelle = anonymiseur.restaurer(element.echeance_textuelle)
        element.clause_identifiant = clause.identifiant
        element.citation_verifiee = verifier_citation(element.citation, clause.texte)

    return extraction


def verifier_citation(citation: str, texte_source: str) -> bool:
    """Indique si la citation figure mot pour mot dans le texte source.

    La comparaison tolère les seules différences qui ne changent pas le sens :
    espacement, retours à la ligne, apostrophes et guillemets typographiques.
    Toute autre réécriture est considérée comme une citation non fidèle.
    """
    if not citation or not texte_source:
        return False
    return _comparable(citation) in _comparable(texte_source)


def _comparable(texte: str) -> str:
    texte = unicodedata.normalize("NFC", texte)
    for caractere, remplacement in _GUILLEMETS.items():
        texte = texte.replace(caractere, remplacement)
    return re.sub(r"\s+", " ", texte).strip()
