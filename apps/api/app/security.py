"""Sécurité de la plateforme : argon2, JWT, OAuth, rate-limit, rôles, dépendances d'auth."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger("app.security")

_ph = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# GitHub OAuth (flux d'échange de code côté serveur)
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com/user"

# --------------------------------------------------------------------------- #
# Rôles
# --------------------------------------------------------------------------- #
ROLE_USER = "user"
ROLE_SUPPORT = "support"
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"

#: Hiérarchie des rôles. Un rôle donne accès à tout ce que donnent les rangs
#: inférieurs — le contrôle se fait par comparaison de rang, jamais par égalité, sans
#: quoi ajouter un rôle intermédiaire obligerait à relire chaque `if`.
ROLE_RANK = {ROLE_USER: 0, ROLE_SUPPORT: 1, ROLE_ADMIN: 2, ROLE_OWNER: 3}

#: Rôles autorisés à ouvrir le back-office. `support` y accède en lecture ; les
#: mutations exigent `admin` (cf. `require_admin`).
STAFF_ROLES = frozenset({ROLE_SUPPORT, ROLE_ADMIN, ROLE_OWNER})


def has_role(user: dict[str, Any] | None, minimum: str) -> bool:
    """Vrai si l'utilisateur atteint au moins ce rang."""
    if not user:
        return False
    return ROLE_RANK.get(user.get("role", ROLE_USER), 0) >= ROLE_RANK.get(minimum, 99)


# --------------------------------------------------------------------------- #
# Rate-limit d'authentification (persistant)
# --------------------------------------------------------------------------- #
def check_rate_limit(key: str) -> None:
    """Lève 429 si trop de tentatives échouées récentes pour la clé (email+ip).

    Le compteur vit en base et non en mémoire. La version en mémoire ne protégeait
    qu'un processus : derrière quatre workers uvicorn, la limite de dix tentatives en
    devenait quarante, et le moindre redémarrage remettait le compteur à zéro — ce
    qu'un attaquant patient obtient en provoquant simplement du trafic.

    Un échec de lecture laisse passer la tentative : rendre l'authentification
    indisponible parce que le compteur est inaccessible serait un déni de service
    qu'on s'infligerait à soi-même. Le mot de passe, lui, reste vérifié.
    """
    from app import db

    horizon = datetime.now(timezone.utc) - timedelta(minutes=settings.auth_window_minutes)
    try:
        with db.session_scope() as s:
            recent = (
                s.query(db.AuthAttempt)
                .filter(db.AuthAttempt.key == key, db.AuthAttempt.ts >= horizon)
                .count()
            )
    except Exception:
        logger.exception("Compteur de tentatives illisible — contrôle de débit ignoré")
        return

    if recent >= settings.auth_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessayez plus tard.",
            headers={"Retry-After": str(settings.auth_window_minutes * 60)},
        )


def record_failure(key: str) -> None:
    """Consigne un échec d'authentification et purge les traces expirées.

    La purge est faite ici, au fil de l'eau, plutôt que par une tâche planifiée : la
    table ne grossit que sur des échecs, et le nettoyage se paie exactement au moment
    où quelqu'un en produit.
    """
    from app import db

    horizon = datetime.now(timezone.utc) - timedelta(minutes=settings.auth_window_minutes * 4)
    try:
        with db.session_scope() as s:
            s.add(db.AuthAttempt(key=key[:320], ts=datetime.now(timezone.utc)))
            s.query(db.AuthAttempt).filter(db.AuthAttempt.ts < horizon).delete(synchronize_session=False)
    except Exception:
        logger.exception("Échec d'authentification non consigné")


def reset_failures(key: str) -> None:
    """Efface les échecs d'une clé après une authentification réussie."""
    from app import db

    try:
        with db.session_scope() as s:
            s.query(db.AuthAttempt).filter(db.AuthAttempt.key == key).delete(synchronize_session=False)
    except Exception:
        logger.exception("Purge des tentatives en échec")


# --------------------------------------------------------------------------- #
# Mots de passe (argon2)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerificationError:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "iat": int(now.timestamp()), "exp": int(expire.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    """Décode un JWT. Lève HTTPException 401 si invalide/expiré."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré.",
        ) from exc


def _require_jwt_secret() -> None:
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET non configurée. Voir .env.example.",
        )


