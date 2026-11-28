# Chiffres clés — Tsuzuku

Généré le 2026-11-28T19:49:26Z par `make figures`.
Sources :
- `reports/data_quality.json` (généré le 2026-11-16T11:16:43Z)
- `reports/marts_summary.json` (généré le 2026-11-16T11:18:57Z)
- `reports/drop_metrics.json` (généré le 2026-11-16T21:20:13Z)
- `reports/reco_metrics.json` (généré le 2026-11-16T22:58:02Z)
- `reports/powerbi_summary.json` (généré le 2026-11-28T19:49:26Z)

## Données (phase 1)

| indicateur | valeur |
|---|---|
| interactions_raw | 109 224 747 |
| interactions_clean | 107 289 122 |
| users | 325 770 |
| anime_raw | 17 562 |
| anime_clean | 16 214 |
| adult_anime | 1 348 |
| adult_anime_by_genre_only | 3 |
| adult_interactions_removed | 1 935 084 |
| unknown_status_rows_removed | 540 |
| duplicate_rows_removed | 1 |
| ratings_raw | 57 633 278 |
| ratings_clean | 56 726 861 |

### status_counts

| status | rows |
|---|---|
| Completed | 68 089 751 |
| Plan to Watch | 27 938 693 |
| Currently Watching | 5 228 658 |
| Dropped | 4 266 591 |
| On Hold | 3 700 514 |
| unknown(0) | 531 |
| unknown(5) | 6 |
| unknown(33) | 2 |
| unknown(55) | 1 |

## Marts (phase 2)

| indicateur | valeur |
|---|---|
| drop_curve_rows | 97 100 |
| anime_with_drop_curve | 15 665 |
| anime_with_critical_episode | 3 339 |
| anime_with_point_of_no_return | 3 306 |
| genres_published | 41 |
| studios_published | 220 |

### genres_by_drop_rate

| genre | nb_anime | drop_rate | completion_rate | median_drop_progress |
|---|---|---|---|---|
| Shoujo Ai | 77 | 0.0851 | 0.8031 | 0.1667 |
| Martial Arts | 411 | 0.0791 | 0.7996 | 0.1538 |
| Josei | 92 | 0.0738 | 0.8149 | 0.1538 |
| Kids | 2 651 | 0.069 | 0.8647 | 0 |
| Shoujo | 678 | 0.0673 | 0.8267 | 0.12 |
| Seinen | 808 | 0.0648 | 0.8275 | 0.1667 |
| Samurai | 200 | 0.0643 | 0.7999 | 0.1 |
| Historical | 1 101 | 0.0642 | 0.8092 | 0.1154 |
| Demons | 414 | 0.0627 | 0.8149 | 0.1538 |
| Ecchi | 759 | 0.0622 | 0.8533 | 0.1667 |
| Action | 3 716 | 0.061 | 0.8332 | 0.16 |
| Super Power | 614 | 0.0608 | 0.8255 | 0.1628 |
| Magic | 1 031 | 0.0607 | 0.8306 | 0.1538 |
| Space | 474 | 0.0606 | 0.8227 | 0.1154 |
| Fantasy | 3 090 | 0.0604 | 0.832 | 0.1538 |
| Shounen Ai | 96 | 0.0604 | 0.8616 | 0.125 |
| Harem | 348 | 0.06 | 0.8583 | 0.1667 |
| Sci-Fi | 2 484 | 0.0599 | 0.8393 | 0.1538 |
| Sports | 692 | 0.0599 | 0.8342 | 0.1176 |
| Mecha | 1 071 | 0.0594 | 0.849 | 0.125 |
| Vampire | 129 | 0.0587 | 0.8411 | 0.1667 |
| Game | 380 | 0.0584 | 0.8476 | 0.1667 |
| Comedy | 5 872 | 0.0581 | 0.8381 | 0.1538 |
| School | 1 523 | 0.0581 | 0.8422 | 0.1667 |
| Slice of Life | 1 854 | 0.0571 | 0.8329 | 0.1538 |
| Horror | 421 | 0.0569 | 0.8524 | 0.1667 |
| Adventure | 2 876 | 0.0567 | 0.8371 | 0.1333 |
| Shounen | 1 957 | 0.0564 | 0.8238 | 0.1448 |
| Music | 2 205 | 0.0561 | 0.8544 | 0.0833 |
| Parody | 646 | 0.0558 | 0.8391 | 0.1257 |
| Mystery | 694 | 0.0555 | 0.8339 | 0.1667 |
| Romance | 1 799 | 0.0551 | 0.8543 | 0.1667 |
| Police | 239 | 0.0536 | 0.8429 | 0.1538 |
| Supernatural | 1 354 | 0.0532 | 0.8498 | 0.1667 |
| Drama | 2 517 | 0.0501 | 0.8489 | 0.1538 |
| Psychological | 330 | 0.0497 | 0.8424 | 0.1667 |
| Military | 550 | 0.0476 | 0.8512 | 0.1538 |
| Dementia | 508 | 0.0465 | 0.8541 | 0.1667 |
| Thriller | 124 | 0.0387 | 0.8524 | 0.1739 |
| Cars | 133 | 0.034 | 0.8958 | 0.0385 |
| Yaoi | 29 | 0.0208 | 0.9438 | 0.25 |

