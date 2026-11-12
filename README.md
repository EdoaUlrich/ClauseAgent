# ClauseAgent

Agent IA qui lit un contrat et en extrait les **obligations**, les **droits**,
les **échéances** et les **pénalités**, puis produit un tableau de suivi
exploitable par un gestionnaire de contrats.

L'agent n'exécute pas un script figé : on lui donne un contrat et un jeu
d'outils, et il décide lui-même lesquels appeler et dans quel ordre.

```
$ clauseagent analyser contrats/maintenance.pdf
  · lire_document(chemin=contrats/maintenance.pdf)
  · decouper_clauses()
  · definir_evenement(nom=prise_effet, date=2026-03-01)
  · extraire_clause(clause_identifiant=Article 3.1)
  · extraire_clause(clause_identifiant=Article 4.2)
  · calculer_echeance(expression=30 jours à compter de la réception de la facture)
  · signaler_risque()
  · exporter_excel(nom_fichier=maintenance_suivi.xlsx)
```

## Les outils

| Outil               | Rôle                                                                              |
| ------------------- | --------------------------------------------------------------------------------- |
| `lire_document`     | Extrait le texte d'un PDF, d'un Word ou d'un TXT (pypdf, python-docx)              |
| `decouper_clauses`  | Sépare le contrat en articles et clauses numérotés, positions conservées            |
| `extraire_clause`   | Demande au modèle une sortie structurée : type, partie, échéance, citation exacte   |
| `calculer_echeance` | Transforme « 30 jours après la livraison » en date réelle                           |
| `signaler_risque`   | Repère les clauses sensibles (pénalités, résiliation, responsabilité…)              |
| `exporter_excel`    | Produit le tableau de suivi (openpyxl)                                              |
| `definir_evenement` | Mémorise une date de référence du contrat, nécessaire aux échéances relatives       |

Un seul de ces outils appelle le modèle : `extraire_clause`. Tous les autres
sont déterministes, donc gratuits, reproductibles et testables.

## Démarrage

```bash
python -m pip install -e ".[interface,dev]"
cp .env.example .env        # puis renseigner ANTHROPIC_API_KEY
```

```bash
# Analyse complète par l'agent
clauseagent analyser exemples/contrat_maintenance.txt

# Découpage et signalement seuls : aucune clé d'API requise
clauseagent inspecter exemples/contrat_maintenance.txt

# Interface graphique
clauseagent interface

# Évaluation sur CUAD (voir donnees/README.md)
clauseagent evaluer --jeu donnees/cuad/CUAD_v1.json
```

La configuration se fait par variables d'environnement (`.env.example` les
documente) : modèle, niveau d'effort, anonymisation, nombre maximal
d'itérations, répertoire de sorties.

## L'interface

Fenêtre PySide6 : sélection du contrat, suivi de l'avancement pendant
l'analyse, puis quatre vues — suivi, clauses signalées, inventaire des clauses,
synthèse — et le journal des outils appelés. **Un double-clic sur n'importe
quelle ligne affiche la citation d'origine** et son état de vérification : un
tableau d'obligations sans retour au texte ne serait pas exploitable par un
juriste.

L'analyse tourne dans un fil séparé ; la fenêtre reste utilisable pendant les
appels réseau.

## Trois partis pris

### Fiabilité : chaque ligne cite sa source, et la citation est vérifiée

Le modèle doit recopier l'extrait qui justifie chaque élément extrait. Cette
citation est ensuite **recherchée dans la clause d'origine** côté local : si
elle ne s'y trouve pas mot pour mot, l'élément est conservé mais marqué « à
contrôler » dans le tableau de suivi.

La vérification tolère les seules différences qui ne changent pas le sens
(espacement, apostrophes et guillemets typographiques). Une reformulation, même
fidèle, est signalée. Le taux de citations vérifiées figure dans la feuille de
synthèse : c'est un indicateur de confiance, pas une garantie d'exactitude
juridique.

### Sécurité : le contrat ne quitte pas le poste en clair

Avant tout appel distant, noms de sociétés et de personnes, montants,
adresses, courriels, téléphones, IBAN et numéros SIREN sont remplacés par des
jetons stables (`[SOCIETE_1]`, `[MONTANT_3]`). Les valeurs réelles restent dans
le processus local.

Trois propriétés rendent le dispositif tenable :

- **La substitution est bijective.** Après restauration, une citation produite
  sur le texte masqué redevient un extrait exact du contrat d'origine : la
  confidentialité ne coûte pas la vérifiabilité.
- **Le masquage a un point de passage unique.** Tout résultat d'outil transite
  par la même fonction avant de repartir vers l'API. Un nouvel outil ne peut
  pas créer une fuite par omission ; un test le vérifie en inspectant
  l'intégralité de ce qui a été transmis.
- **Les désignations fonctionnelles sont conservées.** « le Prestataire » et
  « le Client » ne sont pas identifiants, et l'agent en a besoin pour rattacher
  chaque obligation à son débiteur. Les pourcentages restent lisibles pour la
  même raison : sans eux, une clause de pénalité devient incalculable.

