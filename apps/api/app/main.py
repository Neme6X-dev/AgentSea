"""Point d'entrée de l'API — plateforme de création de sites pour l'Afrique."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import settings
from app.core import logging as applog
from app.core.middleware import (
    PublicRateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.gemini import LLMError
from app.routers import account, admin, agents, auth, chat, deploy, dev, public, sessions

logger = logging.getLogger("app")

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    applog.configure(settings.log_level, settings.log_json)
    settings.ensure_dirs()
    db.init_db()
    _check_configuration()
    logger.info(
        "API démarrée — environnement %s, mode travaux %s", settings.env, settings.job_mode,
        extra={"environment": settings.env, "job_mode": settings.job_mode, "version": VERSION},
    )
    yield


def _check_configuration() -> None:
    """Journalise les anomalies de configuration, et refuse de démarrer si c'est grave.

    En production, une anomalie marquée CRITIQUE arrête le démarrage. C'est délibéré :
    ces défauts-là — secret JWT vide, CORS ouvert à tous, modèle en mode simulation —
    ne cassent rien immédiatement. Ils produisent une plateforme qui *semble*
    fonctionner tout en étant vulnérable ou en livrant des sites factices. Un
    démarrage refusé se remarque tout de suite ; le conteneur ne passe pas son
    healthcheck et le déploiement précédent reste en place.

    En développement, on se contente d'avertir : une configuration incomplète y est
    normale.
    """
    problems = settings.validate()
    critical = [p for p in problems if p.startswith("CRITIQUE")]

    for problem in problems:
        (logger.error if problem.startswith("CRITIQUE") else logger.warning)("Configuration : %s", problem)

    if critical and settings.is_production:
        raise RuntimeError(
            "Démarrage refusé — configuration de production invalide :\n  - "
            + "\n  - ".join(critical)
        )


app = FastAPI(
    title="Jarvis — Plateforme de création de sites web",
    description=(
        "Backend de la plateforme : authentification (e-mail, Google, GitHub), sessions "
        "par utilisateur, agents de génération (codeur + revue sécurité via Gemini), "
        "file de travaux durable, déploiement, facturation régionale et back-office.\n\n"
        "**Ancrage africain** : devises et formats locaux (FCFA sans décimales, naira, "
        "cedi…), numéros au format E.164 avec liens WhatsApp, moyens de paiement mobile "
        "money par pays, tarification indexée sur le pouvoir d'achat local.\n\n"
        "Les endpoints `/api/agents/*` sont appelés par les workflows n8n ; le front-end "
        "consomme `/api/auth`, `/api/sessions`, `/api/account` et `/api/dev` ; le "
        "back-office consomme `/api/admin/*`."
    ),
    version=VERSION,
    lifespan=lifespan,
)

# L'ordre d'ajout compte : Starlette exécute les middlewares du dernier ajouté au
# premier. Le contexte de requête est donc ajouté en dernier pour s'exécuter en
# premier — sans quoi les journaux des autres middlewares n'auraient pas encore
# d'identifiant de corrélation à afficher.
app.add_middleware(PublicRateLimitMiddleware, limit_per_minute=settings.public_rate_limit_per_min)
app.add_middleware(SecurityHeadersMiddleware)

# Front-end séparé. `*` convient au développement ; en production, renseigner
# CORS_ORIGINS avec les origines réelles (l'auth passe par un Bearer, pas par un cookie,
# donc allow_credentials reste à False).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # Le front lit l'identifiant de corrélation pour l'afficher dans ses messages
    # d'erreur : sans exposition explicite, le navigateur le masque en cross-origin.
    expose_headers=["X-Request-ID", "Server-Timing"],
)

app.add_middleware(RequestContextMiddleware)


@app.exception_handler(LLMError)
async def _llm_error_handler(_request: Request, exc: LLMError) -> JSONResponse:
    """Une panne du fournisseur LLM est une erreur de dépendance amont, pas un bug.

    Renvoyer 502 plutôt que 500 permet à n8n et au front de distinguer « réessayer plus
    tard » de « la requête est invalide », et de déclencher leur propre retry.
    """
    # Le handler remplace la trace d'exception par défaut : on journalise nous-mêmes,
    # sinon la cause réelle (clé absente, TLS, quota) disparaît des logs.
    logger.warning("Appel LLM en échec sur %s : %s", _request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": f"Service de génération indisponible : {exc}", "retryable": True},
    )


app.include_router(auth.router)
app.include_router(account.router)
app.include_router(sessions.router)
app.include_router(agents.router)
app.include_router(deploy.router)
app.include_router(dev.router)
app.include_router(chat.router)
app.include_router(public.router)
app.include_router(admin.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    """Sonde de vivacité pour Docker / Caddy / CI (doit rester gratuite — aucun accès base)."""
    return {"status": "ok", "service": "jarvis-api", "version": VERSION}


@app.get("/api/health", tags=["ops"])
def api_health() -> dict:
    return healthz()


@app.get("/readyz", tags=["ops"])
def readyz() -> JSONResponse:
    """Sonde de disponibilité : vérifie que la base répond réellement.

    Distincte de `/healthz`, et la distinction est utile en production : un
    orchestrateur redémarre un conteneur dont la *vivacité* échoue, mais se contente
    de le retirer du service quand sa *disponibilité* échoue. Confondre les deux fait
    redémarrer en boucle des serveurs parfaitement sains dont la base est momentanément
    injoignable — ce qui aggrave la panne au lieu de la résoudre.
    """
    from sqlalchemy import text

    try:
        with db.session_scope() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Sonde de disponibilité en échec : %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": False},
        )
    return JSONResponse(content={"status": "ready", "database": True})


@app.get("/")
def root() -> dict:
    return {
        "service": "Jarvis — Plateforme de création de sites web",
        "version": VERSION,
        "docs": "/docs",
        "healthz": "/healthz",
        "readyz": "/readyz",
        "sites": "/sites/<slug>/live/",
        "region": {
            "default_country": settings.default_country,
            "default_currency": settings.default_currency,
        },
    }


# Sites vitrines générés, servis en statique : /sites/<slug>/v{n}/ et /sites/<slug>/live/
# Monté en dernier pour que les routes d'API restent joignables.
settings.sites_dir.mkdir(parents=True, exist_ok=True)
# `html=True` sert index.html pour une URL de répertoire : sans lui,
# `/sites/<slug>/live/` — l'URL exacte que l'API renvoie dans `site_url` — répond 404
# alors que les fichiers sont bien là. En production, Caddy le fait déjà de son côté.
app.mount("/sites", StaticFiles(directory=settings.sites_dir, html=True), name="sites")
