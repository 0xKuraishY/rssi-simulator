# Contribuer à RSSI Simulator

Merci de votre intérêt. Que vous soyez formateur, étudiant, RSSI ou développeur, il y a
forcément quelque chose que vous pouvez améliorer.

## Signaler un problème ou proposer une idée

Ouvrez une issue en décrivant :

- ce que vous faisiez (organisation, difficulté, semaine) ;
- ce qui s'est passé, et ce que vous attendiez ;
- si possible la graine de la partie (affichée dans le rapport de fin) pour reproduire.

Pour une erreur réglementaire ou technique, citez la source (article de loi, guide ANSSI,
bulletin CERT-FR, fiche CVE).

## Ajouter un scénario d'incident

C'est la contribution la plus utile, et elle ne demande pas de programmer.

1. Copiez un fichier existant de `scenarios/incidents/`, par exemple `inc_002_phishing_daf.yaml`.
2. Donnez-lui un identifiant unique et adaptez le récit, les décisions et leurs conséquences.
3. Appuyez-vous sur des faits réels : CVE publiées, techniques MITRE ATT&CK, retours
   d'expérience publics. Les organisations, elles, restent fictives.
4. Lancez les tests : ils vérifient la structure des fichiers et la cohérence des références.

Même principe pour les organisations (`scenarios/organisations/`) et les événements
(`scenarios/events/`).

## Proposer du code

```bash
make install
make test
```

- Une modification = une pull request, avec une description claire de ce qu'elle change.
- Ajoutez un test quand vous corrigez un bug ou ajoutez une fonctionnalité.
- Le jeu doit rester **100 % hors ligne** : aucune bibliothèque d'accès à Internet, les sockets
  restent confinés au dossier `net/` (un test le vérifie).
- Aucune donnée personnelle ne doit être collectée ni stockée.
- Le texte visible par le joueur est en français.

## Licences des contributions

En contribuant, vous acceptez que votre code soit diffusé sous GNU GPL v3 et vos contenus
pédagogiques sous CC BY-SA 4.0, comme le reste du projet.
