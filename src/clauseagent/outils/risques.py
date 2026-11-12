"""Outil `signaler_risque` : repérage des clauses à faire relire par un humain.

La détection repose sur un lexique et des indices rédactionnels plutôt que sur
le modèle. Trois raisons à ce choix : le résultat est stable d'une exécution à
l'autre, il reste explicable devant un juriste, et il ne coûte aucun appel
distant. L'agent garde la main sur l'interprétation ; cet outil se contente de
dire « cette clause mérite un œil humain, pour tel motif ».

Le lexique est bilingue. Les contrats d'infrastructure sont fréquemment rédigés
en anglais, et c'est aussi la langue de CUAD, le jeu annoté par des juristes qui
sert à mesurer précision et rappel (voir `clauseagent.evaluation`).

## Pourquoi un score plutôt qu'une liste de mots

Une première version signalait une clause dès qu'un terme du lexique y
apparaissait. Mesurée sur CUAD, elle atteignait 87 % de rappel pour 37 % de
précision : un gestionnaire recevait deux clauses à relire pour une qui le
méritait, ce qui vide le signalement de son intérêt. Trois corrections ont été
apportées.

**Comparaison sur mots entiers.** `amende` reconnaissait `amended`, `assurance`
reconnaissait `assurances`, `licence` reconnaissait `license` : le lexique
français déclenchait sur du texte anglais. Les motifs exigent désormais des
frontières de mots.

**Expressions discriminantes plutôt que mots isolés.** `termination` apparaît
dans presque toutes les clauses d'un contrat de travail ; `terminate this
agreement` désigne une vraie faculté de résiliation. Les mots génériques ne
sont plus conservés que comme indices d'intitulé.

**Score de pertinence.** Une clause est signalée si son intitulé porte sur le
sujet, si elle contient une expression décisive, ou si une expression ordinaire
apparaît en ouverture ou s'accompagne d'une autre. C'est la transposition de ce
que fait un lecteur qui survole : une section qui s'ouvre sur « Either party may
terminate this Agreement » traite de résiliation ; une qui mentionne « after the
Termination Date » au détour d'une phrase n'en traite pas.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from clauseagent.models import CategorieRisque, Clause, Gravite, Risque

# Un intitulé qui porte sur le sujet suffit à signaler la clause.
POIDS_INTITULE = 3
# Une expression décisive : « liquidated damages » ne figure pas par hasard.
POIDS_DECISIVE = 3
# Une expression ordinaire, qui demande un indice supplémentaire.
POIDS_EXPRESSION = 2
# Bonus si l'expression ouvre la clause, ou si plusieurs expressions coexistent.
POIDS_POSITION = 1
POIDS_REPETITION = 1

# En deçà, la clause n'est pas signalée. Valeur retenue après balayage sur un
# échantillon de mise au point distinct de l'échantillon de validation.
SEUIL_DEFAUT = 3

# Fenêtre d'ouverture d'une clause, en caractères.
OUVERTURE = 400


@dataclass(frozen=True, slots=True)
class Signature:
    """Indices permettant de reconnaître une catégorie de clause.

    `decisives` regroupe les expressions dont une seule occurrence caractérise
    la clause ; `expressions` celles qui demandent un indice de renfort —
    figurer en ouverture de clause, ou s'accompagner d'une autre expression de
    la même catégorie.

    `composes` contient des motifs qui décrivent une tournure plutôt qu'un
    terme. Certaines clauses ne se reconnaissent qu'ainsi : une résiliation
    sans motif s'écrit rarement « for convenience », mais presque toujours
    « may terminate this Agreement upon sixty days' written notice », soit une
    faculté de résilier, un préavis, et aucune mention de faute.
    """

    decisives: tuple[str, ...]
    expressions: tuple[str, ...]
    intitules: tuple[str, ...]
    gravite: Gravite
    composes: tuple[str, ...] = ()


LEXIQUE: dict[CategorieRisque, Signature] = {
    CategorieRisque.PENALITE: Signature(
        # Les passages annotés par CUAD sous « Liquidated Damages » recouvrent
        # aussi les indemnités de sortie : frais de résiliation anticipée,
        # rachat de contrat, forfait de dédit.
        decisives=(
            "liquidated damages",
            "liquidated damage",
            "termination fee",
            "termination fees",
            "early termination fee",
            "cancellation fee",
            "break fee",
            "buyout payment",
            "contract buyout",
            "late payment charge",
            "penalite",
            "penalites",
            "clause penale",
            "astreinte",
            "astreintes",
            "indemnite forfaitaire",
        ),
        expressions=(
            "a penalty",
            "as a penalty",
            "penalty of",
            "penalties of",
            "penalty equal to",
            "late fee",
            "late fees",
            "late payment fee",
            "default interest",
            "interest on overdue",
            "interest on any overdue",
            "interets de retard",
            "dommages et interets",
            "amende",
        ),
        intitules=(
            "liquidated damages",
            "penalty",
            "penalties",
            "late payment",
            "termination fee",
            "penalite",
            "penalites",
            "astreinte",
        ),
        gravite=Gravite.ELEVEE,
    ),
    CategorieRisque.RESILIATION: Signature(
        decisives=(
            "resiliation",
            "resilier",
            "rupture du contrat",
            "mise en demeure",
        ),
        expressions=(
            "terminate this agreement",
            "terminate the agreement",
            "termination of this agreement",
            "right to terminate",
            "may terminate",
            "may be terminated",
            "terminated for cause",
            "notice of termination",
            "cure period",
            "resilie",
        ),
        intitules=(
            "termination",
            "terminate",
            "cancellation",
            "resiliation",
            "rupture",
        ),
        gravite=Gravite.ELEVEE,
    ),
    CategorieRisque.RESILIATION_CONVENANCE: Signature(
        decisives=(
            "termination for convenience",
            "terminate for convenience",
            "for convenience",
            "without cause",
            "with or without cause",
            "for any reason or no reason",
            "resiliation pour convenance",
            "resilier pour convenance",
            "resiliation sans motif",
        ),
        expressions=(
            "for any reason whatsoever",
            "at its sole discretion terminate",
            "in its sole discretion terminate",
            "terminate at any time",
            "sans avoir a justifier",
            "sans motif",
        ),
        intitules=(
            "termination for convenience",
            "convenience",
            "resiliation pour convenance",
        ),
        gravite=Gravite.ELEVEE,
        composes=(
            # Faculté de résilier, puis préavis, sans mention de faute entre
            # les deux : c'est la définition d'une résiliation sans motif.
            r"(?:may\s+terminate|may\s+be\s+terminated|is\s+terminable"
            r"|shall\s+be\s+terminable|has\s+the\s+right\s+to\s+terminate)"
            r"(?:(?!for\s+cause|material\s+breach|uncured|for\s+default"
            r"|for\s+any\s+breach|in\s+the\s+event\s+of\s+a?\s*breach).){0,240}?"
            r"(?:written\s+notice|prior\s+notice|days'?\s+notice"
            r"|months'?\s+notice|at\s+any\s+time)",
            r"(?:resilier|resiliation)"
            r"(?:(?!manquement|faute|inexecution|defaut).){0,200}?"
            r"(?:preavis|a\s+tout\s+moment)",
        ),
    ),
    CategorieRisque.RESPONSABILITE: Signature(
        # Cette catégorie vise les plafonds et exclusions de responsabilité.
        # Les engagements de garantie relèvent de INDEMNISATION.
        decisives=(
            "limitation of liability",
            "limitations of liability",
            "limit of liability",
            "liability cap",
            "aggregate liability",
            "total liability",
            "maximum liability",
            "consequential damages",
            "limitation de responsabilite",
            "responsabilite est limitee",
            "exoneration de responsabilite",
        ),
        expressions=(
            "shall not exceed",
            "shall not be liable",
            "will not be liable",
            "in no event shall",
            "indirect damages",
            "incidental damages",
            "punitive damages",
            "loss of profits",
            "lost profits",
            "responsabilite ne saurait",
            "ne saurait exceder",
        ),
        intitules=(
            "limitation of liability",
            "liability",
            "liabilities",
            "responsabilite",
        ),
        gravite=Gravite.ELEVEE,
    ),
    CategorieRisque.INDEMNISATION: Signature(
        decisives=(
            "indemnify and hold harmless",
            "shall indemnify",
            "agrees to indemnify",
            "defend and indemnify",
            "hold harmless",
            "garantir et indemniser",
            "garantie d'eviction",
            "fait son affaire personnelle",
        ),
        expressions=(
            "indemnification",
            "indemnify",
            "indemnified party",
            "indemnisation",
        ),
        intitules=("indemnification", "indemnity", "indemnisation", "garantie"),
        gravite=Gravite.ELEVEE,
    ),
    CategorieRisque.CONFIDENTIALITE: Signature(
        decisives=(
            "confidential information",
            "confidentiality obligations",
            "non-disclosure",
            "nondisclosure",
            "trade secret",
            "trade secrets",
            "informations confidentielles",
            "secret des affaires",
            "obligation de confidentialite",
            "non-divulgation",
        ),
        expressions=("keep confidential", "shall not disclose", "confidentiel"),
        intitules=(
            "confidentiality",
            "confidential",
            "non-disclosure",
            "confidentialite",
        ),
        gravite=Gravite.MOYENNE,
    ),
    CategorieRisque.PROPRIETE_INTELLECTUELLE: Signature(
        decisives=(
            "intellectual property",
            "work made for hire",
            "works made for hire",
            "ownership of inventions",
            "assignment of inventions",
            "hereby grants",
            "grants to licensee",
            "jointly owned",
            "propriete intellectuelle",
            "droits d'auteur",
            "cession de droits",
            "concede une licence",
        ),
        expressions=(
            "license to use",
            "right and license",
            "assigns to",
            "patent rights",
            "copyrights",
            "trademarks",
            "licence non exclusive",
            "licence exclusive",
        ),
        intitules=(
            "intellectual property",
            "license",
            "licence",
            "ownership",
            "copyright",
            "patent",
            "propriete intellectuelle",
        ),
        gravite=Gravite.MOYENNE,
    ),
    CategorieRisque.ASSURANCE: Signature(
        decisives=(
            "maintain insurance",
            "maintain in effect insurance",
            "insurance policy",
            "insurance policies",
            "insurance coverage",
            "liability insurance",
            "certificate of insurance",
            "certificates of insurance",
            "commercial general liability",
            "workers compensation insurance",
            "self-insurance",
            "police d'assurance",
            "attestation d'assurance",
            "souscrire une assurance",
            "assurance responsabilite civile",
        ),
        expressions=("insured", "insurer", "insurers", "assureur"),
        intitules=("insurance", "assurance", "assurances"),
        gravite=Gravite.MOYENNE,
    ),
    CategorieRisque.FORCE_MAJEURE: Signature(
        decisives=("force majeure", "act of god", "acts of god"),
        expressions=("cas fortuit", "evenement imprevisible"),
        intitules=("force majeure", "acts of god"),
        gravite=Gravite.FAIBLE,
    ),
    CategorieRisque.RENOUVELLEMENT_TACITE: Signature(
        decisives=(
            "automatically renew",
            "automatically renewed",
            "automatically be renewed",
            "automatically extend",
            "automatically extended",
            "automatic renewal",
            "auto-renew",
            "renewal term",
            "renewal terms",
            "non-renewal",
            "successive renewal",
            "renewed for successive",
            "evergreen",
            "tacite reconduction",
            "reconduction tacite",
            "renouvele tacitement",
            "renouvellement tacite",
        ),
        expressions=(
            "renewal period",
            "renewal periods",
            "initial term",
            "then-current term",
            "then current term",
            "successive periods",
            "successive one year",
            "additional one-year",
            "additional one year",
            "additional periods",
            "extendable for",
            "shall be extended automatically",
            "unless either party",
            "unless written notice",
            "renouvele par periodes",
        ),
        intitules=(
            "renewal",
            "term and renewal",
            "renewal and termination",
            "renouvellement",
            "reconduction",
        ),
        gravite=Gravite.ELEVEE,
    ),
}

# Formulations qui aggravent une clause déjà sensible.
AGGRAVANTS: tuple[tuple[str, str], ...] = (
    ("de plein droit", "effet automatique, sans décision préalable"),
    ("sans mise en demeure", "aucune mise en demeure requise"),
    ("sans preavis", "aucun préavis requis"),
    ("sans indemnite", "aucune indemnité prévue"),
    ("irrevocable", "engagement irrévocable"),
    ("illimitee", "absence de plafond"),
    ("sans limitation", "absence de plafond"),
    ("solidairement", "responsabilité solidaire"),
    ("renonce", "renonciation à un droit"),
    ("exclusive", "exclusivité consentie"),
    ("without notice", "aucun préavis requis"),
    ("without further notice", "aucun préavis requis"),
    ("immediately upon", "effet immédiat"),
    ("unlimited", "absence de plafond"),
    ("perpetual", "engagement perpétuel"),
    ("jointly and severally", "responsabilité solidaire"),
    ("waives", "renonciation à un droit"),
)

# Formules juridiques qui contiennent un terme du lexique sans en avoir le sens.
# « société à responsabilité limitée » désigne une forme sociale, pas une clause
# de limitation de responsabilité : sans ce filtre, l'en-tête de tout contrat
# conclu avec une SARL serait signalé.
FAUX_AMIS: tuple[str, ...] = (
    "societe a responsabilite limitee",
    "a responsabilite limitee",
    "societe par actions simplifiee a responsabilite",
    "limited liability company",
    "limited liability partnership",
    "national insurance",
    # « Further assurances » est une clause de style — chaque partie s'engage à
    # accomplir les formalités utiles — et n'a rien d'une clause d'assurance.
    "further assurances",
    "further assurance",
)

# Clauses de forme : elles citent les notions du contrat sans rien en régler.
# Une section « Definitions » mentionne la propriété intellectuelle, la
# résiliation et la responsabilité ; les y signaler noierait le gestionnaire
# sous des renvois. Elles ne sont retenues que si leur propre intitulé porte
# sur une des catégories.
#
# La liste est volontairement courte. Une version plus large, incluant
# « miscellaneous », « notices » et « representations and warranties », faisait
# chuter le rappel de douze points sur CUAD : ces sections fourre-tout abritent
# souvent la clause de résiliation ou le préavis de renouvellement. Seules
# figurent ici les sections qui ne règlent rien par elles-mêmes.
#
# La règle ne s'applique qu'aux clauses courtes. Sur un document mal structuré,
# un bloc intitulé « Definitions » peut couvrir le tiers du contrat et contenir
# de vraies obligations ; l'écarter en bloc coûterait bien plus en rappel qu'il
# ne rapporterait en précision.
CLAUSES_DE_FORME: tuple[str, ...] = (
    "definitions",
    "definition",
    "interpretation",
    "definitions et interpretation",
    "entire agreement",
    "severability",
    "counterparts",
    "headings",
    "further assurances",
    "recitals",
    "preamble",
    "witnesseth",
    "preambule",
    "en-tete du contrat",
    "identification des parties",
)

# Au-delà, une clause de forme est trop volumineuse pour être écartée en bloc.
# Écarter sans cette borne les seuls blocs réputés non normatifs — préambule,
# recitals, identification des parties — coûtait cinq points de F1 : sur un
# contrat dont le premier intitulé arrive tard, ce bloc couvre une large part
# du texte et contient de vraies stipulations.
TAILLE_FORME_MAX = 1500

_ORDRE_GRAVITE = {Gravite.FAIBLE: 0, Gravite.MOYENNE: 1, Gravite.ELEVEE: 2}
_PHRASE = re.compile(r"[^.!?]+[.!?]?")


def _compiler(expressions: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile une alternative sur mots entiers, tolérante à l'espacement."""
    if not expressions:
        return None
    alternatives = "|".join(
        r"\s+".join(re.escape(mot) for mot in expression.split())
        for expression in sorted(expressions, key=len, reverse=True)
    )
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


