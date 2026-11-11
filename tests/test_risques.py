"""Tests du signalement des clauses sensibles."""

from __future__ import annotations

from clauseagent.models import CategorieRisque, Clause, Gravite
from clauseagent.outils.decoupage import decouper_clauses
from clauseagent.outils.risques import signaler_risque


def clause(identifiant: str, texte: str, titre: str = "") -> Clause:
    return Clause(identifiant=identifiant, titre=titre, texte=texte)


def test_detection_des_categories(texte_contrat: str):
    risques = signaler_risque(decouper_clauses(texte_contrat))
    categories = {risque.categorie for risque in risques}

    assert CategorieRisque.PENALITE in categories
    assert CategorieRisque.RESILIATION in categories
    assert CategorieRisque.RESPONSABILITE in categories
    assert CategorieRisque.RENOUVELLEMENT_TACITE in categories


def test_la_forme_sociale_n_est_pas_une_clause_de_responsabilite():
    """« société à responsabilité limitée » désigne une forme juridique."""
    risques = signaler_risque(
        [
            clause(
                "En-tête du contrat",
                "Nordis Infra SARL, société à responsabilité limitée au capital de "
                "50 000 euros, immatriculée au RCS de Lille.",
            )
        ]
    )
    assert all(risque.categorie is not CategorieRisque.RESPONSABILITE for risque in risques)


def test_les_formulations_aggravantes_elevent_la_gravite():
    sans = signaler_risque([clause("Article 9", "Un cas de force majeure suspend le contrat.")])
    avec = signaler_risque(
        [
            clause(
                "Article 9",
                "Un cas de force majeure suspend le contrat de plein droit et sans préavis.",
            )
        ]
    )

    assert sans[0].gravite is Gravite.FAIBLE
    assert avec[0].gravite is Gravite.MOYENNE
    assert "effet automatique" in avec[0].justification


def test_la_citation_provient_du_texte_source():
    texte = (
        "Le contrat est renouvelé tacitement par périodes de douze mois. "
        "Toute dénonciation est notifiée par lettre recommandée."
    )
    risques = signaler_risque([clause("Article 2", texte)])

    assert risques[0].citation
    assert risques[0].citation in texte


def test_tri_par_gravite_decroissante(texte_contrat: str):
    risques = signaler_risque(decouper_clauses(texte_contrat))
    ordre = {Gravite.ELEVEE: 0, Gravite.MOYENNE: 1, Gravite.FAIBLE: 2}
    rangs = [ordre[risque.gravite] for risque in risques]

    assert rangs == sorted(rangs)


def test_clause_anodine_non_signalee():
    anodine = clause("Article 10", "Le présent contrat est rédigé en français.")
    assert signaler_risque([anodine]) == []