L'anonymisation se désactive explicitement (`--sans-anonymisation`), avec
avertissement.

### Évaluation : mesurée sur CUAD, pas sur une impression

Le signalement des clauses sensibles est évalué sur **CUAD** (Contract
Understanding Atticus Dataset), 510 contrats annotés par des juristes. La
commande `clauseagent evaluer` produit précision, rappel et F1 **par type de
clause**, sur les six catégories dont le périmètre correspond à un libellé CUAD.

Le jeu est coupé en deux moitiés à graine fixe. Le lexique et le seuil ont été
réglés sur la première ; les chiffres ci-dessous viennent de la seconde, qui
n'a servi à aucun réglage. 213 contrats, 1 699 passages annotés, seuil 3 :

| Catégorie                  | Précision | Rappel |   F1 |
| -------------------------- | --------: | -----: | ---: |
| assurance                  |      80 % |   94 % | 0,87 |
| responsabilité (plafonds)  |      79 % |   77 % | 0,78 |
| renouvellement tacite      |      69 % |   77 % | 0,73 |
| propriété intellectuelle   |      60 % |   89 % | 0,72 |
| pénalités                  |      67 % |   70 % | 0,68 |
| résiliation sans motif     |      41 % |   69 % | 0,52 |
| **Ensemble**               |  **66 %** | **83 %** | **0,73** |

La première version du détecteur obtenait 37 % de précision pour 87 % de
rappel, soit un F1 de 0,51 : deux clauses à relire pour une qui le méritait.
Ce qui a changé, et pourquoi, est détaillé dans
[`docs/architecture.md`](docs/architecture.md). La comparaison n'est pas tout à
fait à périmètre constant : la catégorie « résiliation » a été scindée en cours
de route, sa définition débordant celle que CUAD annote.

La mesure se fait au niveau de la clause et non du passage exact : elle n'est
donc pas comparable aux publications sur CUAD, qui exigent un recouvrement de
Jaccard supérieur à 0,5. Le protocole complet est dans
[`donnees/README.md`](donnees/README.md).

L'évaluation porte sur la chaîne déterministe et n'appelle pas le modèle : elle
est gratuite et reproductible, donc relançable à chaque modification du lexique.

## Architecture

```
contrat ──▶ lire_document ──▶ decouper_clauses ──▶ [clauses]
                                                      │
        ┌─────────────────────────────────────────────┤
        │                                             │
   extraire_clause                              signaler_risque
   (seul appel au modèle)                       (lexique bilingue)
        │                                             │
   [éléments extraits] ──▶ calculer_echeance          │
        │                                             │
        └──────────────▶ exporter_excel ◀─────────────┘
                              │
                     tableau de suivi .xlsx
```

**L'état reste local.** Le texte du contrat, les clauses et les éléments
extraits vivent dans l'objet `Agent`. Les outils ne renvoient au modèle que des
références de clauses et des résumés. Le contexte ne grossit donc pas avec la
taille du contrat, et le document n'est pas retransmis à chaque tour.

**La boucle est écrite à la main** plutôt que confiée à l'exécuteur automatique
du SDK : il faut pouvoir intercaler l'anonymisation, le journal d'audit et le
contrôle des écritures disque entre chaque appel d'outil. Ce sont précisément
les points qu'un gestionnaire de contrats voudra inspecter.

Détail des choix de conception : [`docs/architecture.md`](docs/architecture.md).

## Tests

```bash
pytest
ruff check .
```

La suite couvre les outils déterministes, l'anonymisation, la boucle agentique
(client factice, aucun appel réseau), l'interface graphique (rendu hors écran)
et le harnais d'évaluation. Deux tests portent sur des promesses explicites du
projet : qu'aucune valeur identifiante ne soit transmise au modèle, et qu'un
nom de fichier proposé par le modèle ne permette pas d'écrire hors du
répertoire de sorties.

## Limites connues

- Les PDF scannés sans couche texte ne sont pas traités : il faut une
  reconnaissance de caractères en amont.
- Le calcul en jours ouvrés exclut les week-ends mais pas les jours fériés.
- Le découpage repose sur les numérotations usuelles. Un contrat sans
  numérotation bascule sur un découpage en paragraphes, moins précis.
- L'anonymisation est à base de motifs : elle couvre les formes courantes
  (formes sociales, civilités, montants, coordonnées), pas une entité nommée
  arbitraire. Un nom propre isolé, sans civilité ni forme sociale, peut lui
  échapper.
- La sortie reste une aide à la lecture. Elle ne remplace pas l'analyse d'un
  juriste, et les clauses signalées le sont précisément pour être relues.

## Pile technique

Python 3.10+, API Claude (outils natifs et sorties structurées), Pydantic pour
les schémas, pypdf et python-docx pour la lecture, openpyxl pour l'export,
PySide6 pour l'interface, pytest et ruff pour la qualité.
