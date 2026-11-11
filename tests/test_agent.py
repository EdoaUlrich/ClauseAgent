"""Tests de la boucle agentique, client factice à l'appui."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ClientFactice, tour_final, tour_outil

from clauseagent.agent import Agent
from clauseagent.config import Configuration


def construire_agent(
    configuration: Configuration, scenario: list[SimpleNamespace]
) -> tuple[Agent, ClientFactice]:
    client = ClientFactice(scenario)
    return Agent(configuration=configuration, client=client), client


def test_enchainement_nominal(
    configuration: Configuration, scenario_complet, chemin_contrat: Path
):
    agent, _ = construire_agent(configuration, scenario_complet)
    analyse = agent.analyser(chemin_contrat)

    assert len(analyse.clauses) > 15
    assert len(analyse.elements) == 2
    assert analyse.risques
    assert analyse.synthese.startswith("Inventaire terminé")
    assert agent.chemin_export is not None
    assert agent.chemin_export.exists()


def test_le_journal_retrace_les_appels(
    configuration: Configuration, scenario_complet, chemin_contrat: Path
):
    etapes: list[str] = []
    client = ClientFactice(scenario_complet)
    agent = Agent(configuration=configuration, client=client, journaliser=etapes.append)
    agent.analyser(chemin_contrat)

    assert any(etape.startswith("lire_document") for etape in etapes)
    assert any(etape.startswith("exporter_excel") for etape in etapes)
    assert etapes == agent.journal


def test_aucune_valeur_reelle_ne_quitte_le_poste(
    configuration: Configuration, scenario_complet, chemin_contrat: Path
):
    """Le test central de la promesse de confidentialité.

    On inspecte tout ce qui a été transmis au client : invites, résultats
    d'outils et aperçus de document. Aucune des valeurs identifiantes du
    contrat ne doit y figurer.
    """
    agent, client = construire_agent(configuration, scenario_complet)
    agent.analyser(chemin_contrat)

    transmis = json.dumps(
        [
            {
                "messages": parametres["messages"],
                "system": parametres.get("system"),
            }
            for parametres in client.messages.appels_create
        ],
        default=str,
        ensure_ascii=False,
    )
    transmis += json.dumps(client.messages.appels_parse, default=str, ensure_ascii=False)

    for valeur in (
        "Atlas Énergie SAS",
        "Jean Dupont",
        "Claire Moreau",
        "jean.dupont@atlas-energie.fr",
        "812 345 678",
        "96 000 euros",
        "FR76 3000 6000 0112 3456 7890 189",
    ):
        assert valeur not in transmis, f"valeur transmise au modèle : {valeur}"


def test_l_echeance_est_reportee_sur_les_elements(
    configuration: Configuration, scenario_complet, chemin_contrat: Path
):
    agent, _ = construire_agent(configuration, scenario_complet)
    analyse = agent.analyser(chemin_contrat)

    datees = [element for element in analyse.elements if element.echeance_calculee]
    assert datees
    assert datees[0].base_calcul == "réception de la facture"


def test_erreur_d_outil_rendue_au_modele_sans_interrompre(
    configuration: Configuration, chemin_contrat: Path
):
    """Un appel invalide doit être corrigeable par le modèle au tour suivant."""
    scenario = [
        tour_outil("extraire_clause", {"clause_identifiant": "Article 1"}, "a"),
        tour_outil("lire_document", {"chemin": str(chemin_contrat)}, "b"),
        tour_final("Je reprends dans le bon ordre."),
    ]
    agent, client = construire_agent(configuration, scenario)
    agent.analyser(chemin_contrat)

    premier_retour = client.messages.appels_create[1]["messages"][-1]["content"][0]
    assert premier_retour["is_error"] is True
    assert "decouper_clauses" in premier_retour["content"]
    assert agent.document is not None


def test_clause_introuvable_liste_les_references(
    configuration: Configuration, chemin_contrat: Path
):
    scenario = [
        tour_outil("lire_document", {"chemin": str(chemin_contrat)}, "a"),
        tour_outil("decouper_clauses", {}, "b"),
        tour_outil("extraire_clause", {"clause_identifiant": "Article 99"}, "c"),
        tour_final("Référence inexistante."),
    ]
    agent, client = construire_agent(configuration, scenario)
    agent.analyser(chemin_contrat)

    retour = client.messages.appels_create[3]["messages"][-1]["content"][0]
    assert retour["is_error"] is True
    assert "introuvable" in retour["content"]


def test_tolerance_sur_la_forme_des_references(
    configuration: Configuration, chemin_contrat: Path
):
    """« art. 4.2 » doit désigner « Article 4.2 »."""
    scenario = [
        tour_outil("lire_document", {"chemin": str(chemin_contrat)}, "a"),
        tour_outil("decouper_clauses", {}, "b"),
        tour_outil("extraire_clause", {"clause_identifiant": "art. 4.2"}, "c"),
        tour_final("Fait."),
    ]
    agent, _ = construire_agent(configuration, scenario)
    analyse = agent.analyser(chemin_contrat)

    assert analyse.elements[0].clause_identifiant == "Article 4.2"


def test_le_nom_de_fichier_reste_dans_le_repertoire_de_sorties(
    configuration: Configuration, chemin_contrat: Path
):
    """Un chemin proposé par le modèle ne doit pas permettre d'écrire ailleurs."""
    scenario = [
        tour_outil("lire_document", {"chemin": str(chemin_contrat)}, "a"),
        tour_outil("decouper_clauses", {}, "b"),
        tour_outil("signaler_risque", {}, "c"),
        tour_outil("exporter_excel", {"nom_fichier": "../../ailleurs/evasion.xlsx"}, "d"),
        tour_final("Export réalisé."),
    ]
    agent, _ = construire_agent(configuration, scenario)
    agent.analyser(chemin_contrat)

    assert agent.chemin_export is not None
    assert agent.chemin_export.parent == configuration.repertoire_sorties
    assert agent.chemin_export.name == "evasion.xlsx"


def test_limite_d_iterations_respectee(configuration: Configuration, chemin_contrat: Path):
    configuration.max_iterations = 3
    boucle = [tour_outil("lire_document", {"chemin": str(chemin_contrat)}, "x")] * 10
    agent, client = construire_agent(configuration, boucle)
    agent.analyser(chemin_contrat)

    assert client.messages.tour == 3
    assert any("limite atteinte" in etape for etape in agent.journal)


def test_refus_du_modele_remonte(configuration: Configuration, chemin_contrat: Path):
    agent, _ = construire_agent(
        configuration, [SimpleNamespace(content=[], stop_reason="refusal", stop_details=None)]
    )

    with pytest.raises(RuntimeError, match="refusé"):
        agent.analyser(chemin_contrat)


def test_les_consignes_sont_mises_en_cache(
    configuration: Configuration, scenario_complet, chemin_contrat: Path
):
    agent, client = construire_agent(configuration, scenario_complet)
    agent.analyser(chemin_contrat)

    systeme = client.messages.appels_create[0]["system"]
    assert systeme[0]["cache_control"] == {"type": "ephemeral"}
