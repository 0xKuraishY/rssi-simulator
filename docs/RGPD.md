# Protection des données — RSSI Simulator

RSSI Simulator est conçu selon le principe de **protection des données dès la conception** (RGPD, art. 25).

## Aucune donnée personnelle collectée

- Le jeu ne demande **aucun nom, identifiant, adresse électronique ou information sur le joueur**.
- La base SQLite contient deux tables :
  - `saves` : l'état de la partie (semaine, organisation fictive, budget, décisions de jeu…) ;
  - `meta` : les préférences (volume, plein écran, tutoriel déjà vu, difficulté, pseudonyme réseau éventuel).
- Aucun identifiant d'appareil, adresse IP ni télémétrie n'est enregistré.
- Le test `tests/test_save_manager.py::test_no_personal_data_columns` vérifie l'absence de colonnes
  à caractère personnel.

## Aucune communication avec Internet

- Le code n'importe **aucun** client Internet (`urllib`, `requests`, `http.client`, `ssl`…). Le test
  automatisé `tests/test_data_and_platform.py::test_no_internet_access_in_code` le vérifie à chaque
  exécution de la suite de tests.
- Les sockets ne sont utilisés que par le **multijoueur en réseau local**, confiné au package `net/`
  (vérifié par le même test). Ce mode est **désactivé par défaut** : il ne s'ouvre que si l'utilisateur
  héberge ou rejoint une session.

## Multijoueur en réseau local

- **Données échangées** : un pseudonyme librement choisi (1 à 20 caractères) et la progression de jeu
  (semaine, score provisoire, réputation, nombre d'incidents). Aucune autre information ne circule.
- **Périmètre** : toute connexion ou tout datagramme venant d'une adresse non privée est refusé
  (réseaux privés, boucle locale, lien local). Ces filtres sont testés dans `tests/test_net.py`.
- **Accès** : un code PIN à 4 chiffres est exigé. Contre la force brute : chaque erreur est ralentie
  d'une seconde, une adresse est bannie pour la session après 3 codes faux, et la session se ferme à
  toute nouvelle connexion après 30 échecs au total. Une même adresse ne peut ouvrir que 4 connexions.
- **Protocole** : JSON ligne par ligne, avec des messages bornés (16 Ko), validés et limités en débit,
  sans désérialisation de code.
- **Aucune persistance** : la session n'existe qu'en mémoire. Le pseudonyme n'est enregistré que dans les
  préférences locales du joueur, pour être proposé de nouveau.
- **Limite connue** : le flux n'est pas chiffré, et le PIN peut être lu par quelqu'un qui écoute le réseau
  local. Réservez ce mode à un réseau de confiance, comme une salle de formation. N'y saisissez pas de
  données personnelles réelles comme pseudonyme si l'organisme de formation ne l'a pas prévu.
- **Ports utilisés** :

  | Port | Rôle |
  |---|---|
  | 47111/TCP | Session |
  | 47110/UDP | Découverte automatique (facultative) |

  Le pare-feu du poste hôte peut demander une autorisation.
- L'IA narrative optionnelle (llama-cpp-python) s'exécute **localement**. Le modèle GGUF doit être
  déposé manuellement : le jeu ne télécharge rien.
- Le rapport HTML de fin de partie est **autonome** : styles intégrés, aucun script, aucune police ni
  image externe. Son ouverture ne déclenche aucune requête. Le bouton « Ouvrir le rapport » ouvre le
  fichier local (`file://`) dans le navigateur par défaut.
- Les URL citées dans les données (sources officielles) sont affichées comme du texte : elles ne sont
  jamais appelées.

## Emplacement des fichiers

| Système | Dossier |
|---|---|
| Windows | `%APPDATA%\rssi-simulator\` |
| Linux | `$XDG_DATA_HOME/rssi-simulator/` (par défaut `~/.local/share/rssi-simulator/`) |
| Surcharge (tests, mode portable) | variable d'environnement `RSSI_SIMULATOR_DATA_DIR` |

Contenu du dossier :

| Fichier | Rôle |
|---|---|
| `saves.sqlite3` | Sauvegardes et préférences |
| `rapports/` | Rapports HTML générés à la demande du joueur |
| `models/` | Modèle d'IA optionnel, déposé par l'utilisateur |

**Effacement** : supprimer le dossier efface toutes les données du jeu.

## Usage en formation

Les rapports HTML peuvent être joints au dossier de l'apprenant. Ils ne contiennent que des éléments
de jeu (décisions, scores, références). Si le formateur y ajoute le nom de l'apprenant, ce traitement
relève de l'organisme de formation (registre, durée de conservation, information des personnes).

## Licences

- Code source : GNU General Public License v3 (`LICENSE`).
- Contenus pédagogiques (scénarios, données, textes) : Creative Commons BY-SA 4.0 (`LICENSE-CONTENUS.md`).