### showcase

| title | episodes | critical_episode | point_of_no_return | initial_drop_risk | drop_rate |
|---|---|---|---|---|---|
| Death Note | 37 | 25 | 26 | 0.0325 | 0.0385 |
| Naruto | 220 | 135 | 138 | 0.0861 | 0.1037 |
| Steins;Gate | 24 | 1 | 9 | 0.0225 | 0.0272 |
| Shingeki no Kyojin | 25 | 1 | 14 | 0.0217 | 0.025 |
| Sword Art Online | 25 | 3 | 15 | 0.048 | 0.0544 |
| Fullmetal Alchemist: Brotherhood | 64 | 1 | 22 | 0.0194 | 0.0237 |

## Modèle de drop (phase 3)

| indicateur | valeur |
|---|---|
| run_id | 3e8b164f-1a69-4423-bf5d-df30210f0f99 |
| final_model | hgb |
| calibration | none |

### sample

| rows | users |
|---|---|
| 2 114 716 | 9 576 |

### splits

| split | rows | users | prevalence |
|---|---|---|---|
| train | 1 485 922 | 6 702 | 0.0572 |
| val | 315 549 | 1 437 | 0.0648 |
| test | 313 245 | 1 437 | 0.056 |

### models_on_test

| model | pr_auc | roc_auc | f1 | precision | recall | brier | ece | threshold |
|---|---|---|---|---|---|---|---|---|
| dummy | 0.056 | 0.5 | 0.1061 | 0.056 | 1 | 0.0529 | 0.0012 | 0.0572 |
| logreg | 0.3614 | 0.8692 | 0.3961 | 0.3469 | 0.4617 | 0.0437 | 0.0065 | 0.1612 |
| hgb | 0.4322 | 0.901 | 0.4369 | 0.3947 | 0.4892 | 0.0404 | 0.0053 | 0.2406 |

### confusion_final_test

| tn | fp | fn | tp |
|---|---|---|---|
| 282 524 | 13 169 | 8 965 | 8 587 |

### top_features

| feature | importance | std |
|---|---|---|
| user_drop_rate | 0.3006 | 0.0014 |
| episodes | 0.2155 | 0.0022 |
| popularity | 0.1242 | 0.002 |
| start_year | 0.0888 | 0.0005 |
| duration_min | 0.0124 | 0.0004 |
| genre_affinity | 0.0084 | 0.0006 |
| main_studio | 0.0081 | 0.0006 |
| format | 0.0063 | 0.0006 |
| source | 0.006 | 0.0003 |
| genre_ecchi | 0.0036 | 0.0005 |

### calibration_bins_test

| mean_pred | observed | n |
|---|---|---|
| 0.0005 | 0.0001 | 31 325 |
| 0.0011 | 0.0004 | 31 324 |
| 0.0023 | 0.0018 | 31 325 |
| 0.0052 | 0.0043 | 31 324 |
| 0.01 | 0.0077 | 31 324 |
| 0.0188 | 0.0152 | 31 325 |
| 0.0346 | 0.0305 | 31 324 |
| 0.0636 | 0.0556 | 31 325 |
| 0.1256 | 0.1129 | 31 324 |
| 0.3516 | 0.3319 | 31 325 |

## Recommandation ALS (phase 4)

