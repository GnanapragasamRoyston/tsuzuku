"""Schémas des comptes (phase 7).

La longueur du mot de passe est vérifiée par le service, avec les règles de settings.yaml (une
seule source). Le schéma ne pose qu'une borne de sécurité large : une entrée énorme est refusée
avant tout traitement.
"""

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

# Pseudo : sert d'URL de profil public (phase 9) → minuscules, chiffres et _ uniquement.
Pseudo = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{3,20}$")]
RawPassword = Annotated[str, Field(min_length=1, max_length=1024)]


class _Strict(BaseModel):
    # Champ inconnu → 422 : un client ne peut pas glisser `id` ou `token_version`.
    # hide_input_in_errors protège les journaux (str de l'erreur) ; la RÉPONSE 422, elle, est
    # nettoyée par le gestionnaire _invalid_request de main.py (revue de sécurité).
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _WithEmail(_Strict):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def lower_email(cls, email: str) -> str:
        # Unicité insensible à la casse : Royston@x.com et royston@x.com sont le même compte.
        return email.lower()


class RegisterRequest(_WithEmail):
    pseudo: Pseudo
    password: RawPassword


class LoginRequest(_WithEmail):
    password: RawPassword


class DeleteAccountRequest(_Strict):
    password: RawPassword


class UserOut(BaseModel):
    id: int
    email: str
    pseudo: str
    created_at: dt.datetime


class MeOut(UserOut):
    onboarding_done: bool
    list_size: int
    profile_public: bool


class MeUpdate(BaseModel):
    """Corps de PATCH /me : seul réglage modifiable pour l'instant (phase 9). strict : pas de
    conversion silencieuse ("oui" → True) ; extra interdit : ni pseudo ni email par ce biais."""

    model_config = ConfigDict(extra="forbid", strict=True)

    profile_public: bool
