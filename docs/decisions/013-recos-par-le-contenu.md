# ADR 013 — Recos par le contenu : embeddings, pgvector, hybride avec la popularité

**Date** : 2026-11-22 · **Statut** : accepté (plan et choix validés par Royston le 2026-11-22)

## Contexte
Phase 10 (SPEC § 6.3) : recommander mangas, manhwas et manhuas, qui n'ont aucun historique
d'interactions (l'ALS de la phase 4 est impossible), et permettre le cross-média (« tu as aimé
l'anime X → manhwa Y »). Toutes les mesures viennent de `reports/content_reco_metrics.json` et
sont prises avec **le protocole de la phase 4** : mêmes utilisateurs de test, mêmes notes masquées,
mêmes 10 859 animes candidats, NDCG@10 (`reports/reco_metrics.json` pour l'ALS).

## Décisions

### a) Texte et modèle
- Texte d'une œuvre : titre (+ titre secondaire), type, genres, 10 tags AniList les plus
  pertinents, synopsis en dernier (les modèles tronquent par la fin).
- Deux modèles multilingues légers (384 dimensions, CPU) comparés en contenu pur :

| Modèle | NDCG@10 test | Onboarding 3 aimés | Encodage (10 859 animes) |
|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 0,0065 | 0,024 | 138 s |
| **multilingual-e5-small** (préfixe « query: ») | **0,027** | **0,054** | 157 s |

  **e5-small retenu.** Les 21 218 œuvres sont encodées en 365 s (`reports/embeddings_run.json`).

### b) Le contenu seul ne suffit pas : hybride avec la popularité
Le contenu pur (0,027) fait bien moins bien que la popularité (0,193) : il recommande des œuvres
proches mais obscures (7,5 % du catalogue recommandé), alors que ce que les gens aiment est
majoritairement connu. Le contrôle de popularité retrouve exactement le 0,193 de la phase 4 : ce
n'est pas une erreur de mesure.

Score servi = cosinus + β × 1 / log2(1 + rang de popularité). β est réglé sur **5 000 utilisateurs
de validation** ; le test n'est mesuré qu'une fois :

| β | 0 | 0,05 | 0,1 | 0,2 | **0,3** | 0,5 | 1 | 2 |
|---|---|---|---|---|---|---|---|---|
| NDCG@10 validation | 0,025 | 0,124 | 0,157 | 0,179 | **0,181** | 0,182 | 0,182 | 0,182 |

Règle (choix de Royston) : **le coude**, plus petit β à moins de 1 % du meilleur NDCG de
validation, soit **β = 0,3**. Test : NDCG@10 **0,182**, rappel@10 0,084 ; onboarding 3 / 5 / 10 /
20 aimés : 0,182 / 0,182 / 0,183 / 0,190.

**Limites, dites telles quelles** :
- sur ce protocole, l'hybride ne bat jamais la popularité seule (0,193) ; il s'en approche ;
- la couverture du catalogue au test n'est que de **0,7 %** à β = 0,3 (contre 7,5 % en contenu
  pur) : sur les animes, le coude n'a pas apporté la diversité attendue (la couverture par β n'est
  pas mesurée sur la validation). Baisser β (0,1 : 0,157 en validation) donnerait plus de
  découverte au prix du score : c'est un réglage produit (`content_popularity_beta`) ;
- l'évaluation porte sur des animes (seules œuvres avec des notes) ; pour les mangas et manhwas,
  le même β est appliqué faute de vérité terrain.

Les animes restent servis par l'**ALS** (0,493 au test), bien au-dessus.

### c) Où tournent les calculs
- Embeddings : `make embeddings` (batch, comme `make spark`), PyTorch CPU dans un extra
  `embeddings` du pipeline. **Ni l'image Airflow ni l'API ne l'installent** ; le DAG AniList
  compte seulement les œuvres sans embedding (module sans numpy, l'image Airflow n'en a pas).
- L'API ne charge aucun modèle : profil = moyenne des embeddings des œuvres aimées, **tous types
  confondus**, pondérée par (note − 5) ; requête pgvector ; « parce que tu as aimé X » = l'œuvre
  aimée la plus proche de la reco (cross-média).
- **Recherche exacte, sans index ANN** : 21 218 vecteurs, environ 22 ms sur tout le catalogue et 4 ms
  pour les manhwas et manhuas (EXPLAIN ANALYZE, 3 passages, 2026-11-22) ; un index HNSW perdrait des
  résultats une fois filtré par type et par œuvres déjà vues.

### d) Produit
- `/me/recommendations?kind=manga|manhwa|manhua` (plusieurs types acceptés) : hybride ;
  `kind=anime` : ALS ; mélanger les deux est refusé (scores non comparables).
- `/media/{id}/similar` : « Dans le même esprit » en fin de fiche, en similarité **pure** : il
  mélange tous les types, et les rangs MAL (animes) et AniList (mangas) ne se comparent pas.

## Exemples (similarité pure, `reports/content_reco_examples.json`)
- Solo Leveling → *Solo Leveling: Ragnarok*, *Leveling Up Alone*, *The Lone Necromancer*.
- Monster → manhwas médicaux (*The Divine Surgeon*, *Doctor, Live Again*) : lien thématique réel.
- Your Name. → manhwas sans rapport évident : le cross-média reste approximatif quand le texte
  est pauvre ou très différent d'un type à l'autre.

## Conséquences
- Relancer `make embeddings` après chaque synchro AniList (le rapport du DAG l'indique).
- Pistes : texte plus riche pour les manhwas (tags), réglage de β par type quand Tsuzuku aura ses
  propres notes de lecteurs, évaluation sur ces notes.
