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
clauseagent evaluer --jeu donnees/cuad/CUAD_v1.json --contrats 50 --rapport sorties/cuad.json
```

L'évaluation n'appelle pas le modèle : elle porte sur le découpage en clauses
et le signalement des risques, deux étapes déterministes. Elle est donc
gratuite et reproductible à graine fixée.

### Ce qui est mesuré, et ce qui ne l'est pas

ClauseAgent ne couvre pas les 41 catégories CUAD. L'évaluation se limite aux
six catégories qu'il revendique, via la correspondance définie dans
`src/clauseagent/evaluation/cuad.py` :

| Catégorie ClauseAgent    | Libellés CUAD correspondants                                                        |
| ------------------------ | ----------------------------------------------------------------------------------- |
| `penalite`               | Liquidated Damages                                                                    |
| `resiliation`            | Termination For Convenience, Post-Termination Services                                |
| `responsabilite`         | Cap On Liability, Uncapped Liability                                                  |
| `assurance`              | Insurance                                                                             |
| `propriete_intellectuelle` | IP Ownership Assignment, Joint IP Ownership, License Grant, Irrevocable Or Perpetual License |
| `renouvellement_tacite`  | Renewal Term, Notice Period To Terminate Renewal                                      |

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