def _compiler_composes(motifs: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile des motifs déjà écrits comme des expressions régulières."""
    if not motifs:
        return None
    return re.compile("|".join(f"(?:{motif})" for motif in motifs))


_MOTIFS_DECISIVES = {
    categorie: _compiler(signature.decisives)
    for categorie, signature in LEXIQUE.items()
}
_MOTIFS_COMPOSES = {
    categorie: _compiler_composes(signature.composes)
    for categorie, signature in LEXIQUE.items()
}
_MOTIFS_EXPRESSIONS = {
    categorie: _compiler(signature.expressions)
    for categorie, signature in LEXIQUE.items()
}
_MOTIFS_INTITULES = {
    categorie: _compiler(signature.intitules)
    for categorie, signature in LEXIQUE.items()
}
_MOTIF_AGGRAVANTS = _compiler(tuple(marqueur for marqueur, _ in AGGRAVANTS))
_EXPLICATIONS_AGGRAVANTS = dict(AGGRAVANTS)
_MOTIF_FORME = _compiler(CLAUSES_DE_FORME)


def signaler_risque(clauses: list[Clause], seuil: int = SEUIL_DEFAUT) -> list[Risque]:
    """Signale les clauses sensibles d'un contrat.

    Args:
        clauses: Clauses issues de `decouper_clauses`.
        seuil: Score minimal de pertinence. L'abaisser augmente le rappel au
            détriment de la précision.

    Returns:
        Un signalement par couple (clause, catégorie), classé du plus grave au
        moins grave puis par ordre d'apparition dans le contrat.
    """
    signalements: list[Risque] = []
    rang_clause = {clause.identifiant: rang for rang, clause in enumerate(clauses)}

    for clause in clauses:
        corps = _neutraliser_faux_amis(_normaliser(clause.texte))
        intitule = _normaliser(f"{clause.identifiant} {clause.titre}")
        de_forme = (
            len(clause.texte) <= TAILLE_FORME_MAX
            and _MOTIF_FORME.search(intitule) is not None
        )
        motifs_aggravants = _reperer_aggravants(corps)

        for categorie, signature in LEXIQUE.items():
            score, expression, par_intitule = _noter(categorie, corps, intitule)
            if score < seuil:
                continue
            if de_forme and not par_intitule:
                # Clause de style : seul un intitulé explicitement consacré à
                # la catégorie la fait retenir.
                continue

            gravite, explications = _evaluer(signature.gravite, motifs_aggravants)
            justification = f"Clause relative {_libelle(categorie)}"
            if explications:
                justification += " — " + " ; ".join(explications)

            signalements.append(
                Risque(
                    clause_identifiant=clause.identifiant,
                    categorie=categorie,
                    gravite=gravite,
                    justification=justification + ".",
                    citation=_phrase_contenant(clause.texte, expression),
                )
            )

    signalements.sort(
        key=lambda risque: (
            -_ORDRE_GRAVITE[risque.gravite],
            rang_clause.get(risque.clause_identifiant, 0),
        )
    )
    return signalements


def _noter(
    categorie: CategorieRisque, corps: str, intitule: str
) -> tuple[int, str | None, bool]:
    """Calcule le score de pertinence d'une catégorie pour une clause.

    Le score retenu est celui de l'indice le plus fort, et non leur somme :
    cumuler plusieurs indices faibles ne vaut pas un indice décisif.

    Returns:
        Le score, l'expression déclenchante utilisée pour citer la clause, et
        si l'intitulé de la clause porte lui-même sur la catégorie.
    """
    score = 0
    declencheur: str | None = None

    motif_intitule = _MOTIFS_INTITULES[categorie]
    par_intitule = motif_intitule is not None and bool(motif_intitule.search(intitule))
    if par_intitule:
        score = POIDS_INTITULE

    motif_decisif = _MOTIFS_DECISIVES[categorie]
    if motif_decisif is not None:
        decisive = motif_decisif.search(corps)
        if decisive is not None:
            score = max(score, POIDS_DECISIVE)
            declencheur = decisive.group(0)

    motif_compose = _MOTIFS_COMPOSES[categorie]
    if motif_compose is not None and declencheur is None:
        compose = motif_compose.search(corps)
        if compose is not None:
            score = max(score, POIDS_DECISIVE)
            # La citation porte sur le début de la tournure, pas sur toute la
            # fenêtre parcourue par le motif.
            declencheur = compose.group(0).split(" ", 3)[0]

    motif_expression = _MOTIFS_EXPRESSIONS[categorie]
    if motif_expression is not None:
        occurrences = list(motif_expression.finditer(corps))
        if occurrences:
            ordinaire = POIDS_EXPRESSION
            if occurrences[0].start() < OUVERTURE:
                ordinaire += POIDS_POSITION
            if len({occurrence.group(0) for occurrence in occurrences}) > 1:
                ordinaire += POIDS_REPETITION
            if ordinaire > score or declencheur is None:
                declencheur = declencheur or occurrences[0].group(0)
            score = max(score, ordinaire)

    return score, declencheur, par_intitule


def _reperer_aggravants(corps: str) -> list[str]:
    trouves = {
        correspondance.group(0) for correspondance in _MOTIF_AGGRAVANTS.finditer(corps)
    }
    return sorted({_EXPLICATIONS_AGGRAVANTS[marqueur] for marqueur in trouves})


def _evaluer(gravite_base: Gravite, motifs: list[str]) -> tuple[Gravite, list[str]]:
    if not motifs:
        return gravite_base, motifs
    if gravite_base is Gravite.FAIBLE:
        return Gravite.MOYENNE, motifs
    return Gravite.ELEVEE, motifs


def _neutraliser_faux_amis(contenu: str) -> str:
    for formule in FAUX_AMIS:
        contenu = contenu.replace(formule, " ")
    return contenu


def _libelle(categorie: CategorieRisque) -> str:
    libelles = {
        CategorieRisque.PENALITE: "aux pénalités et indemnités de sortie",
        CategorieRisque.RESILIATION: "à la résiliation",
        CategorieRisque.RESILIATION_CONVENANCE: "à la résiliation sans motif",
        CategorieRisque.RESPONSABILITE: "à la limitation de responsabilité",
        CategorieRisque.INDEMNISATION: "aux engagements de garantie",
        CategorieRisque.CONFIDENTIALITE: "à la confidentialité",
        CategorieRisque.PROPRIETE_INTELLECTUELLE: "à la propriété intellectuelle",
        CategorieRisque.ASSURANCE: "à l'assurance",
        CategorieRisque.FORCE_MAJEURE: "à la force majeure",
        CategorieRisque.RENOUVELLEMENT_TACITE: "au renouvellement tacite",
    }
    return libelles[categorie]


def _phrase_contenant(texte: str, expression: str | None) -> str:
    """Retourne la phrase d'origine qui contient l'expression déclenchante."""
    if not expression:
        return ""
    for correspondance in _PHRASE.finditer(texte):
        phrase = correspondance.group(0).strip()
        if expression in _normaliser(phrase):
            return " ".join(phrase.split())
    return ""


def _normaliser(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.lower())
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans_accents)
