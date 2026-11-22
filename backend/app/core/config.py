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
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → racine du dépôt (en Docker, chemins fournis par l'environnement).
REPO_ROOT = Path(__file__).resolve().parents[3]


class JikanSettings(BaseModel):
    base_url: str
    timeout_s: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    cache_seconds: int = Field(ge=0)
    failure_backoff_s: int = Field(ge=0)


class RateLimit(BaseModel):
    max_attempts: int = Field(ge=1)
    window_s: int = Field(ge=1)


class AuthRules(BaseModel):
    token_ttl_hours: int = Field(ge=1)
    password_min_length: int = Field(ge=8)
    password_max_length: int = Field(ge=8)
    login_limit: RateLimit
    register_limit: RateLimit


class ApiRules(BaseModel):
    min_liked_for_als: int = Field(ge=1)
    default_k: int = Field(ge=1)
    max_k: int = Field(ge=1)
    max_list_items: int = Field(ge=1)
    search_limit_default: int = Field(ge=1)
    search_limit_max: int = Field(ge=1)
    trending_max_age_days: int = Field(ge=0)
    onboarding_min_choices: int = Field(ge=1)
    list_max_entries: int = Field(ge=1)
    review_max_length: int = Field(ge=1)
    list_page_max: int = Field(ge=1)
    profile_min_finished_for_drop_rate: int = Field(ge=1)
    profile_top_genres: int = Field(ge=1)
    profile_recent_scores: int = Field(ge=1)
    cover_suggestion_prefixes: list[str] = Field(min_length=1)
    cover_suggestions_per_day: int = Field(ge=1)
    cover_url_max_length: int = Field(ge=20)
    jikan: JikanSettings
    auth: AuthRules


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str
    models_dir: Path = REPO_ROOT / "models"
    settings_file: Path = REPO_ROOT / "config" / "settings.yaml"
    # Origines autorisées à appeler l'API depuis un navigateur (le front Next.js en phase 8).
    cors_origins: list[str] = ["http://localhost:3000"]
    # Clé de signature des jetons de session (make api-keys). Absente : l'API démarre quand même,
    # mais les routes de compte répondent 503 (la CI construit l'image sans secret).
    jwt_secret: SecretStr | None = None
    # Cookie `Secure` : envoyé seulement en HTTPS. À désactiver UNIQUEMENT en local, en http.
    cookie_secure: bool = True


def load_rules(path: Path) -> ApiRules:
    with path.open(encoding="utf-8") as f:
        return ApiRules.model_validate(yaml.safe_load(f)["api"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
