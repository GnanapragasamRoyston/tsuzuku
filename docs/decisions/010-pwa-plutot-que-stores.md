# ADR 010 — Installation mobile : une PWA plutôt que les stores

**Date** : 2026-11-21 · **Statut** : accepté (demandé par Royston le 2026-11-21) · **Mise en œuvre** : phase 12 (SPEC § 8.1)

## Contexte
Tsuzuku sert surtout sur téléphone (on note un épisode juste après l'avoir vu) : le front est
déjà pensé mobile d'abord (SPEC § 8, `docs/DESIGN.md`). On veut que l'appli puisse s'installer
sur l'écran d'accueil d'un Android et d'un iPhone. Contraintes : projet étudiant à budget nul,
une seule personne pour maintenir le code, et une base Next.js qui existe déjà (phase 8).

Publier sur les stores a un coût fixe (tarifs à revérifier au moment de publier) :
- App Store : compte Apple Developer à 99 $ par an, et un Mac avec Xcode pour compiler ;
- Google Play : 25 $ une fois, et pour un nouveau compte personnel, un test fermé avec
  12 testeurs pendant 14 jours avant la mise en production.

## Décision
Tsuzuku devient une **Progressive Web App** : manifest, service worker, page hors ligne, aide à
l'installation (`/installer`). Elle s'installe depuis le navigateur, sans store, sans compte
développeur, à partir du même code que le site. La phase vient après le déploiement (phase 11) :
un service worker exige HTTPS, et les tests sur de vrais téléphones ont besoin d'une URL publique.

## Alternatives écartées
- **Appli native ou React Native / Expo** : une deuxième base de code (écrans, état, tests) à
  maintenir en parallèle du front, plus les frais des deux stores. Disproportionné pour un
  projet dont la valeur est la partie Data/ML.
- **Capacitor (front Next.js empaqueté dans une coquille native)** : réutilise le code, mais
  garde les 99 $ par an et le Mac pour iOS, et impose un export statique ou une coquille qui
  charge le site distant (Apple refuse les applis qui ne sont qu'un site web). Gardé comme piste
  pour l'App Store.
- **TWA (Trusted Web Activity) sur Google Play** : empaquette la PWA telle quelle (Bubblewrap ou
  PWABuilder), donc elle est un **prolongement** de cette décision et pas une alternative :
  possible plus tard, une fois la PWA faite, si les 25 $ et les 12 testeurs valent le coup.

## Conséquences
- Coût : 0 €. Un seul code, une seule CI, un seul déploiement : chaque mise en ligne du front met
  à jour l'appli installée (pas de validation de store à attendre).
- Limites d'iOS à assumer et à expliquer sur `/installer` :
  - pas d'invite d'installation automatique (`beforeinstallprompt` n'existe pas sur Safari) :
    il faut un mini-guide « Partager → Sur l'écran d'accueil » ;
  - les notifications push ne marchent que si l'appli est installée ;
  - Safari peut effacer les données d'un site non installé (cache compris) après quelques jours
    sans visite : le hors ligne n'est fiable sur iPhone qu'une fois l'appli installée.
- Pas de présence dans les stores (découvrabilité moindre) : noté dans les limites du README.
- Le service worker met des réponses de l'API en cache sur l'appareil : risque de montrer la
  liste d'un compte à la personne suivante sur un appareil partagé. Règle posée dès la SPEC :
  rien de ce qui touche l'authentification ou les écritures en cache, et les données du compte
  effacées du cache à la déconnexion et à la suppression du compte.
- Le choix de la bibliothèque de service worker (Serwist ou équivalent) fera l'objet de son
  propre ADR en phase 12 : Next 16 compile avec Turbopack par défaut (ADR 009), et la
  compatibilité de chaque option avec Turbopack sera à vérifier à ce moment-là.
