# Rapport qualité des données

Généré le 2026-11-16T10:30:46Z depuis `reports/data_quality.json`.
Source : Kaggle `hernan4444/anime-recommendation-database-2020` · licence CC0-1.0.

## Table `anime` (staging)

| Métrique | Valeur |
|---|---:|
| rows | 17 562 |
| duplicate_anime_ids | 0 |
| adult_total | 1 348 |
| adult_by_genre_only | 3 |
| unknown_rating | 688 |
| empty_genres | 63 |
| null_counts · mal_score | 5 141 |
| null_counts · english_name | 10 565 |
| null_counts · japanese_name | 48 |
| null_counts · type | 37 |
| null_counts · episodes | 516 |
| null_counts · aired | 309 |
| null_counts · premiered | 12 817 |
| null_counts · source | 3 567 |
| null_counts · duration | 555 |
| null_counts · rating | 688 |
| null_counts · ranked | 1 762 |
| null_counts · score_10 | 437 |
| null_counts · score_9 | 3 167 |
| null_counts · score_8 | 1 371 |
| null_counts · score_7 | 503 |
| null_counts · score_6 | 511 |
| null_counts · score_5 | 584 |
| null_counts · score_4 | 977 |
| null_counts · score_3 | 1 307 |
| null_counts · score_2 | 1 597 |
| null_counts · score_1 | 459 |
| null_counts · duration_min | 555 |
| null_counts · start_year | 309 |
| null_counts · premiered_season | 12 817 |

## Table `synopsis` (staging)

| Métrique | Valeur |
|---|---:|
| rows | 16 214 |
| missing_synopsis | 8 |

## Table `animelist` (staging)

| Métrique | Valeur |
|---|---:|
| rows | 109 224 747 |
| null_keys | 0 |
| duplicate_pairs | 1 |
| distinct_users | 325 770 |
| distinct_anime | 17 562 |
| score_out_of_range | 0 |
| score_zero | 46 827 035 |
| score_null | 0 |
| negative_watched_episodes | 0 |
| unknown_status_rows | 540 |
| status_counts · Completed | 68 089 751 |
| status_counts · Plan to Watch | 27 938 693 |
| status_counts · Currently Watching | 5 228 658 |
| status_counts · Dropped | 4 266 591 |
| status_counts · On Hold | 3 700 514 |
| status_counts · unknown(0) | 531 |
| status_counts · unknown(5) | 6 |
| status_counts · unknown(33) | 2 |
| status_counts · unknown(55) | 1 |
| watched_gt_episodes | 197 231 |

## Table `rating_complete` (staging)

| Métrique | Valeur |
|---|---:|
| rows | 57 633 278 |
| null_keys | 0 |
| duplicate_pairs | 0 |
| distinct_users | 310 059 |
| distinct_anime | 16 872 |
| score_out_of_range | 0 |
| score_zero | 0 |
| score_null | 0 |

## Filtrage `anime` (staging → clean)

| Métrique | Valeur |
|---|---:|
| rows_before | 17 562 |
| rows_after | 16 214 |

## Filtrage `animelist` (staging → clean)

| Métrique | Valeur |
|---|---:|
| rows_before | 109 224 747 |
| removed_null_keys | 0 |
| removed_unknown_status | 540 |
| removed_duplicates | 1 |
| removed_adult | 1 935 084 |
| removed_orphan | 0 |
| orphan_anime_ids | 0 |
| rows_after | 107 289 122 |

## Filtrage `rating_complete` (staging → clean)

| Métrique | Valeur |
|---|---:|
| rows_before | 57 633 278 |
| removed_null_keys | 0 |
| removed_unknown_status | 0 |
| removed_duplicates | 0 |
| removed_adult | 906 417 |
| removed_orphan | 0 |
| orphan_anime_ids | 0 |
| rows_after | 56 726 861 |

- **rating_complete_pairs_missing_from_animelist** : 0
