# Méthodologie — RSSI Simulator

Ce document décrit les modèles de calcul du jeu, leurs sources et leurs limites. Il est destiné
aux formateurs, aux relecteurs institutionnels et aux contributeurs.

> **Avertissement.** RSSI Simulator est un outil pédagogique. Les probabilités, coûts et montants de
> sanction sont des **modèles simplifiés et calibrés pour l'apprentissage**. Ils ne constituent ni
> un barème officiel, ni une statistique publiée, ni un conseil juridique.

---

## 1. Boucle de jeu

| Élément | Valeur | Fichier |
|---|---|---|
| Durée d'un tour | 1 semaine | `config.py` |
| Durée du mandat | 156 tours (3 ans) | `config.py` |
| Date de début | lundi 5 janvier 2026 | `config.py` |
| Période de prise en main | aucune compromission les 3 premières semaines | `game/incident_engine.py` |
| Incidents ouverts simultanés | 2 au maximum | `game/incident_engine.py` |
| Événements hors incident | 10 par an au maximum | `game/event_engine.py` |

États de l'interface : `MENU | ORG_SELECT | DASHBOARD | INCIDENT | EBIOS | AUDIT | BUDGET | GAME_OVER`.
Les systèmes communiquent par un bus Pub/Sub (`engine/event_bus.py`) : les événements sont mis en file
et distribués une fois par image, ce qui garantit un ordre déterministe (partie rejouable avec `--seed`).

## 2. Moteur de risque — EBIOS Risk Manager

Référence : ANSSI, *EBIOS Risk Manager — Le guide* (2018, version 1.5 de 2024).

### Échelles
- Vraisemblance V : 1 Peu vraisemblable · 2 Vraisemblable · 3 Très vraisemblable · 4 Quasi certain
- Gravité G : 1 Mineure · 2 Significative · 3 Grave · 4 Critique
- **Niveau de risque = V × G** (1 à 16). Catégories : 1-3 faible, 4-6 modéré, 8-9 élevé, 12-16 critique.

### Ateliers
| Atelier | Mécanique | Score de qualité |
|---|---|---|
| 1. Cadrage et socle | Classement glisser-déposer des biens supports (primaire/secondaire) ; revue des 42 mesures du *Guide d'hygiène informatique* (ANSSI, 2017) et choix de 10 écarts prioritaires | Part des biens correctement classés |
| 2. Sources de risque | Sélection des couples SR/OV parmi 12 sources × objectifs visés | F-mesure par rapport à la référence sectorielle (pertinence ≥ 3) |
| 3. Scénarios stratégiques | SR/OV + chemin d'attaque ; matrice 4×4 où l'on peut glisser les scénarios | 50 % couverture des couples, 50 % calibration (écart ≤ 1 cran) |
| 4. Scénarios opérationnels | Déclinaison automatique en modes opératoires MITRE ATT&CK | — |
| 5. Traitement | Accepter / Réduire / Transférer / Refuser + sélection de mesures sous contrainte budgétaire, matrice avant/après | Pertinence de l'option selon le niveau de risque |

