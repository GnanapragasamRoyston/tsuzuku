# Données — dictionnaire et provenance

## Source
- **Dataset** : « Anime Recommendation Database 2020 », Kaggle `hernan4444/anime-recommendation-database-2020`
  (slug vérifié via l'API Kaggle le 2026-11-16).
- **Licence** : CC0-1.0 (champ `licenses` des métadonnées Kaggle).
- **Origine** : données collectées sur MyAnimeList par l'auteur du dataset, entre le 26 février et le
  20 mars 2020 (description Kaggle). Code de collecte : <https://github.com/Hernan4444/MyAnimeList-Database>.
- **Fichiers utilisés** : `anime.csv`, `anime_with_synopsis.csv`, `animelist.csv`, `rating_complete.csv`,
  `watching_status.csv`. Le dossier `html/` du dataset n'est pas téléchargé.
- Empreintes sha256 : `data/raw/manifest.json` (généré par `make data`).

Tous les volumes et taux de qualité sont dans [`reports/data_quality.md`](../reports/data_quality.md)
(généré depuis `reports/data_quality.json`). Ce document n'en recopie aucun pour ne jamais diverger.

## Reproduire
```bash
# Jeton Kaggle dans ~/.kaggle/access_token (chmod 600), puis :
make data                       # idempotent : saute ce qui est à jour
make data ARGS=--force          # refait tout (re-téléchargement compris)
make data ARGS="--step quality --force"
```

## Couches
| Dossier | Contenu | Usage |
|---|---|---|
| `data/raw/` | CSV d'origine + `manifest.json` | jamais modifié |
| `data/parquet/staging/<table>` | typé, **non filtré** | rapport qualité, EDA |
| `data/parquet/clean/<table>` | filtré | **seule entrée** des phases 2 à 4 |
| `data/samples/<table>` | ~2 % des utilisateurs de clean (toutes leurs lignes) | développement rapide |

## Règles staging → clean
1. Clés `user_id` / `anime_id` nulles : retirées.
2. `watching_status` absent de `watching_status.csv` : retiré. Codes valides : 1 Currently Watching,
   2 Completed, 3 On Hold, 4 Dropped, 6 Plan to Watch (**pas de 5**). Le fichier source contient aussi
   des codes 0, 5, 33 et 55 sur quelques centaines de lignes.
3. Doublons exacts : une seule copie gardée.
4. Animes adultes (`rating` commençant par `Rx` **ou** genre `Hentai`) et orphelins (anime_id absent
   d'`anime.csv`) : retirés du catalogue, des synopsis et de toutes les interactions.

Le rapport ventile chaque retrait (`filters.<table>.removed_*`), et la somme est vérifiée par les tests.

## Tables clean
### `anime`
| Colonne | Type | Remarque |
|---|---|---|
| anime_id | int | MAL_ID |
| name, english_name, japanese_name | string | |
| mal_score | double | null si `Unknown` |
| genres, studios, producers, licensors | array<string> | liste vide si `Unknown` |
| type | string | TV, OVA, Movie, Special, ONA, Music |
| episodes | int | null si inconnu (série en cours en 2020) |
| aired, premiered, duration | string | valeurs d'origine |
| duration_min | double | minutes (par épisode si « per ep. ») |
| start_year | int | 1ʳᵉ année trouvée dans `aired` |
| premiered_season | string | Winter / Spring / Summer / Fall, souvent null |
| source, rating | string | |
| ranked, popularity, members, favorites | int | |
| watching, completed, on_hold, dropped, plan_to_watch, score_1..score_10 | int | ⚠️ **agrégats MAL : interdits comme features** du modèle de drop (fuite de la cible) |

### `animelist`
| Colonne | Type | Remarque |
|---|---|---|
| user_id, anime_id | int | |
| score | int | `rating` dans le CSV ; **0 = non noté** |
| watching_status | int | voir codes ci-dessus |
| watched_episodes | int | ⚠️ peut dépasser `episodes` (cf. `watched_gt_episodes` du rapport) : à plafonner en phase 2 ; **interdit comme feature** en phase 3 |

### `rating_complete`
`user_id`, `anime_id`, `score` (1 à 10). Sous-ensemble des animes terminés et notés ; le rapport
vérifie que chaque paire existe dans `animelist` (`consistency`).

### `synopsis`, `watching_status`
`synopsis(anime_id, synopsis)` (colonne `sypnopsis` renommée) ; `watching_status(status, description)`.

## Limites connues
- Instantané figé de début 2020 : aucune œuvre récente (Jikan/AniList prendront le relais).
- Un rating `Unknown` n'exclut pas l'œuvre (aucune preuve qu'elle est adulte) : le rapport en donne le nombre.
