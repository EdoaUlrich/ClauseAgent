"""Outil `exporter_excel` : production du tableau de suivi du gestionnaire.

Le classeur est le livrable final : il doit être lisible sans ouvrir le
contrat, mais permettre de remonter à la source de chaque ligne. D'où la
colonne « Citation » présente sur chaque feuille, et la colonne « Citation
vérifiée » qui distingue ce qui a été recoupé automatiquement de ce qui reste
à contrôler.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from clauseagent.models import AnalyseContrat, Gravite, TypeElement

_ENTETE_FOND = PatternFill("solid", fgColor="1F3864")
_ENTETE_POLICE = Font(color="FFFFFF", bold=True)

_COULEURS_GRAVITE = {
    Gravite.ELEVEE: PatternFill("solid", fgColor="F8CBAD"),
    Gravite.MOYENNE: PatternFill("solid", fgColor="FFE699"),
    Gravite.FAIBLE: PatternFill("solid", fgColor="E2EFDA"),
}

_LIBELLES_TYPE = {
    TypeElement.OBLIGATION: "Obligation",
    TypeElement.DROIT: "Droit",
    TypeElement.PENALITE: "Pénalité",
    TypeElement.AUTRE: "Autre",
}


def exporter_excel(analyse: AnalyseContrat, chemin: str | Path) -> Path:
    """Écrit le tableau de suivi au format xlsx.

    Args:
        analyse: Résultat complet de l'analyse.
        chemin: Chemin du classeur à produire. Les dossiers manquants sont créés.

    Returns:
        Le chemin du fichier écrit.
    """
    destination = Path(chemin).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)

    classeur = Workbook()
    _feuille_suivi(classeur.active, analyse)
    _feuille_risques(classeur.create_sheet("Risques"), analyse)
    _feuille_clauses(classeur.create_sheet("Clauses"), analyse)
    _feuille_synthese(classeur.create_sheet("Synthèse"), analyse)

    classeur.save(destination)
    return destination


def _feuille_suivi(feuille: Worksheet, analyse: AnalyseContrat) -> None:
    feuille.title = "Suivi"
    entetes = (
        "Clause",
        "Type",
        "Partie concernée",
        "Description",
        "Échéance au contrat",
        "Date calculée",
        "Base de calcul",
        "Citation",
        "Citation vérifiée",
    )
    _ecrire_entetes(feuille, entetes)

    for element in analyse.elements:
        feuille.append(
            [
                element.clause_identifiant,
                _LIBELLES_TYPE[element.type],
                element.partie_concernee,
                element.description,
                element.echeance_textuelle or "",
                element.echeance_calculee,
                element.base_calcul or "",
                element.citation,
                "Oui" if element.citation_verifiee else "À contrôler",
            ]
        )

    for ligne in feuille.iter_rows(min_row=2, min_col=6, max_col=6):
        for cellule in ligne:
            cellule.number_format = "DD/MM/YYYY"

    _mettre_en_forme(
        feuille,
        {
            "A": 14,
            "B": 12,
            "C": 20,
            "D": 52,
            "E": 30,
            "F": 14,
            "G": 22,
            "H": 60,
            "I": 16,
        },
    )


def _feuille_risques(feuille: Worksheet, analyse: AnalyseContrat) -> None:
    _ecrire_entetes(feuille, ("Clause", "Catégorie", "Gravité", "Motif", "Citation"))

    for risque in analyse.risques:
        feuille.append(
            [
                risque.clause_identifiant,
                risque.categorie.value.replace("_", " ").capitalize(),
                risque.gravite.value.capitalize(),
                risque.justification,
                risque.citation,
            ]
        )
        feuille.cell(row=feuille.max_row, column=3).fill = _COULEURS_GRAVITE[risque.gravite]

    _mettre_en_forme(feuille, {"A": 14, "B": 24, "C": 12, "D": 56, "E": 60})


def _feuille_clauses(feuille: Worksheet, analyse: AnalyseContrat) -> None:
    _ecrire_entetes(feuille, ("Référence", "Intitulé", "Position", "Extrait"))

    for clause in analyse.clauses:
        feuille.append(
            [clause.identifiant, clause.titre, f"{clause.debut}-{clause.fin}", clause.apercu]
        )

    _mettre_en_forme(feuille, {"A": 16, "B": 34, "C": 14, "D": 80})


def _feuille_synthese(feuille: Worksheet, analyse: AnalyseContrat) -> None:
    _ecrire_entetes(feuille, ("Indicateur", "Valeur"))

    verifiees = sum(1 for element in analyse.elements if element.citation_verifiee)
    lignes = [
        ("Document analysé", Path(analyse.source).name),
        ("Date d'analyse", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Taille du document (caractères)", analyse.nombre_caracteres),
        ("Clauses identifiées", len(analyse.clauses)),
        ("Éléments extraits", len(analyse.elements)),
        ("dont obligations", len(analyse.elements_par_type(TypeElement.OBLIGATION))),
        ("dont droits", len(analyse.elements_par_type(TypeElement.DROIT))),
        ("dont pénalités", len(analyse.elements_par_type(TypeElement.PENALITE))),
        ("Échéances datées", sum(1 for e in analyse.elements if e.echeance_calculee)),
        ("Citations vérifiées", f"{verifiees}/{len(analyse.elements)}"),
        ("Clauses signalées", len(analyse.risques)),
        (
            "dont gravité élevée",
            sum(1 for risque in analyse.risques if risque.gravite is Gravite.ELEVEE),
        ),
        ("Anonymisation avant envoi", "Activée" if analyse.anonymisation_active else "Désactivée"),
    ]
    for libelle, valeur in lignes:
        feuille.append([libelle, valeur])

    if analyse.synthese:
        feuille.append([])
        feuille.append(["Synthèse", analyse.synthese])

    if analyse.journal:
        feuille.append([])
        feuille.append(["Journal des outils appelés", ""])
        for entree in analyse.journal:
            feuille.append(["", entree])

    _mettre_en_forme(feuille, {"A": 34, "B": 90}, filtre=False)


def _ecrire_entetes(feuille: Worksheet, entetes: tuple[str, ...]) -> None:
    feuille.append(list(entetes))
    for colonne in range(1, len(entetes) + 1):
        cellule = feuille.cell(row=1, column=colonne)
        cellule.fill = _ENTETE_FOND
        cellule.font = _ENTETE_POLICE
        cellule.alignment = Alignment(vertical="center", horizontal="left")
    feuille.row_dimensions[1].height = 22


def _mettre_en_forme(
    feuille: Worksheet, largeurs: dict[str, int], filtre: bool = True
) -> None:
    for colonne, largeur in largeurs.items():
        feuille.column_dimensions[colonne].width = largeur

    for ligne in feuille.iter_rows(min_row=2):
        for cellule in ligne:
            cellule.alignment = Alignment(vertical="top", wrap_text=True)

    feuille.freeze_panes = "A2"
    if filtre and feuille.max_row > 1:
        derniere_colonne = get_column_letter(feuille.max_column)
        feuille.auto_filter.ref = f"A1:{derniere_colonne}{feuille.max_row}"
