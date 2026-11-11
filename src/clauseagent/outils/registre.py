"""Déclaration des outils exposés au modèle.

Les descriptions sont rédigées pour le modèle, pas pour le lecteur humain :
elles disent quand appeler l'outil, pas seulement ce qu'il fait. C'est ce qui
détermine la qualité de l'enchaînement choisi par l'agent.

Les outils ne renvoient jamais le contrat entier. L'état de l'analyse (texte
intégral, clauses, éléments extraits) reste dans le processus local ; le modèle
ne manipule que des références de clauses et des résumés. Le contexte reste
donc court même sur un contrat de cent pages, et les données sensibles ne sont
pas rediffusées à chaque tour.
"""

from __future__ import annotations

from typing import Any

OUTILS: list[dict[str, Any]] = [
    {
        "name": "lire_document",
        "description": (
            "Extrait le texte d'un contrat au format PDF, Word ou TXT. "
            "À appeler en premier, une seule fois, avec le chemin fourni par "
            "l'utilisateur. Retourne le format, la taille et le début du texte."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chemin": {
                    "type": "string",
                    "description": "Chemin du fichier à analyser.",
                }
            },
            "required": ["chemin"],
        },
    },
    {
        "name": "decouper_clauses",
        "description": (
            "Découpe le contrat déjà lu en articles et clauses numérotés. "
            "Retourne la liste des références de clauses avec leur intitulé et "
            "leur longueur. Ces références servent d'identifiant pour tous les "
            "autres outils."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "definir_evenement",
        "description": (
            "Enregistre la date d'un événement de référence du contrat (date de "
            "signature, prise d'effet, réception d'une facture...). À appeler "
            "dès qu'une date est repérée dans le texte, avant de calculer les "
            "échéances relatives : sans ces dates, un délai comme « 30 jours "
            "après la livraison » ne peut pas être converti en date réelle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nom": {
                    "type": "string",
                    "enum": [
                        "signature",
                        "prise_effet",
                        "livraison",
                        "facture",
                        "mise_en_demeure",
                        "signalement",
                        "intervention",
                        "echeance",
                    ],
                    "description": "Événement auquel la date se rattache.",
                },
                "date": {
                    "type": "string",
                    "description": "Date au format AAAA-MM-JJ.",
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Référence de la clause où la date figure, et extrait "
                        "correspondant."
                    ),
                },
            },
            "required": ["nom", "date"],
        },
    },
    {
        "name": "extraire_clause",
        "description": (
            "Analyse une clause et en extrait les obligations, droits et "
            "pénalités, chacun accompagné de la citation qui le justifie. "
            "À appeler sur chaque clause susceptible de contenir un engagement. "
            "Les clauses purement définitionnelles ou de forme (droit "
            "applicable, juridiction, intitulés) peuvent être ignorées."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clause_identifiant": {
                    "type": "string",
                    "description": (
                        "Référence exacte de la clause telle que retournée par "
                        "decouper_clauses, par exemple « Article 4.2 »."
                    ),
                }
            },
            "required": ["clause_identifiant"],
        },
    },
    {
        "name": "calculer_echeance",
        "description": (
            "Convertit un délai rédigé en langage naturel en date réelle, en "
            "s'appuyant sur les événements déjà enregistrés. À appeler pour "
            "chaque élément extrait qui porte une échéance. Si la date de "
            "l'événement de départ est inconnue, l'outil le signale au lieu de "
            "deviner."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "Délai tel qu'il est écrit au contrat, par exemple "
                        "« 30 jours à compter de la réception de la facture »."
                    ),
                },
                "clause_identifiant": {
                    "type": "string",
                    "description": (
                        "Clause concernée. La date calculée est alors reportée "
                        "sur les éléments correspondants du tableau de suivi."
                    ),
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "signaler_risque",
        "description": (
            "Repère les clauses sensibles (pénalités, résiliation, "
            "responsabilité, confidentialité, renouvellement tacite...) qui "
            "doivent être relues par un humain. À appeler une fois le découpage "
            "effectué. Retourne un signalement par clause concernée avec son "
            "niveau de gravité."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "exporter_excel",
        "description": (
            "Écrit le tableau de suivi au format xlsx : éléments extraits, "
            "clauses signalées, inventaire des clauses et synthèse. À appeler en "
            "dernier, une fois l'extraction terminée."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nom_fichier": {
                    "type": "string",
                    "description": (
                        "Nom du classeur à produire. Par défaut, le nom du "
                        "contrat suivi de « _suivi.xlsx »."
                    ),
                }
            },
        },
    },
]

NOMS_OUTILS: tuple[str, ...] = tuple(outil["name"] for outil in OUTILS)
