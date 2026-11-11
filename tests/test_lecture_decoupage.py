"""Tests de la lecture des documents et du découpage en clauses."""

from __future__ import annotations

from pathlib import Path

import pytest

from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.lecture import lire_document


def test_lecture_d_un_fichier_texte(chemin_contrat: Path):
    document = lire_document(chemin_contrat)

    assert document.format == "txt"
    assert document.nombre_caracteres > 2000
    assert "PÉNALITÉS DE RETARD" in document.texte


def test_fichier_absent():
    with pytest.raises(FileNotFoundError):
        lire_document("contrat_qui_n_existe_pas.pdf")


def test_format_refuse(tmp_path: Path):
    fichier = tmp_path / "contrat.odt"
    fichier.write_text("contenu", encoding="utf-8")

    with pytest.raises(ValueError, match="Format non pris en charge"):
        lire_document(fichier)


def test_document_vide(tmp_path: Path):
    fichier = tmp_path / "vide.txt"
    fichier.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(ValueError, match="Aucun texte extrait"):
        lire_document(fichier)


def test_nettoyage_des_artefacts_de_mise_en_page(tmp_path: Path):
    fichier = tmp_path / "contrat.txt"
    fichier.write_text(
        "ARTICLE 1 - OBJET\n"
        "Le Prestataire assure la main-\ntenance des installations.\n"
        "3\n"
        "Page 4 / 12\n"
        "Fin de l'article.\n",
        encoding="utf-8",
    )

    texte = lire_document(fichier).texte

    assert "maintenance" in texte
    assert "Page 4 / 12" not in texte
    assert "\n3\n" not in texte


def test_decoupage_reconnait_les_articles(texte_contrat: str):
    clauses = decouper_clauses(texte_contrat)
    references = [clause.identifiant for clause in clauses]

    assert "Article 1" in references
    assert "Article 5.1" in references
    assert "Préambule" in references
    assert "En-tête du contrat" in references


def test_les_positions_pointent_vers_le_texte_source(texte_contrat: str):
    """Garantie de vérifiabilité : chaque clause est localisable à l'octet près."""
    for clause in decouper_clauses(texte_contrat):
        assert clause.texte in texte_contrat[clause.debut : clause.fin]


def test_les_identifiants_sont_uniques(texte_contrat: str):
    references = [clause.identifiant for clause in decouper_clauses(texte_contrat)]
    assert len(references) == len(set(references))


def test_identifiants_dupliques_suffixes():
    texte = (
        "ANNEXE 1 - Périmètre\n\nPremière annexe détaillant le périmètre couvert "
        "par le contrat de maintenance.\n\n"
        "ANNEXE 1 - Tarifs\n\nSeconde annexe reprenant par erreur la même "
        "numérotation que la précédente.\n"
    )
    references = [clause.identifiant for clause in decouper_clauses(texte)]

    assert references.count("Annexe 1") == 1
    assert "Annexe 1 (2)" in references


def test_repli_en_paragraphes_sans_numerotation():
    texte = (
        "Le vendeur livre les marchandises au plus tard le 15 mars 2026 à l'adresse "
        "indiquée par l'acheteur.\n\n"
        "L'acheteur règle le prix convenu dans les trente jours suivant la livraison "
        "des marchandises.\n"
    )
    clauses = decouper_clauses(texte)

    assert [clause.identifiant for clause in clauses] == ["Paragraphe 1", "Paragraphe 2"]


def test_texte_vide():
    assert decouper_clauses("") == []
