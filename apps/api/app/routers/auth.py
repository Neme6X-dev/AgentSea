"""Authentification : email/mot de passe (argon2 + JWT), Google et GitHub OAuth."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app import db
from app.africa import countries, phone as phonelib
from app.analytics import events
from app.contracts import (
    GitHubAuthRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserPublic,
)
from app.security import (
    CurrentUser,
    check_rate_limit,
    create_access_token,
    exchange_github_code,
    get_github_user,
    hash_password,
    initial_role_for,
    record_failure,
    reset_failures,
    verify_google_id_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(user: dict) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user["id"]), user=UserPublic.from_row(user))


def _client_ip(request: Request) -> str:
    """IP réelle du client, en tenant compte du proxy inverse.

    Caddy et nginx placent l'IP d'origine dans `X-Forwarded-For` ; sans cette lecture,
    le contrôle de débit voit l'IP du proxy et limite tous les utilisateurs ensemble —
    autrement dit, une seule personne peut bloquer les connexions de tout le monde.
    """
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "?")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request) -> TokenResponse:
    ip = _client_ip(request)
    check_rate_limit(f"register:{payload.email}:{ip}")
    if db.get_user_by_email(payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé.")

    country = (payload.country or "BJ").upper()
    if countries.find(country) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Pays non desservi : {country}.")

    user = db.create_user(
        payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
        provider="local",
        country=country,
        # Le numéro est normalisé en E.164 dès l'inscription : c'est le seul format
        # qu'acceptent les liens WhatsApp et les passerelles SMS, et le convertir plus
        # tard suppose de deviner le pays d'un numéro déjà stocké sans indicatif.
        phone=phonelib.normalize(payload.phone or "", country) or None,
        company=payload.company,
        locale=countries.get(country).primary_language,
        role=initial_role_for(payload.email),
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé.")

    events.track(
        events.SIGNUP, user_id=user["id"], country=country,
        props={"provider": "local"}, ip=ip, user_agent=request.headers.get("User-Agent"),
    )
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    ip = _client_ip(request)
    key = f"login:{payload.email}:{ip}"
    check_rate_limit(key)
    user = db.get_user_by_email(payload.email)
    valid = user is not None and bool(user.get("password_hash")) and verify_password(
        payload.password, user["password_hash"]
    )
    if not valid:
        record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants invalides.",
        )
    reset_failures(key)
    db.touch_user(user["id"])
    events.track(events.LOGIN, user_id=user["id"], country=user.get("country"), props={"provider": "local"}, ip=ip)
    return _token_response(user)


@router.post("/google", response_model=TokenResponse)
def google_auth(payload: GoogleAuthRequest) -> TokenResponse:
    info = verify_google_id_token(payload.id_token)
    email = (info.get("email") or "").lower()
    sub = str(info["sub"])
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email manquant dans le token Google.")

    user = db.get_user_by_google_sub(sub) or (db.get_user_by_email(email) if email else None)
    is_new = user is None
    if user is None:
        user = db.create_user(
            email,
            provider="google",
            name=info.get("name"),
            google_sub=sub,
            role=initial_role_for(email),
        )
    elif not user.get("google_sub"):
        db.link_google_sub(user["id"], sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Impossible de créer l'utilisateur.")

    db.touch_user(user["id"])
    events.track(
        events.SIGNUP if is_new else events.LOGIN,
        user_id=user["id"], country=user.get("country"), props={"provider": "google"},
    )
    return _token_response(user)


@router.post("/github", response_model=TokenResponse)
def github_auth(payload: GitHubAuthRequest) -> TokenResponse:
    access_token = exchange_github_code(payload.code)
    info = get_github_user(access_token)
    github_id = info["id"]
    email = info.get("email") or ""

    user = db.get_user_by_github_id(github_id)
    if user is None and email:
        user = db.get_user_by_email(email)

    is_new = user is None
    if user is None:
        user = db.create_user(
            email,
            provider="github",
            name=info.get("name") or info.get("login"),
            github_id=github_id,
            role=initial_role_for(email),
        )
    elif not user.get("github_id"):
        db.link_github_id(user["id"], github_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Impossible de créer l'utilisateur.")

    db.touch_user(user["id"])
    events.track(
        events.SIGNUP if is_new else events.LOGIN,
        user_id=user["id"], country=user.get("country"), props={"provider": "github"},
    )
    return _token_response(user)


@router.get("/me", response_model=UserPublic)
def me(user: CurrentUser) -> UserPublic:
    # Chaque appel à /me note le passage : c'est l'endpoint que le front interroge au
    # chargement de chaque page, donc la mesure d'activité la moins coûteuse et la
    # plus fidèle dont on dispose.
    db.touch_user(user["id"])
    return UserPublic.from_row(user)


@router.patch("/me", response_model=UserPublic)
def update_me(payload: UpdateProfileRequest, user: CurrentUser) -> UserPublic:
    """Met à jour son propre profil. Ni le rôle ni l'offre ne passent par ici."""
    updates = payload.model_dump(exclude_none=True)

    if "country" in updates:
        code = updates["country"].upper()
        if countries.find(code) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Pays non desservi : {code}.")
        updates["country"] = code

    reference = updates.get("country", user.get("country") or "BJ")
    for field in ("phone", "whatsapp"):
        if updates.get(field):
            normalized = phonelib.normalize(updates[field], reference)
            if not normalized:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Numéro {field} non reconnu pour {countries.get(reference).name_fr}.",
                )
            updates[field] = normalized

    updated = db.update_user(user["id"], **updates)
    return UserPublic.from_row(updated or user)
