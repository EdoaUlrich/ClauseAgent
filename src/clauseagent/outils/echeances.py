"""Outil `calculer_echeance` : conversion d'un délai contractuel en date réelle.

« 30 jours après la livraison » ne devient une échéance exploitable que si l'on
sait quand la livraison a eu lieu. Le calcul est fait en Python plutôt que par
le modèle : l'arithmétique de dates est exacte, reproductible et vérifiable,
alors qu'un modèle de langage peut se tromper d'un jour sans le signaler.

L'outil accepte un dictionnaire d'événements de référence (signature, prise
d'effet, livraison, réception de facture...) et retourne la date obtenue avec
la base de calcul employée.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

MOIS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}

NOMBRES_EN_MOTS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "quinze": 15,
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "quarante-cinq": 45,
    "soixante": 60,
    "quatre-vingt-dix": 90,
}

# Unités reconnues, exprimées sous forme normalisée (sans accent, au singulier).
UNITES = (
    "heure",
    "jour ouvre",
    "jour calendaire",
    "jour",
    "semaine",
    "mois",
    "trimestre",
    "semestre",
    "annee",
    "an",
)

_MOTS_AVANT = ("avant", "anterieurement", "au plus tard le")
_MOTS_APRES = (
    "apres",
    "a compter",
    "suivant",
    "a partir",
    "dans les",
    "dans un delai",
    "sous",
)

_RECURRENCES = {
    "par trimestre": "trimestriel",
    "trimestriel": "trimestriel",
    "par semestre": "semestriel",
    "semestriel": "semestriel",
    "par mois": "mensuel",
    "mensuel": "mensuel",
    "annuel": "annuel",
    "chaque annee": "annuel",
    "par an": "annuel",
}

# Libellés reconnus pour chaque événement de référence. Ils sont écrits avec
# leurs accents car ils sont réutilisés tels quels dans le tableau de suivi ;
# la comparaison, elle, se fait sur une forme normalisée. Les expressions
# contractuelles se chevauchant souvent (« réception de la facture » contient
# « réception »), c'est le libellé le plus long qui est retenu.
_EVENEMENTS_CONNUS = {
    "signature": ("date de signature", "signature", "conclusion du contrat"),
    "prise_effet": (
        "date de prise d'effet",
        "prise d'effet",
        "entrée en vigueur",
        "effet du contrat",
    ),
    "livraison": (
        "réception des travaux",
        "réception des prestations",
        "réception définitive",
        "réception provisoire",
        "livraison",
    ),
    "facture": (
        "réception de la facture",
        "émission de la facture",
        "date de la facture",
        "facture",
    ),
    "mise_en_demeure": ("réception de la mise en demeure", "mise en demeure"),
    "signalement": ("signalement", "déclaration de l'incident", "incident"),
    "intervention": ("intervention", "visite"),
    "echeance": ("échéance", "expiration du contrat", "expiration", "terme du contrat"),
}


@dataclass(slots=True)
class EcheanceCalculee:
    """Résultat de l'interprétation d'un délai contractuel."""

    texte_source: str
    date_calculee: date | None = None
    base: str = ""
    date_base: date | None = None
    quantite: int | None = None
    unite: str | None = None
    jours_ouvres: bool = False
    sens: str = "apres"
    recurrence: str | None = None
    commentaire: str = ""
    avertissements: list[str] = field(default_factory=list)

    @property
    def resolue(self) -> bool:
        return self.date_calculee is not None


def calculer_echeance(
    expression: str,
    date_reference: date | None = None,
    evenements: dict[str, date] | None = None,
) -> EcheanceCalculee:
    """Transforme un délai exprimé en langage naturel en date réelle.

    Args:
        expression: Délai tel qu'il figure au contrat, par exemple
            « 30 jours à compter de la réception de la facture ».
        date_reference: Date utilisée lorsque aucun événement n'est identifié
            (par défaut la date du jour).
        evenements: Dates connues des événements contractuels, indexées par
            nom libre (« livraison », « prise d'effet », ...).

    Returns:
        Un `EcheanceCalculee`. Si l'expression désigne un événement dont la
        date est inconnue, `date_calculee` vaut None et l'événement attendu est
        indiqué dans `base`, afin que le gestionnaire sache quelle information
        lui manque.
    """
    resultat = EcheanceCalculee(texte_source=expression)
    if not expression or not expression.strip():
        resultat.commentaire = "Aucun délai fourni."
        return resultat

    normalise = _normaliser(expression)
    reference = date_reference or date.today()
    evenements = {_normaliser(cle): valeur for cle, valeur in (evenements or {}).items()}

    resultat.recurrence = _detecter_recurrence(normalise)
    resultat.sens = _detecter_sens(normalise)

    # 1. Date absolue explicite : elle prime sur toute interprétation relative.
    absolue = _lire_date_absolue(normalise, reference)
    if absolue is not None:
        resultat.date_calculee = absolue
        resultat.base = "date explicite"
        resultat.commentaire = "Date lue directement dans la clause."
        return resultat

    # 2. Délai relatif : quantité + unité.
    duree = _lire_duree(normalise)
    if duree is None:
        resultat.commentaire = (
            "Aucune durée ni date exploitable n'a été reconnue dans l'expression."
        )
        return resultat

    quantite, unite, jours_ouvres = duree
    resultat.quantite = quantite
    resultat.unite = unite
    resultat.jours_ouvres = jours_ouvres

    nom_base, date_base = _resoudre_base(normalise, evenements, reference)
    resultat.base = nom_base
    resultat.date_base = date_base

    duree_lisible = _duree_lisible(quantite, unite, jours_ouvres)

    if date_base is None:
        resultat.commentaire = (
            f"Délai de {duree_lisible} identifié, mais la date de l'événement "
            f"« {nom_base} » n'est pas connue."
        )
        resultat.avertissements.append(f"Date manquante : {nom_base}")
        return resultat

    signe = -1 if resultat.sens == "avant" else 1
    resultat.date_calculee = _appliquer_duree(
        date_base, quantite * signe, unite, jours_ouvres
    )
    sens_lisible = "avant" if resultat.sens == "avant" else "après"
    resultat.commentaire = (
        f"{duree_lisible} {sens_lisible} {nom_base} ({date_base.isoformat()})."
    )

    if unite == "heure":
        resultat.avertissements.append(
            "Délai exprimé en heures : la date retenue est arrondie au jour."
        )
    if jours_ouvres:
        resultat.avertissements.append(
            "Jours ouvrés calculés hors samedi et dimanche, sans calendrier des "
            "jours fériés."
        )

    return resultat


def _normaliser(texte: str) -> str:
    """Minuscules sans accents, pour comparer des libellés rédigés librement."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans_accents).strip()


def _detecter_sens(normalise: str) -> str:
    position_avant = min(
        (normalise.find(mot) for mot in _MOTS_AVANT if mot in normalise), default=-1
    )
    position_apres = min(
        (normalise.find(mot) for mot in _MOTS_APRES if mot in normalise), default=-1
    )
    if position_avant == -1:
        return "apres"
    if position_apres == -1:
        return "avant"
    return "avant" if position_avant < position_apres else "apres"


def _detecter_recurrence(normalise: str) -> str | None:
    for marqueur, valeur in _RECURRENCES.items():
        if marqueur in normalise:
            return valeur
    return None


def _lire_date_absolue(normalise: str, reference: date) -> date | None:
    jour_mois_annee = re.search(
        rf"\b(\d{{1,2}})(?:er)?\s+({'|'.join(MOIS)})\s+(\d{{4}})\b", normalise
    )
    if jour_mois_annee:
        jour, mois, annee = jour_mois_annee.groups()
        return _date_sure(int(annee), MOIS[mois], int(jour))

    numerique = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", normalise)
    if numerique:
        jour, mois, annee = (int(valeur) for valeur in numerique.groups())
        if annee < 100:
            annee += 2000
        return _date_sure(annee, mois, jour)

    jour_mois = re.search(
        rf"\b(\d{{1,2}})(?:er)?\s+({'|'.join(MOIS)})\b", normalise
    )
    if jour_mois:
        jour, mois = jour_mois.groups()
        candidate = _date_sure(reference.year, MOIS[mois], int(jour))
        if candidate is None:
            return None
        # « au plus tard le 31 janvier de chaque année » : la prochaine occurrence.
        if candidate < reference:
            candidate = candidate.replace(year=reference.year + 1)
        return candidate

    return None


def _date_sure(annee: int, mois: int, jour: int) -> date | None:
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


def _lire_duree(normalise: str) -> tuple[int, str, bool] | None:
    # Le pluriel peut porter sur chacun des mots : « jours ouvrés », « jour ouvré ».
    motif_unites = "|".join(
        r"s?\s+".join(re.escape(mot) for mot in unite.split(" ")) + r"s?"
        for unite in UNITES
    )
    motif = re.compile(
        rf"\b(?P<quantite>\d+|{'|'.join(NOMBRES_EN_MOTS)})\s+(?P<unite>{motif_unites})\b"
    )
    correspondance = motif.search(normalise)
    if correspondance is None:
        return None

    brut_quantite = correspondance.group("quantite")
    quantite = (
        int(brut_quantite)
        if brut_quantite.isdigit()
        else NOMBRES_EN_MOTS[brut_quantite]
    )

    brut_unite = _singulier(correspondance.group("unite"))
    jours_ouvres = brut_unite.startswith("jour ouvre")
    unite = _unite_canonique(brut_unite)
    return quantite, unite, jours_ouvres


_UNITES_LISIBLES = {
    "heure": ("heure", "heures"),
    "jour": ("jour", "jours"),
    "semaine": ("semaine", "semaines"),
    "mois": ("mois", "mois"),
    "trimestre": ("trimestre", "trimestres"),
    "semestre": ("semestre", "semestres"),
    "an": ("an", "ans"),
}


def _duree_lisible(quantite: int, unite: str, jours_ouvres: bool) -> str:
    singulier, pluriel = _UNITES_LISIBLES.get(unite, (unite, unite))
    libelle = singulier if abs(quantite) <= 1 else pluriel
    if jours_ouvres:
        libelle += " ouvré" if abs(quantite) <= 1 else " ouvrés"
    return f"{quantite} {libelle}"


def _singulier(unite: str) -> str:
    """Ramène « jours ouvrés » à « jour ouvre » pour comparer les unités."""
    mots = re.sub(r"\s+", " ", unite).strip().split(" ")
    return " ".join(mot if mot == "mois" else mot.rstrip("s") for mot in mots)


def _unite_canonique(brut: str) -> str:
    if brut.startswith("jour"):
        return "jour"
    if brut.startswith("annee") or brut == "an":
        return "an"
    for unite in ("heure", "semaine", "mois", "trimestre", "semestre"):
        if brut.startswith(unite):
            return unite
    return brut


def _resoudre_base(
    normalise: str, evenements: dict[str, date], reference: date
) -> tuple[str, date | None]:
    """Identifie l'événement de départ et sa date si elle est connue.

    Le libellé le plus long l'emporte : « réception de la mise en demeure »
    désigne la mise en demeure, pas une réception de travaux.
    """
    candidats: list[tuple[int, str, date | None]] = []

    for cle, libelles in _EVENEMENTS_CONNUS.items():
        for libelle in libelles:
            libelle_normalise = _normaliser(libelle)
            if libelle_normalise in normalise:
                date_connue = evenements.get(cle) or evenements.get(libelle_normalise)
                candidats.append((len(libelle_normalise), libelle, date_connue))

    # Un événement fourni par l'appelant peut être cité sous son propre nom.
    for nom, valeur in evenements.items():
        if nom in normalise:
            candidats.append((len(nom), nom, valeur))

    if candidats:
        _, libelle, date_connue = max(candidats, key=lambda candidat: candidat[0])
        return libelle, date_connue

    if "prise_effet" in evenements:
        return "prise d'effet", evenements["prise_effet"]
    return "date de référence", reference


def _appliquer_duree(
    depart: date, quantite: int, unite: str, jours_ouvres: bool
) -> date:
    if jours_ouvres:
        return _ajouter_jours_ouvres(depart, quantite)
    if unite == "heure":
        jours = math.ceil(abs(quantite) / 24) * (1 if quantite >= 0 else -1)
        return depart + timedelta(days=jours)
    if unite == "jour":
        return depart + timedelta(days=quantite)
    if unite == "semaine":
        return depart + timedelta(weeks=quantite)
    if unite == "mois":
        return depart + relativedelta(months=quantite)
    if unite == "trimestre":
        return depart + relativedelta(months=3 * quantite)
    if unite == "semestre":
        return depart + relativedelta(months=6 * quantite)
    if unite == "an":
        return depart + relativedelta(years=quantite)
    return depart + timedelta(days=quantite)


def _ajouter_jours_ouvres(depart: date, quantite: int) -> date:
    pas = 1 if quantite >= 0 else -1
    restants = abs(quantite)
    courant = depart
    while restants > 0:
        courant += timedelta(days=pas)
        if courant.weekday() < 5:
            restants -= 1
    return courant
