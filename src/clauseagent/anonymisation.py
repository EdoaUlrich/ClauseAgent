"""Anonymisation reversible des donnees sensibles avant envoi au modele.

Principe : le texte transmis au modele ne contient aucun nom, montant ou
coordonnee reels. Chaque valeur detectee est remplacee par un jeton stable
(`[SOCIETE_1]`, `[MONTANT_3]`, ...) et la correspondance reste en memoire du
processus local. Les sorties du modele sont restaurees avant affichage.

Deux consequences utiles :

* un contrat d'infrastructure sensible peut etre analyse sans que les
  identites et les montants quittent le poste de travail ;
* comme la substitution est bijective, une citation produite par le modele
  redevient apres restauration un extrait mot pour mot du contrat d'origine,
  ce qui permet de la verifier.

Les designations fonctionnelles des parties (« le Prestataire », « le Client »)
sont volontairement conservees : elles ne sont pas identifiantes et l'agent en
a besoin pour rattacher chaque obligation a son debiteur.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_MAJUSCULE = "A-ZÀ-ÖØ-Þ"
_MINUSCULE = "a-zà-öø-ÿ"
_MOT_PROPRE = rf"[{_MAJUSCULE}][{_MINUSCULE}{_MAJUSCULE}'’\-]+"

_FORMES_SOCIALES = (
    "SAS",
    "SASU",
    "SARL",
    "SARLU",
    "EURL",
    "SNC",
    "SCOP",
    "SA",
    "GIE",
    "GmbH",
    "AG",
    "Ltd",
    "LLC",
    "Inc",
    "PLC",
    "BV",
    "NV",
)

_VOIES = (
    "rue",
    "avenue",
    "boulevard",
    "chemin",
    "impasse",
    "place",
    "allée",
    "allee",
    "quai",
    "route",
    "zone industrielle",
)

# L'ordre est significatif : les motifs les plus specifiques passent d'abord
# pour qu'un IBAN ne soit pas decoupe en montants, ni un courriel en telephone.
# Le numero SIREN n'est pas dans cette liste : il n'est masque que s'il est
# precede d'un mot-cle, ce qui demande un traitement a part.
MOTIFS: tuple[tuple[str, str], ...] = (
    ("COURRIEL", r"[\w.+-]+@[\w-]+\.[\w.-]{2,}"),
    # Le dernier groupe d'un IBAN peut compter moins de quatre caracteres.
    ("IBAN", r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b"),
    ("TELEPHONE", r"(?:\+33|0033|0)\s*[1-9](?:[\s.\-]?\d{2}){4}\b"),
    (
        "SOCIETE",
        rf"\b{_MOT_PROPRE}(?:\s+(?:{_MOT_PROPRE}|&|de|du|des|la|le|les))*\s+"
        rf"(?:{'|'.join(_FORMES_SOCIALES)})\b",
    ),
    (
        "PERSONNE",
        rf"\b(?:M\.|Mme|Mlle|Monsieur|Madame|Maitre|Maître|Me|Dr)\s+"
        rf"{_MOT_PROPRE}(?:\s+{_MOT_PROPRE})?",
    ),
    (
        "ADRESSE",
        rf"\b\d{{1,4}}(?:\s*(?:bis|ter))?,?\s+(?:{'|'.join(_VOIES)})\s+"
        rf"[^\n,;.]{{3,60}}",
    ),
    (
        "MONTANT",
        r"\b\d[\d\s .,]*\s*(?:€|EUR\b|euros?\b|USD\b|dollars?\b)"
        r"|(?:€|\$)\s?\d[\d\s .,]*",
    ),
)

_MOTIF_SIREN_CONTEXTE = re.compile(
    r"(?P<prefixe>(?:SIREN|SIRET|RCS)[^\d\n]{0,20})(?P<valeur>\d[\d\s]{8,16}\d)",
    re.IGNORECASE,
)

_MOTIF_JETON = re.compile(r"\[(?P<categorie>[A-Z]+)_(?P<index>\d+)\]")


@dataclass(slots=True)
class Anonymiseur:
    """Substitue les donnees identifiantes par des jetons reversibles."""

    actif: bool = True
    _vers_jeton: dict[str, str] = field(default_factory=dict)
    _vers_valeur: dict[str, str] = field(default_factory=dict)
    _compteurs: Counter[str] = field(default_factory=Counter)

    def anonymiser(self, texte: str) -> str:
        """Retourne le texte prive de ses donnees identifiantes."""
        if not self.actif or not texte:
            return texte

        resultat = _MOTIF_SIREN_CONTEXTE.sub(
            lambda m: m.group("prefixe") + self._jeton("SIREN", m.group("valeur")),
            texte,
        )
        for categorie, motif in MOTIFS:
            resultat = re.sub(
                motif,
                lambda m, c=categorie: self._jeton(c, m.group(0)),
                resultat,
            )
        return resultat

    def restaurer(self, texte: str) -> str:
        """Remplace les jetons par les valeurs d'origine."""
        if not self.actif or not texte:
            return texte
        return _MOTIF_JETON.sub(
            lambda m: self._vers_valeur.get(m.group(0), m.group(0)), texte
        )

    def resume(self) -> dict[str, int]:
        """Nombre de valeurs distinctes masquees par categorie.

        Sert a tracer l'anonymisation dans le journal d'audit sans jamais y
        inscrire les valeurs elles-memes.
        """
        return dict(self._compteurs)

    def _jeton(self, categorie: str, valeur: str) -> str:
        valeur_nette = valeur.strip()
        if not valeur_nette:
            return valeur
        cle = f"{categorie}:{valeur_nette.casefold()}"
        jeton = self._vers_jeton.get(cle)
        if jeton is None:
            self._compteurs[categorie] += 1
            jeton = f"[{categorie}_{self._compteurs[categorie]}]"
            self._vers_jeton[cle] = jeton
            self._vers_valeur[jeton] = valeur_nette
        # L'espacement d'origine est preserve pour ne pas decaler le texte.
        prefixe = valeur[: len(valeur) - len(valeur.lstrip())]
        suffixe = valeur[len(valeur.rstrip()) :]
        return f"{prefixe}{jeton}{suffixe}"
