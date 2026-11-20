"""Configuration de l'API.

Deux sources, deux rôles :
- variables d'environnement (.env en local, environnement du conteneur en Docker) : ce qui change
  d'une machine à l'autre ou est secret (URL de la base, dossier des modèles, origines CORS) ;
- config/settings.yaml, section `api` : les règles du produit (seuils, limites), versionnées avec
  le code comme toutes les autres valeurs « magiques » du projet.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → racine du dépôt (en Docker, chemins fournis par l'environnement).
REPO_ROOT = Path(__file__).resolve().parents[3]


class JikanSettings(BaseModel):
    base_url: str
    timeout_s: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    cache_seconds: int = Field(ge=0)
    failure_backoff_s: int = Field(ge=0)


class ApiRules(BaseModel):
    min_liked_for_als: int = Field(ge=1)
    default_k: int = Field(ge=1)
    max_k: int = Field(ge=1)
    max_list_items: int = Field(ge=1)
    search_limit_default: int = Field(ge=1)
    search_limit_max: int = Field(ge=1)
    trending_max_age_days: int = Field(ge=0)
    jikan: JikanSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str
    models_dir: Path = REPO_ROOT / "models"
    settings_file: Path = REPO_ROOT / "config" / "settings.yaml"
    # Origines autorisées à appeler l'API depuis un navigateur (le front Next.js en phase 8).
    cors_origins: list[str] = ["http://localhost:3000"]


def load_rules(path: Path) -> ApiRules:
    with path.open(encoding="utf-8") as f:
        return ApiRules.model_validate(yaml.safe_load(f)["api"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
