# Chiffres clés — Tsuzuku

Généré le 2026-11-16T21:21:10Z par `make figures`.
Sources :
- `reports/data_quality.json` (généré le 2026-11-16T11:16:43Z)
- `reports/marts_summary.json` (généré le 2026-11-16T11:18:57Z)
- `reports/drop_metrics.json` (généré le 2026-11-16T21:20:13Z)

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

## Mesures d'exploration (ponctuelles)

- **phase2_drop_profile** (phase 2) — script d'exploration phase 2 (profil des drops, lignes Completed/Dropped jointes au catalogue) ; voir ADR 003 — `reports/exploration_2026-11-16.json`
- **phase2_point_of_no_return_definitions** (phase 2) — scratchpad ponr_options.py sur les 3 339 animes publiés dans mart.critical_episode ; voir ADR 003 — `reports/exploration_2026-11-16.json`
- **phase3_population_profile** (phase 3) — scratchpad phase3_profile.py sur clean/animelist ; voir ADR 004 — `reports/exploration_2026-11-16.json`
