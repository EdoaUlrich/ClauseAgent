"""Outil `lire_document` : extraction du texte d'un PDF, d'un Word ou d'un TXT."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

EXTENSIONS_SUPPORTEES = {".pdf", ".docx", ".txt", ".md"}

# Coupure de mot en fin de ligne, fréquente dans les PDF mis en colonnes.
_COUPURE_MOT = re.compile(r"(\w)-\n(\w)")
_ESPACES_MULTIPLES = re.compile(r"[ \t]{2,}")
_LIGNES_VIDES = re.compile(r"\n{3,}")
_NUMERO_PAGE = re.compile(r"^\s*(?:page\s+)?\d+\s*(?:/\s*\d+)?\s*$", re.IGNORECASE)


@dataclass(slots=True)
class DocumentLu:
    """Texte et métadonnées d'un document source."""

    chemin: str
    texte: str
    format: str
    nombre_pages: int = 0

    @property
    def nombre_caracteres(self) -> int:
        return len(self.texte)


def lire_document(chemin: str | Path) -> DocumentLu:
    """Lit un contrat et retourne son texte nettoyé.

    Args:
        chemin: Chemin du fichier à lire (.pdf, .docx, .txt ou .md).

    Raises:
        FileNotFoundError: Le fichier n'existe pas.
        ValueError: L'extension n'est pas prise en charge, ou le document ne
            contient aucun texte extractible (cas d'un PDF scanné sans OCR).
    """
    fichier = Path(chemin).expanduser()
    if not fichier.is_file():
        raise FileNotFoundError(f"Document introuvable : {fichier}")

    extension = fichier.suffix.lower()
    if extension not in EXTENSIONS_SUPPORTEES:
        attendues = ", ".join(sorted(EXTENSIONS_SUPPORTEES))
        raise ValueError(
            f"Format non pris en charge : '{extension}'. Formats attendus : {attendues}."
        )

    if extension == ".pdf":
        texte, pages = _lire_pdf(fichier)
    elif extension == ".docx":
        texte, pages = _lire_docx(fichier), 0
    else:
        texte, pages = fichier.read_text(encoding="utf-8", errors="replace"), 0

    texte = _nettoyer(texte)
    if not texte.strip():
        raise ValueError(
            f"Aucun texte extrait de {fichier.name}. S'il s'agit d'un PDF scanné, "
            "il faut d'abord le passer par une reconnaissance de caractères."
        )

    return DocumentLu(
        chemin=str(fichier), texte=texte, format=extension.lstrip("."), nombre_pages=pages
    )


def _lire_pdf(fichier: Path) -> tuple[str, int]:
    from pypdf import PdfReader

    lecteur = PdfReader(str(fichier))
    if lecteur.is_encrypted:
        # Un chiffrement sans mot de passe est courant : on tente l'ouverture vide.
        try:
            lecteur.decrypt("")
        except Exception as erreur:  # pragma: no cover - dépend du fichier
            raise ValueError(
                f"{fichier.name} est protégé par mot de passe et ne peut pas être lu."
            ) from erreur

    pages = [page.extract_text() or "" for page in lecteur.pages]
    return "\n\n".join(pages), len(pages)


def _lire_docx(fichier: Path) -> str:
    from docx import Document

    document = Document(str(fichier))
    morceaux: list[str] = [paragraphe.text for paragraphe in document.paragraphs]

    # Les contrats Word placent souvent les annexes et les barèmes en tableaux.
    for tableau in document.tables:
        for ligne in tableau.rows:
            cellules = [cellule.text.strip() for cellule in ligne.cells]
            if any(cellules):
                morceaux.append(" | ".join(cellules))

    return "\n".join(morceaux)


def _nettoyer(texte: str) -> str:
    """Normalise le texte sans en altérer le contenu juridique.

    Les citations devant rester vérifiables mot pour mot, on se limite à la
    suppression d'artefacts de mise en page : coupures de mots, numéros de
    page isolés et espacement redondant.
    """
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    # Espace insécable et marque d'ordre des octets, fréquents dans les exports Word.
    texte = texte.replace("\u00a0", " ").replace("\ufeff", "")
    texte = _COUPURE_MOT.sub(r"\1\2", texte)

    lignes = [
        ligne.rstrip() for ligne in texte.split("\n") if not _NUMERO_PAGE.match(ligne)
    ]
    texte = "\n".join(lignes)

    texte = _ESPACES_MULTIPLES.sub(" ", texte)
    return _LIGNES_VIDES.sub("\n\n", texte).strip()
