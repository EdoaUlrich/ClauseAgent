"""Tests de l'export Excel."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from clauseagent.models import (
    AnalyseContrat,
    CategorieRisque,
    Clause,
    ElementExtrait,
    Gravite,
    Risque,
    TypeElement,
)
from clauseagent.outils.export import exporter_excel


def analyse_exemple() -> AnalyseContrat:
    return AnalyseContrat(
        source="exemples/contrat_maintenance.txt",
        nombre_caracteres=4200,
        clauses=[
            Clause(identifiant="Article 4.2", titre="Conditions de paiement", texte="Texte.")
        ],
        elements=[
            ElementExtrait(
                type=TypeElement.OBLIGATION,
                partie_concernee="le Client",
                description="Régler les factures sous 30 jours.",
                echeance_textuelle="30 jours à compter de la réception de la facture",
                citation="Le Client règle les factures dans un délai de 30 jours",
                clause_identifiant="Article 4.2",
                echeance_calculee=date(2026, 5, 15),
                base_calcul="réception de la facture",
                citation_verifiee=True,
            ),
            ElementExtrait(
                type=TypeElement.PENALITE,
                partie_concernee="le Prestataire",
                description="Pénalité de 500 euros par heure de retard.",
                citation="une pénalité de 500 euros par heure de retard",
                clause_identifiant="Article 5.1",
                citation_verifiee=False,
            ),
        ],
        risques=[
            Risque(
                clause_identifiant="Article 5.1",
                categorie=CategorieRisque.PENALITE,
                gravite=Gravite.ELEVEE,
                justification="Clause relative aux pénalités.",
                citation="une pénalité de 500 euros par heure de retard",
            )
        ],
        synthese="Deux engagements relevés.",
        journal=["lire_document", "decouper_clauses"],
    )


def test_le_classeur_contient_les_quatre_feuilles(tmp_path: Path):
    chemin = exporter_excel(analyse_exemple(), tmp_path / "suivi.xlsx")
    classeur = load_workbook(chemin)

    assert classeur.sheetnames == ["Suivi", "Risques", "Clauses", "Synthèse"]


def test_les_lignes_de_suivi_sont_completes(tmp_path: Path):
    chemin = exporter_excel(analyse_exemple(), tmp_path / "suivi.xlsx")
    feuille = load_workbook(chemin)["Suivi"]
    lignes = list(feuille.iter_rows(min_row=2, values_only=True))

    assert len(lignes) == 2
    assert lignes[0][0] == "Article 4.2"
    assert lignes[0][1] == "Obligation"
    # openpyxl relit les dates sous forme de datetime.
    assert lignes[0][5].date() == date(2026, 5, 15)
    assert lignes[0][8] == "Oui"
    assert lignes[1][8] == "À contrôler"


def test_la_synthese_reprend_les_indicateurs(tmp_path: Path):
    chemin = exporter_excel(analyse_exemple(), tmp_path / "suivi.xlsx")
    feuille = load_workbook(chemin)["Synthèse"]
    valeurs = {
        ligne[0]: ligne[1] for ligne in feuille.iter_rows(min_row=2, values_only=True) if ligne[0]
    }

    assert valeurs["Clauses identifiées"] == 1
    assert valeurs["Éléments extraits"] == 2
    assert valeurs["Citations vérifiées"] == "1/2"
    assert valeurs["Anonymisation avant envoi"] == "Activée"


def test_les_repertoires_manquants_sont_crees(tmp_path: Path):
    chemin = exporter_excel(analyse_exemple(), tmp_path / "a" / "b" / "suivi.xlsx")
    assert chemin.exists()


def test_le_filtre_et_le_volet_fige_sont_poses(tmp_path: Path):
    chemin = exporter_excel(analyse_exemple(), tmp_path / "suivi.xlsx")
    feuille = load_workbook(chemin)["Suivi"]

    assert feuille.freeze_panes == "A2"
    assert feuille.auto_filter.ref is not None
