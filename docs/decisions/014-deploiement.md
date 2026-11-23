# ADR 014 — Déploiement : Vercel, Cloud Run, Neon, relais de confiance

**Date** : 2026-11-23 · **Statut** : accepté (plan validé par Royston le 2026-11-23)

## Contexte
Phase 11 (SPEC § 9) : mettre Tsuzuku en ligne avec CI/CD, secrets gérés et monitoring de base,
à coût nul (offres gratuites vérifiées le 2026-11-23). Trois points attendaient cette phase :
l'IP réelle derrière le relais (ADR 009), l'ordre schéma du pipeline → API (ADR 012) et les
embeddings en production (ADR 013).

## Décisions

### a) Hébergement (tout en Europe, région de Francfort)
| Brique | Service | Pourquoi |
|---|---|---|
| Front | Vercel Hobby, `tsuzuku.vercel.app`, fonctions `fra1` | Next.js natif, déploiement à chaque push |
| API | Cloud Run `europe-west3`, 0 à 2 instances, 1 Gio | Conteneur existant, 0 € au repos |
| Base | Neon Free `eu-central-1` (Postgres 16 + pgvector, 1 Go) | pgvector inclus ; catalogue + marts = 100 Mo mesurés |
| Modèles | Bucket Cloud Storage privé, lu au démarrage (`MODELS_URI`) | Le disque de Cloud Run est éphémère ; sha256 toujours vérifiés |
| Ingestion | Cloud Run Jobs + Cloud Scheduler (mêmes tâches et horaires que les DAG) | Airflow reste l'outil de dev et de démo |

Limites gratuites à surveiller : 5 000 transformations d'images par mois sur Vercel Hobby (le
cache garde les images déjà vues), 1 Go et 100 CU-heures par mois sur Neon.

### b) Relais de confiance (remplace la limite globale de l'ADR 009)
L'API Cloud Run a une URL publique (Vercel ne sait pas s'authentifier auprès de Cloud Run). Le
relais du front (`proxy.ts`, requêtes `/api/*`) ajoute :
- `X-Tsuzuku-Proxy` : secret partagé (Secret Manager côté API, variable serveur côté Vercel,
  jamais `NEXT_PUBLIC_`) ; sans lui, l'API répond **403** (sauf `/health`, pour la sonde) ;
- `X-Tsuzuku-Client-IP` : l'IP du visiteur, lue dans `x-forwarded-for` **seulement sur Vercel**
  (posé par la plateforme) ; ailleurs rien n'est transmis. Les valeurs envoyées par le client
  sont toujours écrasées ; une IP mal formée n'est pas crue.
La limite de connexion redevient **par visiteur**. Les pages rendues côté serveur envoient le
même secret. Vérifié : l'E2E tourne avec le relais actif (un appel direct prend 403).

### c) Ordre de déploiement (`.github/workflows/deploy.yml`, après une CI backend verte)
1. Images API et ingestion → Artifact Registry ;
2. **job de migration** (`python -m app.migrate`) : schéma du pipeline PUIS Alembic, AVANT la
   nouvelle API (ADR 012) ;
3. API Cloud Run ; jobs d'ingestion ;
4. test de fumée : `/health/ready` à 200 et appel direct refusé (403).
GitHub → GCP par **Workload Identity Federation** : pas de clé JSON, seul ce dépôt peut
emprunter le compte de déploiement. Comptes de service à droits minimaux (API, ingestion,
déploiement, planificateur).

### d) Données
`make db-publish` copie catalogue, marts et embeddings locaux vers Neon en **une transaction**
(taille vérifiée, refus si des comptes existent déjà sauf `FORCE=1`, confirmation tapée). Répété
sur une base jetable : 21 218 œuvres et embeddings, relance identique ; l'historique quotidien de la
production (job jikan-daily) est mis de côté par clé naturelle puis remis (vérifié). Les nouvelles œuvres
d'AniList en production reçoivent leur embedding par `make embeddings` lancé contre Neon (PyTorch
reste hors du cloud) ; le rapport du job AniList compte celles qui en manquent.

## Écartés
- Clés JSON de compte de service dans GitHub (fuite durable) → Workload Identity.
- Modèles dans l'image (fichiers ignorés par Git, image reconstruite à chaque réentraînement).
- Airflow en production (coût d'une VM permanente) → Cloud Run Jobs + Scheduler.
- API privée derrière IAM (Vercel ne signe pas ses requêtes) → secret partagé + 403.

## Conséquences
- Démarrage à froid de l'API (modèles copiés puis chargés) : à mesurer à la mise en ligne.
- Coût cible 0 € ; alerte de budget à 5 € (50, 90, 100 %), sonde `/health/ready`.
- La base de dev locale était restée à la révision Alembic 0001 (les tests ont leurs propres
  bases) : le job de migration l'a mise à jour ; `make migrate` à lancer après chaque `git pull`.
