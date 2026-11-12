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

## 6. Ce que la mesure a corrigé

La première version signalait une clause dès qu'un terme du lexique y figurait.
Sur CUAD : **37 % de précision pour 87 % de rappel**, soit un F1 de 0,51. Un
gestionnaire recevait deux clauses à relire pour une qui le méritait. Cinq
corrections, chacune validée par une mesure, ont porté le F1 à **0,73** sur une
moitié du jeu tenue à l'écart des réglages.

**Collisions entre langues.** `amende` reconnaissait `amended`, `assurance`
reconnaissait `assurances`, `licence` reconnaissait `license` : le lexique
français déclenchait sur du texte anglais. La comparaison se fait désormais sur
mots entiers. Dans la même veine, « further assurances » — une clause de style
par laquelle chacun s'engage à accomplir les formalités utiles — n'a rien d'une
clause d'assurance et figure parmi les faux amis, aux côtés de « société à
responsabilité limitée », qui désigne une forme sociale et non un plafond de
responsabilité.

**Expressions plutôt que mots.** `termination` apparaît dans presque toutes les
sections d'un contrat de travail ; `terminate this agreement` désigne une vraie
faculté de résiliation. Les mots génériques ne servent plus que d'indices
d'intitulé.

**Score de pertinence.** Un intitulé consacré au sujet, une expression décisive,
ou une expression ordinaire placée en ouverture ou répétée. C'est ce que fait un
lecteur qui survole : une section qui s'ouvre sur « Either party may terminate
this Agreement » traite de résiliation ; une qui mentionne « after the
Termination Date » au détour d'une phrase n'en traite pas.

**Tournures, et non plus seulement termes.** Les clauses que CUAD annote comme
résiliation sans motif ne contiennent presque jamais l'expression « for
convenience ». Elles s'écrivent « may terminate this Agreement upon sixty (60)
days' written notice » : une faculté de résilier, un préavis, et aucune mention
de faute entre les deux. Un motif composé décrit cette tournure, ce qui a fait
passer le rappel de la catégorie de 30 % à 69 %.

**Découpage des contrats mal mis en forme.** 42 % des contrats CUAD portaient
leurs intitulés au milieu d'une phrase, séquelle de l'extraction PDF, et
basculaient sur le découpage de repli en paragraphes. Une seconde passe les
reconnaît, ramenant ce taux à 24 %.

### Deux pistes qui ont échoué

Écarter les sections fourre-tout — « miscellaneous », « notices »,
« representations and warranties » — paraissait évident : elles revenaient
souvent parmi les faux positifs. Le rappel a chuté de douze points. Ces
sections abritent fréquemment la clause de résiliation ou le préavis de
renouvellement des contrats courts.

Écarter les blocs non normatifs quelle que soit leur taille — préambule,
recitals, identification des parties — a coûté cinq points de F1. Sur un
contrat dont le premier intitulé arrive tard, ce bloc couvre une large part du
texte et contient de vraies stipulations. La règle ne s'applique donc qu'aux
clauses de forme réellement courtes.

Ces deux essais sont conservés dans les commentaires du lexique : l'intuition
était raisonnable, et sans la mesure elle serait passée pour une amélioration.

### Le périmètre d'une catégorie doit correspondre à celui du libellé mesuré

La catégorie `resiliation` signalait toute faculté de mettre fin au contrat,
alors que CUAD n'annote que la résiliation sans motif. Mesurer l'une par
l'autre comptait comme erreurs des signalements parfaitement corrects : la
précision affichée, 11 %, ne mesurait rien.

Deux issues : restreindre la catégorie pour coller au jeu, ou séparer ce qui
devait l'être. La première aurait dégradé l'outil pour flatter la mesure. La
seconde a été retenue : `resiliation_convenance` isole la résiliation sans
motif — généralement assortie d'une indemnité, donc un risque commercial d'une
autre nature qu'une résiliation pour manquement — et c'est elle qui est mise en
regard de CUAD. `resiliation` reste dans le produit, simplement non mesurée.

Le même raisonnement a séparé `responsabilite`, qui vise les plafonds et
exclusions, de `indemnisation`, qui vise les engagements de garantie. L'un
limite ce que l'on peut réclamer, l'autre crée une dette potentielle.

Il reste un écart assumé sur la propriété intellectuelle : la catégorie couvre
les clauses d'indemnité ou de garantie portant sur la PI, que CUAD n'annote pas
sous ce libellé. Sa précision mesurée, 60 %, est donc un plancher.

## 7. Ce qui reste ouvert

- **Précision de la résiliation sans motif.** 41 %, le point faible. Le motif
  composé reconnaît la tournure mais ne distingue pas encore une faculté
  réciproque d'une faculté unilatérale, ni le préavis contractuel du délai de
  notification d'un autre événement.
- **Découpage des contrats sans numérotation.** 24 % des contrats CUAD basculent
  encore sur le repli en paragraphes. Un modèle de segmentation entraîné sur des
  contrats ferait mieux qu'un jeu de motifs, au prix de la reproductibilité.
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