| indicateur | valeur |
|---|---|
| run_id | 1263a415-e570-4b02-9a74-1d330ba0fb77 |
| final_model | als_implicit |
| ratings_before_filter | 56 726 861 |
| ratings_after_filter | 56 272 898 |
| users_after_filter | 264 532 |
| anime_after_filter | 10 859 |
| catalog_size | 10 859 |
| relevant_min_score | 8 |

### splits

| split | rows | users | masked |
|---|---|---|---|
| test | 5 646 050 | 26 562 | 1 129 026 |
| val | 5 649 392 | 26 501 | 1 127 948 |
| train | 44 977 456 | 211 469 | 0 |

### models_on_test

| model | k | precision | recall | ndcg | coverage |
|---|---|---|---|---|---|
| popularity | 5 | 0.1931 | 0.0556 | 0.2113 | 0.0042 |
| popularity | 10 | 0.1635 | 0.0912 | 0.193 | 0.0064 |
| popularity | 20 | 0.1282 | 0.1376 | 0.1821 | 0.0117 |
| als_explicit | 5 | 0.2128 | 0.0749 | 0.2321 | 0.3359 |
| als_explicit | 10 | 0.1733 | 0.1153 | 0.2119 | 0.4454 |
| als_explicit | 20 | 0.1374 | 0.1716 | 0.2076 | 0.5568 |
| als_implicit | 5 | 0.4988 | 0.1678 | 0.5345 | 0.1809 |
| als_implicit | 10 | 0.418 | 0.2602 | 0.4933 | 0.2134 |
| als_implicit | 20 | 0.3294 | 0.3778 | 0.4766 | 0.2525 |

### rmse_test

| model | rmse |
|---|---|
| item_mean | 1.5026 |
| als_explicit | 1.0964 |

### onboarding_test

| n_liked | users | model | k | ndcg | recall |
|---|---|---|---|---|---|
| 3 | 26 547 | popularity | 5 | 0.2114 | 0.0556 |
| 3 | 26 547 | popularity | 10 | 0.193 | 0.0912 |
| 3 | 26 547 | popularity | 20 | 0.1821 | 0.1376 |
| 3 | 26 547 | als_explicit | 5 | 0.1608 | 0.0489 |
| 3 | 26 547 | als_explicit | 10 | 0.1353 | 0.0679 |
| 3 | 26 547 | als_explicit | 20 | 0.1259 | 0.0956 |
| 3 | 26 547 | als_implicit | 5 | 0.1986 | 0.0613 |
| 3 | 26 547 | als_implicit | 10 | 0.1746 | 0.0918 |
| 3 | 26 547 | als_implicit | 20 | 0.1679 | 0.1359 |
| 5 | 26 512 | popularity | 5 | 0.2115 | 0.0556 |
| 5 | 26 512 | popularity | 10 | 0.1931 | 0.0911 |
| 5 | 26 512 | popularity | 20 | 0.1822 | 0.1375 |
| 5 | 26 512 | als_explicit | 5 | 0.199 | 0.0636 |
| 5 | 26 512 | als_explicit | 10 | 0.1706 | 0.0896 |
| 5 | 26 512 | als_explicit | 20 | 0.1605 | 0.1261 |
| 5 | 26 512 | als_implicit | 5 | 0.243 | 0.0779 |
| 5 | 26 512 | als_implicit | 10 | 0.2143 | 0.1158 |
| 5 | 26 512 | als_implicit | 20 | 0.2063 | 0.1693 |
| 10 | 26 236 | popularity | 5 | 0.2128 | 0.0553 |
| 10 | 26 236 | popularity | 10 | 0.194 | 0.0907 |
| 10 | 26 236 | popularity | 20 | 0.1827 | 0.1371 |
| 10 | 26 236 | als_explicit | 5 | 0.221 | 0.075 |
| 10 | 26 236 | als_explicit | 10 | 0.2005 | 0.1138 |
| 10 | 26 236 | als_explicit | 20 | 0.1955 | 0.1644 |
| 10 | 26 236 | als_implicit | 5 | 0.3161 | 0.1025 |
| 10 | 26 236 | als_implicit | 10 | 0.2807 | 0.154 |
| 10 | 26 236 | als_implicit | 20 | 0.27 | 0.2228 |
| 20 | 23 806 | popularity | 5 | 0.2249 | 0.053 |
| 20 | 23 806 | popularity | 10 | 0.2028 | 0.0875 |
| 20 | 23 806 | popularity | 20 | 0.1884 | 0.1335 |
| 20 | 23 806 | als_explicit | 5 | 0.2284 | 0.0681 |
| 20 | 23 806 | als_explicit | 10 | 0.2104 | 0.1105 |
| 20 | 23 806 | als_explicit | 20 | 0.2091 | 0.1721 |
| 20 | 23 806 | als_implicit | 5 | 0.412 | 0.1197 |
| 20 | 23 806 | als_implicit | 10 | 0.3628 | 0.1821 |
| 20 | 23 806 | als_implicit | 20 | 0.343 | 0.2654 |