### Formules
- Vraisemblance stratégique = arrondi((2 × pertinence sectorielle de la SR + ressources de la SR + exposition de l'organisation au vecteur) / 4)
- Gravité = max(D, I, C, T) de l'impact du scénario (approche « pire cas » d'EBIOS RM)
- Réduction combinée des mesures = 1 − Π(1 − rᵢ), plafonnée à 90 % (aucune mesure n'annule un risque)
- Vraisemblance opérationnelle = max(1, arrondi(V × (1 − réduction combinée)))
- Gravité résiduelle = ⌈G × (1 − 0,5 × réduction d'impact)⌉
- Option « Refuser » : probabilité du type de menace × 0,4 (activité supprimée), coût de 2 points de réputation « usagers »

La pertinence sectorielle des sources de risque (`data/threats/sources_risque.yaml`) est un **calibrage
pédagogique** inspiré des tendances des panoramas de la cybermenace de l'ANSSI, pas une donnée publiée.

## 3. Probabilités d'incident

Chaque organisation définit une probabilité **annuelle** de base par type de menace
(`scenarios/organisations/*.yaml`). À chaque tour :

```
p_annuelle = p_base × facteur_hygiène × (1 − réduction des mesures) × modificateurs temporaires × facteur de traitement
facteur_hygiène = 1,2 − 0,4 × (part des 42 mesures d'hygiène en place)     (de ×1,2 à ×0,8)
p_hebdomadaire = 1 − (1 − p_annuelle)^(1/52)
```

Les modificateurs temporaires viennent des décisions (payer une rançon multiplie le risque de
rançongiciel par 1,6 pendant un an, par exemple) et des événements (alerte CERT-FR ignorée).

Pour le tableau de bord, la probabilité annuelle est convertie en vraisemblance :
≥ 30 % → V4, ≥ 15 % → V3, ≥ 5 % → V2, sinon V1.

## 4. Incidents (10 scénarios)

Chaque scénario suit 7 phases : compromission initiale et latence (invisibles), détection (salle de
crise), confinement, éradication et reprise (3 à 5 décisions horodatées H+n), puis retour d'expérience.

- **Délai de détection** = tirage uniforme dans `phase_detection_semaines` × facteur de détection
  (1 − réduction combinée des capacités de détection : journalisation, SIEM, SOC, EDR, plafond 85 %).
- **Coût** = tirage dans [`cout_min`, `cout_max`] selon le facteur de taille de l'organisation × 0,6 à 1,4,
  × multiplicateurs des décisions × (1 + 2 % par semaine non détectée, plafonné à ×1,5) + coûts fixes,
  × (1 − réduction d'impact des mesures : sauvegardes, PCA, PRIS…).
- Les fourchettes de coûts reprennent le cahier des charges du projet (sources Hiscox et CESIN 2024
  citées par le commanditaire). **À vérifier** avant toute diffusion institutionnelle.
- Les coûts d'incident sont supportés par l'organisation, pas par le budget SSI.

## 5. Budget et ROI

- 6 postes : outils, formation, audit, assurance, externalisation, divers. Si un poste est épuisé,
  le jeu réalloue automatiquement depuis les autres (le budget total ne peut jamais être dépassé).
- Budget de l'année suivante : +2 % d'inflation, +15 % si un incident majeur (G ≥ 3) a eu lieu
  (effet « prise de conscience » de la direction), −10 % par contrat majeur perdu, plancher 60 % du budget initial.
- Maintenance annuelle des mesures imputée en début d'exercice ; une mesure non finançable est suspendue.

**ROI affiché au joueur :**

```
ROI = Σ_types (fréquence annuelle × coût moyen d'incident × coefficient de réduction) / coût annuel de la mesure
coefficient = 1 − (1 − réduction de probabilité) × (1 − réduction d'impact)
coût annuel = coût de déploiement / 3 + maintenance annuelle
```

Les mesures d'hygiène peu coûteuses (désactivation de SMBv1, LAPS, procédure anti-fraude…) affichent
des ROI très élevés : c'est un message pédagogique volontaire, cohérent avec les recommandations de l'ANSSI.

### Écart assumé au cahier des charges : la prime d'assurance
Le cahier des charges indique une prime de « 0,3 à 1,5 % du chiffre d'affaires ». Appliqué
littéralement, ce taux dépasse le budget SSI annuel de toutes les organisations (par exemple 225 000 €
pour un hôpital au taux minimal, contre 72 000 € de budget SSI). Le jeu applique donc ce taux au
**plafond de garantie** souscrit : 0,3 % (profil mature) à 1,5 % (profil exposé, ou sans MFA ni
sauvegardes). La couverture est de 70 % des pertes au-delà d'une franchise de 10 000 €. Elle est
conditionnée au dépôt de plainte sous 72 h (Code des assurances, art. L.12-10-1, loi LOPMI).

## 6. Conformité et sanctions

| Obligation | Délai modélisé | Référence |
|---|---|---|
| Alerte précoce ANSSI | 24 h | NIS2 art. 23 §4 a) |
| Notification d'incident ANSSI | 72 h | NIS2 art. 23 §4 b) |
| Rapport final ANSSI | 1 mois (720 h) | NIS2 art. 23 §4 d) |
| Notification CNIL | 72 h | RGPD art. 33 |
| Information des personnes | 7 jours (« meilleurs délais ») | RGPD art. 34 |
| Déclaration OIV | 24 h (« sans délai ») | Code de la défense L.1332-6-2 |
| Signalement ARS / CERT Santé | 24 h (« sans délai ») | Code de la santé publique L.1111-8-2 |
| Dépôt de plainte (assurance) | 72 h | Code des assurances L.12-10-1 |

Le jeu traduit en heures les délais « sans délai » et « dans les meilleurs délais » afin de pouvoir les évaluer.

**Sanctions (modèles pédagogiques, bornés par les plafonds légaux) :**
- **CNIL**, notification manquée : CA × 0,03 % × gravité × 1,5 (données de santé) × (1 + retard/168 h, borné à ×2).
  Plancher 15 000 €, plafond RGPD art. 83 §4 (10 M€ ou 2 % du CA). La CNIL ne publie pas de formule
  de calcul : ce modèle ne reproduit pas sa pratique, il illustre l'ordre de grandeur et la proportionnalité.
- **NIS2** : 0,5 % × gravité du plafond de l'art. 34. Ce plafond est max(10 M€, 2 % du CA) pour une entité
  essentielle et max(7 M€, 1,4 % du CA) pour une entité importante. Le modèle sanctionne pleinement la
  notification à 72 h, applique 25 % pour le rapport final et seulement un impact sur la réputation pour
  l'alerte à 24 h. Le régime français de transposition (dont le cas des collectivités) est à vérifier
  sur cyber.gouv.fr.
- **LPM** : 150 000 € (Code de la défense, art. L.1332-7).
- **Contrôles simulés** : un contrôle CNIL par an avec une probabilité de 30 % (45 % dans la santé). Un
  contrôle ANSSI une année sur deux pour les entités essentielles et les OIV, et a posteriori après un
  incident pour les entités importantes. Un audit ISO 27001 par an si l'organisation est certifiée ou
  si ses clients l'exigent.
- **ISO 27001** : 93 contrôles de l'annexe A. Ils sont couverts par les mesures et par les travaux SMSI
  (3 000 € pour 5 contrôles). L'audit est réussi à partir de 70 % de couverture. La certification est
  suspendue 26 semaines en cas de non-conformité, notamment après un incident majeur mal géré.
- **DPO** : le jeu applique la règle du cahier des charges (plus de 250 employés ou traitement à grande
  échelle). En droit (RGPD art. 37), le DPO est aussi obligatoire pour **tout organisme public** : la
  mairie y est soumise de toute façon.

## 7. Réputation

Quatre dimensions de 0 à 100 :

| Dimension | Valeur initiale | Poids dans la moyenne pondérée |
|---|---|---|
| Usagers | 75 | 30 % |
| Partenaires | 80 | 25 % |
| Régulateurs | 70 | 25 % |
| Presse | 65 | 20 % |

Les poids n'étaient pas précisés dans le cahier des charges ; ils ont été choisis par l'équipe. Chaque
dimension remonte de 0,25 point par semaine vers sa valeur initiale.

- Score global < 40 : un contrat ou partenariat majeur est perdu (une fois par passage sous le seuil).
- Score global < 20 : fin de partie.

## 8. Score final

| Critère | Poids | Calcul |
|---|---|---|
| Réputation | 30 % | score global / 100 |
| Maîtrise du risque | 20 % | 60 % amélioration du risque moyen + 40 % qualité EBIOS RM |
| Conformité | 20 % | 50 % notifications dans les délais + 50 % obligations permanentes |
| Gestion de crise | 20 % | qualité moyenne des décisions (bonne 1 / moyenne 0,5 / mauvaise 0) |
| Impact financier | 10 % | 1 − (pertes + sanctions) / (3 × budget IT) |

Grille : 0-39 Insuffisant · 40-64 Moyen · 65-84 Bon · 85-100 Expert. Le score est plafonné à 30 en
cas de perte de confiance totale.

**Percentile.** Il n'existe pas de benchmark officiel de l'ANSSI pour ce jeu. Le percentile est calculé
par rapport à une loi normale (moyenne 52, écart-type 20), calibrée sur 60 parties simulées par les
joueurs automatiques de `game/autoplay.py` : 3 profils × 5 organisations × 4 graines. Moyennes
observées : expert 82,5, moyen 54,4, novice 17,9.

## 9. Références à vérifier avant diffusion

Les références suivantes ont été rédigées avec prudence mais doivent être confrontées aux publications
officielles par un relecteur :

1. Chiffres clés du Panorama de la cybermenace ANSSI 2024 (`data/threats/anssi_panorama_2024.json`, statut « a_verifier »).
2. Fourchettes de coûts d'incident (Hiscox / CESIN 2024) issues du cahier des charges.
3. INC-005 : numéro d'alerte CERTFR-2024-ALE-001 (Ivanti Connect Secure).
4. INC-010 : avis CISA relatif à CVE-2021-22681 (cité sans numéro) ; attaques de fin 2023 contre des automates de traitement d'eau.
5. INC-004 : « près de 18 000 clients » (chiffre déclaré par SolarWinds) ; CVE-2020-10148, liée à SUPERNOVA et non à SUNBURST, ce que le texte précise.
6. INC-007 : la médiane de « 197 jours » vient du rapport IBM/Ponemon *Cost of a Data Breach* 2018. C'est le délai moyen d'identification, tous incidents confondus, et non un chiffre propre aux initiés malveillants.
7. Intitulés exacts des fiches Cybermalveillance.gouv.fr et de certains guides ANSSI cités dans les événements.
8. Nom du portail d'enregistrement NIS2 (« MonEspaceNIS2 ») et état de la transposition française de NIS2.
9. Intitulés français des 93 contrôles ISO/IEC 27001:2022. Ce sont des traductions libres : se référer à la norme NF EN ISO/IEC 27001.

## 10. Choix d'architecture

| Choix | Justification |
|---|---|
| Sauvegarde : état JSON unique + version de schéma + SHA-256 dans SQLite | Corruption détectée, état sérialisable sans migrations, aucune donnée personnelle |
| Bus d'événements avec file et distribution par image | Déterminisme (`--seed`) |
| Interface en « mode immédiat » (widgets maison, sans dépendance) | Pas de synchronisation d'état ; tous les écrans sont testables en mode headless |
| Façade `game/simulation.py` | Toutes les règles sont testables sans affichage, et le mode `--headless` joue une partie complète |
| IA narrative optionnelle avec repli statique | Le jeu reste 100 % fonctionnel sans modèle ; l'exécution est locale uniquement |

## 11. Niveaux de difficulté

La difficulté est indépendante de l'organisation choisie. L'organisation fixe le contexte (taille,
budget, réglementation) ; la difficulté règle l'intensité de la menace et les aides affichées.

| Paramètre | Découverte | Standard | Expert | Crise majeure |
|---|---|---|---|---|
| Probabilité des incidents | ×0,65 | ×1 | ×1,35 | ×1,8 |
| Coût des incidents | ×0,75 | ×1 | ×1,2 | ×1,4 |
| Sanctions | ×0,5 | ×1 | ×1 | ×1,2 |
| Budget SSI initial | ×1,25 | ×1 | ×0,9 | ×0,8 |
| Crises simultanées max. | 1 | 2 | 2 | 3 |
| Comptes à rebours | ×2 | ×1 | ×0,75 | ×0,5 |
| Capacité de l'équipe | ×1,3 | ×1 | ×0,9 | ×0,8 |
| Seuil de licenciement (confiance) | 5 | 12 | 15 | 20 |
| Probabilités affichées / rappels | oui / oui | oui / oui | non / non | non / non |
| Conseil « réflexe ANSSI » en crise | oui | non | non | non |

Durée du mandat : 1, 2 ou 3 ans (52 à 156 semaines).

**Calibrage** : 180 parties automatiques (4 difficultés × 3 durées × 5 organisations × 3 profils). Scores
moyens observés sur un mandat de 3 ans :

| Difficulté | Profil expert | Profil moyen | Profil novice |
|---|---|---|---|
| Découverte | ≈ 82 | ≈ 58, aucune fin anticipée | ≈ 18, environ 3 sur 10 terminent avant la fin |
| Standard | ≈ 76 | ≈ 46, environ 3 sur 10 terminent avant la fin | ≈ 18 |
| Expert | ≈ 75 | ≈ 33, la plupart terminent avant la fin | ≈ 20 |
| Crise majeure | ≈ 72 | ≈ 32, la plupart terminent avant la fin | ≈ 22 |

Le profil expert connaît les bonnes réponses : un joueur humain se situe entre les profils moyen et expert.

## 12. Opérations SSI

**Équipe et capacité.** Chaque membre de l'équipe SSI apporte 4 jours-homme (j·h) par semaine, multipliés
par le coefficient de difficulté. Cette capacité baisse de 40 % pendant une crise. Elle est consommée par :
- les actions : ateliers EBIOS (1,5 j·h), démarches de conformité (0,5 à 3 j·h), travaux SMSI (2 j·h),
  corrections de vulnérabilités, campagnes de faux hameçonnage (1 j·h) ;
- la charge de fond des déploiements : 1,5 j·h par semaine et par mesure technique, 0,5 j·h pour une
  mesure externalisée.

Quand la charge dépasse la capacité, les déploiements les plus récents sont retardés d'une semaine. Après
6 semaines consécutives de surcharge, chaque semaine comporte 25 % de risque qu'un membre parte
(épuisement). L'équipe se renforce par un consultant en régie (2 j·h par semaine pendant 8 semaines,
TJM 800 €) ou par un recrutement accordé en comité de direction (arrivée sous 8 semaines).

**Vulnérabilités.** Le catalogue `data/threats/vulnerabilites.yaml` compte 26 CVE réelles et largement
documentées, avec une gravité qualitative : aucun score CVSS n'est recopié. Le jeu publie environ 0,3
vulnérabilité par semaine, multiplié par le coefficient de difficulté. Une vulnérabilité est visible avec
une probabilité de 55 %, portée à 85 % avec le scan de vulnérabilités (M26) et à 95 % avec, en plus, la
cartographie (M40). Les tests d'intrusion (M25) et les scans révèlent les failles ignorées.

Chaque vulnérabilité ouverte augmente la probabilité du type d'incident associé. Le poids est de 0,14
pour une gravité critique et de 0,07 pour une gravité élevée ; il gagne 0,10 si la faille est exploitée
activement, et il est divisé par 2 si elle n'est atteignable qu'en interne. Le facteur total est plafonné
à ×1,8.

Une faille exposée et exploitée activement peut être exploitée en silence. La probabilité hebdomadaire
est de 1 % × difficulté × (1 + âge/10) et déclenche un incident. Le joueur dispose de quatre traitements :

| Traitement | Charge | Effet |
|---|---|---|
| Corriger en urgence | ×1,5 | Correction la semaine suivante, avec interruption de service éventuelle |
| Planifier | ×1 | Correction à la prochaine fenêtre de maintenance (toutes les 4 semaines) |
| Contourner | ×0,5 | Effet divisé par 2, faille non exploitable de l'extérieur |
| Accepter | aucune | Risque conservé ; si la faille est exploitée, l'erreur figure au rapport |

La gestion outillée des correctifs (M08) corrige automatiquement au bout de 4 semaines les failles qui ne
sont pas à la fois critiques et exposées.

**Niveau de menace.** Des bulletins de veille génériques (`data/threats/campagnes.yaml`) multiplient
temporairement certaines menaces. Exemple : ×1,6 sur les rançongiciels pendant 8 semaines.

**Vigilance du personnel.** Le taux de clic initial dépend de l'organisation (10 % à 24 %). Avec la
sensibilisation (M01), il est multiplié par 0,78 chaque trimestre, avec un plancher de 3 %. La
probabilité d'hameçonnage et de compromission cloud est multipliée par (taux / taux initial). Une campagne
de faux hameçonnage mesure le taux et le réduit de 8 %.

## 13. Gouvernance

**Confiance de la direction (0-100, départ 60).**

| Événement | Effet |
|---|---|
| Crise bien gérée | +4 |
| Crise mal gérée | −8 (incident majeur) ou −5 |
| Sanction (une seule fois par incident) | −5 |
| Contrat perdu | −10 |
| Contrôle conforme / non conforme | +2 / −3 |
| Objectif atteint / manqué | +5 / −4 |
| Bilan trimestriel transparent | +4 |
| Exercice de crise avec le comité | +6 |
| Analyse EBIOS RM finalisée | +3 |

Les pertes sont multipliées par la sensibilité de la difficulté. La confiance remonte lentement vers 60.
Sous le seuil de la difficulté, le RSSI est remercié et la partie s'arrête, avec un score plafonné à 30.

**Comité de direction** (toutes les 13 semaines). Quatre options :

| Option | Chances de succès | Effet |
|---|---|---|
| Rallonge budgétaire (15 % du budget, ponctuelle) | Bienveillance × (0,5 + 0,5 × confiance), +15 % si EBIOS RM finalisée, +10 % si risque critique ou incident majeur, −10 % par rallonge déjà obtenue dans l'année | Crédits supplémentaires sur l'exercice en cours |
| Recrutement | Bienveillance × confiance, +25 % si l'équipe est surchargée | Un analyste de plus sous 8 semaines |
| Exercice de crise | Certain (3 000 €) | Coûts des crises −10 % pendant 26 semaines |
| Bilan sans demande | Certain | Confiance +4 |

**Objectifs de mandat.** La direction tire 3 objectifs parmi 11 (EBIOS RM en 6 mois, socle d'hygiène,
ISO 27001, zéro sanction, notifications exemplaires, taux de clic < 8 %, surface exposée maîtrisée,
réputation ≥ 70, confiance ≥ 65, pertes contenues, risque ramené sous le critique). Ils comptent pour
15 % du score.

**Nouvelle pondération du score.**

| Critère | Poids |
|---|---|
| Réputation et confiance de la direction (80/20) | 25 % |
| Maîtrise du risque | 20 % |
| Conformité | 15 % |
| Gestion de crise | 15 % |
| Finances | 10 % |
| Objectifs | 15 % |

Percentile de référence : loi normale de moyenne 46 et d'écart-type 25, issue des 120 parties de
calibrage (4 difficultés × 3 profils × 5 organisations × 2 graines).

## 14. Corrections issues des tests croisés

Les bancs de test automatisés (parties complètes, sauvegarde et rechargement en cours de partie, clics
aléatoires sur l'interface) ont mis en évidence et permis de corriger :
- une coupe budgétaire en cours d'année pouvait rendre le budget négatif (crédits déjà dépensés) ;
- une mesure offerte par un événement réinitialisait le déploiement d'une mesure déjà en place ;
- un événement pouvait ouvrir un incident au-delà du plafond de crises simultanées ;
- le message de fin indiquait toujours « 3 ans » ;
- une vulnérabilité au correctif déjà planifié pouvait être retraitée ;
- en mode réseau synchronisé, un joueur ayant terminé sa partie bloquait les autres ;
- un plantage de SDL_ttf survenait quand des polices mises en cache étaient réutilisées après `pygame.quit()`.
