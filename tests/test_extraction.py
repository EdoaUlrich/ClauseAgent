"""Tests de l'extraction par le modèle et de la vérification des citations."""

from __future__ import annotations

from conftest import ClientFactice

from clauseagent.anonymisation import Anonymiseur
from clauseagent.config import Configuration
from clauseagent.models import Clause
from clauseagent.outils.extraction import extraire_clause, verifier_citation

CLAUSE = Clause(
    identifiant="Article 4.2",
    titre="Conditions de paiement",
    texte=(
        "Le Client règle les factures dans un délai de 30 jours à compter de la date "
        "de réception de la facture. La redevance annuelle s'élève à 96 000 euros hors "
        "taxes, payable par trimestre à terme échu."
    ),
)


def test_citation_exacte():
    assert verifier_citation(
        "Le Client règle les factures dans un délai de 30 jours", CLAUSE.texte
    )


def test_citation_tolerante_aux_variantes_typographiques():
    assert verifier_citation(
        "Le  Client règle\nles factures dans un délai de 30 jours", CLAUSE.texte
    )


def test_citation_reformulee_rejetee():
    assert not verifier_citation(
        "Le Client doit payer ses factures sous trente jours", CLAUSE.texte
    )


def test_citation_vide_rejetee():
    assert not verifier_citation("", CLAUSE.texte)


def test_extraction_restaure_les_valeurs_et_verifie_la_citation(configuration: Configuration):
    client = ClientFactice()
    anonymiseur = Anonymiseur(actif=True)

    extraction = extraire_clause(
        CLAUSE, client=client, configuration=configuration, anonymiseur=anonymiseur
    )

    element = extraction.elements[0]
    assert element.clause_identifiant == "Article 4.2"
    # La citation produite sur le texte masqué redevient vérifiable après
    # restauration : c'est tout l'intérêt d'une substitution bijective.
    assert element.citation_verifiee
    assert "96 000 euros" in CLAUSE.texte


def test_le_texte_envoye_au_modele_est_masque(configuration: Configuration):
    client = ClientFactice()
    extraire_clause(
        CLAUSE,
        client=client,
        configuration=configuration,
        anonymiseur=Anonymiseur(actif=True),
    )

    invite = client.messages.appels_parse[0]["messages"][0]["content"]
    assert "96 000 euros" not in invite
    assert "[MONTANT_1]" in invite


def test_le_schema_pydantic_est_transmis(configuration: Configuration):
    client = ClientFactice()
    extraire_clause(CLAUSE, client=client, configuration=configuration)

    parametres = client.messages.appels_parse[0]
    assert parametres["output_format"].__name__ == "ExtractionClause"
    assert parametres["model"] == "modele-de-test"
