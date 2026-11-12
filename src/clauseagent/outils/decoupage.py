"""Outil `decouper_clauses` : segmentation d'un contrat en articles numérotés.

Le découpage est purement déterministe. Le modèle n'intervient pas ici : un
agent qui déciderait lui-même des frontières de clauses produirait des
citations impossibles à recouper avec le document source. Ici, chaque clause
conserve ses positions de début et de fin dans le texte d'origine, ce qui rend
toute citation vérifiable par simple comparaison de chaînes.

## Intitulés en début de ligne et intitulés en ligne

Un contrat bien mis en forme place ses intitulés en début de ligne, et c'est ce
que repèrent les motifs ci-dessous. Mais un contrat extrait d'un PDF perd
souvent ses retours à la ligne : l'intitulé se retrouve au milieu d'une phrase,
sous la forme « … Chief Executive Officer. 2. No Control by the Company. The
Parties agree … ».

Mesuré sur CUAD, ce cas concernait 42 % des contrats, qui basculaient alors sur
le découpage de repli en paragraphes — des blocs arbitraires qui ne
correspondent à aucune clause. Une seconde passe reconnaît donc les intitulés
en ligne, mais uniquement lorsque la première n'a rien donné d'exploitable :
sur un document correctement structuré, elle ne ferait que sur-découper.
"""

from __future__ import annotations

import re

from clauseagent.models import Clause

_LONGUEUR_TITRE_MAX = 90
_LONGUEUR_CLAUSE_MIN = 40

# Seuils de déclenchement de la seconde passe.
_ENTETES_MINIMUM = 4
_TAILLE_MOYENNE_MAX = 2000
_ECART_MINIMUM = 20

# Contraintes sur un intitulé repéré en ligne.
_MOTS_TITRE_MAX = 8
_MOTS_LIAISON = frozenset(
    {
        "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or",
        "the", "to", "with",
        "au", "aux", "de", "des", "du", "en", "et", "la", "le", "les", "ou",
        "par", "pour", "sur", "un", "une",
    }
)

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

# « … Chief Executive Officer. 2. No Control by the Company. The Parties … »
_ENTETE_EN_LIGNE = re.compile(
    r"(?:(?<=[.;:])|(?<=\n))[ \t]{1,8}"
    r"(?P<numero>\d{1,2}(?:\.\d{1,2})*)\.[ \t]+"
    r"(?P<titre>[^\n.]{2,70}?)"
    r"(?:\.[ \t]+|[ \t]{2,})"
    r"(?=[A-ZÀ-Þ\"(])"
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
    if _decoupage_insuffisant(entetes, len(texte)):
        entetes = _fusionner(entetes, _reperer_entetes_en_ligne(texte))
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

    return _rendre_identifiants_uniques(_absorber_entetes_sans_corps(clauses))


def _absorber_entetes_sans_corps(clauses: list[Clause]) -> list[Clause]:
    """Supprime les clauses qui ne contiennent que leur propre intitulé.

    « ARTICLE 8 — RÉSILIATION » suivi immédiatement de « 8.1 » n'est pas une
    clause : c'est le titre d'une section. L'émettre produisait une ligne vide
    dans le tableau de suivi et un signalement sans contenu — sur CUAD, 97 %
    des signalements portant sur ces blocs étaient des faux positifs. Son
    intitulé est reporté sur les sous-clauses, qui en héritent le contexte.
    """
    resultat: list[Clause] = []
    contextes: list[tuple[str, str]] = []

    for rang, clause in enumerate(clauses):
        corps = clause.texte.split("\n", 1)[1].strip() if "\n" in clause.texte else ""
        suivante = clauses[rang + 1] if rang + 1 < len(clauses) else None

        if (
            len(corps) < _LONGUEUR_CLAUSE_MIN
            and suivante is not None
            and _est_sous_clause(suivante.identifiant, clause.identifiant)
        ):
            if clause.titre:
                contextes.append((clause.identifiant, clause.titre))
            continue

        herite = next(
            (
                titre
                for identifiant, titre in reversed(contextes)
                if _est_sous_clause(clause.identifiant, identifiant)
            ),
            "",
        )
        if herite and herite != clause.titre:
            clause.titre = f"{herite} — {clause.titre}" if clause.titre else herite

        resultat.append(clause)

    return resultat


def _est_sous_clause(identifiant: str, parent: str) -> bool:
    """Indique si `identifiant` désigne une subdivision de `parent`."""
    return identifiant != parent and identifiant.startswith(f"{parent}.")


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


def _decoupage_insuffisant(entetes: list[tuple[int, str, str]], taille: int) -> bool:
    """Indique si la première passe laisse des clauses trop grosses.

    Deux cas : presque aucun en-tête trouvé, ou des en-têtes si espacés que les
    clauses obtenues couvrent chacune plusieurs sections.
    """
    if len(entetes) < _ENTETES_MINIMUM:
        return True
    return taille / len(entetes) > _TAILLE_MOYENNE_MAX


def _fusionner(
    premiers: list[tuple[int, str, str]], seconds: list[tuple[int, str, str]]
) -> list[tuple[int, str, str]]:
    """Réunit deux listes d'en-têtes en écartant les positions voisines."""
    retenus = dict(enumerate(premiers))
    positions = {debut for debut, _, _ in premiers}

    for entete in seconds:
        debut = entete[0]
        if any(abs(debut - connue) < _ECART_MINIMUM for connue in positions):
            continue
        positions.add(debut)
        retenus[len(retenus)] = entete

    return sorted(retenus.values(), key=lambda entete: entete[0])


def _reperer_entetes_en_ligne(texte: str) -> list[tuple[int, str, str]]:
    """Repère les intitulés noyés dans un paragraphe.

    Exige une numérotation, un intitulé court dont les mots significatifs
    portent une majuscule, puis une reprise de phrase. Ces trois conditions
    réunies, la confusion avec une énumération ordinaire est peu probable.
    """
    entetes: list[tuple[int, str, str]] = []

    for correspondance in _ENTETE_EN_LIGNE.finditer(texte):
        titre = correspondance.group("titre").strip()
        if not _ressemble_a_un_entete(titre):
            continue
        numero = correspondance.group("numero")
        entetes.append(
            (correspondance.start("numero"), f"Article {numero}", titre)
        )

    return entetes


def _ressemble_a_un_entete(titre: str) -> bool:
    mots = titre.split()
    if not 1 <= len(mots) <= _MOTS_TITRE_MAX:
        return False

    significatifs = [mot for mot in mots if mot.lower() not in _MOTS_LIAISON]
    if not significatifs:
        return False

    majuscules = sum(1 for mot in significatifs if mot[:1].isupper())
    return majuscules / len(significatifs) >= 0.8


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
