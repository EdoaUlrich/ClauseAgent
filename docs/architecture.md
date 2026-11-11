# Choix de conception

Ce document explique les décisions qui ne se lisent pas dans le code, et les
options qui ont été écartées.

## 1. Le modèle orchestre, le code calcule

L'agent décide **quoi** faire ; il ne fait presque rien lui-même.

| Confié au modèle                         | Confié au code Python                          |
| ---------------------------------------- | ---------------------------------------------- |
| Choix et ordre des outils                | Lecture des fichiers                            |
| Lecture juridique d'une clause           | Découpage en clauses                            |
| Identification des parties et des dates  | Arithmétique des dates                          |
| Synthèse finale                          | Détection lexicale des clauses sensibles        |
|                                          | Vérification des citations, export              |

La règle : tout ce qui a une réponse exacte est calculé, pas demandé. Une
soustraction de dates est juste ou fausse ; un modèle de langage peut se
tromper d'un jour sans le signaler, et rien ne permettrait de s'en apercevoir.
À l'inverse, décider si « le Prestataire garantit l'habilitation de ses
intervenants » est une obligation ou une déclaration relève de la lecture, pas
du calcul.

Ce partage a un effet secondaire utile : la moitié des fonctionnalités
s'exécute sans clé d'API, ce qui rend la commande `inspecter` et toute la suite
de tests exécutables hors ligne.

## 2. L'état ne circule pas

Une implémentation naïve passerait le texte du contrat dans la conversation.
Sur un contrat de cent pages, le contexte est saturé dès le premier tour, et le
même texte est refacturé à chaque itération.

Ici, `Agent` conserve le document, les clauses et les éléments extraits. Les
outils retournent des **références** (`Article 4.2`) et des résumés. Le modèle
raisonne sur une table des matières, pas sur le contrat.

Conséquences :

- le coût par tour est stable, indépendant de la taille du contrat ;
- les données sensibles ne sont pas rediffusées à chaque appel ;
- une clause mal identifiée produit une erreur explicite listant les références
  disponibles, que le modèle peut corriger au tour suivant.

## 3. Boucle manuelle plutôt qu'exécuteur automatique

Le SDK propose un exécuteur qui enchaîne les appels d'outils tout seul. Il a
été écarté, pour trois besoins qui tombent tous *entre* deux appels :

1. **L'anonymisation.** Chaque résultat d'outil doit être masqué avant de
   repartir. `_executer` est le point de passage unique ; un outil ajouté plus
   tard en hérite sans rien faire.
2. **Le journal d'audit.** Chaque appel est horodaté dans un journal exporté
   avec le classeur. Un gestionnaire doit pouvoir reconstituer ce que l'agent a
   fait.
3. **Le contrôle des écritures.** Le nom de fichier d'export vient du modèle.
   Seul son nom de base est retenu, et il est joint au répertoire de sorties :
   un chemin relatif ne permet pas d'écrire ailleurs. Un test le vérifie.

Le coût de ce choix est une quarantaine de lignes de boucle, avec la gestion
des motifs d'arrêt (`tool_use`, `end_turn`, `pause_turn`, `refusal`,
`max_tokens`) et de la limite d'itérations.

## 4. Pourquoi la citation est vérifiée côté client

Demander une citation ne suffit pas : rien ne garantit qu'elle soit fidèle. La
sortie structurée garantit la *forme* du JSON, pas la *véracité* du contenu.

La vérification consiste à rechercher la citation dans le texte de la clause,
après normalisation des espaces et des guillemets typographiques. Trois
résultats possibles :

- citation retrouvée : l'élément est marqué vérifié ;
- citation reformulée ou inventée : l'élément est conservé mais marqué « à
  contrôler », et apparaît en rouge dans l'interface ;
- taux global de vérification : reporté dans la feuille de synthèse.

Conserver les éléments non vérifiés plutôt que les supprimer est délibéré. Un
élément écarté silencieusement est invisible ; un élément signalé est contrôlé.

Cette vérification ne fonctionne que parce que l'anonymisation est bijective :
le modèle cite un texte masqué, la restauration rend la citation comparable au
contrat d'origine.

## 5. Détection lexicale des risques, et non par le modèle

Le signalement des clauses sensibles repose sur un lexique bilingue et des
formulations aggravantes (« de plein droit », « sans préavis », « unlimited »).

Un modèle ferait sans doute mieux sur les cas tordus. Trois raisons l'ont
emporté :

- **stabilité** : deux exécutions sur le même contrat donnent le même résultat,
  ce qui est une attente légitime pour un outil de conformité ;
- **explicabilité** : le motif cite le terme déclencheur et la phrase d'origine,
  justifiable devant un juriste ;
- **mesurabilité** : l'évaluation sur CUAD est gratuite et reproductible, donc
  relancée à chaque modification du lexique.

Le lexique comporte une liste de faux amis : « société à responsabilité
limitée » désigne une forme sociale, pas une clause de limitation de
responsabilité. Sans ce filtre, l'en-tête de tout contrat conclu avec une SARL
serait signalé.

## 6. Ce qui reste ouvert

- **Détection d'entités nommées.** L'anonymisation par motifs couvre les formes
  courantes. Une reconnaissance d'entités locale (sans appel distant) élargirait
  la couverture aux noms propres isolés.
- **Jours fériés.** Le calcul en jours ouvrés saute les week-ends ; un
  calendrier des jours fériés par juridiction le rendrait exact.
- **Évaluation de l'extraction elle-même.** Seul le signalement est mesuré sur
  CUAD aujourd'hui. Mesurer l'extraction supposerait d'aligner les éléments
  extraits sur les passages annotés, et de décider ce qui compte comme une
  obligation correctement identifiée — un travail d'annotation à part entière.
- **Traitement par lots.** L'agent traite un contrat à la fois. Un portefeuille
  entier demanderait une file d'exécution et une consolidation des échéances
  sur plusieurs contrats.
