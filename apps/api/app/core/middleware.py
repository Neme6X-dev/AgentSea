"""Middlewares HTTP : corrélation, mesure, en-têtes de sécurité, garde-fou de débit.

Chaque middleware règle un problème constaté, pas une bonne pratique abstraite :

- `RequestContextMiddleware` donne un identifiant à chaque requête et le renvoie dans
  la réponse. Un client qui signale une erreur peut alors citer un identifiant qu'on
  retrouve directement dans les journaux, plutôt que de décrire ce qu'il a fait.
- `SecurityHeadersMiddleware` durcit les réponses de l'API *et* les sites publiés
  servis en statique — ces derniers sont du HTML généré par un modèle, donc la surface
  la plus exposée de la plateforme.
- `PublicRateLimitMiddleware` protège l'ingestion de statistiques, seul endpoint
  ouvert sans authentification : il reçoit des appels depuis chaque site publié.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import logging as applog
from app.core.logging import bind, current_request_id

#: En-tête portant l'identifiant de corrélation, à l'aller comme au retour.
REQUEST_ID_HEADER = "X-Request-ID"

_logger = applog.logging.getLogger("app.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Identifiant de corrélation, mesure de durée, journal d'accès structuré."""

    async def dispatch(self, request: Request, call_next):
        # Un identifiant fourni par l'appelant est repris tel quel : c'est ce qui
        # permet de suivre une requête depuis le front, ou depuis un workflow n8n,
        # jusqu'aux journaux du backend.
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()[:64]
        bind(incoming or applog.new_request_id())

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            _logger.exception(
                "%s %s — exception non gérée", request.method, request.url.path,
                extra={"method": request.method, "path": request.url.path, "duration_ms": round(elapsed, 1)},
            )
            raise

        elapsed = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = current_request_id()
        # Le temps serveur aide à trancher « c'est lent » entre le backend et le
        # réseau — distinction qui compte quand une partie des utilisateurs est en 3G.
        response.headers["Server-Timing"] = f"app;dur={elapsed:.1f}"

        # Les sondes de santé passent toutes les quelques secondes : les journaliser
        # en INFO noierait le trafic réel.
        level = 10 if request.url.path in {"/healthz", "/api/health"} else 20
        _logger.log(
            level,
            "%s %s → %s en %.0f ms",
            request.method, request.url.path, response.status_code, elapsed,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed, 1),
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """En-têtes de sécurité, différenciés entre l'API et les sites publiés.

    La distinction est essentielle. L'API n'a besoin que d'en-têtes défensifs
    génériques. Les sites publiés sous `/sites/` sont du HTML, du CSS et du JS produits
    par un modèle génératif à partir d'un texte fourni par l'utilisateur : ils
    reçoivent une politique de sécurité de contenu stricte, qui interdit tout script
    distant et toute iframe. L'agent codeur a déjà pour consigne de ne rien charger de
    l'extérieur ; cette politique est le filet qui rattrape le jour où il le fera
    quand même.
    """

    @staticmethod
    def site_csp() -> str:
        """Politique appliquée aux sites publiés.

        Autorise exactement ce que produit légitimement l'agent codeur — styles et
        scripts locaux, images en `data:` (SVG en ligne, dégradés) — et rien d'autre.
        Le codeur a déjà pour consigne de ne rien charger de l'extérieur ; cette
        politique est le filet qui rattrape le jour où il le fera quand même.

        `connect-src` inclut l'origine publique de l'API : la balise de fréquentation
        y poste ses événements, et un site servi depuis un domaine personnalisé émet
        alors une requête vers une origine tierce. Sans cette entrée, la mesure
        échouerait silencieusement — précisément sur les sites qui comptent le plus,
        ceux des clients ayant leur propre domaine.

        `style-src` conserve `'unsafe-inline'` : les sites générés portent des styles
        d'attribut (`style="..."`), et l'interdire casserait leur mise en page. Le
        risque résiduel est faible en regard — c'est `script-src`, strict lui, qui
        empêche l'exécution de code injecté.
        """
        from app.config import settings

        origine = settings.public_base_url.rstrip("/")
        connect = f"'self' {origine}" if origine.startswith("http") else "'self'"
        return (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            f"connect-src {connect}; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "base-uri 'none'; "
            "object-src 'none'"
        )

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )

        if request.url.path.startswith("/sites/"):
            response.headers.setdefault("Content-Security-Policy", self.site_csp())
            # Les aperçus sont affichés dans une iframe de l'éditeur : `SAMEORIGIN`
            # convient, mais la CSP `frame-ancestors` fait foi sur les navigateurs
            # récents et doit rester cohérente.
        else:
            response.headers.setdefault("Cache-Control", "no-store")

        return response


class PublicRateLimitMiddleware(BaseHTTPMiddleware):
    """Plafond de requêtes par IP sur les chemins publics non authentifiés.

    Volontairement en mémoire, contrairement au rate-limit d'authentification qui vit
    en base : il ne s'agit pas ici de sécurité mais d'hygiène de charge. Une limite
    approximative par processus suffit à absorber une boucle de collecte emballée, et
    ne mérite pas un aller-retour en base sur chaque appel.

    Le rate-limit qui protège les mots de passe, lui, doit être exact et partagé —
    c'est `app.security.check_rate_limit`, adossé à la table `auth_attempts`.
    """

    #: Chemins concernés. Tout le reste est authentifié et déjà limité en amont.
    PUBLIC_PREFIXES = ("/api/public/",)

    def __init__(self, app, limit_per_minute: int = 120) -> None:
        super().__init__(app)
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.PUBLIC_PREFIXES):
            return await call_next(request)

        client = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client:
            client = request.client.host if request.client else "?"

        now = time.monotonic()
        hits = self._hits[client]
        while hits and now - hits[0] > 60:
            hits.popleft()

        if len(hits) >= self.limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Trop de requêtes. Réessayez dans une minute.", "retryable": True},
                headers={"Retry-After": "60"},
            )

        hits.append(now)
        # Sans ce ménage, le dictionnaire garde une entrée par IP vue depuis le
        # démarrage : sur un service exposé, c'est une fuite mémoire lente.
        if len(self._hits) > 10_000:
            for key in [k for k, v in self._hits.items() if not v]:
                del self._hits[key]

        return await call_next(request)
