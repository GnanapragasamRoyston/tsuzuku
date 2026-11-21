# Confidentialité — Tsuzuku

*Brouillon de la page de confidentialité (affichée par le front en phase 8). Décisions
techniques : [ADR 008](decisions/008-comptes-et-listes.md).*

## Ce que Tsuzuku enregistre
| Donnée | Pourquoi |
|---|---|
| Email | te connecter ; jamais affiché publiquement, jamais partagé |
| Pseudo | t'identifier dans l'appli (profil public à venir) |
| Mot de passe | **jamais stocké en clair** : seulement son empreinte argon2id, qui ne permet pas de le retrouver |
| Ta liste (statut, progression, épisode ou chapitre de drop, note, critique, dates) | te montrer ta liste, calculer tes recommandations et ton risque de drop |
| Tes choix d'onboarding | premières recommandations |
| Date de création du compte | — |

Aucun traceur tiers, aucune publicité, aucun cookie de mesure d'audience. Le seul cookie est
celui de ta session (`tsuzuku_session`), strictement nécessaire à la connexion : il est
illisible par les scripts de la page et n'est envoyé qu'en HTTPS.

## Usage des données
- Recommandations et risque de drop : calculés à partir de **ta** liste uniquement.
- Statistiques de l'appli (tableau de bord, phase 13) : **agrégées et anonymes** (par exemple,
  « œuvres les plus ajoutées »), jamais au niveau d'un compte.
- Couvertures et fiches : servies depuis MyAnimeList (via Jikan) et AniList, crédités en pied de
  page ; ces sites ne reçoivent aucune donnée de ton compte.

## Tes droits (RGPD)
- **Accès et portabilité** : *Paramètres → Exporter mes données* télécharge un fichier JSON avec
  ton profil, ta liste et tes choix d'onboarding (`GET /me/export`).
- **Effacement** : *Paramètres → Supprimer mon compte* (mot de passe demandé) efface
  immédiatement et définitivement ton compte, ta liste et tes choix (`DELETE /me`). Rien n'est
  conservé.
- **Rectification** : tu modifies ta liste à tout moment.

## Sécurité
Mots de passe hachés (argon2id), session dans un cookie `httpOnly` + `Secure` + `SameSite=Lax`,
connexion limitée après plusieurs échecs, journaux sans email ni mot de passe.

TODO (phase 11, mise en ligne) : hébergeur et localisation des données, contact du responsable du
traitement.
