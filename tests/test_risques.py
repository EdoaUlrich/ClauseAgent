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


def categories(clauses: list[Clause]) -> set[CategorieRisque]:
    return {risque.categorie for risque in signaler_risque(clauses)}


def test_le_lexique_francais_ne_declenche_pas_sur_de_l_anglais():
    """« amended » n'est pas « amende », « assurances » n'est pas « assurance »."""
    anglais = clause(
        "Section 12",
        "This Agreement may not be amended except by an instrument in writing. "
        "Each party shall execute such further assurances and representations "
        "and assurances as may reasonably be required.",
    )
    trouvees = categories([anglais])

    assert CategorieRisque.PENALITE not in trouvees
    assert CategorieRisque.ASSURANCE not in trouvees


def test_une_mention_de_passage_ne_suffit_pas():
    """Une expression ordinaire, tardive et isolée, ne caractérise pas la clause."""
    remplissage = "The parties acknowledge the matters set out in this schedule. " * 10
    tardive = clause("Section 9", f"{remplissage} Either party may terminate.")
    precoce = clause("Section 9", f"Either party may terminate. {remplissage}")

    assert CategorieRisque.RESILIATION not in categories([tardive])
    assert CategorieRisque.RESILIATION in categories([precoce])


def test_une_expression_decisive_suffit_ou_qu_elle_soit():
    remplissage = "The parties acknowledge the matters set out in this schedule. " * 10
    tardive = clause(
        "Section 9", f"{remplissage} The Supplier shall pay liquidated damages."
    )

    assert CategorieRisque.PENALITE in categories([tardive])


def test_clause_de_forme_courte_ecartee():
    definitions = clause(
        "Section 1",
        "Definitions. In this Agreement, Intellectual Property Rights means "
        "patents, copyrights and trade secrets.",
        titre="Definitions",
    )

    assert categories([definitions]) == set()


def test_clause_de_forme_longue_reste_analysee():
    """Un bloc « Definitions » démesuré contient souvent de vraies stipulations."""
    corps = (
        "Definitions and interpretation of the present agreement. " * 40
        + "The Supplier shall maintain insurance coverage of two million euros."
    )
    definitions = clause("Section 1", corps, titre="Definitions")

    assert CategorieRisque.ASSURANCE in categories([definitions])


def test_resiliation_sans_motif_reconnue_par_la_tournure():
    """CUAD annote ces clauses alors qu'elles ne disent jamais « for convenience »."""
    sans_motif = clause(
        "Section 8",
        "Either party may terminate this Agreement upon sixty (60) days' prior "
        "written notice to the other party.",
    )

    assert CategorieRisque.RESILIATION_CONVENANCE in categories([sans_motif])


def test_resiliation_pour_faute_non_confondue():
    pour_faute = clause(
        "Section 8",
        "Either party may terminate this Agreement for cause in the event of a "
        "material breach that remains uncured after written notice.",
    )
    trouvees = categories([pour_faute])

    assert CategorieRisque.RESILIATION in trouvees
    assert CategorieRisque.RESILIATION_CONVENANCE not in trouvees


def test_plafond_et_garantie_sont_distingues():
    plafond = clause(
        "Section 10",
        "The aggregate liability of the Supplier shall not exceed the fees paid "
        "during the preceding twelve months.",
    )
    garantie = clause(
        "Section 11",
        "The Supplier shall indemnify and hold harmless the Customer against any "
        "third party claim arising from the services.",
    )

    assert CategorieRisque.RESPONSABILITE in categories([plafond])
    assert CategorieRisque.INDEMNISATION in categories([garantie])
    assert CategorieRisque.RESPONSABILITE not in categories([garantie])


def test_le_reglage_sur_cuad_ne_degrade_pas_le_francais(texte_contrat: str):
    """Garde-fou : le lexique a été réglé sur un corpus anglais."""
    trouvees = categories(decouper_clauses(texte_contrat))

    assert {
        CategorieRisque.PENALITE,
        CategorieRisque.RESILIATION,
        CategorieRisque.ASSURANCE,
        CategorieRisque.RENOUVELLEMENT_TACITE,
        CategorieRisque.CONFIDENTIALITE,
    } <= trouvees


def test_le_seuil_arbitre_entre_precision_et_rappel():
    remplissage = "The parties acknowledge the matters set out in this schedule. " * 10
    tardive = [clause("Section 9", f"{remplissage} Either party may terminate.")]

    assert signaler_risque(tardive, seuil=4) == []
    assert signaler_risque(tardive, seuil=2) != []
