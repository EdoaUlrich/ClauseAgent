"""Fenêtre principale de ClauseAgent.

L'interface est pensée pour le poste de travail d'un gestionnaire de contrats :
on ouvre un fichier, on lance l'analyse, on suit l'avancement, puis on exporte.
Deux partis pris :

* **La traçabilité est accessible en un geste.** Un double-clic sur n'importe
  quelle ligne affiche la citation d'origine et son état de vérification. Un
  tableau d'obligations sans retour au texte ne serait pas exploitable.
* **L'analyse sans modèle reste possible.** Le bouton « Inspecter » exécute la
  chaîne déterministe seule : utile pour vérifier un découpage, ou pour
  travailler sur un document que l'on ne veut transmettre à aucun service
  distant.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from clauseagent.config import EFFORTS_VALIDES, Configuration
from clauseagent.interface.travailleur import Travailleur
from clauseagent.models import AnalyseContrat, Gravite, TypeElement

FILTRE_FICHIERS = "Contrats (*.pdf *.docx *.txt *.md);;Tous les fichiers (*)"

_LIBELLES_TYPE = {
    TypeElement.OBLIGATION: "Obligation",
    TypeElement.DROIT: "Droit",
    TypeElement.PENALITE: "Pénalité",
    TypeElement.AUTRE: "Autre",
}

_COULEURS_GRAVITE = {
    Gravite.ELEVEE: QColor(248, 203, 173),
    Gravite.MOYENNE: QColor(255, 230, 153),
    Gravite.FAIBLE: QColor(226, 239, 218),
}


class FenetrePrincipale(QMainWindow):
    """Fenêtre unique : paramètres, résultats et journal."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ClauseAgent — extraction des obligations contractuelles")
        self.resize(1180, 760)

        self.configuration = Configuration.depuis_environnement()
        self.analyse: AnalyseContrat | None = None
        self.chemin_export: Path | None = None
        self._fil: QThread | None = None
        self._travailleur: Travailleur | None = None

        central = QWidget()
        disposition = QVBoxLayout(central)
        disposition.addWidget(self._construire_parametres())
        disposition.addWidget(self._construire_resultats(), stretch=1)
        disposition.addLayout(self._construire_barre_etat())
        self.setCentralWidget(central)

        self._rafraichir_boutons()

    # ------------------------------------------------------------ composition

    def _construire_parametres(self) -> QGroupBox:
        groupe = QGroupBox("Contrat à analyser")
        formulaire = QFormLayout(groupe)

        self.champ_fichier = QLineEdit()
        self.champ_fichier.setPlaceholderText("Aucun fichier sélectionné")
        self.champ_fichier.textChanged.connect(self._rafraichir_boutons)
        bouton_parcourir = QPushButton("Parcourir…")
        bouton_parcourir.clicked.connect(self._choisir_fichier)

        ligne_fichier = QHBoxLayout()
        ligne_fichier.addWidget(self.champ_fichier, stretch=1)
        ligne_fichier.addWidget(bouton_parcourir)
        formulaire.addRow("Fichier", ligne_fichier)

        self.champ_consigne = QLineEdit()
        self.champ_consigne.setPlaceholderText(
            "Facultatif : par exemple « concentre-toi sur les obligations du prestataire »"
        )
        formulaire.addRow("Consigne", self.champ_consigne)

        self.champ_effort = QComboBox()
        self.champ_effort.addItems(EFFORTS_VALIDES)
        self.champ_effort.setCurrentText(self.configuration.effort)

        self.champ_anonymisation = QCheckBox(
            "Anonymiser noms, montants et coordonnées avant envoi au modèle"
        )
        self.champ_anonymisation.setChecked(self.configuration.anonymisation)

        options = QVBoxLayout()
        options.addWidget(self.champ_anonymisation)
        formulaire.addRow("Profondeur", self.champ_effort)
        formulaire.addRow("Confidentialité", options)

        self.bouton_analyser = QPushButton("Analyser avec l'agent")
        self.bouton_analyser.clicked.connect(lambda: self._lancer(avec_modele=True))
        self.bouton_inspecter = QPushButton("Inspecter sans modèle")
        self.bouton_inspecter.clicked.connect(lambda: self._lancer(avec_modele=False))
        self.bouton_exporter = QPushButton("Exporter en Excel")
        self.bouton_exporter.clicked.connect(self._exporter)

        actions = QHBoxLayout()
        actions.addWidget(self.bouton_analyser)
        actions.addWidget(self.bouton_inspecter)
        actions.addStretch(1)
        actions.addWidget(self.bouton_exporter)
        formulaire.addRow(actions)

        return groupe

    def _construire_resultats(self) -> QTabWidget:
        self.onglets = QTabWidget()

        self.table_suivi = self._table(
            [
                "Clause",
                "Type",
                "Partie concernée",
                "Description",
                "Échéance au contrat",
                "Date calculée",
                "Citation",
            ]
        )
        self.table_risques = self._table(["Clause", "Catégorie", "Gravité", "Motif"])
        self.table_clauses = self._table(["Référence", "Intitulé", "Taille", "Extrait"])

        self.zone_journal = QPlainTextEdit()
        self.zone_journal.setReadOnly(True)

        self.zone_synthese = QPlainTextEdit()
        self.zone_synthese.setReadOnly(True)

        self.onglets.addTab(self.table_suivi, "Suivi")
        self.onglets.addTab(self.table_risques, "Clauses signalées")
        self.onglets.addTab(self.table_clauses, "Clauses")
        self.onglets.addTab(self.zone_synthese, "Synthèse")
        self.onglets.addTab(self.zone_journal, "Journal")
        return self.onglets

    def _construire_barre_etat(self) -> QHBoxLayout:
        self.etiquette_etat = QLabel("Prêt.")
        self.barre_progression = QProgressBar()
        self.barre_progression.setRange(0, 1)
        self.barre_progression.setValue(0)
        self.barre_progression.setMaximumWidth(220)

        ligne = QHBoxLayout()
        ligne.addWidget(self.etiquette_etat, stretch=1)
        ligne.addWidget(self.barre_progression)
        return ligne

    def _table(self, entetes: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(entetes))
        table.setHorizontalHeaderLabels(entetes)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            len(entetes) - 1, QHeaderView.ResizeMode.Stretch
        )
        table.doubleClicked.connect(lambda index: self._afficher_detail(table, index.row()))
        return table

    # ---------------------------------------------------------------- actions

    def _choisir_fichier(self) -> None:
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Choisir un contrat", "", FILTRE_FICHIERS
        )
        if chemin:
            self.champ_fichier.setText(chemin)

    def _lancer(self, avec_modele: bool) -> None:
        chemin = Path(self.champ_fichier.text().strip())
        if not chemin.is_file():
            QMessageBox.warning(self, "Fichier introuvable", f"Chemin invalide : {chemin}")
            return

        self.configuration.effort = self.champ_effort.currentText()
        self.configuration.anonymisation = self.champ_anonymisation.isChecked()

        if avec_modele and not self.configuration.cle_api:
            QMessageBox.critical(
                self,
                "Clé d'API manquante",
                "Renseignez ANTHROPIC_API_KEY dans l'environnement ou un fichier .env.\n"
                "Le bouton « Inspecter sans modèle » reste utilisable sans clé.",
            )
            return

        if avec_modele and not self.configuration.anonymisation:
            reponse = QMessageBox.question(
                self,
                "Anonymisation désactivée",
                "Le contrat sera transmis au modèle en clair, noms et montants compris.\n"
                "Confirmer l'envoi ?",
            )
            if reponse is not QMessageBox.StandardButton.Yes:
                return

        self._reinitialiser()
        self._basculer_en_cours(True)

        self._travailleur = Travailleur(
            chemin=chemin,
            configuration=self.configuration,
            consigne=self.champ_consigne.text().strip() or None,
            avec_modele=avec_modele,
        )
        self._fil = QThread(self)
        self._travailleur.moveToThread(self._fil)
        self._fil.started.connect(self._travailleur.executer)
        self._travailleur.etape.connect(self._journaliser)
        self._travailleur.termine.connect(self._afficher_resultat)
        self._travailleur.echoue.connect(self._afficher_erreur)
        self._fil.start()

    def _exporter(self) -> None:
        if self.analyse is None:
            return

        defaut = str(
            self.configuration.repertoire_sorties
            / f"{Path(self.analyse.source).stem}_suivi.xlsx"
        )
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le tableau de suivi", defaut, "Classeur Excel (*.xlsx)"
        )
        if not chemin:
            return

        from clauseagent.outils.export import exporter_excel

        try:
            ecrit = exporter_excel(self.analyse, chemin)
        except Exception as erreur:
            QMessageBox.critical(self, "Export impossible", str(erreur))
            return

        self.chemin_export = ecrit
        self.etiquette_etat.setText(f"Classeur écrit : {ecrit}")

    # -------------------------------------------------------------- affichage

    def _journaliser(self, message: str) -> None:
        self.zone_journal.appendPlainText(message)
        self.etiquette_etat.setText(message)

    def _afficher_resultat(self, analyse: AnalyseContrat, export: Path | None) -> None:
        self.analyse = analyse
        self.chemin_export = export
        self._arreter_fil()
        self._basculer_en_cours(False)

        self._remplir_suivi(analyse)
        self._remplir_risques(analyse)
        self._remplir_clauses(analyse)

        verifiees = analyse.taux_citations_verifiees
        entete = (
            f"{len(analyse.clauses)} clauses, {len(analyse.elements)} éléments extraits, "
            f"{len(analyse.risques)} clauses signalées.\n"
            f"Citations vérifiées : {verifiees:.0%}.\n"
        )
        if export:
            entete += f"Classeur écrit : {export}\n"
        self.zone_synthese.setPlainText(entete + "\n" + analyse.synthese)

        self.etiquette_etat.setText("Analyse terminée.")
        self._rafraichir_boutons()

    def _afficher_erreur(self, message: str) -> None:
        self._arreter_fil()
        self._basculer_en_cours(False)
        self._journaliser(f"Échec : {message}")
        QMessageBox.critical(self, "Analyse interrompue", message)

    def _remplir_suivi(self, analyse: AnalyseContrat) -> None:
        self.table_suivi.setRowCount(len(analyse.elements))
        for ligne, element in enumerate(analyse.elements):
            valeurs = [
                element.clause_identifiant,
                _LIBELLES_TYPE[element.type],
                element.partie_concernee,
                element.description,
                element.echeance_textuelle or "",
                element.echeance_calculee.strftime("%d/%m/%Y")
                if element.echeance_calculee
                else "",
                element.citation,
            ]
            for colonne, valeur in enumerate(valeurs):
                cellule = QTableWidgetItem(valeur)
                if not element.citation_verifiee:
                    cellule.setToolTip("Citation non retrouvée dans la clause : à contrôler.")
                    cellule.setForeground(QColor(150, 40, 40))
                self.table_suivi.setItem(ligne, colonne, cellule)
        self.table_suivi.resizeColumnsToContents()

    def _remplir_risques(self, analyse: AnalyseContrat) -> None:
        self.table_risques.setRowCount(len(analyse.risques))
        for ligne, risque in enumerate(analyse.risques):
            valeurs = [
                risque.clause_identifiant,
                risque.categorie.value.replace("_", " ").capitalize(),
                risque.gravite.value.capitalize(),
                risque.justification,
            ]
            for colonne, valeur in enumerate(valeurs):
                cellule = QTableWidgetItem(valeur)
                if colonne == 2:
                    cellule.setBackground(_COULEURS_GRAVITE[risque.gravite])
                cellule.setToolTip(risque.citation)
                self.table_risques.setItem(ligne, colonne, cellule)
        self.table_risques.resizeColumnsToContents()

    def _remplir_clauses(self, analyse: AnalyseContrat) -> None:
        self.table_clauses.setRowCount(len(analyse.clauses))
        for ligne, clause in enumerate(analyse.clauses):
            valeurs = [
                clause.identifiant,
                clause.titre,
                f"{len(clause.texte)} caractères",
                clause.apercu,
            ]
            for colonne, valeur in enumerate(valeurs):
                self.table_clauses.setItem(ligne, colonne, QTableWidgetItem(valeur))
        self.table_clauses.resizeColumnsToContents()

    def _afficher_detail(self, table: QTableWidget, ligne: int) -> None:
        """Ramène l'utilisateur au texte du contrat depuis n'importe quelle ligne."""
        if self.analyse is None or ligne < 0:
            return

        if table is self.table_suivi and ligne < len(self.analyse.elements):
            element = self.analyse.elements[ligne]
            etat = "vérifiée" if element.citation_verifiee else "NON vérifiée — à contrôler"
            detail = (
                f"Clause : {element.clause_identifiant}\n"
                f"Type : {_LIBELLES_TYPE[element.type]}\n"
                f"Partie : {element.partie_concernee}\n\n"
                f"{element.description}\n\n"
                f"Échéance au contrat : {element.echeance_textuelle or 'aucune'}\n"
                f"Base de calcul : {element.base_calcul or 'non applicable'}\n\n"
                f"Citation ({etat}) :\n« {element.citation} »"
            )
        elif table is self.table_risques and ligne < len(self.analyse.risques):
            risque = self.analyse.risques[ligne]
            detail = (
                f"Clause : {risque.clause_identifiant}\n"
                f"Gravité : {risque.gravite.value}\n\n"
                f"{risque.justification}\n\nExtrait :\n« {risque.citation} »"
            )
        elif table is self.table_clauses and ligne < len(self.analyse.clauses):
            clause = self.analyse.clauses[ligne]
            detail = f"{clause.identifiant} — {clause.titre}\n\n{clause.texte}"
        else:
            return

        boite = QMessageBox(self)
        boite.setWindowTitle("Retour au texte du contrat")
        boite.setText(detail)
        boite.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        boite.exec()

    # --------------------------------------------------------------- internes

    def _reinitialiser(self) -> None:
        self.analyse = None
        self.chemin_export = None
        for table in (self.table_suivi, self.table_risques, self.table_clauses):
            table.setRowCount(0)
        self.zone_journal.clear()
        self.zone_synthese.clear()

    def _basculer_en_cours(self, en_cours: bool) -> None:
        self.barre_progression.setRange(0, 0 if en_cours else 1)
        self.barre_progression.setValue(0 if en_cours else 1)
        self.bouton_analyser.setEnabled(not en_cours)
        self.bouton_inspecter.setEnabled(not en_cours)
        self.bouton_exporter.setEnabled(not en_cours and self.analyse is not None)

    def _rafraichir_boutons(self) -> None:
        possible = bool(self.champ_fichier.text().strip())
        self.bouton_analyser.setEnabled(possible)
        self.bouton_inspecter.setEnabled(possible)
        self.bouton_exporter.setEnabled(self.analyse is not None)

    def _arreter_fil(self) -> None:
        if self._fil is not None:
            self._fil.quit()
            self._fil.wait()
            self._fil = None
        self._travailleur = None

    def closeEvent(self, event) -> None:  # noqa: N802 - signature imposée par Qt
        self._arreter_fil()
        super().closeEvent(event)


def lancer() -> int:
    """Point d'entrée de l'interface graphique."""
    application = QApplication(sys.argv)
    application.setApplicationName("ClauseAgent")
    fenetre = FenetrePrincipale()
    fenetre.show()
    return application.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(lancer())