### grid

| kind | rank | reg_param | val_ndcg | fit_seconds |
|---|---|---|---|---|
| als_explicit | 16 | 0.01 | 0.0061 | 7.4 |
| als_explicit | 16 | 0.03 | 0.0393 | 5.2 |
| als_explicit | 16 | 0.05 | 0.0654 | 4.8 |
| als_explicit | 16 | 0.1 | 0.0807 | 4.7 |
| als_explicit | 16 | 0.2 | 0.0478 | 4.8 |
| als_explicit | 32 | 0.01 | 0.016 | 9.3 |
| als_explicit | 32 | 0.03 | 0.0681 | 8.7 |
| als_explicit | 32 | 0.05 | 0.1005 | 10.3 |
| als_explicit | 32 | 0.1 | 0.0976 | 9.9 |
| als_explicit | 32 | 0.2 | 0.049 | 9.9 |
| als_explicit | 64 | 0.01 | 0.0278 | 25.7 |
| als_explicit | 64 | 0.03 | 0.0998 | 26.3 |
| als_explicit | 64 | 0.05 | 0.136 | 26 |
| als_explicit | 64 | 0.1 | 0.1052 | 26.2 |
| als_explicit | 64 | 0.2 | 0.0489 | 26.3 |
| als_explicit | 128 | 0.01 | 0.0543 | 85.9 |
| als_explicit | 128 | 0.03 | 0.14 | 85.4 |
| als_explicit | 128 | 0.05 | 0.173 | 85.5 |
| als_explicit | 128 | 0.1 | 0.1105 | 85.3 |
| als_explicit | 128 | 0.2 | 0.0489 | 85.9 |
| als_implicit | 16 | 0.01 | 0.3697 | 5.8 |
| als_implicit | 16 | 0.03 | 0.3695 | 5.3 |
| als_implicit | 16 | 0.05 | 0.3698 | 5.4 |
| als_implicit | 16 | 0.1 | 0.3675 | 5.1 |
| als_implicit | 16 | 0.2 | 0.3633 | 5.4 |
| als_implicit | 32 | 0.01 | 0.4068 | 9.3 |
| als_implicit | 32 | 0.03 | 0.4065 | 9.4 |
| als_implicit | 32 | 0.05 | 0.4058 | 9.5 |
| als_implicit | 32 | 0.1 | 0.405 | 9.7 |
| als_implicit | 32 | 0.2 | 0.3984 | 9.5 |
| als_implicit | 64 | 0.01 | 0.4463 | 23.5 |
| als_implicit | 64 | 0.03 | 0.4462 | 24.4 |
| als_implicit | 64 | 0.05 | 0.4453 | 24.1 |
| als_implicit | 64 | 0.1 | 0.4431 | 24.7 |
| als_implicit | 64 | 0.2 | 0.4262 | 24.6 |
| als_implicit | 128 | 0.01 | 0.4829 | 82.1 |
| als_implicit | 128 | 0.03 | 0.4848 | 82.6 |
| als_implicit | 128 | 0.05 | 0.4852 | 81.5 |
| als_implicit | 128 | 0.1 | 0.4798 | 81.8 |
| als_implicit | 128 | 0.2 | 0.4509 | 81.9 |

### showcase

