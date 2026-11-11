"""Tests de l'anonymisation réversible."""

from __future__ import annotations

from clauseagent.anonymisation import Anonymiseur

EXTRAIT = (
    "Atlas Énergie SAS, SIREN 812 345 678, représentée par M. Jean Dupont "
    "(jean.dupont@atlas-energie.fr, 01 44 55 66 77), domiciliée 12 rue de la Paix, "
    "versera 1 500 EUR par jour de retard sur le compte FR76 3000 6000 0112 3456 7890 189."
)


def test_les_valeurs_identifiantes_disparaissent():
    anonymiseur = Anonymiseur()
    masque = anonymiseur.anonymiser(EXTRAIT)

    for valeur in (
        "Atlas Énergie SAS",
        "812 345 678",
        "Jean Dupont",
        "jean.dupont@atlas-energie.fr",
        "01 44 55 66 77",
        "rue de la Paix",
        "1 500 EUR",
        "FR76 3000 6000 0112 3456 7890 189",
    ):
        assert valeur not in masque


def test_la_restauration_rend_le_texte_identique():
    anonymiseur = Anonymiseur()
    assert anonymiseur.restaurer(anonymiseur.anonymiser(EXTRAIT)) == EXTRAIT


def test_une_meme_valeur_recoit_toujours_le_meme_jeton():
    anonymiseur = Anonymiseur()
    masque = anonymiseur.anonymiser(
        "Atlas Énergie SAS facture Atlas Énergie SAS pour le compte de Nordis Infra SARL."
    )
    assert masque.count("[SOCIETE_1]") == 2
    assert "[SOCIETE_2]" in masque


def test_les_designations_fonctionnelles_sont_conservees():
    """L'agent doit pouvoir rattacher chaque obligation à son débiteur."""
    anonymiseur = Anonymiseur()
    masque = anonymiseur.anonymiser(
        "Le Prestataire s'engage envers le Client à intervenir sous 4 heures."
    )
    assert "Prestataire" in masque
    assert "Client" in masque
    assert "4 heures" in masque


def test_les_pourcentages_restent_lisibles():
    """Les taux servent au calcul des pénalités : les masquer serait contre-productif."""
    masque = Anonymiseur().anonymiser("Intérêts de retard au taux de 10 % l'an.")
    assert "10 %" in masque


def test_le_mode_inactif_ne_modifie_rien():
    anonymiseur = Anonymiseur(actif=False)
    assert anonymiseur.anonymiser(EXTRAIT) == EXTRAIT
    assert anonymiseur.restaurer(EXTRAIT) == EXTRAIT


def test_le_resume_compte_sans_divulguer():
    anonymiseur = Anonymiseur()
    anonymiseur.anonymiser(EXTRAIT)
    resume = anonymiseur.resume()

    assert resume["SOCIETE"] == 1
    assert resume["PERSONNE"] == 1
    assert all(isinstance(valeur, int) for valeur in resume.values())
