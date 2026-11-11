"""Tests du calcul des échéances."""

from __future__ import annotations

from datetime import date

import pytest

from clauseagent.outils.echeances import calculer_echeance

REFERENCE = date(2026, 2, 12)
EVENEMENTS = {
    "signature": date(2026, 2, 12),
    "prise_effet": date(2026, 3, 1),
    "facture": date(2026, 4, 15),
    "signalement": date(2026, 5, 4),
    "mise_en_demeure": date(2026, 7, 1),
}


@pytest.mark.parametrize(
    ("expression", "attendue"),
    [
        ("30 jours à compter de la réception de la facture", date(2026, 5, 15)),
        ("dans un délai de 4 heures après réception d'un signalement", date(2026, 5, 5)),
        ("2 jours ouvrés après le signalement", date(2026, 5, 6)),
        ("trois ans à compter de la prise d'effet", date(2029, 3, 1)),
        ("préavis de six mois", date(2026, 9, 1)),
        ("30 jours à compter de la réception de la mise en demeure", date(2026, 7, 31)),
        ("le 1er mars 2026", date(2026, 3, 1)),
        ("15/01/2027", date(2027, 1, 15)),
        ("au plus tard le 31 janvier de chaque année", date(2027, 1, 31)),
    ],
)
def test_conversion_en_date_reelle(expression: str, attendue: date):
    resultat = calculer_echeance(expression, date_reference=REFERENCE, evenements=EVENEMENTS)
    assert resultat.date_calculee == attendue


def test_le_libelle_le_plus_long_emporte():
    """« réception de la mise en demeure » n'est pas une réception de travaux."""
    resultat = calculer_echeance(
        "30 jours après la réception de la mise en demeure",
        date_reference=REFERENCE,
        evenements=EVENEMENTS,
    )
    assert resultat.base == "réception de la mise en demeure"


def test_delai_avant_une_echeance():
    resultat = calculer_echeance(
        "quatre mois avant l'échéance",
        date_reference=REFERENCE,
        evenements={"echeance": date(2029, 3, 1)},
    )
    assert resultat.sens == "avant"
    assert resultat.date_calculee == date(2028, 11, 1)


def test_evenement_de_depart_inconnu():
    """Une date manquante doit être signalée, jamais devinée."""
    resultat = calculer_echeance(
        "15 jours suivant chaque intervention préventive",
        date_reference=REFERENCE,
        evenements={},
    )

    assert resultat.date_calculee is None
    assert resultat.quantite == 15
    assert "intervention" in resultat.base
    assert resultat.avertissements


def test_jours_ouvres_sautent_le_week_end():
    resultat = calculer_echeance(
        "3 jours ouvrés après la signature",
        date_reference=date(2026, 2, 12),
        evenements={"signature": date(2026, 2, 12)},
    )
    # 12/02/2026 est un jeudi : 13 (ven), 16 (lun), 17 (mar).
    assert resultat.date_calculee == date(2026, 2, 17)
    assert resultat.jours_ouvres


def test_recurrence_detectee():
    resultat = calculer_echeance(
        "payable par trimestre à terme échu", date_reference=REFERENCE, evenements=EVENEMENTS
    )
    assert resultat.recurrence == "trimestriel"


def test_expression_non_exploitable():
    resultat = calculer_echeance("sans délai particulier", date_reference=REFERENCE)

    assert not resultat.resolue
    assert "Aucune durée" in resultat.commentaire


def test_expression_vide():
    assert calculer_echeance("").date_calculee is None