| liked | liked_ids | default_score | recommended | recommended_ids | popularity_top10 | shared_with_popularity |
|---|---|---|---|---|---|---|
| ['Naruto', 'Death Note', 'Fullmetal Alchemist: Brotherhood', 'Steins;Gate', 'Sword Art Online', 'Shingeki no Kyojin'] | [20, 1535, 5114, 9253, 11757, 16498] | 8 | ['Fullmetal Alchemist', 'One Punch Man', 'Angel Beats!', 'Code Geass: Hangyaku no Lelouch', 'Tokyo Ghoul', 'Code Geass: Hangyaku no Lelouch R2', 'No Game No Life', 'Shingeki no Kyojin Season 2', 'Sword Art Online II', 'Hunter x Hunter (2011)'] | [121, 30276, 6547, 1575, 22319, 2904, 19815, 25777, 21881, 11061] | ['Code Geass: Hangyaku no Lelouch', 'One Punch Man', 'Sen to Chihiro no Kamikakushi', 'Kimi no Na wa.', 'Code Geass: Hangyaku no Lelouch R2', 'Toradora!', 'Angel Beats!', 'No Game No Life', 'Koe no Katachi', 'Boku no Hero Academia'] | 5 |

## Power BI (phase 13)

| indicateur | valeur |
|---|---|
| database | locale |
| anime_with_drop_data | 3 339 |
| anime_with_tags | 3 236 |
| global_drop_rate | 0.0752 |
| statuses_finished | 51 379 108 |

### segments

| segment | nb_anime | nb_drops | nb_completed | drop_rate |
|---|---|---|---|---|
| Autres | 2 478 | 2 691 812 | 31 545 739 | 0.0786 |
| Isekai | 200 | 274 605 | 3 782 317 | 0.0677 |
| Shounen | 690 | 934 264 | 12 500 856 | 0.0695 |

## Mesures d'exploration (ponctuelles)

- **phase2_drop_profile** (phase 2) — script d'exploration phase 2 (profil des drops, lignes Completed/Dropped jointes au catalogue) ; voir ADR 003 — `reports/exploration_2026-11-16.json`
- **phase2_point_of_no_return_definitions** (phase 2) — scratchpad ponr_options.py sur les 3 339 animes publiés dans mart.critical_episode ; voir ADR 003 — `reports/exploration_2026-11-16.json`
- **phase3_population_profile** (phase 3) — scratchpad phase3_profile.py sur clean/animelist ; voir ADR 004 — `reports/exploration_2026-11-16.json`
- **reco_ratings_profile** (phase 4) — scratchpad explore_ratings.py sur clean/rating_complete (Spark, approxQuantile erreur relative 0,001) ; voir ADR 005 — `reports/exploration_2026-11-16.json`
- **api_serving_feature_parity** (phase 5) — scratchpad check_skew.py : infos d'anime servies par l'API (catalog.media via catalog_service.anime_infos) comparées à celles de l'entraînement (clean/anime) ; voir ADR 006 — `reports/exploration_2026-11-20.json`
- **api_docker_image** (phase 5) — docker image ls tsuzuku-api après make api-up ; voir ADR 006 — `reports/exploration_2026-11-20.json`
- **api_jikan_worst_case** (phase 5) — curl /trending sur l'API Docker alors que api.jikan.moe ne répondait pas (aussi injoignable depuis Windows) ; voir ADR 006 — `reports/exploration_2026-11-20.json`
- **api_real_data_smoke** (phase 5) — scratchpad smoke_api.py (TestClient sur la base de dev et les vrais modèles, runs 1263a415 reco et 3e8b164f drop) ; voir ADR 006 — `reports/exploration_2026-11-20.json`
- **anilist_first_runs** (phase 6) — reports/ingestion/anilist_2026-11-16.json puis anilist_2026-11-20.json (DAG anilist_catalog_sync dans Airflow, le 2026-11-20 : exécution planifiée, relance sur le même intervalle, puis 3e exécution après la revue de code : romans exclus, date = jour réel) + requêtes SQL sur catalog ; voir ADR 007 — `reports/exploration_2026-11-20.json`
- **jikan_first_run** (phase 6) — DAG jikan_daily_ingest dans Airflow le 2026-11-20 (airflow tasks states-for-dag-run) : tâche collect en échec à ses 2 premiers essais (Jikan injoignable : timeout, aussi hors WSL), statut up_for_retry ; curl api.jikan.moe toujours en échec à 15:2x UTC ; voir ADR 007 — `reports/exploration_2026-11-20.json`
- **anime_covers_first_run** (phase 8) — make covers le 2026-11-21 (jobs.anilist_covers, AniList par idMal) : sortie de la commande et rapport reports/ingestion/covers_2026-11-21.json ; voir ADR 009 — `reports/exploration_2026-11-20.json`
