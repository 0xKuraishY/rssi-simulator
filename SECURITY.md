# Politique de sécurité

## Signaler une vulnérabilité

Merci de ne pas ouvrir d'issue publique pour une faille de sécurité.

Utilisez plutôt le signalement privé de GitHub : onglet **Security**, puis
**Report a vulnerability**. Indiquez :

- la version du jeu (visible en bas du menu principal) et votre système ;
- les étapes pour reproduire le problème ;
- l'impact que vous avez constaté ou que vous supposez.

Vous recevrez une réponse dans les 7 jours. Une fois la correction publiée, votre signalement
pourra être crédité dans les notes de version si vous le souhaitez.

## Périmètre

Sont notamment concernés :

- le multijoueur en réseau local (`net/`) : contournement du PIN, plantage à distance,
  déni de service, connexion depuis une adresse non locale ;
- le chargement des sauvegardes et des préférences (`engine/save_manager.py`) ;
- le rapport HTML de fin de partie (injection de contenu) ;
- toute communication réseau non prévue.

Hors périmètre : la triche sur son propre score en multijoueur (chaque joueur calcule sa
partie localement, le classement est indicatif), et la lecture du trafic réseau local, qui
n'est pas chiffré par conception (voir `docs/RGPD.md`).

## Versions maintenues

Seule la dernière version publiée reçoit des correctifs de sécurité.
