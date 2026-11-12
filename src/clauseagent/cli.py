"""Interface en ligne de commande de ClauseAgent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clauseagent import __version__
from clauseagent.config import EFFORTS_VALIDES, Configuration
from clauseagent.evaluation.executer import ECHANTILLONS
from clauseagent.models import AnalyseContrat, Gravite, TypeElement
from clauseagent.outils.risques import SEUIL_DEFAUT


def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="clauseagent",
        description="Extrait les obligations, échéances et pénalités d'un contrat.",
    )
    analyseur.add_argument("--version", action="version", version=f"ClauseAgent {__version__}")
    sous_commandes = analyseur.add_subparsers(dest="commande", required=True)

    analyser = sous_commandes.add_parser(
        "analyser", help="analyse complète d'un contrat par l'agent"
    )
    analyser.add_argument("contrat", help="chemin du contrat (.pdf, .docx, .txt)")
    analyser.add_argument("--sortie", help="nom du classeur de suivi à produire")
    analyser.add_argument("--consigne", help="demande particulière adressée à l'agent")
    analyser.add_argument("--modele", help="identifiant du modèle à utiliser")
    analyser.add_argument("--effort", choices=EFFORTS_VALIDES, help="profondeur de raisonnement")
    analyser.add_argument(
        "--sans-anonymisation",
        action="store_true",
        help="désactive le masquage des données avant envoi au modèle",
    )
    analyser.add_argument(
        "--silencieux", action="store_true", help="n'affiche pas le journal des outils"
    )

    inspecter = sous_commandes.add_parser(
        "inspecter",
        help="découpage, risques et export sans appel au modèle (aucune clé requise)",
    )
    inspecter.add_argument("contrat", help="chemin du contrat")
    inspecter.add_argument("--sortie", help="nom du classeur de suivi à produire")

    evaluer = sous_commandes.add_parser(
        "evaluer", help="mesure la précision et le rappel sur le jeu CUAD"
    )
    evaluer.add_argument("--jeu", required=True, help="chemin du fichier CUAD_v1.json")
    evaluer.add_argument(
        "--contrats", type=int, help="nombre de contrats à évaluer (tous par défaut)"
    )
    evaluer.add_argument(
        "--echantillon",
        choices=ECHANTILLONS,
        default="validation",
        help="moitié du jeu à utiliser ; « validation » n'a servi à aucun réglage",
    )
    evaluer.add_argument(
        "--seuil", type=int, default=SEUIL_DEFAUT, help="score minimal de signalement"
    )
    evaluer.add_argument("--rapport", help="chemin du rapport JSON à écrire")
    evaluer.add_argument(
        "--graine", type=int, default=0, help="graine de tirage des contrats"
    )

    sous_commandes.add_parser("interface", help="lance l'interface graphique")

    return analyseur


def main(argv: list[str] | None = None) -> int:
    arguments = construire_analyseur().parse_args(argv)

    try:
        if arguments.commande == "analyser":
            return _commande_analyser(arguments)
        if arguments.commande == "inspecter":
            return _commande_inspecter(arguments)
        if arguments.commande == "evaluer":
            return _commande_evaluer(arguments)
        if arguments.commande == "interface":
            return _commande_interface()
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130
    except Exception as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    return 0


def _commande_analyser(arguments: argparse.Namespace) -> int:
    from clauseagent.agent import Agent

    configuration = Configuration.depuis_environnement()
    if arguments.modele:
        configuration.modele = arguments.modele
    if arguments.effort:
        configuration.effort = arguments.effort
    if arguments.sans_anonymisation:
        configuration.anonymisation = False
        print(
            "Attention : anonymisation désactivée, le contrat sera transmis en clair.",
            file=sys.stderr,
        )

    agent = Agent(
        configuration=configuration,
        journaliser=None if arguments.silencieux else _afficher_etape,
    )
    analyse = agent.analyser(arguments.contrat, consigne=arguments.consigne)

    if arguments.sortie and agent.chemin_export is None:
        from clauseagent.outils.export import exporter_excel

        agent.chemin_export = exporter_excel(
            analyse, configuration.repertoire_sorties / Path(arguments.sortie).name
        )

    _afficher_rapport(analyse, agent.chemin_export)
    return 0


def _commande_inspecter(arguments: argparse.Namespace) -> int:
    """Chaîne déterministe : utile pour vérifier l'outillage sans clé d'API."""
    from clauseagent.outils.decoupage import decouper_clauses
    from clauseagent.outils.export import exporter_excel
    from clauseagent.outils.lecture import lire_document
    from clauseagent.outils.risques import signaler_risque

    configuration = Configuration.depuis_environnement()
    document = lire_document(arguments.contrat)
    clauses = decouper_clauses(document.texte)
    risques = signaler_risque(clauses)

    analyse = AnalyseContrat(
        source=document.chemin,
        nombre_caracteres=document.nombre_caracteres,
        clauses=clauses,
        risques=risques,
        synthese="Inspection sans appel au modèle : découpage et signalement seuls.",
        anonymisation_active=configuration.anonymisation,
        journal=["lire_document", "decouper_clauses", "signaler_risque"],
    )

    nom = (
        Path(arguments.sortie).name
        if arguments.sortie
        else f"{Path(document.chemin).stem}_inspection.xlsx"
    )
    chemin = exporter_excel(analyse, configuration.repertoire_sorties / nom)

    print(f"{len(clauses)} clauses découpées")
    for clause in clauses:
        intitule = f" — {clause.titre}" if clause.titre else ""
        print(f"  {clause.identifiant}{intitule} ({len(clause.texte)} caractères)")

    _afficher_risques(analyse)
    print(f"\nClasseur écrit : {chemin}")
    return 0


def _commande_evaluer(arguments: argparse.Namespace) -> int:
    from clauseagent.evaluation.executer import evaluer_sur_cuad

    rapport = evaluer_sur_cuad(
        chemin_jeu=arguments.jeu,
        nombre_contrats=arguments.contrats,
        chemin_rapport=arguments.rapport,
        graine=arguments.graine,
        echantillon=arguments.echantillon,
        seuil=arguments.seuil,
    )
    print(rapport.rendu_texte())
    return 0


def _commande_interface() -> int:
    try:
        from clauseagent.interface.application import lancer
    except ImportError as erreur:
        print(
            "L'interface nécessite PySide6 : pip install PySide6",
            file=sys.stderr,
        )
        raise SystemExit(1) from erreur
    return lancer()


def _afficher_etape(message: str) -> None:
    print(f"  · {message}", file=sys.stderr)


def _afficher_rapport(analyse: AnalyseContrat, export: Path | None) -> None:
    print()
    print(f"Contrat          : {Path(analyse.source).name}")
    print(f"Clauses          : {len(analyse.clauses)}")
    print(f"Éléments extraits: {len(analyse.elements)}")
    print(f"  obligations    : {len(analyse.elements_par_type(TypeElement.OBLIGATION))}")
    print(f"  droits         : {len(analyse.elements_par_type(TypeElement.DROIT))}")
    print(f"  pénalités      : {len(analyse.elements_par_type(TypeElement.PENALITE))}")
    print(f"Citations vérifiées : {analyse.taux_citations_verifiees:.0%}")

    echeances = sorted(
        (e for e in analyse.elements if e.echeance_calculee),
        key=lambda element: element.echeance_calculee,
    )
    if echeances:
        print("\nProchaines échéances :")
        for element in echeances[:8]:
            print(
                f"  {element.echeance_calculee:%d/%m/%Y}  "
                f"[{element.clause_identifiant}] {element.description[:70]}"
            )

    _afficher_risques(analyse)

    if analyse.synthese:
        print("\nSynthèse de l'agent :")
        print(analyse.synthese)

    if export:
        print(f"\nClasseur écrit : {export}")


def _afficher_risques(analyse: AnalyseContrat) -> None:
    graves = [risque for risque in analyse.risques if risque.gravite is Gravite.ELEVEE]
    if not analyse.risques:
        return
    print(f"\nClauses signalées : {len(analyse.risques)} dont {len(graves)} à gravité élevée")
    for risque in analyse.risques[:10]:
        print(
            f"  [{risque.gravite.value:<7}] {risque.clause_identifiant:<14} "
            f"{risque.justification}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