# --------------------------------------------------------------------------- #
# Google OAuth
# --------------------------------------------------------------------------- #
def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Vérifie un id_token Google (RS256 contre les certs publics) et retourne le payload."""
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth non configuré.",
        )
    try:
        jwks_client = jwt.PyJWKClient(GOOGLE_CERTS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            options={"verify_aud": True},
        )
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="id_token Google invalide.",
        ) from exc
    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Émetteur inconnu.")
    return payload


# --------------------------------------------------------------------------- #
# GitHub OAuth (échange de code côté serveur)
# --------------------------------------------------------------------------- #
def exchange_github_code(code: str) -> str:
    """Échange un code d'autorisation GitHub contre un access_token (côté serveur)."""
    if not settings.github_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth non configuré.",
        )
    resp = httpx.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
        },
        timeout=15,
    )
    data = resp.json() if resp.status_code == 200 else {}
    token = data.get("access_token")
    if resp.status_code != 200 or not token or data.get("error"):
        detail = data.get("error_description") or data.get("error") or "Échange de code échoué."
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return token


def get_github_user(access_token: str) -> dict[str, Any]:
    """Récupère le profil GitHub (id, login, name, email) via l'API /user."""
    resp = httpx.get(
        GITHUB_API_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Impossible de récupérer le profil GitHub.",
        )
    data = resp.json()
    github_id = str(data.get("id", "")).strip()
    if not github_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Profil GitHub invalide.")
    return {
        "id": github_id,
        "login": data.get("login"),
        "name": data.get("name"),
        "email": (data.get("email") or "").strip().lower(),
    }


# --------------------------------------------------------------------------- #
# Dépendance FastAPI
# --------------------------------------------------------------------------- #
def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    """Retourne le user courant depuis le Bearer JWT (requiert auth).

    Un compte suspendu est rejeté ici, à la porte d'entrée : c'est le seul point par
    lequel passent tous les endpoints authentifiés. Le contrôler ailleurs laisserait
    forcément un chemin ouvert.
    """
    from app import db

    _require_jwt_secret()
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise.")
    payload = decode_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.") from exc
    user = db.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable.")
    if user.get("status") == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=user.get("suspension_reason") or "Ce compte est suspendu. Contactez le support.",
        )
    return user


def current_staff(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    """Membre de l'équipe, en lecture sur le back-office (support, admin, owner).

    Le 404 sur rôle insuffisant n'est pas une coquetterie : répondre 403 confirmerait
    à un compte client que `/api/admin/...` existe et l'inviterait à chercher une
    faille d'élévation. Un endpoint qu'on ne sait pas être là ne se sonde pas.
    """
    user = current_user(credentials)
    if user.get("role") not in STAFF_ROLES:
        logger.warning(
            "Accès back-office refusé pour %s (rôle %s)", user.get("email"), user.get("role"),
            extra={"user_id": user.get("id"), "role": user.get("role")},
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ressource introuvable.")
    return user


def current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    """Administrateur : requis pour toute écriture depuis le back-office.

    La distinction avec `current_staff` est le cœur du modèle : le support consulte
    les comptes pour aider un client, il ne change pas leur offre ni ne les suspend.
    """
    user = current_staff(credentials)
    if not has_role(user, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette action demande le rôle administrateur.",
        )
    return user


def require_service_or_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any] | None:
    """Autorise soit le JWT utilisateur, soit la clé INTERNAL_API_KEY (n8n).

    Retourne le user si identifié, sinon None (appel service).
    """
    from app import db

    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise.")
    token = credentials.credentials
    if settings.internal_api_key and token == settings.internal_api_key:
        return None
    _require_jwt_secret()
    payload = decode_token(token)
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.") from exc
    user = db.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable.")
    return user


CurrentUser = Annotated[dict[str, Any], Depends(current_user)]
CurrentStaff = Annotated[dict[str, Any], Depends(current_staff)]
CurrentAdmin = Annotated[dict[str, Any], Depends(current_admin)]
ServiceOrUser = Annotated[dict[str, Any] | None, Depends(require_service_or_user)]


def initial_role_for(email: str) -> str:
    """Rôle attribué à la création d'un compte.

    `ADMIN_EMAILS` sert d'amorçage : sur une base neuve, personne ne peut ouvrir le
    back-office pour y nommer le premier administrateur. La liste est lue à
    l'inscription seulement — en retirer une adresse ne rétrograde pas un compte déjà
    créé, ce qui se fait depuis le back-office et laisse une trace d'audit.
    """
    return ROLE_OWNER if email.strip().lower() in settings.admin_emails else ROLE_USER
