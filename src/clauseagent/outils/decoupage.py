"""Outil `decouper_clauses` : segmentation d'un contrat en articles numérotés.

Le découpage est purement déterministe. Le modèle n'intervient pas ici : un
agent qui déciderait lui-même des frontières de clauses produirait des
citations impossibles à recouper avec le document source. Ici, chaque clause
conserve ses positions de début et de fin dans le texte d'origine, ce qui rend
toute citation vérifiable par simple comparaison de chaînes.
"""

from __future__ import annotations

import re

from clauseagent.models import Clause

_LONGUEUR_TITRE_MAX = 90
_LONGUEUR_CLAUSE_MIN = 40

# Un en-tête d'article ne se termine pas par une ponctuation de phrase.
_FINS_INTERDITES = (".", ";", ",", ":")

_MAJUSCULE = "A-ZÀ-ÖØ-Þ"

MOTIFS_TITRES: tuple[re.Pattern[str], ...] = (
    # « ARTICLE 4 - Pénalités de retard », « Art. 4.2 : Objet », « Section 7.1 »
    re.compile(
        r"^[ \t]*(?P<mot>ARTICLE|Article|ART\.|Art\.|CLAUSE|Clause"
        r"|SECTION|Section|Sec\.)[ \t]+"
        r"(?P<numero>\d+(?:\.\d+)*|[IVXLC]{1,6})"
        r"[ \t]*[-–—:.)]?[ \t]*(?P<titre>[^\n]{0,120})$",
        re.MULTILINE,
    ),
    # « PRÉAMBULE », « TITRE II - Exécution », « ANNEXE 1 », « EXHIBIT A »
    re.compile(
        r"^[ \t]*(?P<mot>PRÉAMBULE|PREAMBULE|Préambule|Preambule|TITRE|Titre"
        r"|ANNEXE|Annexe|AVENANT|Avenant|EXHIBIT|Exhibit|SCHEDULE|Schedule"
        r"|APPENDIX|Appendix|RECITALS|Recitals)"
        r"[ \t]*(?P<numero>\d+(?:\.\d+)*|[IVXLC]{1,6}|[A-Z])?"
        r"[ \t]*[-–—:.)]?[ \t]*(?P<titre>[^\n]{0,120})$",
        re.MULTILINE,
    ),
    # « 4.2 Pénalités », « 4.2.1 - Calcul »
    re.compile(
        r"^[ \t]*(?P<numero>\d+(?:\.\d+)+)[ \t]*[-–—.)]?[ \t]+"
        r"(?P<titre>[^\n]{2,120})$",
        re.MULTILINE,
    ),
    # « 4. Pénalités » : exige un titre commençant par une majuscule pour ne pas
    # confondre un en-tête avec une énumération interne à une phrase.
    re.compile(
        rf"^[ \t]*(?P<numero>\d{{1,2}})[.)][ \t]+"
        rf"(?P<titre>[{_MAJUSCULE}][^\n]{{2,120}})$",
        re.MULTILINE,
    ),
)


def decouper_clauses(texte: str) -> list[Clause]:
    """Segmente un contrat en clauses numérotées.

    Args:
        texte: Texte intégral du contrat.

    Returns:
        Les clauses dans l'ordre du document. Si aucun en-tête n'est
        reconnaissable, le texte est découpé en paragraphes afin que l'agent
        puisse travailler malgré une mise en forme inhabituelle.
    """
    if not texte or not texte.strip():
        return []

    entetes = _reperer_entetes(texte)
    if len(entetes) < 2:
        return _decouper_en_paragraphes(texte)

    clauses: list[Clause] = []

    # Le bloc qui précède le premier en-tête identifie les parties : on le
    # conserve, car c'est lui qui nomme le Prestataire et le Client.
    entete_contrat = texte[: entetes[0][0]].strip()
    if len(entete_contrat) >= _LONGUEUR_CLAUSE_MIN:
        clauses.append(
            Clause(
                identifiant="En-tête du contrat",
                titre="Identification des parties",
                texte=entete_contrat,
                debut=0,
                fin=entetes[0][0],
            )
        )

    for rang, (debut, identifiant, titre) in enumerate(entetes):
        fin = entetes[rang + 1][0] if rang + 1 < len(entetes) else len(texte)
        corps = texte[debut:fin].strip()
        if not corps:
            continue
        clauses.append(
            Clause(identifiant=identifiant, titre=titre, texte=corps, debut=debut, fin=fin)
        )

    return _rendre_identifiants_uniques(clauses)


def _rendre_identifiants_uniques(clauses: list[Clause]) -> list[Clause]:
    """Suffixe les références en doublon.

    Un contrat peut comporter deux « Annexe 1 » ou répéter une numérotation.
    Les identifiants servant de clé de rattachement entre les clauses, les
    éléments extraits et les risques, ils doivent rester distincts.
    """
    vus: dict[str, int] = {}
    for clause in clauses:
        occurrences = vus.get(clause.identifiant, 0) + 1
        vus[clause.identifiant] = occurrences
        if occurrences > 1:
            clause.identifiant = f"{clause.identifiant} ({occurrences})"
    return clauses


def _reperer_entetes(texte: str) -> list[tuple[int, str, str]]:
    """Retourne les en-têtes repérés sous forme (position, identifiant, titre)."""
    trouves: dict[int, tuple[str, str]] = {}

    for motif in MOTIFS_TITRES:
        for correspondance in motif.finditer(texte):
            debut = correspondance.start()
            if debut in trouves:
                continue
            titre = (correspondance.groupdict().get("titre") or "").strip()
            if not _titre_plausible(titre):
                continue
            trouves[debut] = (_identifiant(correspondance), titre)

    # Un en-tête plus spécifique peut en recouvrir un plus générique sur la même
    # ligne ; on ne garde qu'une entrée par position, dans l'ordre du document.
    return [(debut, *trouves[debut]) for debut in sorted(trouves)]


def _titre_plausible(titre: str) -> bool:
    if not titre:
        return True
    if len(titre) > _LONGUEUR_TITRE_MAX:
        return False
    return not titre.endswith(_FINS_INTERDITES)


def _identifiant(correspondance: re.Match[str]) -> str:
    groupes = correspondance.groupdict()
    mot = (groupes.get("mot") or "").strip().rstrip(".")
    numero = (groupes.get("numero") or "").strip()

    if mot:
        mot = mot.capitalize() if mot.isupper() else mot
        if mot in {"Art", "Article"}:
            mot = "Article"
        return f"{mot} {numero}".strip()
    return f"Article {numero}" if numero else "Clause"


def _decouper_en_paragraphes(texte: str) -> list[Clause]:
    """Repli lorsqu'aucune numérotation n'est détectable."""
    clauses: list[Clause] = []
    position = 0
    rang = 0

    for bloc in re.split(r"\n{2,}", texte):
        debut = texte.find(bloc, position)
        if debut == -1:
            debut = position
        position = debut + len(bloc)
        if len(bloc.strip()) < _LONGUEUR_CLAUSE_MIN:
            continue
        rang += 1
        clauses.append(
            Clause(
                identifiant=f"Paragraphe {rang}",
                titre="",
                texte=bloc.strip(),
                debut=debut,
                fin=position,
            )
        )

    return clauses
