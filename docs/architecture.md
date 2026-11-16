# Architecture — Tsuzuku

```mermaid
flowchart LR
    subgraph sources[Sources]
        K[Kaggle CSV<br/>109 M interactions]
        J[API Jikan]
        A[API AniList]
    end

    subgraph pipeline[pipeline/]
        S[PySpark<br/>nettoyage, Parquet, features]
        D[Modèle de drop<br/>scikit-learn]
        R[Recommandation ALS<br/>Spark MLlib]
        M[Marts analytiques]
        AF[Airflow<br/>ingestion quotidienne]
        E[Embeddings<br/>sentence-transformers]
    end

    subgraph pg[PostgreSQL + pgvector]
        C[(catalog)]
        AP[(app)]
        MA[(mart)]
    end

    ART[(Artefacts modèles<br/>models/ ou GCS)]
    API[backend/ FastAPI]
    WEB[frontend/ Next.js]
    PBI[Power BI]
    U((Utilisateurs))

    K --> S
    S --> D --> ART
    S --> R --> ART
    S --> M --> MA
    J --> AF --> C
    A --> AF
    C --> E --> C
    ART --> API
    C --> API
    AP <--> API
    MA --> API
    API <--> WEB <--> U
    MA --> PBI
```

## Schémas Postgres

- **catalog** : œuvres, genres, tags, embeddings, stats quotidiennes Jikan
- **app** : comptes et listes des utilisateurs Tsuzuku
- **mart** : agrégats analytiques produits par Spark (courbes de drop, rétention, runs de modèles)

Détail des tables : [SPEC.md § 5](SPEC.md).
