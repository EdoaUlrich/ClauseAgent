# Jeux de données

## CUAD (Contract Understanding Atticus Dataset)

CUAD rassemble 510 contrats commerciaux annotés par des juristes, répartis en
41 types de clauses. Il sert ici à mesurer la précision et le rappel du
signalement des clauses sensibles.

Le jeu n'est pas versionné dans ce dépôt : il pèse environ 100 Mo et possède sa
propre licence (CC BY 4.0, The Atticus Project).

### Obtenir le jeu

Télécharger `CUAD_v1.zip` depuis la page du projet Atticus
(<https://www.atticusprojectai.org/cuad>) ou depuis le dépôt Hugging Face
`theatticusproject/cuad-qa`, puis décompresser le fichier `CUAD_v1.json` dans
`donnees/cuad/` :

```
donnees/
└── cuad/
    └── CUAD_v1.json
```

### Lancer l'évaluation

```bash
# Mesure de référence : moitié du jeu jamais utilisée pour les réglages
clauseagent evaluer --jeu donnees/cuad/CUAD_v1.json --rapport sorties/cuad.json

# Moitié ayant servi au réglage du lexique, ou jeu complet
clauseagent evaluer --jeu donnees/cuad/CUAD_v1.json --echantillon mise-au-point
clauseagent evaluer --jeu donnees/cuad/CUAD_v1.json --echantillon tout

# Arbitrage précision / rappel
clauseagent evaluer --jeu donnees/cuad/CUAD_v1.json --seuil 2
```

L'évaluation n'appelle pas le modèle : elle porte sur le découpage en clauses
et le signalement des risques, deux étapes déterministes. Elle est donc
gratuite et reproductible.

### Deux échantillons

Le lexique et le seuil de signalement ont été réglés en examinant les erreurs
commises sur CUAD. Mesurer ensuite la performance sur ces mêmes contrats
reviendrait à noter une copie sur les exercices ayant servi à la réviser.

Le jeu est donc coupé en deux moitiés tirées à graine fixe, donc stables d'une
exécution à l'autre : `mise-au-point` (212 contrats) et `validation` (213). Les
chiffres publiés sont ceux de la validation, qui n'a servi à aucun réglage.
L'option `tout` reste disponible pour un inventaire, mais son résultat est
optimiste et le rapport le signale.

### Résultats

Moitié de validation, 213 contrats, 1 699 passages annotés, seuil 3 :

| Catégorie                  | Attendus | Précision | Rappel |   F1 |
| -------------------------- | -------: | --------: | -----: | ---: |
| `assurance`                |      278 |      80 % |   94 % | 0,87 |
| `responsabilite`           |      427 |      79 % |   77 % | 0,78 |
| `renouvellement_tacite`    |      165 |      69 % |   77 % | 0,73 |
| `propriete_intellectuelle` |      629 |      60 % |   89 % | 0,72 |
| `penalite`                 |       71 |      67 % |   70 % | 0,68 |
| `resiliation_convenance`   |      129 |      41 % |   69 % | 0,52 |
| **Ensemble**               | **1 699** |  **66 %** | **83 %** | **0,73** |

85 contrats sont écartés faute d'annotation sur les catégories couvertes.

### Ce qui est mesuré, et ce qui ne l'est pas

ClauseAgent ne couvre pas les 41 catégories CUAD, et toutes ses catégories n'ont
pas d'équivalent de même portée. L'évaluation se limite à celles dont le
périmètre correspond à un libellé CUAD, via la correspondance définie dans
`src/clauseagent/evaluation/cuad.py` :

| Catégorie ClauseAgent      | Libellés CUAD correspondants                                                                 |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| `penalite`                 | Liquidated Damages                                                                             |
| `resiliation_convenance`   | Termination For Convenience                                                                    |
| `responsabilite`           | Cap On Liability, Uncapped Liability                                                           |
| `assurance`                | Insurance                                                                                      |
| `propriete_intellectuelle` | IP Ownership Assignment, Joint IP Ownership, License Grant, Irrevocable Or Perpetual License    |
| `renouvellement_tacite`    | Renewal Term, Notice Period To Terminate Renewal                                               |

Les catégories `resiliation` (toute faculté de mettre fin au contrat),
`indemnisation`, `confidentialite` et `force_majeure` n'ont pas de libellé CUAD
de portée équivalente : elles restent dans le produit mais ne sont pas mesurées
ici. Une version antérieure confrontait `resiliation` au libellé « Termination
For Convenience », bien plus étroit, et affichait 11 % de précision — un chiffre
qui ne mesurait rien d'autre que l'écart entre les deux définitions.

La mesure se fait **au niveau de la clause** : un passage annoté compte comme
retrouvé dès qu'une clause signalée dans la même catégorie recouvre sa
position. C'est plus permissif que la métrique officielle de CUAD, qui exige un
recouvrement de Jaccard supérieur à 0,5 sur le passage exact. Les chiffres
obtenus ici ne sont donc **pas comparables** aux résultats publiés sur CUAD ;
ils mesurent ce que l'outil prétend faire, c'est-à-dire orienter un
gestionnaire vers les bonnes clauses.

## Jeu réduit de test

`tests/donnees/mini_cuad.json` reproduit la structure de CUAD sur deux contrats
écrits pour l'occasion. Il sert aux tests automatisés du harnais d'évaluation,
afin que ceux-ci s'exécutent sans télécharger le jeu complet. Les scores
obtenus sur ce fichier ne valent évidemment rien comme mesure de performance :
seul le jeu réel est significatif.
