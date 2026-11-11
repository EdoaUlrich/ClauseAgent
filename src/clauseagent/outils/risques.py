"""Outil `signaler_risque` : repérage des clauses à faire relire par un humain.

La détection repose sur un lexique et des indices rédactionnels plutôt que sur
le modèle. Trois raisons à ce choix : le résultat est stable d'une exécution à
l'autre, il reste explicable devant un juriste, et il ne coûte aucun appel
distant. L'agent garde la main sur l'interprétation ; cet outil se contente de
dire « cette clause mérite un œil humain, pour tel motif ».

Le lexique est bilingue. Les contrats d'infrastructure sont fréquemment rédigés
en anglais, et c'est aussi la langue de CUAD, le jeu annoté par des juristes qui
sert à mesurer la précision et le rappel de cet outil (voir `clauseagent.evaluation`).
"""

from __future__ import annotations

import re
import unicodedata

from clauseagent.models import CategorieRisque, Clause, Gravite, Risque

# Pour chaque catégorie : termes déclencheurs (français puis anglais) et
# gravité de base.
LEXIQUE: dict[CategorieRisque, tuple[tuple[str, ...], Gravite]] = {
    CategorieRisque.PENALITE: (
        (
            "penalite",
            "penalites",
            "astreinte",
            "interets de retard",
            "indemnite forfaitaire",
            "dommages et interets",
            "amende",
            "liquidated damages",
            "penalty",
            "penalties",
            "late payment charge",
            "late fee",
        ),
        Gravite.ELEVEE,
    ),
    CategorieRisque.RESILIATION: (
        (
            "resiliation",
            "resilier",
            "rupture du contrat",
            "mise en demeure",
            "decheance",
            "terminaison",
            "termination",
            "terminate",
            "may be terminated",
            "cure period",
        ),
        Gravite.ELEVEE,
    ),
    CategorieRisque.RESPONSABILITE: (
        (
            "responsabilite",
            "limitation de responsabilite",
            "garantie",
            "indemnisation",
            "prejudice",
            "exoneration",
            "limitation of liability",
            "shall not be liable",
            "aggregate liability",
            "consequential damages",
            "indemnify",
            "indemnification",
            "hold harmless",
        ),
        Gravite.ELEVEE,
    ),
    CategorieRisque.CONFIDENTIALITE: (
        (
            "confidentialite",
            "confidentiel",
            "secret des affaires",
            "non-divulgation",
            "confidential information",
            "confidentiality",
            "non-disclosure",
            "trade secret",
        ),
        Gravite.MOYENNE,
    ),
    CategorieRisque.PROPRIETE_INTELLECTUELLE: (
        (
            "propriete intellectuelle",
            "droits d'auteur",
            "licence",
            "brevet",
            "cession de droits",
            "intellectual property",
            "license grant",
            "hereby grants",
            "copyright",
            "patent",
            "work made for hire",
        ),
        Gravite.MOYENNE,
    ),
    CategorieRisque.ASSURANCE: (
        (
            "assurance",
            "responsabilite civile professionnelle",
            "attestation d'assurance",
            "insurance",
            "commercial general liability",
            "certificate of insurance",
        ),
        Gravite.MOYENNE,
    ),
    CategorieRisque.FORCE_MAJEURE: (
        (
            "force majeure",
            "cas fortuit",
            "evenement imprevisible",
            "act of god",
        ),
        Gravite.FAIBLE,
    ),
    CategorieRisque.RENOUVELLEMENT_TACITE: (
        (
            "tacite reconduction",
            "renouvele tacitement",
            "reconduction tacite",
            "renouvellement tacite",
            "automatically renew",
            "automatic renewal",
            "auto-renew",
            "renewal term",
            "successive renewal",
        ),
        Gravite.ELEVEE,
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

_ORDRE_GRAVITE = {Gravite.FAIBLE: 0, Gravite.MOYENNE: 1, Gravite.ELEVEE: 2}
_PHRASE = re.compile(r"[^.!?]+[.!?]?")

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
)


def signaler_risque(clauses: list[Clause]) -> list[Risque]:
    """Signale les clauses sensibles d'un contrat.

    Args:
        clauses: Clauses issues de `decouper_clauses`.

    Returns:
        Un signalement par couple (clause, catégorie), classé du plus grave au
        moins grave puis par ordre d'apparition dans le contrat.
    """
    signalements: list[Risque] = []
    rang_clause = {clause.identifiant: rang for rang, clause in enumerate(clauses)}

    for clause in clauses:
        contenu = _neutraliser_faux_amis(
            _normaliser(f"{clause.identifiant} {clause.titre}\n{clause.texte}")
        )

        for categorie, (termes, gravite_base) in LEXIQUE.items():
            terme_trouve = next((terme for terme in termes if terme in contenu), None)
            if terme_trouve is None:
                continue

            gravite, motifs = _evaluer(contenu, gravite_base)
            justification = f"Clause relative {_libelle(categorie)}"
            if motifs:
                justification += " — " + " ; ".join(motifs)

            signalements.append(
                Risque(
                    clause_identifiant=clause.identifiant,
                    categorie=categorie,
                    gravite=gravite,
                    justification=justification + ".",
                    citation=_phrase_contenant(clause.texte, terme_trouve),
                )
            )

    signalements.sort(
        key=lambda risque: (
            -_ORDRE_GRAVITE[risque.gravite],
            rang_clause.get(risque.clause_identifiant, 0),
        )
    )
    return signalements


def _evaluer(contenu: str, gravite_base: Gravite) -> tuple[Gravite, list[str]]:
    motifs = [explication for marqueur, explication in AGGRAVANTS if marqueur in contenu]
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
        CategorieRisque.PENALITE: "aux pénalités",
        CategorieRisque.RESILIATION: "à la résiliation",
        CategorieRisque.RESPONSABILITE: "à la responsabilité",
        CategorieRisque.CONFIDENTIALITE: "à la confidentialité",
        CategorieRisque.PROPRIETE_INTELLECTUELLE: "à la propriété intellectuelle",
        CategorieRisque.ASSURANCE: "à l'assurance",
        CategorieRisque.FORCE_MAJEURE: "à la force majeure",
        CategorieRisque.RENOUVELLEMENT_TACITE: "au renouvellement tacite",
    }
    return libelles[categorie]


def _phrase_contenant(texte: str, terme_normalise: str) -> str:
    """Retourne la phrase d'origine qui contient le terme déclencheur."""
    for correspondance in _PHRASE.finditer(texte):
        phrase = correspondance.group(0).strip()
        if terme_normalise in _normaliser(phrase):
            return " ".join(phrase.split())
    return ""


def _normaliser(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.lower())
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans_accents)
